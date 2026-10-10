"""Read-only UDF 2.50 metadata preflight for Full HD Blu-ray ISO images.

Checks VRS, anchor, LVD revision, descriptor tags/CRC. Does not traverse
file tree or verify BDMV, menus, disc burning or physical player compatibility.
"""
from __future__ import annotations

import argparse
import binascii
import json
from dataclasses import asdict, dataclass
from pathlib import Path

SECTOR_SIZE = 2048
CAPACITIES = {"BD25": 25_000_000_000, "BD50": 50_000_000_000}
UDF_DOMAIN = b"*OSTA UDF Compliant"
MAX_VDS_SECTORS = 256


@dataclass
class Report:
    path: str
    profile: str
    valid: bool
    size_bytes: int
    udf_revision: str | None
    errors: list[str]
    warnings: list[str]


def _sector(handle, lba: int, count: int) -> bytes:
    if not 0 <= lba < count:
        raise ValueError("Sector outside ISO image.")
    handle.seek(lba * SECTOR_SIZE)
    data = handle.read(SECTOR_SIZE)
    if len(data) != SECTOR_SIZE:
        raise ValueError("Truncated ISO sector.")
    return data


def _tag(block: bytes, lba: int) -> int:
    """Validate ECMA-167 descriptor tag, checksum, location and CRC-16."""
    tag_id = int.from_bytes(block[0:2], "little")
    version = int.from_bytes(block[2:4], "little")
    if tag_id == 0 or version not in (2, 3):
        raise ValueError("Invalid descriptor tag or version.")
    if (sum(block[0:4]) + sum(block[5:16])) % 256 != block[4]:
        raise ValueError("Descriptor tag checksum mismatch.")
    if int.from_bytes(block[12:16], "little") != lba:
        raise ValueError("Descriptor tag location mismatch.")
    crc_length = int.from_bytes(block[10:12], "little")
    if crc_length > SECTOR_SIZE - 16:
        raise ValueError("Descriptor CRC extends beyond inspected sector.")
    crc_expected = int.from_bytes(block[8:10], "little")
    if binascii.crc_hqx(block[16:16 + crc_length], 0) != crc_expected:
        raise ValueError("Descriptor CRC mismatch.")
    # The CRC must cover every descriptor field used by this preflight.
    # LVD's UDF domain identifier and revision end at byte offset 242.
    if tag_id == 6 and crc_length < 226:
        raise ValueError("LVD CRC does not cover the UDF domain revision.")
    # The AVDP Main VDS extent is bytes 16:24, Reserve is bytes 24:32.
    # An empty or short CRC would otherwise allow unchecked extent changes.
    if tag_id == 2:
        required = 16 if any(block[24:32]) else 8
        if crc_length < required:
            raise ValueError("Anchor CRC does not cover advertised VDS extents.")
    return tag_id


def _vrs(handle, count: int) -> bool:
    """Find ordered BEA01 / NSR03 / TEA01 recognition sequence."""
    state = 0
    for lba in range(16, min(count, 64)):
        identifier = _sector(handle, lba, count)[1:6]
        if state == 0 and identifier == b"BEA01":
            state = 1
        elif state == 1 and identifier == b"NSR03":
            state = 2
        elif state == 2 and identifier == b"TEA01":
            return True
        elif state in (1, 2) and identifier in (b"BEA01", b"NSR02"):
            return False
    return False


def _vds_extent(block: bytes, offset: int, count: int) -> tuple[int, int] | None:
    length = int.from_bytes(block[offset:offset + 4], "little")
    start = int.from_bytes(block[offset + 4:offset + 8], "little")
    sectors = (length + SECTOR_SIZE - 1) // SECTOR_SIZE
    if 1 <= sectors <= MAX_VDS_SECTORS and start < count and sectors <= count - start:
        return start, sectors
    return None


