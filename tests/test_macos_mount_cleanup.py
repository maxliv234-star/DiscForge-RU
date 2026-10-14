"""Regression tests: partial macOS ISO attachment must fail closed and clean up safely.

All subprocess calls are mocked. No real images, mounts or drives are accessed.
"""
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools import macos_mounted_bdmv as mount


def result(returncode=0, stderr=""):
    return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)


class MountedCleanupTests(unittest.TestCase):
    def test_attach_error_with_partial_mount_detaches_before_failure(self):
        with patch.object(mount.sys, "platform", "darwin"), \
             patch.object(Path, "is_mount", return_value=True), \
             patch.object(mount.subprocess, "run",
                          side_effect=[result(1, "attach failed"), result()]) as runner:
            with self.assertRaisesRegex(mount.MountedBDMVError, "attach failed"):
                mount.inspect_mounted_bdmv("film.iso", profile="BD25")
        self.assertEqual(runner.call_count, 2)
        self.assertEqual(runner.call_args_list[1].args[0][:2], ["hdiutil", "detach"])
        self.assertNotIn("-force", runner.call_args_list[1].args[0])

    def test_attach_timeout_with_partial_mount_detaches_before_failure(self):
        with patch.object(mount.sys, "platform", "darwin"), \
             patch.object(Path, "is_mount", return_value=True), \
             patch.object(mount.subprocess, "run", side_effect=[
                 subprocess.TimeoutExpired("hdiutil", 120), result()
             ]) as runner:
            with self.assertRaisesRegex(mount.MountedBDMVError, "смонтировать"):
                mount.inspect_mounted_bdmv("film.iso", profile="BD50")
        self.assertEqual(runner.call_count, 2)
        self.assertEqual(runner.call_args_list[1].args[0][:2], ["hdiutil", "detach"])

    def test_failed_partial_mount_cleanup_is_reported(self):
        with patch.object(mount.sys, "platform", "darwin"), \
             patch.object(Path, "is_mount", return_value=True), \
             patch.object(mount.subprocess, "run",
                          side_effect=[result(1, "partial attach"),
                                       result(16, "volume busy")]) as runner:
            with self.assertRaisesRegex(mount.MountedBDMVError, "мог остаться смонтированным.*volume busy"):
                mount.inspect_mounted_bdmv("film.iso", profile="BD25")
        self.assertEqual(runner.call_count, 2)

    def test_unmounted_attach_error_does_not_detach(self):
        with patch.object(mount.sys, "platform", "darwin"), \
             patch.object(Path, "is_mount", return_value=False), \
             patch.object(mount.subprocess, "run", return_value=result(1, "invalid ISO")) as runner:
            with self.assertRaisesRegex(mount.MountedBDMVError, "invalid ISO"):
                mount.inspect_mounted_bdmv("film.iso", profile="BD25")
        runner.assert_called_once()

    def test_failed_detach_does_not_recursively_delete_mounted_contents(self):
        state = {}
        report = SimpleNamespace(structurally_valid=True, errors=[])

        def simulate_hdiutil(command, **kwargs):
            if command[1] == "attach":
                mp = Path(command[command.index("-mountpoint") + 1])
                payload = mp / "BDMV" / "STREAM" / "00000.m2ts"
                payload.parent.mkdir(parents=True)
                payload.write_bytes(b"untouched")
                state["mountpoint"], state["payload"] = mp, payload
                return result()
            self.assertEqual(command[1], "detach")
            return result(16, "volume busy")

        try:
            with patch.object(mount.sys, "platform", "darwin"), \
                 patch.object(mount, "inspect_bdmv", return_value=report), \
                 patch.object(mount.subprocess, "run", side_effect=simulate_hdiutil):
                with self.assertRaisesRegex(mount.MountedBDMVError, "volume busy"):
                    mount.inspect_mounted_bdmv("film.iso", profile="BD25")
            self.assertTrue(state["payload"].exists())
            self.assertEqual(state["payload"].read_bytes(), b"untouched")
        finally:
            # Only test-created mock files are removed here; production never rmtree's a mount.
            if "mountpoint" in state:
                shutil.rmtree(state["mountpoint"])


if __name__ == "__main__":
    unittest.main()
