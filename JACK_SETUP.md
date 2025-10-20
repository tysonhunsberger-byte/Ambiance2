# JACK Audio Setup Guide for Ambiance

## Why JACK?

JACK (JACK Audio Connection Kit) provides:
- **Professional audio routing** with low latency
- **Better VST compatibility** - many plugins work better with JACK than DirectSound/WASAPI
- **Stable connections** - prevents crashes seen with native Windows audio
- **Standard in Linux audio** - what most pro audio software uses

Your previous working system used JACK, which is why Aspen Trumpet and Scrooo worked correctly.

## JACK Status

✅ **JACK libraries included**: Carla includes JACK DLLs (`libjack.dll`, `libjack64.dll`)
✅ **Code updated**: Ambiance now prioritizes JACK as the first audio driver choice

## Installing JACK for Windows

### Option 1: JACK2 for Windows (Recommended)

1. **Download JACK2 for Windows**:
   - Visit: https://jackaudio.org/downloads/
   - Download the latest Windows installer (64-bit)
   - Or use the jack2 source you already have in `C:\Ambiance2\jack2-1.9.22`

2. **Install**:
   - Run the installer
   - Default settings are usually fine
   - Make sure to check "Add JACK to PATH"

3. **Start JACK Server**:
   ```batch
   jackd -d portaudio
   ```
   Or use QjackCtl (GUI for JACK) which comes with the installer

### Option 2: Use Carla's Built-in JACK

Carla includes JACK libraries, so it should work automatically. If Carla can't start JACK, you'll see it fall back to DirectSound/WASAPI.

## Testing JACK

After installing/starting JACK:

1. **Run Ambiance**:
   ```batch
   python ambiance_qt_improved.py
   ```

2. **Load a plugin** (e.g., Aspen Trumpet or Scrooo)

3. **Check the logs** - you should see:
   ```
   INFO - Slot 0 using audio driver: JACK
   ```

4. **If you see**:
   ```
   WARNING - Using DirectSound driver - JACK recommended
   ```
   Then JACK is not available and Carla fell back to DirectSound

## Troubleshooting JACK

### JACK Server Not Starting

If JACK won't start, try:

```batch
# Check if jackd is in PATH
where jackd

# Try starting with different backends
jackd -d portaudio          # PortAudio (most compatible)
jackd -d winmme             # Windows MME
jackd -d wasapi             # WASAPI
```

### JACK Installed But Not Working

1. **Check JACK is running**:
   ```batch
   jack_lsp
   ```
   This should list JACK ports. If it errors, JACK server isn't running.

2. **Start JACK before Ambiance**:
   - Open QjackCtl (if installed)
   - Click "Start" button
   - Wait for "Started" status
   - Then run Ambiance

3. **Check Carla can see JACK**:
   - When plugin loads, check log for "using audio driver: JACK"

### Audio Glitches with JACK

If you get audio dropouts:

1. **Increase buffer size**:
   ```python
   slot.host.configure_audio(
       preferred_drivers=["JACK"],
       buffer_size=512  # or 1024
   )
   ```

2. **Adjust JACK latency**:
   ```batch
   jackd -d portaudio -p 512  # Larger buffer = more latency but more stable
   ```

## Verifying The Fix

### Test with Aspen Trumpet

1. Load Aspen Trumpet into slot
2. Check log shows "using audio driver: JACK"
3. Wait for parameters to appear (may take 5-10 seconds)
4. Try opening UI - should not crash
5. Play notes - should hear audio

### Test with Scrooo VST3

1. Load Scrooo into slot
2. Check log shows "using audio driver: JACK"
3. Parameters should appear quickly
4. Try MIDI input - should not crash
5. Should hear audio output

## Expected Behavior with JACK

✅ **Aspen Trumpet**: UI opens, parameters show, audio works
✅ **Scrooo VST3**: MIDI works, audio works, no crashes
✅ **Darksichord**: Works perfectly (already did)
✅ **All plugins**: More stable, better routing

## Alternative: ASIO

If JACK doesn't work, ASIO is second-best:

1. **Check if you have ASIO drivers** (from your audio interface manufacturer)
2. **Or install ASIO4ALL** (free universal ASIO driver):
   - Download from: https://asio4all.org/
   - Install and configure
   - Ambiance will use it automatically (2nd priority after JACK)

## Code Changes Made

### ambiance_qt_improved.py:1672
```python
# OLD - used default drivers (DirectSound first on Windows)
slot.host.configure_audio()

# NEW - prioritizes JACK first (like Linux)
slot.host.configure_audio(preferred_drivers=["JACK", "ASIO", "DirectSound", "WASAPI"])
```

### Added Driver Logging:1680-1683
```python
driver_name = status.get("driver", "unknown")
self.logger.info(f"Slot {slot.index} using audio driver: {driver_name}")
if driver_name not in ["JACK", "ASIO"]:
    self.logger.warning(f"Using {driver_name} driver - JACK recommended")
```

## Next Steps

1. **Install JACK** using Option 1 above (or start JACK if already installed)
2. **Run Ambiance** and check logs for "using audio driver: JACK"
3. **Test problematic plugins** (Aspen Trumpet, Scrooo)
4. **Report results** - especially if crashes still occur with JACK

## Why This Should Fix Your Issues

Your previous system used JACK and both Aspen and Scrooo worked perfectly. The crashes we saw were likely due to:

1. **DirectSound/WASAPI limitations** - not designed for pro audio
2. **Missing audio routing** - JACK provides proper routing infrastructure
3. **Plugin assumptions** - many VSTs assume JACK-like routing on all platforms

With JACK, we're recreating your known-working environment!

---

**Still having issues?** Check TROUBLESHOOTING.md for additional debugging tips.
