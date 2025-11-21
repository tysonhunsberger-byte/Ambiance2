@echo off
setlocal EnableExtensions
call :main
set "LAUNCH_ERR=%errorlevel%"
if not "%LAUNCH_ERR%"=="0" (
    echo.
    echo ERROR: Failed to start Ambiance (exit code %LAUNCH_ERR%)
)
pause
exit /b %LAUNCH_ERR%

:main
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
set "SCRIPT_ROOT=%~dp0"
set "AMB_PLUGIN_HOST=carla"
set "SCLANG_PATH=C:\Program Files\SuperCollider-3.13.0\sclang.exe"
set "SCSYNTH_PATH=C:\Program Files\SuperCollider-3.13.0\scsynth.exe"
set "PSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

REM Default to direct ASIO via PortAudio unless AMB_USE_JACK=1
set "SC_AUDIO_API=portaudio"
set "SC_AUDIO_DEVICE=MME : SAMSUNG (NVIDIA High Definition Audio)"
set "SC_JACK_DEFAULT_SERVER="
set "SC_JACK_DEFAULT_DEVICE="
set "SC_SERVER_AUDIO_DRIVER= MME"
if not defined AMB_USE_JACK set "AMB_USE_JACK=0"
if not defined AMB_JACK_DEVICE set "AMB_JACK_DEVICE=ASIO::Focusrite USB ASIO"

if /I "%AMB_USE_JACK%"=="1" (
    echo Using JACK backend ^(set AMB_USE_JACK=0 to disable^)
    set "SC_AUDIO_API=jack"
    set "SC_AUDIO_DEVICE="
    set "SC_JACK_DEFAULT_SERVER=default"
    set "SC_JACK_DEFAULT_DEVICE=default"
    call :start_jack
    call :wait_for_jack_ready
) else (
    echo JACK disabled. Using SuperCollider MME backend.
    if not defined SC_SERVER_AUDIO_DRIVER set "SC_SERVER_AUDIO_DRIVER=MME"
)
%PYTHON_CMD% ambiance_qt_improved.py
set "APP_EXIT=%errorlevel%"
call :stop_audio_stack
exit /b %APP_EXIT%


:start_jack
set "JACK_SCRIPT=%SCRIPT_ROOT%scripts\start_jack.ps1"
if not exist "%JACK_SCRIPT%" (
    echo WARNING: %JACK_SCRIPT% not found; skipping JACK auto-launch.
    exit /b
)
echo Starting JACK server on "%AMB_JACK_DEVICE%"...
if not exist "%PSHELL%" set "PSHELL=powershell"
echo Launching PowerShell host: "%PSHELL%" -ExecutionPolicy Bypass -File "%JACK_SCRIPT%" -Interface "%AMB_JACK_DEVICE%"
start "%PSHELL%" -ExecutionPolicy Bypass -File "%JACK_SCRIPT%" -Interface "%AMB_JACK_DEVICE%"
echo JACK start command exit status: %errorlevel%
timeout /t 3 >nul
set "JACK_STARTED_BY_AMBIANCE=1"
exit /b

:wait_for_jack_ready
REM Wait for JACK named pipe to exist before continuing
set "AMB_JACK_PIPE=\\.\pipe\server_jack_default_0"
if defined JACK_PIPE set "AMB_JACK_PIPE=%JACK_PIPE%"
echo Waiting for JACK pipe %AMB_JACK_PIPE% ...
set /a __amb_wait_count=0
:__amb_jack_wait_loop
powershell -NoLogo -NoProfile -Command "if (Test-Path '%AMB_JACK_PIPE%') { exit 0 } else { exit 1 }"
if %errorlevel%==0 (
    echo JACK pipe detected.
    goto :wait_ready_done
)
set /a __amb_wait_count+=1
if %__amb_wait_count% GEQ 20 (
    echo WARNING: JACK pipe %AMB_JACK_PIPE% not detected after waiting. Continuing anyway.
    goto :wait_ready_done
)
timeout /t 1 >nul
goto :__amb_jack_wait_loop
:wait_ready_done
timeout /t 2 >nul
set "__amb_wait_count="
exit /b

:stop_audio_stack
if defined JACK_STARTED_BY_AMBIANCE (
    echo Shutting down JACK...
    taskkill /IM jackd.exe /F >nul 2>&1
)
echo Stopping SuperCollider processes...
taskkill /IM sclang.exe /F >nul 2>&1
taskkill /IM scsynth.exe /F >nul 2>&1
exit /b
