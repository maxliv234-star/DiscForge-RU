"""No-hardware regression tests for macOS ISO mutation during preflight."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import macos_burn


GOOD = SimpleNamespace(valid=True, errors=[])


class MacISOIntegrityTests(unittest.TestCase):
    def make_iso(self, directory):
        image = Path(directory) / "film.iso"
        image.write_bytes(bytes(8 * 2048))
        return image

    def test_resize_during_udf_check_blocks_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            image = self.make_iso(folder)

            def resize(path, *, profile):
                path.write_bytes(bytes(9 * 2048))
                return GOOD

            with (patch("macos_burn.sys.platform", "darwin"),
                  patch("macos_burn.inspect_udf", side_effect=resize),
                  patch("macos_burn.subprocess.run") as writer):
                with self.assertRaisesRegex(macos_burn.MacBurnError, "ISO изменился"):
                    macos_burn.burn(image)
                writer.assert_not_called()

    def test_replacement_during_bdmv_check_blocks_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            image = self.make_iso(folder)

            def replace(path, *, profile):
                replacement = Path(folder) / "replacement.iso"
                replacement.write_bytes(b"X" * (8 * 2048))
                replacement.replace(path)

            with (patch("macos_burn.sys.platform", "darwin"),
                  patch("macos_burn.inspect_udf", return_value=GOOD),
                  patch("tools.macos_mounted_bdmv.inspect_mounted_bdmv", side_effect=replace),
                  patch("macos_burn.subprocess.run") as writer):
                with self.assertRaisesRegex(macos_burn.MacBurnError, "ISO изменился"):
                    macos_burn.burn(image, inspect_bdmv=True)
                writer.assert_not_called()

    def test_deletion_during_udf_check_blocks_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            image = self.make_iso(folder)

            def delete(path, *, profile):
                path.unlink()
                return GOOD

            with (patch("macos_burn.sys.platform", "darwin"),
                  patch("macos_burn.inspect_udf", side_effect=delete),
                  patch("macos_burn.subprocess.run") as writer):
                with self.assertRaisesRegex(macos_burn.MacBurnError, "недоступен"):
                    macos_burn.burn(image)
                writer.assert_not_called()

    def test_change_while_building_command_blocks_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            image = self.make_iso(folder)
            real_command = macos_burn.burn_command

            def mutate(path, device=None, speed=None):
                path.write_bytes(bytes(9 * 2048))
                return real_command(path, device=device, speed=speed)

            with (patch("macos_burn.sys.platform", "darwin"),
                  patch("macos_burn.inspect_udf", return_value=GOOD),
                  patch("macos_burn.burn_command", side_effect=mutate),
                  patch("macos_burn.subprocess.run") as writer):
                with self.assertRaisesRegex(macos_burn.MacBurnError, "ISO изменился"):
                    macos_burn.burn(image)
                writer.assert_not_called()

    def test_unchanged_iso_can_reach_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            image = self.make_iso(folder)
            with (patch("macos_burn.sys.platform", "darwin"),
                  patch("macos_burn.inspect_udf", return_value=GOOD),
                  patch("macos_burn.subprocess.run",
                        return_value=SimpleNamespace(returncode=0)) as writer):
                macos_burn.burn(image)
                writer.assert_called_once()


    def test_replacement_after_preflight_return_blocks_writer(self):
        """A new fingerprint after validation would silently trust a swapped ISO."""
        with tempfile.TemporaryDirectory() as folder:
            image = self.make_iso(folder)
            original_validator = macos_burn._validated_image_with_identity

            def swap_between_preflight_and_writer(*args, **kwargs):
                checked, fingerprint = original_validator(*args, **kwargs)
                replacement = Path(folder) / "other.iso"
                replacement.write_bytes(b"R" * (8 * 2048))
                replacement.replace(checked)
                return checked, fingerprint

            with (patch("macos_burn.sys.platform", "darwin"),
                  patch("macos_burn.inspect_udf", return_value=GOOD),
                  patch("macos_burn._validated_image_with_identity",
                        side_effect=swap_between_preflight_and_writer),
                  patch("macos_burn.subprocess.run") as writer):
                with self.assertRaisesRegex(macos_burn.MacBurnError, "ISO изменился"):
                    macos_burn.burn(image)
                writer.assert_not_called()

if __name__ == "__main__":
    unittest.main()