def _anchor(handle, count: int) -> tuple[int, tuple[int, int] | None, tuple[int, int] | None]:
    """Return anchor LBA plus independently bounded Main and Reserve VDS."""
    for lba in dict.fromkeys((256, count - 1, count - 257)):
        if not 0 <= lba < count:
            continue
        try:
            block = _sector(handle, lba, count)
            if _tag(block, lba) != 2:
                continue
            main = _vds_extent(block, 16, count)
            reserve = _vds_extent(block, 24, count)
            if main is not None or reserve is not None:
                return lba, main, reserve
        except ValueError:
            continue
    raise ValueError("No valid UDF anchor or bounded Main/Reserve VDS extent.")


def _revision(handle, count: int, start: int, sectors: int) -> int:
    """Find a valid LVD and read its UDF revision (EntityID suffix, LE)."""
    for lba in range(start, start + sectors):
        block = _sector(handle, lba, count)
        try:
            tag_id = _tag(block, lba)
        except ValueError:
            continue
        if tag_id == 8:  # Terminating Descriptor
            break
        if tag_id != 6:  # Logical Volume Descriptor
            continue
        if int.from_bytes(block[212:216], "little") != SECTOR_SIZE:
            raise ValueError("LVD logical block size is not 2048.")
        if block[217:240].rstrip(b"\x00") != UDF_DOMAIN:
            raise ValueError("LVD has no OSTA UDF domain identifier.")
        return int.from_bytes(block[240:242], "little")
    raise ValueError("No valid Logical Volume Descriptor in Main VDS.")


def inspect(path: str | Path, profile: str = "BD25") -> Report:
    image = Path(path).expanduser()
    errors: list[str] = []
    warnings = [
        "Metadata-only preflight: UDF directory tree, BDMV contents, menus, "
        "physical burning and player compatibility are NOT verified."
    ]
    size = 0
    revision: str | None = None
    if profile not in CAPACITIES:
        errors.append("Only BD25/BD50 supported; UHD/BDXL deferred.")
    if image.is_symlink() or not image.is_file():
        errors.append("ISO missing, not a regular file, or a symlink.")
    elif image.suffix.lower() != ".iso":
        errors.append("Expected an .iso file.")
    else:
        try:
            size = image.stat().st_size
            if size < 258 * SECTOR_SIZE or size % SECTOR_SIZE:
                errors.append("ISO is too small or not aligned to 2048-byte sectors.")
            elif profile in CAPACITIES and size > CAPACITIES[profile]:
                errors.append(f"ISO size {size} exceeds {profile}.")
            else:
                with image.open("rb") as handle:
                    count = size // SECTOR_SIZE
                    if not _vrs(handle, count):
                        errors.append("Missing ordered BEA01/NSR03/TEA01 UDF VRS.")
                    else:
                        anchor_lba, main_vds, reserve_vds = _anchor(handle, count)
                        if anchor_lba != 256:
                            warnings.append("Primary UDF anchor missing; used backup anchor.")
                        last_error = None
                        for label, extent in (("Main", main_vds), ("Reserve", reserve_vds)):
                            if extent is None:
                                continue
                            try:
                                value = _revision(handle, count, *extent)
                            except ValueError as exc:
                                last_error = exc
                                continue
                            if label == "Reserve":
                                warnings.append("Main VDS invalid or missing; used Reserve VDS.")
                            break
                        else:
                            raise ValueError(f"No valid Logical Volume Descriptor in Main/Reserve VDS: {last_error}")
                        revision = f"0x{value:04x}"
                        if value != 0x0250:
                            errors.append(f"UDF revision {revision} is not 2.50 (0x0250).")
        except (OSError, ValueError) as exc:
            errors.append(f"Cannot validate UDF descriptors: {exc}")
    return Report(str(image), profile, not errors, size, revision, errors, warnings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DiscForge RU ISO UDF 2.50 metadata preflight")
    parser.add_argument("iso", type=Path)
    parser.add_argument("--profile", choices=tuple(CAPACITIES), default="BD25")
    args = parser.parse_args(argv)
    report = inspect(args.iso, args.profile)
    print(json.dumps(asdict(report), indent=2, ensure_ascii=False))
    return 0 if report.valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
