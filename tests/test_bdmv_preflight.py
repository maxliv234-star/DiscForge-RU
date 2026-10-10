import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bdmv_preflight import CAPACITIES, inspect

def fixture(root):
    b = root / "BDMV"
    for d in ("PLAYLIST", "CLIPINF", "STREAM", "BACKUP"):
        (b / d).mkdir(parents=True)
    (root / "CERTIFICATE").mkdir()
    for name, payload in (("index.bdmv", b"INDX0200"),
                          ("MovieObject.bdmv", b"MOBJ0200"),
                          ("PLAYLIST/00000.mpls", b"MPLS0200"),
                          ("CLIPINF/00000.clpi", b"HDMV0200"),
                          ("STREAM/00000.m2ts", b"\x47" * 192)):
        (b / name).write_bytes(payload)

class BDMVPreflightTests(unittest.TestCase):
    def test_minimal_fixture(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture(Path(temp))
            result = inspect(Path(temp))
            self.assertTrue(result.structurally_valid, result.errors)
            self.assertIn("UNVERIFIED", result.warnings[-1])

    def test_missing_and_bad_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            (root / "BDMV/index.bdmv").write_bytes(b"WRONG")
            self.assertFalse(inspect(root).structurally_valid)
            (root / "BDMV/PLAYLIST/00000.mpls").unlink()
            self.assertFalse(inspect(root).structurally_valid)

    def test_rejects_nonstandard_blu_ray_filenames(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            directory = root / "BDMV/PLAYLIST"
            (directory / "00000.mpls").rename(directory / "movie.mpls")
            result = inspect(root)
            self.assertFalse(result.structurally_valid)
            self.assertTrue(any("filename" in error for error in result.errors))

    def test_clip_info_matches_the_stream_number(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            directory = root / "BDMV/CLIPINF"
            (directory / "00000.clpi").rename(directory / "00001.clpi")
            result = inspect(root)
            self.assertFalse(result.structurally_valid)
            self.assertTrue(any("matching CLIPINF" in error for error in result.errors))
            self.assertTrue(any("matching STREAM" in error for error in result.errors))

    def test_invalid_stream_size(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            (root / "BDMV/STREAM/00000.m2ts").write_bytes(b"123")
            self.assertFalse(inspect(root).structurally_valid)

    def test_capacity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            with patch.dict(CAPACITIES, {"BD25": 100}):
                self.assertFalse(inspect(root).structurally_valid)

    def test_bdxl_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            self.assertFalse(inspect(root, "BDXL100").structurally_valid)
            self.assertTrue(inspect(root, "BD50").structurally_valid)

    def test_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            try:
                (root / "BDMV/alias").symlink_to(root / "BDMV/index.bdmv")
            except (OSError, NotImplementedError):
                self.skipTest("No symlinks")
            self.assertFalse(inspect(root).structurally_valid)

    def test_missing_root(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(inspect(Path(temp) / "absent").structurally_valid)

    def test_no_backup_is_warning(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            (root / "BDMV/BACKUP").rmdir()
            result = inspect(root)
            self.assertTrue(result.structurally_valid)
            self.assertTrue(any("BACKUP" in warning for warning in result.warnings))


    def test_metadata_version_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            (root / "BDMV/index.bdmv").write_bytes(b"INDX0300")
            result = inspect(root)
            self.assertFalse(result.structurally_valid)
            self.assertTrue(any("version" in e for e in result.errors))


    def test_all_metadata_headers_reject_bad_versions(self):
        for name in ("index.bdmv", "MovieObject.bdmv",
                     "PLAYLIST/00000.mpls", "CLIPINF/00000.clpi"):
            for suffix in (b"0300", b"02", b""):
                with self.subTest(name=name, suffix=suffix):
                    with tempfile.TemporaryDirectory() as temp:
                        root = Path(temp)
                        fixture(root)
                        path = root / "BDMV" / name
                        path.write_bytes(path.read_bytes()[:4] + suffix)
                        self.assertFalse(inspect(root).structurally_valid)

    def test_metadata_version_0100_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            for name in ("index.bdmv", "MovieObject.bdmv",
                         "PLAYLIST/00000.mpls", "CLIPINF/00000.clpi"):
                path = root / "BDMV" / name
                path.write_bytes(path.read_bytes()[:4] + b"0100")
            self.assertTrue(inspect(root).structurally_valid)
