"""Small synthetic UDF metadata fixtures; not full, mountable Blu-ray images."""
import binascii
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import iso_udf_preflight as udf


def descriptor(tag: int, lba: int, data: bytes = b'') -> bytes:
    block = bytearray(udf.SECTOR_SIZE)
    block[0:2] = tag.to_bytes(2, 'little')
    block[2:4] = (3).to_bytes(2, 'little')
    block[6:8] = (1).to_bytes(2, 'little')
    block[8:10] = binascii.crc_hqx(data, 0).to_bytes(2, 'little')
    block[10:12] = len(data).to_bytes(2, 'little')
    block[12:16] = lba.to_bytes(4, 'little')
    block[16:16 + len(data)] = data
    block[4] = (sum(block[:4]) + sum(block[5:16])) % 256
    return bytes(block)


def iso_fixture(path: Path, *, revision=0x0250, nsr=b'NSR03', anchor=True,
                bad_tag=False, bad_extent=False, block_size=2048):
    sectors = 300
    with path.open('wb') as handle:
        handle.truncate(sectors * udf.SECTOR_SIZE)
        for lba, ident in ((16, b'BEA01'), (17, nsr), (18, b'TEA01')):
            handle.seek(lba * udf.SECTOR_SIZE)
            handle.write(b'\x00' + ident + b'\x01')
        if anchor:
            extent = (16 * udf.SECTOR_SIZE).to_bytes(4, 'little')
            start = (400 if bad_extent else 32).to_bytes(4, 'little')
            avdp = bytearray(descriptor(2, 256, extent + start))
            if bad_tag:
                avdp[4] ^= 1
            handle.seek(256 * udf.SECTOR_SIZE)
            handle.write(avdp)
        payload = bytearray(226)
        payload[196:200] = block_size.to_bytes(4, 'little')  # LVD offset 212
        payload[201:201 + len(udf.UDF_DOMAIN)] = udf.UDF_DOMAIN  # LVD offset 217
        payload[224:226] = revision.to_bytes(2, 'little')  # LVD offset 240
        handle.seek(32 * udf.SECTOR_SIZE)
        handle.write(descriptor(6, 32, bytes(payload)))
        handle.seek(33 * udf.SECTOR_SIZE)
        handle.write(descriptor(8, 33))


