import tempfile
import unittest
from pathlib import Path
from player.backend import SourceError, bluray_uri, bdmv_uri, file_uri

class PlayerBackendTests(unittest.TestCase):
    def test_windows_drive_letter(self):
        self.assertEqual(bluray_uri("d:", "win32"), "bluray:///D:/")
        self.assertEqual(bluray_uri("E:\\", "win32"), "bluray:///E:/")

    def test_invalid_drive(self):
        for value in ("", "D:\n", "relative"):
            with self.subTest(value=value), self.assertRaises(SourceError):
                bluray_uri(value, "win32" if value == "D:\n" else "linux")

    def test_bdmv_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SourceError):
                bdmv_uri(tmp)
            root = Path(tmp)
            (root / "BDMV").mkdir()
            self.assertEqual(bdmv_uri(tmp), bdmv_uri(str(root / "BDMV")))

    def test_video_iso_and_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("Фильм.mkv", "disc.iso"):
                file = root / name
                file.touch()
                self.assertTrue(file_uri(str(file)).startswith("file://"))
            file = root / "script.exe"
            file.touch()
            with self.assertRaises(SourceError):
                file_uri(str(file))

    def test_missing_video(self):
        with self.assertRaises(SourceError):
            file_uri("/not/here/movie.mkv")
