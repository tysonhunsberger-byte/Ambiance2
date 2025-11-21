@echo off
setlocal
set "AMB_USE_JACK=1"
pushd "%~dp0"
cmd /k "%~dp0start_ambiance_improved.bat"
popd
endlocal
