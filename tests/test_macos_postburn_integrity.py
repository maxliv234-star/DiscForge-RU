"""No-hardware regression: do not report burn success after source ISO changed.

The optical writer and UDF inspector are mocked; this is not a disc test.
"""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import macos_burn


GOOD = SimpleNamespace(valid=True, errors=[])


class MacPostburnIntegrityTests(unittest.TestCase):
    def make_image(self, directory: str) -> Path:
        image = Path(directory) / "film.iso"
        image.write_bytes(bytes(300 * 2048))
        return image

    def test_writer_success_with_resized_source_must_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            image = self.make_image(folder)

            def fake_burn(command, **kwargs):
                self.assertEqual(command[:2], ["hdiutil", "burn"])
                image.write_bytes(bytes(301 * 2048))
                return SimpleNamespace(returncode=0)

            with patch("macos_burn.sys.platform", "darwin"), \
                 patch("macos_burn.inspect_udf", return_value=GOOD), \
                 patch("macos_burn.subprocess.run", side_effect=fake_burn) as writer:
                with self.assertRaisesRegex(macos_burn.MacBurnError, "ISO изменился"):
                    macos_burn.burn(image)
                writer.assert_called_once()

    def test_writer_success_with_disconnected_source_must_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            image = self.make_image(folder)

            def fake_burn(command, **kwargs):
                image.unlink()
                return SimpleNamespace(returncode=0)

            with patch("macos_burn.sys.platform", "darwin"), \
                 patch("macos_burn.inspect_udf", return_value=GOOD), \
                 patch("macos_burn.subprocess.run", side_effect=fake_burn):
                with self.assertRaisesRegex(macos_burn.MacBurnError, "ISO стал недоступен"):
                    macos_burn.burn(image)

    def test_cli_never_claims_success_if_source_replaced_during_burn(self):
        with tempfile.TemporaryDirectory() as folder:
            image = self.make_image(folder)

            def fake_burn(command, **kwargs):
                replacement = Path(folder) / "replacement.iso"
                replacement.write_bytes(bytes(300 * 2048))
                replacement.replace(image)
                return SimpleNamespace(returncode=0)

            stdout, stderr = io.StringIO(), io.StringIO()
            with patch("macos_burn.sys.platform", "darwin"), \
                 patch("macos_burn.inspect_udf", return_value=GOOD), \
                 patch("macos_burn.subprocess.run", side_effect=fake_burn), \
                 contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(macos_burn.main(["burn", str(image), "--device", "mock-recorder", "--yes"]), 1)
            self.assertIn("ISO изменился", stderr.getvalue())
            self.assertNotIn("сообщил об успешной записи", stdout.getvalue())

    def test_unchanged_source_still_succeeds(self):
        with tempfile.TemporaryDirectory() as folder:
            image = self.make_image(folder)
            with patch("macos_burn.sys.platform", "darwin"), \
                 patch("macos_burn.inspect_udf", return_value=GOOD), \
                 patch("macos_burn.subprocess.run",
                       return_value=SimpleNamespace(returncode=0)) as writer:
                macos_burn.burn(image)
                writer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
