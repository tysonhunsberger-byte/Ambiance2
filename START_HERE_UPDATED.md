# 🎵 Ambiance - Quick Start Guide (Updated)

## All Issues Fixed! ✅

This guide includes **all recent fixes** for:
- ✅ Digital keyboard not displaying
- ✅ Audio architecture clarification
- ✅ Carla library discovery
- ✅ Included plugins not showing

---

## Quick Start (3 Steps)

### 1. Navigate to the ambiance folder
```bash
cd C:\Ambiance2\ambiance
```
⚠️ **Important:** You MUST run from the `ambiance` subfolder, not from `C:\Ambiance2`!

### 2. Start the server
```bash
python -m ambiance.server
```

You should see:
```
Starting Ambiance server on http://127.0.0.1:8000/
Carla backend available: True
Qt support available: True
```

### 3. Open your browser
Navigate to: **http://127.0.0.1:8000/**

---

## Using the Digital Keyboard

### Step 1: Load a Plugin

1. Find the **"Plugin Library"** section on the page
2. You should see your included plugins:
   - Aspen Trumpet 1.dll
   - Harmonical.dll
   - scrooo.vst3
   - scrooo64.dll

3. Click on one (try **Aspen Trumpet 1** first)
4. Click **"⬆️ Load Selected"**

### Step 2: Find the Keyboard

After loading, scroll down to find the **"Digital Instrument"** panel.

You should see:
- 🎹 **On-screen keyboard** with white and black keys
- **Octave controls** (◀ Oct / Oct ▶)
- **Velocity slider**
- **Preview button**

### Step 3: Play and Listen

1. **Turn on your speakers/headphones!** 🔊
2. **Increase your volume** (audio plays through system audio, not browser)
3. Click a keyboard key
4. **Listen!**

---

## Important: Where Audio Comes From

### ⚠️ Audio plays through your SPEAKERS/HEADPHONES, NOT the browser!

This is the **correct behavior**. Here's how it works:

```
You click a key in browser
    ↓
Browser sends MIDI note-on
    ↓
Carla receives MIDI
    ↓
VST Plugin generates audio
    ↓
Audio goes to Windows audio driver (DirectSound/WASAPI)
    ↓
YOUR SPEAKERS/HEADPHONES 🔊
```

**The browser is NOT involved in audio playback!**

This is how professional audio software works (DAWs, plugin hosts) to provide:
- Lowest latency
- Direct hardware access
- Best audio quality

---

## Troubleshooting

### "Carla backend available: False"

**Fix:**
```bash
# Make sure you're in the right folder!
cd C:\Ambiance2\ambiance
python -m ambiance.server
```

**Still not working?**
Check that `C:\Ambiance2\Carla-main\` exists and contains Carla source code.

---

### "No plugins in library"

Your plugins should automatically appear from `C:\Ambiance2\included_plugins\`.

**If they don't show:**
1. Check the folder exists: `C:\Ambiance2\included_plugins\`
2. Check it contains plugin files (`.vst3`, `.dll`)
3. Restart the server

---

### "Keyboard doesn't show"

The keyboard only appears for **MIDI-capable plugins** (instruments and MIDI effects).

**Check:**
1. Did you click "Load Selected" and wait for it to load?
2. Is the "Digital Instrument" panel visible (not collapsed)?
3. Check browser console (F12) for errors

**Verify the plugin supports MIDI:**
Visit: `http://127.0.0.1:8000/api/vst/status`

Look for:
```json
{
  "capabilities": {
    "midi": true,
    "instrument": true
  }
}
```

If both are `false`, the plugin might be an **effect** (not an instrument), and won't show a keyboard.

---

### "I can't hear any audio"

This is the **#1 most common issue** - and it's usually system audio settings!

**Checklist:**

✅ **1. Are your speakers/headphones ON?**
- Check power, check volume knob
- Test with YouTube or Spotify first

✅ **2. Is Windows audio working?**
- Right-click speaker icon → Open Sound Settings
- Test audio output with another app
- Check that correct output device is selected

