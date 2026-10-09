@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [DiscForge RU] Создание виртуальной среды...
  py -3 -m venv .venv
  if errorlevel 1 (echo Не найден Python 3.11+ с установленным launcher py & pause & exit /b 1)
)
".venv\Scripts\python.exe" -c "import PySide6" >nul 2>&1
if errorlevel 1 (
  echo [DiscForge RU] Установка библиотек...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (echo Не удалось установить PySide6. Проверьте доступ в интернет. & pause & exit /b 1)
)
".venv\Scripts\python.exe" main.py
if errorlevel 1 pause
