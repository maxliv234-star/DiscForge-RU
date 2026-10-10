import tempfile
import unittest
from pathlib import Path
from core import (DiscForgeError, bitrate_plan, CAPACITIES, parse_probe,
                  make_audio_command, make_video_command, write_meta, safe_name, unique_target)

DATA = {'format': {'duration': '5400.12', 'size': '1500000000'}, 'streams': [
    {'codec_type': 'video', 'codec_name': 'h264', 'width': 1920, 'height': 1080,
     'avg_frame_rate': '24000/1001', 'color_transfer': 'bt709'},
    {'codec_type': 'audio', 'codec_name': 'aac', 'channels': 6},
    {'codec_type': 'subtitle', 'codec_name': 'subrip'},
]}

class BackendTests(unittest.TestCase):
    def test_probe(self):
        info = parse_probe('film.mkv', DATA)
        self.assertEqual(info.audio_tracks, 1)
        self.assertEqual(info.subtitle_tracks, 1)
        self.assertFalse(info.is_hdr)
        self.assertEqual(info.width, 1920)
    def test_hdr_detection(self):
        import copy
        d = copy.deepcopy(DATA)
        d['streams'][0]['color_transfer'] = 'smpte2084'
        self.assertTrue(parse_probe('film.mkv', d).is_hdr)
    def test_missing_video(self):
        with self.assertRaises(DiscForgeError):
            parse_probe('empty', {'format': {'duration': 12}, 'streams': []})
    def test_budget(self):
        b = bitrate_plan(5400, 'BD25', True)
        self.assertGreater(b, 5_000_000)
        self.assertLessEqual(b, 28_000_000)
        self.assertLess((b + 640_000)*5400/8, CAPACITIES['BD25'])
    def test_too_long(self):
        with self.assertRaises(DiscForgeError):
            bitrate_plan(100_000, 'BD25', True)
    def test_commands(self):
        v = make_video_command('ffmpeg', 'a.mkv', 'b.h264', 17000000, False)
        self.assertIn('bluray-compat=1', v)
        self.assertIn('libx264', v)
        self.assertIn('h264_nvenc', make_video_command('ffmpeg', 'a.mkv', 'b.h264', 17000000, True))
        self.assertIn('6', make_audio_command('ffmpeg', 'a.mkv', 'audio.ac3', 6))
    def test_meta(self):
        with tempfile.TemporaryDirectory() as temp:
            f = Path(temp) / 'test.meta'
            write_meta(f, Path(temp)/'v.h264', Path(temp)/'a.ac3')
            contents = f.read_text(encoding='utf-8')
            self.assertIn('--blu-ray', contents)
            self.assertIn('V_MPEG4/ISO/AVC', contents)
            self.assertIn('A_AC3', contents)
    def test_safe_unique(self):
        self.assertEqual(safe_name('bad:name?.mkv'), 'bad_name_.mkv')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'Film.iso').touch()
            self.assertEqual(unique_target(root, 'Film', True).name, 'Film_2.iso')

if __name__ == '__main__':
    unittest.main()

