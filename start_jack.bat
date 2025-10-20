@echo off
echo ================================================
echo JACK Audio Server Launcher for Ambiance
echo ================================================
echo.
echo Carla includes JACK client libraries but not the server.
echo Checking for JACK server installation...
echo.

where jackd >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo ✓ JACK server found!
    echo.
    echo Starting JACK with PortAudio backend...
    echo Sample rate: 48000 Hz
    echo Buffer size: 512 samples
    echo.
    echo ⚠ Keep this window open while using Ambiance!
    echo   Press Ctrl+C to stop JACK when done.
    echo.
    jackd -d portaudio -r 48000 -p 512
) else (
    echo ✗ JACK server (jackd.exe) not found in PATH
    echo.
    echo JACK client libraries exist in Carla, but the server is missing.
    echo.
    echo To use JACK, please install JACK2 for Windows:
    echo   1. Visit: https://jackaudio.org/downloads/
    echo   2. Download JACK2 for Windows (64-bit)
    echo   3. Install with default settings
    echo   4. Run this script again
    echo.
    echo Alternatively, Ambiance will use ASIO or DirectSound automatically.
    echo.
    pause
    exit /b 1
)

pause
