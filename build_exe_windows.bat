@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call start_windows.bat
".venv\Scripts\python.exe" -m pip install pyinstaller
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onedir --name "DiscForge_RU" main.py
if errorlevel 1 (echo Не удалось собрать exe & pause & exit /b 1)
echo EXE готов: dist\DiscForge_RU\DiscForge_RU.exe
pause