class ISOUDFFullHDTests(unittest.TestCase):
    def check(self, **kwargs):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / 'test.iso'
            iso_fixture(image, **kwargs)
            return udf.inspect(image)

    def test_valid_metadata_and_revision(self):
        report = self.check()
        self.assertTrue(report.valid, report.errors)
        self.assertEqual(report.udf_revision, '0x0250')
        self.assertIn('NOT verified', report.warnings[0])

    def test_valid_backup_anchor_when_primary_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / 'test.iso'
            iso_fixture(image, anchor=False)
            with image.open('r+b') as handle:
                handle.seek(299 * udf.SECTOR_SIZE)
                handle.write(descriptor(2, 299, (16 * udf.SECTOR_SIZE).to_bytes(4, 'little')
                                        + (32).to_bytes(4, 'little')))
            report = udf.inspect(image)
            self.assertTrue(report.valid, report.errors)
            self.assertTrue(any('backup anchor' in w for w in report.warnings))

    def test_rejects_corrupted_lvd_crc(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / 'test.iso'
            iso_fixture(image)
            with image.open('r+b') as handle:
                handle.seek(32 * udf.SECTOR_SIZE + 240)
                handle.write(b'\x60')  # Break LVD descriptor CRC, not its tag checksum.
            report = udf.inspect(image)
            self.assertFalse(report.valid)
            self.assertTrue(any('Logical Volume Descriptor' in e for e in report.errors))

    def test_rejects_lvd_crc_excluding_revision(self):
        block = bytearray(descriptor(6, 32, bytes(226)))
        block[8:12] = bytes(4)  # CRC 0 over zero bytes, checksum still valid.
        block[4] = (sum(block[:4]) + sum(block[5:16])) % 256
        with self.assertRaisesRegex(ValueError, 'LVD CRC'):
            udf._tag(bytes(block), 32)

    def test_rejects_anchor_crc_excluding_main_extent(self):
        extent = (16 * udf.SECTOR_SIZE).to_bytes(4, 'little') + (32).to_bytes(4, 'little')
        block = bytearray(descriptor(2, 256, extent))
        block[8:12] = bytes(4)
        block[4] = (sum(block[:4]) + sum(block[5:16])) % 256
        with self.assertRaisesRegex(ValueError, 'Anchor CRC'):
            udf._tag(bytes(block), 256)

    def test_rejects_anchor_crc_excluding_reserve_extent(self):
        main = (16 * udf.SECTOR_SIZE).to_bytes(4, 'little') + (32).to_bytes(4, 'little')
        reserve = (16 * udf.SECTOR_SIZE).to_bytes(4, 'little') + (64).to_bytes(4, 'little')
        block = bytearray(descriptor(2, 256, main + reserve))
        block[8:10] = binascii.crc_hqx(main, 0).to_bytes(2, 'little')
        block[10:12] = (8).to_bytes(2, 'little')
        block[4] = (sum(block[:4]) + sum(block[5:16])) % 256
        with self.assertRaisesRegex(ValueError, 'Anchor CRC'):
            udf._tag(bytes(block), 256)

    def test_rejects_udf260(self):
        report = self.check(revision=0x0260)
        self.assertFalse(report.valid)
        self.assertIn('not 2.50', ' '.join(report.errors))

    def test_rejects_nsr02(self):
        self.assertFalse(self.check(nsr=b'NSR02').valid)

    def test_rejects_missing_anchor(self):
        self.assertFalse(self.check(anchor=False).valid)

    def test_rejects_bad_tag_checksum(self):
        self.assertFalse(self.check(bad_tag=True).valid)

    def test_rejects_out_of_range_vds(self):
        self.assertFalse(self.check(bad_extent=True).valid)

    def test_rejects_wrong_block_size(self):
        self.assertFalse(self.check(block_size=4096).valid)

    def test_rejects_bdxl_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / 'test.iso'
            iso_fixture(image)
            self.assertFalse(udf.inspect(image, 'BDXL100').valid)
            self.assertTrue(udf.inspect(image, 'BD50').valid)

    def test_rejects_unaligned_iso(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / 'test.iso'
            iso_fixture(image)
            with image.open('ab') as handle:
                handle.write(b'x')
            self.assertFalse(udf.inspect(image).valid)

    def test_rejects_oversize_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / 'test.iso'
            iso_fixture(image)
            with patch.dict(udf.CAPACITIES, {'BD25': 300000}):
                self.assertFalse(udf.inspect(image).valid)

    def test_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / 'test.iso'
            iso_fixture(image)
            alias = Path(temp) / 'alias.iso'
            try:
                alias.symlink_to(image)
            except (OSError, NotImplementedError):
                self.skipTest('Symlinks not available')
            self.assertFalse(udf.inspect(alias).valid)


    def _install_reserve_vds(self, image, *, bad_main_extent=False, bad_reserve_extent=False):
        with image.open('r+b') as handle:
            handle.seek(32 * udf.SECTOR_SIZE)
            original = handle.read(udf.SECTOR_SIZE)
            crc_length = int.from_bytes(original[10:12], 'little')
            payload = original[16:16 + crc_length]
            handle.seek(64 * udf.SECTOR_SIZE)
            handle.write(descriptor(6, 64, payload))
            handle.seek(65 * udf.SECTOR_SIZE)
            handle.write(descriptor(8, 65))
            main_start = 400 if bad_main_extent else 32
            reserve_start = 400 if bad_reserve_extent else 64
            avdp = (
                (16 * udf.SECTOR_SIZE).to_bytes(4, 'little')
                + main_start.to_bytes(4, 'little')
                + (16 * udf.SECTOR_SIZE).to_bytes(4, 'little')
                + reserve_start.to_bytes(4, 'little')
            )
            handle.seek(256 * udf.SECTOR_SIZE)
            handle.write(descriptor(2, 256, avdp))
            if not bad_main_extent:
                handle.seek(32 * udf.SECTOR_SIZE + 240)
                handle.write(bytes([0x60]))  # Corrupt Main LVD CRC.

    def test_reserve_vds_recovers_corrupted_main(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / 'test.iso'
            iso_fixture(image)
            self._install_reserve_vds(image)
            report = udf.inspect(image)
            self.assertTrue(report.valid, report.errors)
            self.assertTrue(any('Reserve VDS' in w for w in report.warnings))

    def test_reserve_vds_recovers_invalid_main_extent(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / 'test.iso'
            iso_fixture(image)
            self._install_reserve_vds(image, bad_main_extent=True)
            self.assertTrue(udf.inspect(image).valid)

    def test_rejects_when_main_and_reserve_both_invalid(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / 'test.iso'
            iso_fixture(image)
            self._install_reserve_vds(image, bad_reserve_extent=True)
            report = udf.inspect(image)
            self.assertFalse(report.valid)
            self.assertTrue(any('Main/Reserve VDS' in e for e in report.errors))

    def test_cli_json_exit_codes(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / 'test.iso'
            iso_fixture(image)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(udf.main([str(image), '--profile', 'BD25']), 0)
            self.assertIn('"valid": true', out.getvalue())
            image.write_bytes(b'broken')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(udf.main([str(image)]), 2)


if __name__ == '__main__':
    unittest.main()
