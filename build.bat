@echo off
echo === Monitor Control Build ===
echo.

pip install pyinstaller
if %errorlevel% neq 0 (
    echo CHYBA: Nelze nainstalovat PyInstaller
    pause
    exit /b 1
)

echo.
echo Builduji MonitorControl.exe...
pyinstaller --onefile --windowed --name MonitorControl main.py

if %errorlevel% equ 0 (
    echo.
    echo Build uspesny! Soubor: dist\MonitorControl.exe
) else (
    echo.
    echo CHYBA pri buildu!
)

pause
