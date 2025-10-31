@echo off
echo Fixing PyQtWebEngine DLL Issues
echo ================================
echo.

cd /d "C:\Ambiance2"

echo Option 1: Reinstalling PyQtWebEngine and dependencies...
echo.
python -m pip uninstall -y PyQtWebEngine PyQtWebEngine-Qt5 PyQt5-Qt5
python -m pip install --force-reinstall PyQtWebEngine

echo.
echo.
echo Option 2: Trying specific versions known to work...
echo.
python -m pip uninstall -y PyQtWebEngine PyQtWebEngine-Qt5
python -m pip install PyQtWebEngine==5.15.6

echo.
echo.
echo Testing import...
python -c "from PyQt5.QtWebEngineWidgets import QWebEngineView; print('SUCCESS: PyQtWebEngine is working!')"

if %errorlevel% neq 0 (
    echo.
    echo ====================================================================
    echo STILL FAILING. Additional steps needed:
    echo ====================================================================
    echo.
    echo 1. Install Visual C++ Redistributables:
    echo    https://aka.ms/vs/17/release/vc_redist.x64.exe
    echo.
    echo 2. OR use Python 3.10 instead (more stable with PyQt5):
    echo    - Install Python 3.10 from python.org
    echo    - Run: py -3.10 -m pip install PyQt5 PyQtWebEngine
    echo    - Update start_ambiance_improved.bat to use: py -3.10 ambiance_qt_improved.py
    echo.
    echo 3. OR disable Strudel mode and use web browser instead
    echo.
    pause
) else (
    echo.
    echo ====================================================================
    echo SUCCESS! PyQtWebEngine should now work.
    echo Try running start_ambiance_improved.bat again.
    echo ====================================================================
    pause
)
