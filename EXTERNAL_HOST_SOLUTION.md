# External Plugin Host Solution

## The Problem

Carla's `show_custom_ui()` function blocks the Qt event loop, causing a deadlock when called from the Python server. This prevents native plugin UIs from appearing.

## The Solution

Run a **separate Python process** (`plugin_host.py`) that:
1. Has its own Qt event loop
2. Loads the same plugin
3. Shows the native UI
4. Syncs parameter changes back to the server via HTTP

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   BROWSER (Web UI)                      │
│  • Plugin Library                                       │
│  • Digital Keyboard                                     │
│  • Load/Unload buttons                                  │
└─────────────────┬───────────────────────────────────────┘
                  │ HTTP API
                  ↓
┌─────────────────────────────────────────────────────────┐
│              PYTHON SERVER (Carla)                      │
│  • Loads VST plugin                                     │
│  • Processes MIDI → Audio                               │
│  • Routes audio to speakers                             │
│  • Receives parameter updates via HTTP                  │
└──────────────┬──────────────────────────────────────────┘
               │
               │ Spawns
               ↓
┌─────────────────────────────────────────────────────────┐
│         EXTERNAL PLUGIN HOST (Separate Process)         │
│  • plugin_host.py                                       │
│  • Own Carla instance (for UI only)                     │
│  • Own Qt event loop                                    │
│  • Shows native plugin UI                               │
│  • Polls for parameter changes                          │
│  • Sends parameter updates to server via HTTP           │
└─────────────────────────────────────────────────────────┘
```

## How It Works

### 1. Loading a Plugin
1. User loads plugin in web UI
2. Server's Carla instance loads plugin and sets up audio routing
3. Audio flows: MIDI → Server Carla → Speakers

### 2. Showing Native UI
1. User clicks "Show Plugin UI" button
2. Server spawns `plugin_host.py` as separate process:
   ```bash
   python plugin_host.py --plugin "path/to/plugin.dll" --server http://127.0.0.1:8000
   ```
3. External host:
   - Loads the same plugin in its own Carla instance
   - Shows the native UI (works because it has its own Qt event loop)
   - Starts polling for parameter changes every 100ms

### 3. Parameter Synchronization

**User adjusts knob in native UI:**
1. External host detects parameter change via polling
2. Sends HTTP POST to `/api/vst/parameter`:
   ```json
   {"id": 0, "value": 0.75}
   ```
3. Server updates its Carla instance's parameter
4. **Sound changes!** (Server's Carla processes audio)

**User plays notes on web keyboard:**
1. Browser sends MIDI to server
2. Server's Carla processes MIDI with current parameters
3. Audio output reflects the UI changes

## Files Modified

### 1. `plugin_host.py` (C:\Ambiance2\plugin_host.py)
- Added `requests` library import
- Added `server_url` parameter
- Added `send_parameter_to_server()` method
- Modified parameter polling to send changes to server
- Modified slider handlers to send changes to server

### 2. `ambiance/src/ambiance/server.py`
- Modified `/api/vst/editor/open` to launch external host
- Modified `/api/vst/editor/close` to terminate external host
- Modified `/api/vst/unload` to terminate external host
- Kept `/api/vst/parameter` endpoint for receiving updates

### 3. `ambiance/src/ambiance/integrations/carla_host.py`
- Removed blocking `show_ui()` attempts
- Kept parameter setting functionality

## Testing

### Step 1: Install requirements
```bash
pip install requests
```

### Step 2: Reinstall package
```bash
cd C:\Ambiance2\ambiance
pip uninstall ambiance -y
pip install -e .
```

### Step 3: Start server
```bash
python -m ambiance.server
```

### Step 4: Test the flow
1. Open http://127.0.0.1:8000/
2. Load a plugin (e.g., Aspen Trumpet 1)
3. Play notes on web keyboard - **hear audio ✓**
4. Click "🪟 Show Plugin UI"
5. **Native UI window appears!** (separate process)
6. Adjust parameters in native UI (e.g., vibrato, filter)
7. Play notes on web keyboard
8. **Sound reflects parameter changes!** ✓

## Advantages

✅ Native UI actually appears and is responsive
✅ Parameter changes affect the sound
✅ Web keyboard continues to work
✅ Audio routing stays intact
✅ No Qt event loop deadlocks

## Limitations

⚠️ Two separate Carla instances (one for audio, one for UI)
⚠️ Slight latency in parameter sync (100ms polling)
⚠️ External window management (separate process)

## Troubleshooting

### "Module 'requests' not found"
```bash
pip install requests
```

### Native UI doesn't appear
Check server console for:
```
Spawned external plugin host for...
```

Check for `plugin_host.py` in task manager/process list

### Parameter changes don't affect sound
Check server console for:
```
Server parameter update failed: 500
```

Ensure `/api/vst/parameter` endpoint is working

### Multiple UIs appear
Only one external host should run at a time. The server terminates the old one before spawning a new one.

## Summary

This solution provides the best of both worlds:
- **Web UI**: Lightweight keyboard interface, plugin library
- **Native UI**: Full plugin control with all parameters
- **Parameter Sync**: Changes in native UI affect web keyboard audio

The external host approach works around Qt event loop limitations by running the UI in a completely separate process with its own event loop!
