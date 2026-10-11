"""ISO authoring must not expose corrupted images as finished BD25/BD50 output."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from core import DiscForgeError, MediaInfo, create_bluray


class ISOPipelineTests(unittest.TestCase):
    def test_invalid_iso_never_published(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'film.mkv'
            source.write_bytes(b'fake input')
            info = MediaInfo(
                path=str(source), duration=60.0, size=10,
                video_codec='h264', width=1920, height=1080,
                video_fps='24000/1001', video_color_transfer='bt709',
                audio_codec='aac', audio_channels=2, audio_tracks=1,
                subtitle_tracks=0,
            )

            def encode(command, *_args):
                Path(command[-1]).write_bytes(b'fake elementary stream')

            def mux(_binary, _meta, destination, _cancel, _log):
                destination.write_bytes(b'\0' * 2048)  # Not UDF 2.50.

            with patch('core._require_binary'), \
                 patch('core.run_command', side_effect=encode), \
                 patch('core.run_tsmuxer', side_effect=mux):
                with self.assertRaisesRegex(DiscForgeError, 'UDF 2.50'):
                    create_bluray(
                        info, 'BD25', str(root), 'ffmpeg', 'tsmuxer',
                        True, False, threading.Event(), lambda _: None,
                        lambda _: None,
                    )
            self.assertFalse((root / 'film.iso').exists())
            self.assertEqual(list(root.glob('DiscForge_work_*')), [])
