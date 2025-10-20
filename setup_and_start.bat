@echo off
echo ============================================================
echo Ambiance Setup and Server Start
echo ============================================================
echo.

cd /d "%~dp0ambiance"
echo Current directory: %CD%
echo.

echo [1/2] Installing Ambiance package...
pip install -e .
echo.

if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Installation failed!
    pause
    exit /b 1
)

echo [2/2] Starting server...
echo.
python -m ambiance.server

pause
