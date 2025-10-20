# Ambiance Qt Troubleshooting Guide

## Recent Fixes Applied

### 1. UI Opening Crash Fix
**Issue**: "QThread destroyed" error when opening plugin UI
**Cause**: Lock contention - holding `slot.lock` while calling `show_ui()` caused deadlock
**Fix**: Removed lock acquisition before `show_ui()` call since it handles threading internally

### 2. MIDI Crash Fix
**Issue**: App crashes when sending MIDI to some plugins
**Cause**: Lock contention during MIDI operations
**Fix**: Removed lock during `note_on()` and `note_off()` calls since they're thread-safe internally

### 3. Parameter Discovery Improvement
**Issue**: Parameters don't appear for some plugins (Aspen Trumpet)
**Fix**: Increased retry attempts from 3 to 5 with progressive delays (1000ms → 2000ms)

### 4. Plugin Activation Improvements
**Issue**: Some plugins don't process audio until UI is opened
**Fix**: Added extra `engine_idle()` calls after activation and routing to ensure plugin is ready

## Plugin-Specific Issues

### Known Working Plugins
- ✅ **Darksichord VST3**: UI works, MIDI works, audio output confirmed
  - Note: May require UI to be visible for audio processing (plugin limitation)

### Problematic Plugins

#### Aspen Trumpet
**Status**: Has multiple issues
- ❌ **UI Crash**: Opening native UI causes segfault in plugin's C++ code
- ❌ **No Parameters**: Plugin doesn't expose parameters via standard Carla API
- **Recommendation**: Avoid opening native UI, use generic controls if available

#### Scrooo VST3
**Status**: Partial functionality
- ⚠️ **MIDI Crash**: Sending MIDI notes causes segfault in plugin's C++ code
- ✅ **Parameters**: Successfully reports parameters
- **Recommendation**: Avoid sending MIDI input to this plugin

## Understanding Plugin Crashes

### What Causes Crashes?
Many crashes occur at the **C++ level** in either:
1. **Carla's native code** (the VST host library)
2. **Plugin's native code** (the VST plugin itself)

These are called **segmentation faults (segfaults)** and Python cannot catch them with try/except blocks.

### Why Can't We Prevent Them?
- Python runs in a virtual machine that can catch Python exceptions
- Segfaults happen in native C/C++ code below Python's control
- When a segfault occurs, the entire process crashes instantly

### Workarounds
1. **Test plugins individually** before using in production
2. **Avoid problematic operations** (e.g., don't open Aspen UI, don't send MIDI to Scrooo)
3. **Report bugs to plugin developers** - these are plugin bugs, not Ambiance bugs
4. **Use alternative plugins** - many VST plugins exist with similar functionality

## Audio Processing Issues

### Plugin Only Works With UI Open
**Symptoms**: Plugin produces no audio until you press "Show UI"

**Possible Causes**:
1. **Plugin Bug**: Some plugins don't initialize processing until UI is created
2. **Lazy Initialization**: Plugin defers setup until UI access
3. **Activation Timing**: Plugin needs time to fully initialize

**Solutions**:
- Open UI once after loading, then can close it
- Wait a few seconds after loading before sending MIDI
- Use a different plugin that doesn't have this issue

## Debugging Tips

### Check Logs
The app logs detailed information about:
- Plugin loading and activation
- MIDI routing status
- Audio routing status
- UI operations

Look for these emoji markers:
- 🪟 UI operations
- 🎹 MIDI operations
- ⚠️ Warnings
- ✓ Success confirmations

### Test Plugin Capabilities
1. Load plugin into slot
2. Check if parameters appear (wait 10+ seconds)
3. Try MIDI input (if it's an instrument)
4. Try opening UI (expect crash with buggy plugins)
5. Check audio output

### Identify Problematic Plugins
If the app crashes:
1. Note which plugin was loaded
2. Note what operation you performed (UI open, MIDI send, etc.)
3. Restart app and test a different plugin
4. Add problematic plugins to a mental blacklist

## Technical Details

### Thread Safety
- Each plugin slot has its own `RLock` for thread safety
- Locks are NOT held during potentially blocking operations (UI, MIDI)
- This prevents deadlocks but means plugins must be internally thread-safe

### Plugin Loading Process
1. Create CarlaVSTHost instance
2. Configure audio driver
3. Load plugin binary
4. **Activate plugin** (`set_active(True)`)
5. Wait for engine idle
6. Setup audio routing
7. Setup MIDI routing (if plugin supports it)
8. Final engine idle

### MIDI Sending Process
1. Check plugin is loaded and supports MIDI
2. Ensure MIDI routing is established
3. Ensure audio routing is established
4. Send MIDI note via Carla
5. Small delay (2ms) to prevent assertion failures
6. Engine idle to process action

## Recommendations

### For Stable Operation
1. **Use Darksichord** or other well-tested plugins
2. **Test new plugins carefully** in isolated sessions
3. **Save your work often** before experimenting
4. **Keep a list** of working vs problematic plugins

### For Development
1. Check Carla logs for detailed error messages
2. Test plugins in standalone Carla first to isolate issues
3. Report consistent crashes to plugin developers
4. Consider implementing plugin blacklist UI feature

## Future Improvements

Potential enhancements to consider:
- [ ] Plugin blacklist feature
- [ ] Crash recovery (auto-save state)
- [ ] Plugin sandbox (separate process per plugin)
- [ ] Built-in plugin testing tool
- [ ] Community-maintained compatibility database

---

## Need Help?

If you encounter new issues:
1. Check logs for error messages
2. Test the same plugin in standalone Carla
3. Try a different plugin to isolate the issue
4. Document the exact steps that cause crashes
