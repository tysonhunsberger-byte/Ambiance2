@echo off
echo Starting Ambiance Improved VST Host...
echo =====================================
echo Features:
echo - Plugin chaining support (load multiple VSTs)
echo - Extended MIDI keyboard (5 octaves, customizable)
echo - Fixed plugin UI display
echo - Per-slot parameter controls
echo - Bypass functionality
echo.

cd /d "C:\Ambiance2"

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8 or higher
    pause
    exit /b 1
)

REM Check for PyQt5
python -c "import PyQt5" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing PyQt5...
    pip install PyQt5
)

REM Run the improved version
echo.
echo Launching Ambiance Improved...
python ambiance_qt_improved.py

if %errorlevel% neq 0 (
    echo.
    echo ERROR: Failed to start Ambiance
    pause
)
