"""Limited structural preflight for Full HD BD25/BD50 BDMV directories.

A pass does not prove UDF 2.50, disc-menu behavior or hardware compatibility.
"""
from __future__ import annotations
import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path

CAPACITIES = {"BD25": 25_000_000_000, "BD50": 50_000_000_000}
HEADERS = {"index.bdmv": b"INDX", "MovieObject.bdmv": b"MOBJ"}
COLLECTIONS = {"PLAYLIST": ("*.mpls", b"MPLS"),
               "CLIPINF": ("*.clpi", b"HDMV"),
               "STREAM": ("*.m2ts", None)}

@dataclass
class Report:
    root: str
    profile: str
    structurally_valid: bool
    size_bytes: int
    errors: list[str]
    warnings: list[str]
    counts: dict[str, int]

def inspect(root: Path, profile: str = "BD25") -> Report:
    root = Path(root).expanduser()
    errors: list[str] = []
    warnings: list[str] = []
    counts: dict[str, int] = {}
    size = 0
    if profile not in CAPACITIES:
        errors.append("Only BD25/BD50 supported; UHD/BDXL deferred.")
    if not root.is_dir() or root.is_symlink():
        errors.append("Output directory missing or symlink.")
    else:
        for path in root.rglob("*"):
            relative = path.relative_to(root)
            if path.is_symlink():
                errors.append(f"Symlink forbidden: {relative}")
            elif path.is_file():
                try:
                    size += path.stat().st_size
                except OSError as exc:
                    errors.append(f"Cannot stat {relative}: {exc}")
        bdmv = root / "BDMV"
        if not bdmv.is_dir() or bdmv.is_symlink():
            errors.append("Missing BDMV directory.")
        for name, magic in HEADERS.items():
            path = bdmv / name
            if not path.is_file() or path.is_symlink():
                errors.append(f"Missing BDMV/{name}")
                continue
            try:
                with path.open("rb") as handle:
                    if handle.read(4) != magic:
                        errors.append(f"Invalid signature: BDMV/{name}")
            except OSError as exc:
                errors.append(f"Cannot read BDMV/{name}: {exc}")
        for name, (pattern, magic) in COLLECTIONS.items():
            directory = bdmv / name
            matches = (sorted(directory.glob(pattern))
                       if directory.is_dir() and not directory.is_symlink() else [])
            counts[name] = len(matches)
            if not matches:
                errors.append(f"Missing BDMV/{name}/{pattern}")
            for path in matches:
                if path.is_symlink() or not path.is_file():
                    errors.append(f"Invalid BDMV/{name}/{path.name}")
                    continue
                try:
                    length = path.stat().st_size
                    if length == 0:
                        errors.append(f"Empty BDMV/{name}/{path.name}")
                    elif magic is None and length % 192 != 0:
                        errors.append(f"M2TS not 192-byte aligned: {path.name}")
                    elif magic is not None:
                        with path.open("rb") as handle:
                            if handle.read(4) != magic:
                                errors.append(f"Invalid signature: BDMV/{name}/{path.name}")
                except OSError as exc:
                    errors.append(f"Cannot inspect {path.name}: {exc}")
        if not (bdmv / "BACKUP").is_dir():
            warnings.append("Missing BDMV/BACKUP; check redundant metadata.")
        if not (root / "CERTIFICATE").is_dir():
            warnings.append("Missing CERTIFICATE directory.")
    if profile in CAPACITIES and size > CAPACITIES[profile]:
        errors.append(f"Output size {size} exceeds {profile}.")
    warnings.append("Static preflight only: menus, UDF 2.50, burning and player compatibility UNVERIFIED.")
    return Report(str(root), profile, not errors, size, errors, warnings, counts)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DiscForge RU BD25/BD50 BDMV preflight")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--profile", choices=tuple(CAPACITIES), default="BD25")
    args = parser.parse_args(argv)
    result = inspect(args.folder, args.profile)
    print(json.dumps(asdict(result), indent=2, ensure_ascii=False))
    return 0 if result.structurally_valid else 2

if __name__ == "__main__":
    raise SystemExit(main())
