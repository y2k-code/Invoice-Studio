@echo off
REM Creates a private virtual environment on first run, installs the two libraries, starts the app.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
)
call ".venv\Scripts\activate.bat"
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
python main.py
if errorlevel 1 pause
