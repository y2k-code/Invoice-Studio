@echo off
REM Builds a single-folder Windows app in dist\Invoice Studio\ (double-click Invoice Studio.exe)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
)
call ".venv\Scripts\activate.bat"
python -m pip install --quiet --disable-pip-version-check -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean --windowed --name "Invoice Studio" --add-data "fonts;fonts" main.py
echo.
echo Done. Open dist\Invoice Studio\Invoice Studio.exe
pause
