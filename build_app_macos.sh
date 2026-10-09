#!/bin/bash
# Unsigned local macOS app; external ffmpeg and tsMuxer still required.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt pyinstaller
python3 -m PyInstaller --clean --noconfirm --windowed --name DiscForge-RU main.py
echo "Готово: dist/DiscForge-RU.app (без подписи и нотарификации)"
