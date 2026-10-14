"""Hardware-free regression tests for transient macOS ISO filesystem I/O errors."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import macos_burn


class MacISOIOErrorTests(unittest.TestCase):
    def test_iso_disappears_between_file_check_and_stat(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "film.iso"
            image.write_bytes(b"\0" * 2048)
            target = image.resolve()
            original_stat = Path.stat
            calls = 0

            def fail_second_stat(path, *args, **kwargs):
                nonlocal calls
                if path == target:
                    calls += 1
                    if calls == 2:
                        raise PermissionError("NAS disconnected after is_file")
                return original_stat(path, *args, **kwargs)

            with patch.object(Path, "stat", fail_second_stat):
                with self.assertRaisesRegex(macos_burn.MacBurnError, "Не удалось прочитать ISO"):
                    macos_burn.validate_image(image)
            self.assertEqual(calls, 2)

    def test_resolution_error_is_wrapped(self):
        with patch.object(Path, "resolve", side_effect=OSError("mount unavailable")):
            with self.assertRaisesRegex(macos_burn.MacBurnError, "mount unavailable"):
                macos_burn.validate_image("/Volumes/Offline/disc.iso")

    def test_symlink_probe_io_error_is_wrapped(self):
        with patch.object(Path, "is_symlink", side_effect=OSError("network path unavailable")):
            with self.assertRaisesRegex(macos_burn.MacBurnError, "Не удалось проверить путь ISO"):
                macos_burn._validated_image_with_identity("/Volumes/Offline/disc.iso")

    def test_normal_aligned_iso_is_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "film.iso"
            image.write_bytes(b"\0" * (3 * 2048))
            self.assertEqual(macos_burn.validate_image(image), image.resolve())


    def test_udf_reader_io_failure_blocks_optical_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "film.iso"
            image.write_bytes(b"\0" * (300 * 2048))
            with patch("macos_burn.sys.platform", "darwin"), \
                 patch("macos_burn.inspect_udf", side_effect=PermissionError("NAS disconnected")), \
                 patch("macos_burn.subprocess.run") as writer:
                with self.assertRaisesRegex(macos_burn.MacBurnError, "Не удалось прочитать UDF 2.50"):
                    macos_burn.burn(image)
                writer.assert_not_called()

    def test_udf_reader_io_failure_returns_controlled_cli_error(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "film.iso"
            image.write_bytes(b"\0" * (300 * 2048))
            with patch("macos_burn.inspect_udf", side_effect=OSError("USB unavailable")), \
                 patch("macos_burn.subprocess.run") as writer:
                for arguments in (["check", str(image)], ["burn", str(image), "--dry-run"]):
                    with self.subTest(arguments=arguments), \
                         patch("macos_burn.sys.stderr", new_callable=io.StringIO) as error:
                        self.assertEqual(macos_burn.main(arguments), 1)
                        self.assertIn("ОШИБКА:", error.getvalue())
                        self.assertIn("USB unavailable", error.getvalue())
                writer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
