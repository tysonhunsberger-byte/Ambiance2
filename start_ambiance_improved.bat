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

REM Try Python 3.10 first (most stable with PyQt bindings)
py -3.10 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py -3.10
    echo Using Python 3.10 ^(recommended for Qt stability^)
) else (
    REM Fall back to default python
    python --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo ERROR: Python is not installed or not in PATH
        echo Please install Python 3.10 or higher
        pause
        exit /b 1
    )
    set PYTHON_CMD=python
    echo Using default Python
)

echo.

REM Check for PyQt6 + QtPy shim
%PYTHON_CMD% -c "import PyQt6" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing PyQt6...
    %PYTHON_CMD% -m pip install --user PyQt6 PyQt6-WebEngine qtpy
)

REM Verify PyQt6 WebEngine is available
%PYTHON_CMD% -c "from PyQt6 import QtWebEngineWidgets" >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo WARNING: PyQt6-WebEngine is missing or failed to load.
    echo Strudel mode may be disabled until the dependency is installed correctly.
    echo.
    echo To fix PyQtWebEngine, run: %PYTHON_CMD% -m pip install --user PyQt6-WebEngine
    echo.
    timeout /t 3 >nul
)

REM Run the improved version
echo.
echo Launching Ambiance Improved...
%PYTHON_CMD% ambiance_qt_improved.py

if %errorlevel% neq 0 (
    echo.
    echo ERROR: Failed to start Ambiance
    pause
)
