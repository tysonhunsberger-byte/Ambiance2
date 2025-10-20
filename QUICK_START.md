# Quick Start Guide - Testing with Different Audio Drivers

## Current Situation

You're seeing JACK connection errors because the JACK server isn't running. Carla will automatically fallback to the next available driver (likely DirectSound or ASIO).

## Test Plan

Let's test in order to find what works best:

### Test 1: With DirectSound/WASAPI (Current)

**Just run Ambiance as-is:**
```batch
python ambiance_qt_improved.py
```

**Check the console output:**
```
INFO - Slot 0 using audio driver: DirectSound  (or WASAPI)
```

**Try loading:**
1. Aspen Trumpet - does it still crash?
2. Scrooo VST3 - does MIDI still crash?
3. Darksichord - should work

**Why test this?** Maybe the other fixes we made (removing locks, better activation) already solved the issues even without JACK.

---

### Test 2: With JACK Server (Recommended)

**Step 1: Start JACK server**
Double-click: `start_jack.bat`

You should see:
```
Starting JACK Audio Server...
JACK server started successfully
```
Leave this window open!

**Step 2: Run Ambiance** (in a NEW window)
```batch
python ambiance_qt_improved.py
```

**Check the console:**
```
INFO - Slot 0 using audio driver: JACK
```

**Try loading:**
1. Aspen Trumpet - should work perfectly now!
2. Scrooo VST3 - MIDI should work without crashes
3. All audio should be cleaner/more stable

---

### Test 3: With ASIO (Alternative)

**Only if you have ASIO drivers installed** (from audio interface or ASIO4ALL)

1. Make sure JACK is NOT running (close start_jack.bat)
2. Run Ambiance
3. Check console: `INFO - Slot 0 using audio driver: ASIO`

ASIO is the second-best option after JACK.

---

## What to Report

For each test, please tell me:

1. **Which driver was used?**
   - Look for: `INFO - Slot 0 using audio driver: [NAME]`

2. **Did Aspen Trumpet crash when opening UI?**
   - ✅ Works / ❌ Crashes

3. **Did Scrooo crash when sending MIDI?**
   - ✅ Works / ❌ Crashes

4. **Did parameters appear for Aspen?**
   - ✅ Yes, after X seconds / ❌ No

5. **Did you hear audio output?**
   - ✅ Yes / ❌ No / ⚠️ Only with UI open

---

## Expected Results

### DirectSound/WASAPI
- May still have crashes (the original problem)
- Or might work if the lock/threading fixes solved it
- **Purpose**: Baseline test

### JACK
- Should work perfectly (you said it worked before with JACK)
- No crashes expected
- Clean audio routing
- **Purpose**: Known-good configuration

### ASIO
- Should be better than DirectSound
- May work almost as well as JACK
- **Purpose**: Fallback if JACK is too complex

---

## Troubleshooting

### "start_jack.bat" says "JACK server not found"

Check if jackd.exe exists:
```batch
dir "C:\Ambiance2\Carla-main\Carla-2.5.10-win32\Carla\jackd.exe"
```

If not found, download JACK2 from https://jackaudio.org/downloads/

### JACK starts but Ambiance doesn't see it

Wait 2-3 seconds after starting JACK before launching Ambiance.

### JACK audio is crackling/glitchy

Increase buffer size in start_jack.bat:
```batch
jackd.exe -d portaudio -r 48000 -p 1024
```
(Change 512 to 1024 or 2048)

### Can't get JACK working at all

Don't worry! Just use DirectSound/ASIO and report results. We may have already fixed the crashes with the other code changes.

---

## My Prediction

I believe:
- **DirectSound**: May still crash (but worth testing if other fixes helped)
- **JACK**: Will work perfectly (since it did before)
- **ASIO**: Will work better than DirectSound

But let's test to confirm! Start with Test 1 (DirectSound) since that requires no setup.
