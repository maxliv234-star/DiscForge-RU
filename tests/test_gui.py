"""Project-load regressions; run with QT_QPA_PLATFORM=offscreen and PySide6."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6.QtWidgets import QApplication
    from main import Window
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, 'PySide6 is not installed')
class ProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_invalid_project_preserves_current_work(self):
        window = Window()
        window.menu_title.setText('Current project')
        try:
            with tempfile.TemporaryDirectory() as temp:
                file = Path(temp) / 'project.dfr.json'
                for chapters, profile in (([0, float('inf')], 'BD25'), ([0, 'bad'], 'BD25'), ([0], [])):
                    file.write_text(json.dumps({'format_version': 1, 'files': ['film.mkv'],
                                               'chapters': {'film.mkv': chapters},
                                               'profile': profile}), encoding='utf-8')
                    with patch('main.QFileDialog.getOpenFileName', return_value=(str(file), '')), \
                         patch('main.QMessageBox.warning') as warning, \
                         patch.object(window, '_queue_scan') as scan:
                        window.open_project()
                        warning.assert_called_once()
                        scan.assert_not_called()
                        self.assertEqual(window.menu_title.text(), 'Current project')
        finally:
            with patch('main.save_settings'):
                window.close()

    def test_save_failure_is_reported(self):
        window = Window()
        try:
            with patch('main.QFileDialog.getSaveFileName', return_value=('test.json', '')), \
                 patch('main.write_json', side_effect=OSError('disk full')), \
                 patch('main.QMessageBox.warning') as warning:
                window.save_project()
                warning.assert_called_once()
        finally:
            with patch('main.save_settings'):
                window.close()
