@echo off
echo === Monitor Control Build ===
echo.

python -m pip install -r requirements-build.txt
if %errorlevel% neq 0 (
    echo ERROR: Could not install build requirements.
    exit /b 1
)

echo.
python -m unittest -v
if %errorlevel% neq 0 exit /b 1

echo Building MonitorControl.exe...
python -m PyInstaller --noconfirm --onefile --windowed --exclude-module numpy --name MonitorControl main.py

if %errorlevel% neq 0 (
    echo.
    echo ERROR: Build failed.
    exit /b 1
)
echo.
echo Build successful: dist\MonitorControl.exe
python package_release.py
exit /b %errorlevel%
