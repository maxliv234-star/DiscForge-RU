"""Regression tests: standard 1080p BD25/BD50 are the only authoring profiles."""
import contextlib
import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import main as cli_main
from core import CAPACITIES, DiscForgeError, bitrate_plan, create_bluray, parse_probe


class FullHDProfileTests(unittest.TestCase):
    def test_only_bd25_bd50_exposed_to_cli_and_backend(self):
        self.assertEqual(set(CAPACITIES), {"BD25", "BD50"})
        self.assertEqual(CAPACITIES["BD25"], 25_000_000_000)
        self.assertEqual(CAPACITIES["BD50"], 50_000_000_000)
        for profile in ("BDXL100", "UHD", "BD100", "BD66"):
            with self.subTest(profile=profile):
                with self.assertRaises(DiscForgeError):
                    bitrate_plan(5400, profile, True)
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as exit_code:
                        cli_main(["build", "movie.mkv", "--profile", profile])
                self.assertEqual(exit_code.exception.code, 2)

    def test_valid_bd50_budget(self):
        self.assertGreater(bitrate_plan(5400, "BD50", True), 0)

    def test_unsupported_profile_rejected_before_job_output_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "video.mp4"
            source.write_bytes(b"synthetic video placeholder")
            info = parse_probe(str(source), {
                "format": {"duration": "60", "size": "27"},
                "streams": [
                    {"codec_type": "video", "codec_name": "h264",
                     "width": 1920, "height": 1080, "avg_frame_rate": "24000/1001"},
                ],
            })
            output = Path(tmp) / "out"
            with patch("core._require_binary"):
                with self.assertRaises(DiscForgeError):
                    create_bluray(
                        info, "BDXL100", str(output), "ffmpeg", "tsmuxer",
                        False, False, threading.Event(), lambda _: None,
                        lambda _: None,
                    )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
