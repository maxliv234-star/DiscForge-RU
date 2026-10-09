"""Pure unit tests for macOS burn command. They never touch optical hardware."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import macos_burn


class MacBurnTests(unittest.TestCase):
    def make_iso(self, directory: str, sectors: int = 8) -> Path:
        image = Path(directory) / "test.iso"
        image.write_bytes(b"\0" * (sectors * 2048))
        return image

    def test_iso_validation_and_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = self.make_iso(tmp)
            self.assertEqual(macos_burn.validate_image(image), image.resolve())
            cmd = macos_burn.burn_command(image, device="drive-1", speed=4)
            self.assertEqual(cmd[:2], ["hdiutil", "burn"])
            self.assertIn("-verifyburn", cmd)
            self.assertIn("-nosynthesize", cmd)
            self.assertIn("-forceclose", cmd)
            self.assertEqual(cmd[-4:], ["-device", "drive-1", "-speed", "4"])

    def test_invalid_iso(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(macos_burn.MacBurnError):
                macos_burn.validate_image(Path(tmp) / "missing.iso")
            bad = Path(tmp) / "bad.iso"
            bad.write_bytes(b"not aligned")
            with self.assertRaises(macos_burn.MacBurnError):
                macos_burn.validate_image(bad)
            bad.write_bytes(b"")
            with self.assertRaises(macos_burn.MacBurnError):
                macos_burn.validate_image(bad)
            wrong = Path(tmp) / "movie.mkv"
            wrong.touch()
            with self.assertRaises(macos_burn.MacBurnError):
                macos_burn.validate_image(wrong)

    def test_speed_and_device_rejected(self):
        with self.assertRaises(macos_burn.MacBurnError):
            macos_burn.burn_command(Path("test.iso"), speed=0)
        with self.assertRaises(macos_burn.MacBurnError):
            macos_burn.burn_command(Path("test.iso"), speed=25)
        with self.assertRaises(macos_burn.MacBurnError):
            macos_burn.burn_command(Path("test.iso"), device="-erase")

    def test_dry_run_never_executes(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = self.make_iso(tmp)
            with patch("macos_burn.subprocess.run") as runner:
                self.assertEqual(macos_burn.main(["burn", str(image), "--dry-run"]), 0)
                runner.assert_not_called()

    def test_without_yes_never_executes(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = self.make_iso(tmp)
            with patch("macos_burn.subprocess.run") as runner:
                self.assertEqual(macos_burn.main(["burn", str(image)]), 1)
                runner.assert_not_called()

    def test_platform_guard(self):
        with patch("macos_burn.sys.platform", "linux"):
            with self.assertRaises(macos_burn.MacBurnError):
                macos_burn.list_drives()
            with self.assertRaises(macos_burn.MacBurnError):
                macos_burn.burn("/tmp/test.iso")

    def test_success_and_failure_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = self.make_iso(tmp)
            with patch("macos_burn.sys.platform", "darwin"), \
                 patch("macos_burn.subprocess.run") as runner:
                runner.return_value.returncode = 0
                macos_burn.burn(image)
                self.assertTrue(runner.called)
                runner.return_value.returncode = 2
                with self.assertRaises(macos_burn.MacBurnError):
                    macos_burn.burn(image)


if __name__ == "__main__":
    unittest.main()
