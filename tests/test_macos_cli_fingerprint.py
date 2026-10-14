"""CLI integrity regression tests; no optical drive or real ISO is used."""
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import macos_burn


GOOD = SimpleNamespace(valid=True, errors=[])


class MacCLIIntegrityTests(unittest.TestCase):
    def make_iso(self, directory):
        image = Path(directory) / "film.iso"
        image.write_bytes(b"\0" * (300 * 2048))
        return image

    def test_check_rejects_replacement_after_preflight(self):
        with tempfile.TemporaryDirectory() as folder:
            image = self.make_iso(folder)
            original_validate = macos_burn._validated_image_with_identity

            def replace_after_preflight(*args, **kwargs):
                checked, fingerprint = original_validate(*args, **kwargs)
                other = Path(folder) / "other.iso"
                other.write_bytes(b"Z" * (300 * 2048))
                other.replace(checked)
                return checked, fingerprint

            with (patch("macos_burn.inspect_udf", return_value=GOOD),
                  patch("macos_burn._validated_image_with_identity",
                        side_effect=replace_after_preflight),
                  patch("macos_burn.subprocess.run") as writer,
                  patch("macos_burn.sys.stderr", new_callable=io.StringIO) as err):
                self.assertEqual(macos_burn.main(["check", str(image)]), 1)
                self.assertIn("ISO изменился", err.getvalue())
                writer.assert_not_called()

    def test_dry_run_rejects_change_while_building_command(self):
        with tempfile.TemporaryDirectory() as folder:
            image = self.make_iso(folder)
            original_command = macos_burn.burn_command

            def mutate_before_print(path, device=None, speed=None):
                path.write_bytes(b"Q" * (301 * 2048))
                return original_command(path, device=device, speed=speed)

            with (patch("macos_burn.inspect_udf", return_value=GOOD),
                  patch("macos_burn.burn_command", side_effect=mutate_before_print),
                  patch("macos_burn.subprocess.run") as writer,
                  patch("macos_burn.sys.stderr", new_callable=io.StringIO) as err):
                self.assertEqual(macos_burn.main(["burn", str(image), "--dry-run"]), 1)
                self.assertIn("ISO изменился", err.getvalue())
                writer.assert_not_called()

    def test_check_and_dry_run_accept_unchanged_iso(self):
        with tempfile.TemporaryDirectory() as folder:
            image = self.make_iso(folder)
            with (patch("macos_burn.inspect_udf", return_value=GOOD),
                  patch("macos_burn.subprocess.run") as writer,
                  patch("builtins.print")):
                self.assertEqual(macos_burn.main(["check", str(image)]), 0)
                self.assertEqual(macos_burn.main(["burn", str(image), "--dry-run"]), 0)
                writer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
