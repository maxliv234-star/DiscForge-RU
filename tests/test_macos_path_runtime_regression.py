"""Path-handling regressions: malformed ISO paths must fail closed without hardware."""
import contextlib
import io
import unittest
from pathlib import Path
from unittest.mock import patch

import macos_burn


class MacOSPathRuntimeTests(unittest.TestCase):
    def test_resolve_runtime_error_is_wrapped(self):
        # Python 3.11/3.12 pathlib can use RuntimeError for symlink loops.
        with patch.object(Path, "resolve", side_effect=RuntimeError("Symlink loop")):
            with self.assertRaisesRegex(macos_burn.MacBurnError, "Не удалось прочитать ISO"):
                macos_burn.validate_image("loop/film.iso")

    def test_check_path_loop_reports_error_before_udf_read(self):
        stderr = io.StringIO()
        with (
            patch.object(Path, "resolve", side_effect=RuntimeError("Symlink loop")),
            patch("macos_burn.inspect_udf") as reader,
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(macos_burn.main(["check", "loop/film.iso"]), 1)
            reader.assert_not_called()
        self.assertIn("ОШИБКА:", stderr.getvalue())
        self.assertIn("Symlink loop", stderr.getvalue())

    def test_burn_cannot_start_when_home_expansion_fails(self):
        # Frozen or service-like environments may have no usable home directory.
        stderr = io.StringIO()
        with (
            patch.object(Path, "expanduser", side_effect=RuntimeError("No home directory")),
            patch("macos_burn.sys.platform", "darwin"),
            patch("macos_burn.subprocess.run") as writer,
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(macos_burn.main(["burn", "~/film.iso", "--device", "mock-recorder", "--yes"]), 1)
            writer.assert_not_called()
        self.assertIn("Не удалось проверить путь ISO", stderr.getvalue())

    def test_symlink_probe_runtime_error_is_wrapped(self):
        stderr = io.StringIO()
        with (
            patch.object(Path, "is_symlink", side_effect=RuntimeError("Invalid path")),
            patch("macos_burn.inspect_udf") as reader,
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(macos_burn.main(["check", "film.iso"]), 1)
            reader.assert_not_called()
        self.assertIn("Не удалось проверить путь ISO", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