✅ **3. Is the volume up?**
- Windows system volume
- Application volume in Volume Mixer
- Physical speaker/headphone volume

✅ **4. Is Carla engine running?**
Visit: `http://127.0.0.1:8000/api/vst/status`
```json
{
  "available": true,
  "engine": {
    "running": true,
    "driver": "DirectSound"
  }
}
```

✅ **5. Is MIDI routing connected?**
```json
{
  "capabilities": {
    "midi_routed": true  ← Should be true
  }
}
```

If `false`, wait a few seconds and refresh - Carla is still connecting MIDI paths.

✅ **6. Is it actually an instrument?**
```json
{
  "capabilities": {
    "instrument": true  ← Should be true for synths
  }
}
```

**Effects** (reverb, delay, etc.) need an audio input to process. They won't make sound on their own!

---

## Understanding Audio Routing

### Why you don't hear audio in the browser:

1. **Browser sends MIDI** (note-on/note-off messages)
2. **Carla receives MIDI** and passes to plugin
3. **Plugin generates audio** in real-time
4. **Carla outputs to Windows audio driver** (DirectSound, WASAPI, ASIO)
5. **Audio plays through your speakers/headphones**

**The Web Audio API in your browser has NO access to Carla's audio stream.**

This is by design! This is how all professional audio software works (Ableton, FL Studio, Reaper, etc.).

---

## Advanced: Audio Drivers

Carla tries these drivers in order (on Windows):

1. **DirectSound** (most compatible, always works)
2. **WASAPI** (lower latency, Windows Vista+)
3. **MME** (legacy, high latency)
4. **ASIO** (lowest latency, requires ASIO4ALL or audio interface)
5. **Dummy** (no audio output, for testing)

Check which driver is active:
```
http://127.0.0.1:8000/api/vst/status
```

Look for: `"engine": {"driver": "DirectSound"}`

---

## Files You Can Check

### Verify All Fixes Are In Place
```bash
python C:\Ambiance2\check_fixes.py
```

### Documentation
- **FIXES_APPLIED.md** - Summary of keyboard and audio fixes
- **PATH_FIXES.md** - Summary of Carla and plugin discovery fixes
- **CLAUDE.md** - Complete reference documentation
  - See "Audio Architecture & Real-Time Playback" section
  - See "Troubleshooting Audio Issues" section

---

## Summary of What Was Fixed

### Keyboard Display Issue ✅
- **Fixed:** MIDI capability detection in `carla_host.py`
- **Result:** Keyboards now display for MIDI-capable plugins

### Audio Not Working "Issue" ✅
- **Explained:** Not a bug! Audio plays through system audio by design
- **Result:** Users now understand audio flows to speakers, not browser

### Carla Not Found Issue ✅
- **Fixed:** Enhanced sibling directory discovery
- **Result:** Carla-main found correctly when running from `ambiance/`

### Plugins Not Showing Issue ✅
- **Fixed:** Added `included_plugins` to scan paths
- **Result:** Included plugins automatically appear in library

---

## Getting Help

If you still have issues after following this guide:

1. **Check the status endpoint:**
   ```
   http://127.0.0.1:8000/api/vst/status
   ```

2. **Check browser console:**
   - Press F12
   - Look for red errors
   - Check Network tab for failed requests

3. **Read the documentation:**
   - `CLAUDE.md` - Complete reference
   - `FIXES_APPLIED.md` - Detailed troubleshooting
   - `PATH_FIXES.md` - Path and discovery issues

---

## Success Checklist

When everything is working, you should have:

- ✅ Server starts without errors
- ✅ "Carla backend available: True" in startup message
- ✅ Plugins appear in Plugin Library section
- ✅ Can click "Load Selected" and plugin loads
- ✅ "Digital Instrument" panel appears with keyboard
- ✅ Can click keyboard keys
- ✅ **Hear sound from speakers/headphones** 🎵

---

## Enjoy Making Music! 🎶

Remember:
- Run from `C:\Ambiance2\ambiance` folder
- Audio plays through speakers, not browser
- Turn up your volume!
- Have fun! 🎵

For technical details, see `CLAUDE.md` and the other documentation files.
