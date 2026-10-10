"""Standalone DiscForge Player source selection, independent of GUI dependencies."""
from __future__ import annotations
import re
import sys
from pathlib import Path
from urllib.parse import quote

class SourceError(ValueError):
    pass

def bluray_uri(source: str, platform: str | None = None) -> str:
    platform = platform or sys.platform
    if not source or any(c in source for c in "\0\n\r"):
        raise SourceError("Недопустимый путь к Blu-ray.")
    source = source.strip()
    if platform == "win32" and re.fullmatch(r"[A-Za-z]:(?:[/\\])?", source):
        return "bluray:///" + source[0].upper() + ":/"
    path = Path(source).expanduser()
    if not path.is_absolute() or not path.exists():
        raise SourceError("Привод или папка не найдены: " + source)
    return "bluray:///" + quote(path.as_posix().lstrip("/"), safe="/:")

def bdmv_uri(source: str) -> str:
    root = Path(source).expanduser()
    if root.name.upper() == "BDMV":
        root = root.parent
    if not (root / "BDMV").is_dir():
        raise SourceError("Выберите каталог, содержащий папку BDMV.")
    return bluray_uri(str(root))

def file_uri(source: str) -> str:
    path = Path(source).expanduser()
    if not path.is_file() or path.suffix.lower() not in {
            ".iso", ".mp4", ".mkv", ".mov", ".m2ts", ".mts", ".ts", ".avi"}:
        raise SourceError("Файл не найден или формат не поддерживается.")
    return path.resolve().as_uri()
