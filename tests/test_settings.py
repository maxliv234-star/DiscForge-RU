import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import settings


class SettingsTests(unittest.TestCase):
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
