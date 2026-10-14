"""Fail-closed macOS ISO mount setup regressions (no real disc or mounts)."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import macos_burn
from tools import macos_mounted_bdmv as mount


class MountSetupFailures(unittest.TestCase):
    def test_unavailable_temp_directory_does_not_attach(self):
        with (patch.object(mount.sys, "platform", "darwin"),
              patch.object(mount.tempfile, "mkdtemp",
                           side_effect=PermissionError("temp offline")),
              patch.object(mount.subprocess, "run") as runner):
            with self.assertRaisesRegex(
                mount.MountedBDMVError, "создать временную.*temp offline"
            ):
                mount.inspect_mounted_bdmv("film.iso", profile="BD25")
            runner.assert_not_called()

    def test_cli_refuses_to_burn_if_mount_setup_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "film.iso"
            image.write_bytes(bytes(300 * 2048))
            err = io.StringIO()
            with (patch.object(mount.sys, "platform", "darwin"),
                  patch("macos_burn.inspect_udf",
                        return_value=SimpleNamespace(valid=True, errors=[])),
                  patch.object(mount.tempfile, "mkdtemp",
                               side_effect=OSError("temporary storage offline")),
                  patch.object(mount.subprocess, "run") as runner,
                  contextlib.redirect_stderr(err)):
                self.assertEqual(macos_burn.main(
                    ["burn", str(image), "--inspect-bdmv", "--device", "mock-recorder", "--yes"]
                ), 1)
                runner.assert_not_called()
            self.assertIn("временную точку", err.getvalue())

    def test_partial_attach_mount_probe_runtime_error_is_wrapped(self):
        failed = SimpleNamespace(returncode=1, stdout="", stderr="attach failed")
        with (patch.object(mount.sys, "platform", "darwin"),
              patch.object(Path, "is_mount", side_effect=RuntimeError("bad mount path")),
              patch.object(mount.subprocess, "run", return_value=failed) as runner):
            with self.assertRaisesRegex(
                mount.MountedBDMVError, "проверить состояние точки монтирования"
            ):
                mount.inspect_mounted_bdmv("film.iso", profile="BD25")
            runner.assert_called_once()

    def test_hdiutil_output_decoding_is_loss_tolerant(self):
        ok = SimpleNamespace(returncode=0, stdout="", stderr="")
        report = SimpleNamespace(structurally_valid=True, errors=[])
        with (patch.object(mount.sys, "platform", "darwin"),
              patch.object(mount, "inspect_bdmv", return_value=report),
              patch.object(mount.subprocess, "run", side_effect=[ok, ok]) as runner):
            mount.inspect_mounted_bdmv("film.iso", profile="BD25")
        self.assertEqual(
            [call.kwargs.get("errors") for call in runner.call_args_list],
            ["replace", "replace"]
        )


if __name__ == "__main__":
    unittest.main()
