#!/bin/bash
# Unsigned local macOS app; external ffmpeg and tsMuxer still required.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt pyinstaller
python3 -m PyInstaller --clean --noconfirm --windowed --add-data "assets:assets" --add-data "LICENSE:." --add-data "THIRD_PARTY_NOTICES.md:." --name DiscForge-RU main.py
python3 -m PyInstaller --clean --noconfirm --onefile --console --hidden-import tools.macos_mounted_bdmv --name DiscForge-RU-burn macos_burn.py
python3 tests/smoke_macos_burn_cli.py dist/DiscForge-RU-burn
echo "Готово: dist/DiscForge-RU.app и dist/DiscForge-RU-burn (без подписи и нотарификации)"
