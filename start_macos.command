#!/bin/bash
# macOS GUI runner. Run via Terminal: bash start_macos.command
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="$(command -v python3)"
if [ ! -d ".venv" ]; then
    "$PYTHON" -m venv .venv
fi
.venv/bin/python -m pip install -r requirements.txt
echo "Запуск DiscForge RU для macOS..."
.venv/bin/python main.py
