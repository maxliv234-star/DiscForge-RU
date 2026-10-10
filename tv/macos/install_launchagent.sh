#!/bin/bash
# Install a per-user launchd agent (starts after macOS login).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
MEDIA_ROOT="${1:-$HOME/Movies/DiscForge}"
PORT="${2:-8098}"
PYTHON="$(command -v python3)"
[[ -d "$MEDIA_ROOT" ]] || { echo "No media directory: $MEDIA_ROOT" >&2; exit 1; }
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; then
  echo "Port $PORT is already in use. Stop the manually started server first." >&2
  exit 1
fi
mkdir -p "$HOME/.discforge-tv" "$HOME/Library/LaunchAgents"
chmod 700 "$HOME/.discforge-tv"
export REPO MEDIA_ROOT PORT PYTHON
python3 - <<'PY'
import os, plistlib
from pathlib import Path
home = Path.home()
target = home / 'Library/LaunchAgents/ru.discforge.tv.server.plist'
config = {
    'Label': 'ru.discforge.tv.server',
    'ProgramArguments': [os.environ['PYTHON'], '-m', 'tv_server', '--media-root',
                         os.path.abspath(os.environ['MEDIA_ROOT']), '--host', '0.0.0.0',
                         '--port', os.environ['PORT'], '--no-print-token'],
    'WorkingDirectory': os.environ['REPO'],
    'RunAtLoad': True, 'KeepAlive': {'SuccessfulExit': False},
    'StandardOutPath': str(home / '.discforge-tv/server.log'),
    'StandardErrorPath': str(home / '.discforge-tv/server-error.log'),
}
target.write_bytes(plistlib.dumps(config))
target.chmod(0o600)
print(target)
PY
PLIST="$HOME/Library/LaunchAgents/ru.discforge.tv.server.plist"
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/ru.discforge.tv.server"
echo "Started. Logs: $HOME/.discforge-tv/server.log"
echo "To stop: launchctl bootout gui/$(id -u) $PLIST"
