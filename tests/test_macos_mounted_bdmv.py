"""Hardware-free tests for optional read-only ISO BDMV inspection."""
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools import macos_mounted_bdmv as mount


class MacMountedBDMVTests(unittest.TestCase):
    def test_mount_is_read_only_and_detaches_on_valid_report(self):
        ok = SimpleNamespace(returncode=0, stdout="", stderr="")
        report = SimpleNamespace(structurally_valid=True, errors=[])
        with patch.object(mount.sys, "platform", "darwin"), \
             patch.object(mount, "inspect_bdmv", return_value=report) as inspector, \
             patch.object(mount.subprocess, "run", side_effect=[ok, ok]) as runner:
            mount.inspect_mounted_bdmv(Path("film.iso"), profile="BD25")
        attach = runner.call_args_list[0]
        detach = runner.call_args_list[1]
        self.assertEqual(attach.args[0][:4], ["hdiutil", "attach", "-readonly", "-nobrowse"])
        self.assertEqual(attach.args[0][-1], "film.iso")
        self.assertEqual(detach.args[0], ["hdiutil", "detach", attach.args[0][-2]])
        self.assertEqual(inspector.call_args.kwargs["profile"], "BD25")
        self.assertEqual(inspector.call_args.args[0], Path(attach.args[0][-2]))
        self.assertEqual(runner.call_count, 2)

    def test_invalid_bdmv_rejected_and_detached(self):
        ok = SimpleNamespace(returncode=0, stdout="", stderr="")
        bad = SimpleNamespace(structurally_valid=False, errors=["Missing BDMV directory"])
        with patch.object(mount.sys, "platform", "darwin"), \
             patch.object(mount, "inspect_bdmv", return_value=bad), \
             patch.object(mount.subprocess, "run", side_effect=[ok, ok]) as runner:
            with self.assertRaisesRegex(mount.MountedBDMVError, "Missing BDMV"):
                mount.inspect_mounted_bdmv("film.iso", profile="BD50")
        self.assertEqual(runner.call_count, 2)

    def test_attach_failure_never_inspects_or_detaches(self):
        bad = SimpleNamespace(returncode=1, stdout="", stderr="invalid filesystem")
        with patch.object(mount.sys, "platform", "darwin"), \
             patch.object(mount, "inspect_bdmv") as inspector, \
             patch.object(mount.subprocess, "run", return_value=bad) as runner:
            with self.assertRaisesRegex(mount.MountedBDMVError, "invalid filesystem"):
                mount.inspect_mounted_bdmv("film.iso", profile="BD25")
        runner.assert_called_once()
        inspector.assert_not_called()

    def test_detach_failure_blocks_success(self):
        ok = SimpleNamespace(returncode=0, stdout="", stderr="")
        fail = SimpleNamespace(returncode=1, stdout="", stderr="busy")
        report = SimpleNamespace(structurally_valid=True, errors=[])
        with patch.object(mount.sys, "platform", "darwin"), \
             patch.object(mount, "inspect_bdmv", return_value=report), \
             patch.object(mount.subprocess, "run", side_effect=[ok, fail]):
            with self.assertRaisesRegex(mount.MountedBDMVError, "busy"):
                mount.inspect_mounted_bdmv("film.iso", profile="BD25")

    def test_inspection_error_still_detaches(self):
        ok = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(mount.sys, "platform", "darwin"), \
             patch.object(mount, "inspect_bdmv", side_effect=ValueError("bad header")), \
             patch.object(mount.subprocess, "run", side_effect=[ok, ok]) as runner:
            with self.assertRaisesRegex(mount.MountedBDMVError, "bad header"):
                mount.inspect_mounted_bdmv("film.iso", profile="BD25")
        self.assertEqual(runner.call_count, 2)

    def test_unsupported_platform_and_profile_never_mount(self):
        with patch.object(mount.sys, "platform", "linux"), \
             patch.object(mount.subprocess, "run") as runner:
            with self.assertRaisesRegex(mount.MountedBDMVError, "macOS"):
                mount.inspect_mounted_bdmv("film.iso", profile="BD25")
            runner.assert_not_called()
        with patch.object(mount.sys, "platform", "darwin"), \
             patch.object(mount.subprocess, "run") as runner:
            with self.assertRaisesRegex(mount.MountedBDMVError, "BD25"):
                mount.inspect_mounted_bdmv("film.iso", profile="BDXL100")
            runner.assert_not_called()

    def test_attach_timeout_never_inspects(self):
        with patch.object(mount.sys, "platform", "darwin"), \
             patch.object(mount, "inspect_bdmv") as inspector, \
             patch.object(mount.subprocess, "run", side_effect=subprocess.TimeoutExpired("hdiutil", 120)):
            with self.assertRaisesRegex(mount.MountedBDMVError, "смонтировать"):
                mount.inspect_mounted_bdmv("film.iso", profile="BD25")
            inspector.assert_not_called()


if __name__ == "__main__":
    unittest.main()
