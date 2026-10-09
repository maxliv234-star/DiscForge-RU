"""Discover available optical drives for DiscForge Player."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path


def optical_drives(platform: str | None = None, volumes: Path | None = None) -> list[str]:
    """Return candidate optical drives, not a guarantee that media is present."""
    platform = platform or sys.platform
    if platform == "win32":
        try:
            kernel = ctypes.windll.kernel32
            return [f"{letter}:" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                    if kernel.GetDriveTypeW(f"{letter}:\\") == 5]
        except (AttributeError, OSError):
            return []
    if platform == "darwin":
        base = volumes or Path("/Volumes")
        try:
            return sorted(str(p) for p in base.iterdir()
                          if p.is_dir() and (p / "BDMV").is_dir())
        except OSError:
            return []
    return sorted(str(p) for p in Path("/dev").glob("sr[0-9]*") if p.exists())
