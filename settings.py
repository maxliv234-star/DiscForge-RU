"""Persist user tool paths and output directory (never private credentials)."""
from pathlib import Path
import json
import os
import sys
import shutil

def config_dir(platform: str, home: Path, appdata: str | None) -> Path:
    if platform == 'darwin':
        return home / 'Library' / 'Application Support' / 'DiscForgeRU'
    if platform == 'win32':
        return Path(appdata) / 'DiscForgeRU' if appdata else home / 'AppData' / 'Roaming' / 'DiscForgeRU'
    return Path(os.getenv('XDG_CONFIG_HOME') or home / '.config') / 'DiscForgeRU'


CFG = config_dir(sys.platform, Path.home(), os.getenv('APPDATA')) / 'settings.json'


def find_binary(name: str) -> str:
    # Finder-launched .app bundles often omit Homebrew from PATH.
    if sys.platform == 'darwin':
        for root in ('/opt/homebrew/bin', '/usr/local/bin'):
            candidate = Path(root) / name
            if candidate.is_file():
                return str(candidate)
    return shutil.which(name) or name


def defaults():
    return {
        'ffmpeg': find_binary('ffmpeg'),
        'ffprobe': find_binary('ffprobe'),
        'tsmuxer': find_binary('tsmuxer') if sys.platform == 'darwin' else find_binary('tsMuxeR'),
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
