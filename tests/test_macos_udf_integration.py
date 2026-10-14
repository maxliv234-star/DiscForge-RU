"""Integration regressions for the macOS UDF burn gate (synthetic images only).

The fixtures contain valid UDF 2.50 *metadata*, not a mountable Blu-ray.
All optical writer calls are mocked. These checks are not hardware tests.
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import macos_burn
from test_iso_udf_preflight import iso_fixture
from tools.iso_udf_preflight import SECTOR_SIZE


class MacBurnUDFIntegrationTests(unittest.TestCase):
    def test_valid_udf_check_without_macos_or_recorder(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "film.iso"
            iso_fixture(image)
            with patch("macos_burn.subprocess.run") as runner, \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(macos_burn.main(["check", str(image)]), 0)
            runner.assert_not_called()
            self.assertIn("UDF 2.50", output.getvalue())

    def test_valid_udf_dry_run_without_recorder(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "film.iso"
            iso_fixture(image)
            with patch("macos_burn.subprocess.run") as runner, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    macos_burn.main(["burn", str(image), "--dry-run", "--profile", "BD25"]), 0)
            runner.assert_not_called()

    def test_valid_udf_reaches_writer_only_after_preflight(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "film.iso"
            iso_fixture(image)
            with patch("macos_burn.sys.platform", "darwin"), \
                 patch("macos_burn.subprocess.run",
                       return_value=SimpleNamespace(returncode=0)) as runner:
                macos_burn.burn(image, profile="BD25", speed=2)
            runner.assert_called_once()
            command = runner.call_args.args[0]
            self.assertEqual(command[:3], ["hdiutil", "burn", str(image.resolve())])
            self.assertIn("-verifyburn", command)

    def test_corrupt_lvd_never_reaches_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "film.iso"
            iso_fixture(image)
            with image.open("r+b") as handle:
                handle.seek(32 * SECTOR_SIZE + 240)
                handle.write(b"\\x60")  # Wrong CRC for UDF revision.
            with patch("macos_burn.sys.platform", "darwin"), \
                 patch("macos_burn.subprocess.run") as runner:
                with self.assertRaisesRegex(macos_burn.MacBurnError, "UDF 2.50"):
                    macos_burn.burn(image)
            runner.assert_not_called()

    def test_valid_udf_rejected_when_selected_bd25_is_too_small(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "film.iso"
            iso_fixture(image)
            with patch.dict(macos_burn.CAPACITIES, {"BD25": 300_000}):
                with self.assertRaisesRegex(macos_burn.MacBurnError, "BD25"):
                    macos_burn.validate_for_burning(image, profile="BD25")
                self.assertEqual(
                    macos_burn.validate_for_burning(image, profile="BD50"),
                    image.resolve())


if __name__ == "__main__":
    unittest.main()
