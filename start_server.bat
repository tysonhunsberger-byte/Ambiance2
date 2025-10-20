@echo off
echo ============================================================
echo Starting Ambiance Server
echo ============================================================
echo.

cd /d "%~dp0ambiance"
echo Running from: %CD%
echo.

python -m ambiance.server

pause
