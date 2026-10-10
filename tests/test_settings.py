import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import settings


class SettingsTests(unittest.TestCase):
    def test_failed_replace_keeps_previous_project(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'project.json'
            path.write_text('previous project', encoding='utf-8')
            with patch('settings.os.replace', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    settings.write_json(path, {'new': 'project'})
            self.assertEqual(path.read_text(encoding='utf-8'), 'previous project')
            self.assertEqual(list(Path(temp).iterdir()), [path])

    def test_nonfinite_data_does_not_replace_project(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'project.json'
            path.write_text('previous project', encoding='utf-8')
            with self.assertRaises(ValueError):
                settings.write_json(path, {'chapters': [float('inf')]})
            self.assertEqual(path.read_text(encoding='utf-8'), 'previous project')

    def test_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(settings, 'CFG', Path(temp) / 'settings.json'):
            settings.save({'output': 'Фильмы'})
            self.assertEqual(settings.load()['output'], 'Фильмы')

    def test_macos_config_directory(self):
        home = Path('/Users/tester')
        self.assertEqual(
            settings.config_dir('darwin', home, None),
            home / 'Library' / 'Application Support' / 'DiscForgeRU',
        )

    def test_windows_config_directory(self):
        self.assertEqual(
            settings.config_dir('win32', Path('C:/Users/tester'), 'C:/Users/tester/AppData/Roaming'),
            Path('C:/Users/tester/AppData/Roaming') / 'DiscForgeRU',
        )

    def test_defaults_keep_output_folder(self):
        config = settings.defaults()
        self.assertIn('ffmpeg', config)
        self.assertIn('ffprobe', config)
        self.assertIn('tsmuxer', config)
        self.assertTrue(config['output'])


if __name__ == '__main__':
    unittest.main()
