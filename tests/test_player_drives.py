import tempfile
import unittest
from pathlib import Path
from player.drives import optical_drives


class OpticalDriveTests(unittest.TestCase):
    def test_macos_disc_mount(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            movie = root / "MY_MOVIE"
            (movie / "BDMV").mkdir(parents=True)
            (root / "OTHER").mkdir()
            self.assertEqual(optical_drives("darwin", root), [str(movie)])

    def test_missing_mount_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(optical_drives("darwin", Path(tmp) / "missing"), [])


if __name__ == "__main__":
    unittest.main()
