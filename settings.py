"""Persist user tool paths and output directory (never private credentials)."""
from pathlib import Path
import json
import os

CFG = Path(os.getenv('APPDATA') or (Path.home() / '.config')) / 'DiscForgeRU' / 'settings.json'


def defaults():
    return {
        'ffmpeg': 'ffmpeg',
        'ffprobe': 'ffprobe',
        'tsmuxer': 'tsMuxeR',
        'output': str(Path.home() / 'DiscForge_Output'),
    }


def load():
    current = defaults()
    try:
        content = json.loads(CFG.read_text(encoding='utf-8'))
        if isinstance(content, dict):
            current.update({k: str(v) for k, v in content.items() if k in current})
    except (OSError, ValueError):
        pass
    return current


def save(value):
    CFG.parent.mkdir(parents=True, exist_ok=True)
    CFG.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
