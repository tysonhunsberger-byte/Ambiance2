# VST Plugin Integration Fix Guide

## Problem Summary

Your Carla VST integration wasn't working because:

1. **Missing PyQt5 dependency**: Carla requires PyQt5 to display plugin UIs, but it wasn't installed or initialized
2. **No Qt Application Context**: Plugin UIs need a Qt event loop to function, but none was created
3. **Library path issues**: The DLL search might not find all required dependencies

## Solution

I've created a fixed version of `carla_host.py` that addresses all these issues.

### Key Improvements

1. **Qt Integration**
   - Automatically detects and initializes PyQt5 if available
   - Creates a Qt application instance with proper event loop
   - Provides clear error messages if PyQt5 is missing

2. **Better Error Handling**
   - More detailed warnings about what's not working
   - Graceful fallback when Qt isn't available
   - Better library discovery on Windows

3. **Enhanced Library Discovery**
   - Searches more locations for the Carla DLL
   - Properly handles Windows DLL dependencies
   - Better error messages when library isn't found

## Installation Steps

### Step 1: Install PyQt5

```bash
pip install PyQt5
```

This is **required** for plugin UIs to work!

### Step 2: Replace the file

Replace the current `carla_host.py` with the fixed version:

```bash
# Backup the original
copy C:\dev\ambiance\src\ambiance\integrations\carla_host.py C:\dev\ambiance\src\ambiance\integrations\carla_host.py.backup

# Use the fixed version
copy C:\dev\ambiance\src\ambiance\integrations\carla_host_fixed.py C:\dev\ambiance\src\ambiance\integrations\carla_host.py
```

### Step 3: Verify Carla is built

Make sure you have the Carla library built. Check that this file exists:
```
C:\dev\ambiance\Carla-main\Carla\libcarla_standalone2.dll
```

If it doesn't exist, you'll see a helpful error message telling you to build Carla first.

## Testing

Run your app and check the status endpoint:

```python
# In your app or via the API
status = vst_host.status()
print(status)
```

You should see:
- `"available": true` - Carla is loaded
- `"qt_available": true` - PyQt5 is working
- `"capabilities": {"editor": true}` - Plugin UIs are available
- Warnings array explaining any issues

## Common Issues & Solutions

### Issue: "PyQt5 not installed"

**Solution**: Run `pip install PyQt5`

### Issue: "libcarla_standalone2 library not found"

**Solution**: 
1. Check that Carla source is in `C:\dev\ambiance\Carla-main`
2. Make sure you have the binary distribution in `Carla-main\Carla\` folder
3. Or build Carla from source (see Carla documentation)

### Issue: "Qt application not initialized"

**Solution**: This should be automatic now. If you still see this, there may be a conflict with another Qt application. Try restarting your app.

### Issue: Plugin UI doesn't show

**Possible causes**:
1. Plugin doesn't have a custom UI - check `capabilities.editor` in status
2. Qt event loop not running - the fix should handle this automatically
3. Plugin is crashing - check warnings in status

## How Plugin UIs Work Now

When you call `show_ui()`:

1. The fixed code checks if PyQt5 is available
2. Creates/reuses a QApplication instance
3. Starts a Qt event loop timer (60 FPS)
4. Calls Carla's `show_custom_ui()` which opens the plugin's native UI
5. The Qt event loop processes UI events automatically

## API Usage

```python
from ambiance.integrations.carla_host import CarlaVSTHost

# Create host
host = CarlaVSTHost()

# Check status
status = host.status()
print(f"Carla available: {status['available']}")
print(f"Qt available: {status['qt_available']}")
print(f"Warnings: {status['warnings']}")

# Load plugin
try:
    plugin = host.load_plugin("path/to/plugin.vst3", show_ui=False)
    print(f"Loaded: {plugin['metadata']['name']}")
    
    # Show UI if supported
    if plugin['capabilities']['editor']:
        host.show_ui()
    else:
        print("Plugin has no custom UI")
        
except Exception as e:
    print(f"Error: {e}")
```

## HTTP API Usage

The server endpoints should now work properly:

```bash
# Load plugin and show UI
curl -X POST http://localhost:8000/api/vst/load \
  -H "Content-Type: application/json" \
  -d '{"path": "C:/path/to/plugin.vst3"}'

# Show plugin editor
curl -X POST http://localhost:8000/api/vst/editor/open

# Check status
curl http://localhost:8000/api/vst/status
```

## Advanced Configuration

### Custom Carla Location

Set environment variable before running:
```bash
set CARLA_ROOT=C:\path\to\your\carla
python -m ambiance.server
```

### Disable Qt (Headless Mode)

If you don't need plugin UIs, you can run without PyQt5. The app will fall back to parameter-only control.

## Differences from Original

The fixed version:

1. ✅ Auto-initializes Qt application
2. ✅ Provides detailed status information
3. ✅ Better error messages
4. ✅ Checks for PyQt5 availability
5. ✅ Improved DLL/library discovery
6. ✅ More defensive programming
7. ✅ Better documentation

## Still Have Issues?

Check the warnings array in the status response:

```python
status = host.status()
for warning in status['warnings']:
    print(f"Warning: {warning}")
```

Common warnings explained:
- "PyQt5 not installed" → Install PyQt5
- "Carla source tree not found" → Set CARLA_ROOT or put Carla in correct location
- "Failed to load libcarla" → DLL is missing or dependencies aren't met
- "Qt initialization failed" → Conflict with existing Qt app or missing Qt plugins

## Next Steps

1. Install PyQt5: `pip install PyQt5`
2. Replace carla_host.py with the fixed version
3. Test loading a plugin
4. Try showing the plugin UI
5. Enjoy your working VST integration! 🎵

## Support

If you continue to have issues:

1. Check the full error messages in `status['warnings']`
2. Verify Carla binary exists at expected location
3. Make sure you're using Python 3.8+
4. Try with a simple plugin first (like a synth with a UI)

The fixed code is much more robust and provides detailed diagnostic information to help identify remaining issues.
