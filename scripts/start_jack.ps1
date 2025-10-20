<#
.SYNOPSIS
  Helper script to launch the JACK server on Windows.

.DESCRIPTION
  Looks for jackd.exe in the standard JACK2 installation folder and starts it
  with a sensible PortAudio backend configuration. Adjust the -Interface
  parameter if you prefer a different WASAPI/WDM-KS/ASIO device.

.PARAMETER JackPath
  Optional explicit path to jackd.exe. Defaults to "$env:ProgramFiles\JACK2\bin\jackd.exe".

.PARAMETER Backend
  JACK backend driver. Defaults to "portaudio".

.PARAMETER Interface
  The PortAudio host/device string. Defaults to "Windows WASAPI".

.PARAMETER Realtime
  Enable JACK realtime scheduling (enabled by default).

.PARAMETER SuppressXruns
  Suppress XRUN warnings (-S flag). Enabled by default.

.PARAMETER ExtraArgs
  Additional arguments forwarded verbatim to jackd.exe.
#>
param(
    [string]$JackPath = "$env:ProgramFiles\JACK2\jackd.exe",
    [string]$Backend = "portaudio",
    [string]$Interface = "Windows WASAPI",
    [switch]$Realtime = $true,
    [switch]$SuppressXruns = $true,
    [string[]]$ExtraArgs = @()
)

if (-not (Test-Path -LiteralPath $JackPath)) {
    Write-Error "Unable to locate jackd.exe at '$JackPath'. Install JACK2 for Windows or pass -JackPath."
    exit 1
}

$argsList = @()
if ($Realtime)      { $argsList += "-R" }
if ($SuppressXruns) { $argsList += "-S" }
$argsList += "-d"
$argsList += $Backend
if ($Interface) {
    $argsList += "-d"
    $argsList += $Interface
}
if ($ExtraArgs.Count -gt 0) {
    $argsList += $ExtraArgs
}

Write-Host "Starting JACK with command:"
Write-Host "`"$JackPath`" $($argsList -join ' ')"
Write-Host ""
Write-Host "Leave this window open while Ambiance is running. Press Ctrl+C to stop JACK."

& $JackPath @argsList

if ($LASTEXITCODE -ne 0) {
    Write-Error "jackd exited with code $LASTEXITCODE"
}
