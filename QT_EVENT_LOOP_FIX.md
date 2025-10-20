# Qt Event Loop Fix for Native Plugin UIs

## Problem
The "Show Plugin UI" button request was timing out because the Qt event loop wasn't running, making plugin UIs unresponsive.

## Solution Implemented

### 1. Qt Event Loop in Main Thread
**File:** `ambiance/src/ambiance/server.py` (lines 607-666)

The server now:
- Runs the HTTP server in a **background daemon thread**
- Runs the Qt event loop in the **main thread** (via `qt_app.exec_()`)
- This allows plugin UIs to remain responsive

### 2. Thread-Safe UI Operations
**File:** `ambiance/src/ambiance/integrations/carla_host.py`

Simplified approach:
- Carla's `show_custom_ui()` is thread-safe (it's a C library call)
- The Qt event loop keeps the UI responsive
- No complex thread marshalling needed

## Testing

### Step 1: Reinstall
```bash
cd C:\Ambiance2\ambiance
pip uninstall ambiance -y
pip install -e .
```

### Step 2: Start Server
```bash
python -m ambiance.server
```

You should see:
```
PyQt5 available - running Qt event loop for responsive plugin UIs
Qt event loop running for plugin UIs. Press Ctrl+C to exit.
```

### Step 3: Test Plugin UI
1. Open http://127.0.0.1:8000/
2. Load a plugin (e.g., Aspen Trumpet 1)
3. Click "🪟 Show Plugin UI" button
4. **Expected:** Request completes quickly, native UI window appears
5. Adjust parameters in the native UI
6. Play notes - parameters should affect sound

## MIDI Range Issue

The MIDI issue (notes under C4 not producing audio) is a separate problem. This could be:

1. **Plugin range limitation**: Some instrument plugins only respond to specific MIDI note ranges that match the real instrument
2. **Velocity issue**: Lower notes might need higher velocity
3. **Plugin-specific behavior**: The plugin might be filtering certain notes

To diagnose:
- Try different plugins to see if all have the same issue
- Check the plugin's native UI for range settings
- Try playing the same notes directly in the native UI (if it has a keyboard)

## Architecture

```
┌─────────────────────────────────────┐
│     MAIN THREAD (Qt Event Loop)    │
│  - Processes Qt events              │
│  - Keeps plugin UIs responsive      │
│  - Handles window events            │
└─────────────────────────────────────┘
                 ↑
                 │ Thread-safe Carla calls
                 │
┌─────────────────────────────────────┐
│   BACKGROUND THREAD (HTTP Server)   │
│  - Handles API requests             │
│  - Calls show_ui() / hide_ui()      │
│  - Sends MIDI via Carla             │
└─────────────────────────────────────┘
```

## Files Changed

1. `ambiance/src/ambiance/server.py` - Qt event loop setup
2. `ambiance/src/ambiance/integrations/carla_host.py` - Simplified UI operations
