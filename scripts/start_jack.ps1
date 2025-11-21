Write-Host "Starting JACK with command:"
Write-Host "`"C:\Program Files\JACK2\jackd.exe`" -S -X winmme -v -dportaudio -d`"ASIO::Focusrite USB ASIO`""
Write-Host ""
Write-Host "Leave this window open while Ambiance is running. Press Ctrl+C to stop JACK."

& "C:\Program Files\JACK2\jackd.exe" -S -X winmme -v -dportaudio -d"ASIO::Focusrite USB ASIO"

if ($LASTEXITCODE -ne 0) {
    Write-Error "jackd exited with code $LASTEXITCODE"
}