class AuthoringTests(unittest.TestCase):
    def test_custom_chapters_written(self):
        with tempfile.TemporaryDirectory() as temp:
            f = Path(temp) / 'custom.meta'
            write_meta(f, Path(temp) / 'video.h264', None, [0, 120.5, 7234.001])
            text = f.read_text(encoding='utf-8')
            self.assertIn('--custom-chapters=00:00:00.000;00:02:00.500;02:00:34.001', text)
            self.assertNotIn('--auto-chapters', text)

    def test_custom_chapters_reject_wrong_order(self):
        with tempfile.TemporaryDirectory() as temp:
            f = Path(temp) / 'custom.meta'
            for chapters in ([120], [0, 200, 100], [0, 0], [0, float('inf')], []):
                with self.subTest(chapters=chapters):
                    with self.assertRaises(DiscForgeError):
                        write_meta(f, Path(temp) / 'video.h264', None, chapters)

    def test_pipeline_creates_folder_without_overwriting(self):
        import threading
        from unittest.mock import patch
        from core import create_bluray
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = root / 'film.mkv'
            video.write_bytes(b'fake source data')
            info = parse_probe(str(video), DATA)
            info = info.__class__(**{**vars(info), 'duration': 2.0})
            (root / 'film').mkdir()

            def encode(command, stage, pct_start, pct_width, duration, cancel, log, progress):
                Path(command[-1]).write_bytes(b'encoded')
                progress(pct_start + pct_width)

            def mux(binary, meta, target, cancel, log):
                bdmv = target / 'BDMV'
                for section in ('STREAM', 'PLAYLIST', 'CLIPINF', 'BACKUP'):
                    (bdmv / section).mkdir(parents=True)
                (target / 'CERTIFICATE').mkdir()
                for relative, magic in (
                    ('index.bdmv', b'INDX'), ('MovieObject.bdmv', b'MOBJ'),
                    ('PLAYLIST/00000.mpls', b'MPLS'), ('CLIPINF/00000.clpi', b'HDMV')):
                    (bdmv / relative).write_bytes(magic + b'0200')
                (bdmv / 'STREAM' / '00000.m2ts').write_bytes(bytes(4) + bytes([0x47]) + bytes(187))

            with patch('core._require_binary'), patch('core.run_command', side_effect=encode), \
                 patch('core.run_tsmuxer', side_effect=mux):
                result = create_bluray(info, 'BD25', str(root), 'ffmpeg', 'tsmuxer', False, False,
                                       threading.Event(), lambda msg: None, lambda pct: None, chapters=[0.0])
            self.assertEqual(result.name, 'film_2')
            self.assertTrue((result / 'BDMV' / 'STREAM' / '00000.m2ts').exists())

    def test_pipeline_rejects_invalid_bdmv_and_cleans_temporary(self):
        import threading
        from unittest.mock import patch
        from core import create_bluray
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = root / 'film.mkv'
            video.write_bytes(b'fake source')
            info = parse_probe(str(video), DATA)
            info = info.__class__(**{**vars(info), 'duration': 2.0})

            def encode(command, *args):
                Path(command[-1]).write_bytes(b'encoded')

            def invalid_mux(binary, meta, target, cancel, log):
                (target / 'BDMV' / 'STREAM').mkdir(parents=True)
                (target / 'BDMV' / 'STREAM' / '00000.m2ts').write_bytes(b'broken')

            with patch('core._require_binary'), patch('core.run_command', side_effect=encode), \
                 patch('core.run_tsmuxer', side_effect=invalid_mux):
                with self.assertRaisesRegex(DiscForgeError, 'Проверка BDMV не пройдена'):
                    create_bluray(info, 'BD25', str(root), 'ffmpeg', 'tsmuxer', False, False,
                                  threading.Event(), lambda msg: None, lambda pct: None)
            self.assertFalse((root / 'film').exists())
            self.assertEqual(list(root.glob('DiscForge_work_*')), [])

    def test_pipeline_rejects_large_iso_and_cleans_temporary(self):
        import threading
        from unittest.mock import patch
        from core import create_bluray
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = root / 'film.mkv'
            video.write_bytes(b'fake source')
            info = parse_probe(str(video), DATA)
            info = info.__class__(**{**vars(info), 'duration': 2.0})

            def encode(command, *args):
                Path(command[-1]).write_bytes(b'encoded')

            def mux(binary, meta, target, cancel, log):
                with target.open('wb') as f:
                    f.truncate(CAPACITIES['BD25'] + 1)

            with patch('core._require_binary'), patch('core.run_command', side_effect=encode), \
                 patch('core.run_tsmuxer', side_effect=mux), \
                 patch('core.bitrate_plan', return_value=5_000_000), \
                 patch.dict(CAPACITIES, {'BD25': 100}):
                with self.assertRaisesRegex(DiscForgeError, 'превышает'):
                    create_bluray(info, 'BD25', str(root), 'ffmpeg', 'tsmuxer', True, False,
                                  threading.Event(), lambda msg: None, lambda pct: None)
            self.assertFalse((root / 'film.iso').exists())
            self.assertEqual(list(root.glob('DiscForge_work_*')), [])
