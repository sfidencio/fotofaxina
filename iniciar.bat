@echo off
cd /d "%~dp0"
if exist .venv\Scripts\pythonw.exe (
  start "" .venv\Scripts\pythonw.exe main.py --minimizado
) else (
  start "" pythonw main.py --minimizado
)
