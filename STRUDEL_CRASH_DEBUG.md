# Strudel Crash Debugging Guide

## Current Status (2025-10-30)

Strudel mode is **enabled by default again** so you can exercise the embedded playground. The hard disable that routed everyone to strudel.cc has been removed, the Strudel bundle has been rebuilt with a Chrome 87 target, and the static server still falls back to the raw HTML for crash diagnostics.

If you hit instability and want to pause the embedded view, flip `STRUDEL_ENABLED` near the top of `ambiance_qt_improved.py` to `False`. You can also force the UI to load the remote site instead of the bundled assets by toggling `STRUDEL_FORCE_REMOTE`. All other diagnostics described below still apply.

## Debugging Enhancements Added

### 1. Qt WebEngine Crash Detection
**Location**: `ambiance_qt_improved.py` lines 208-226

The `StrudelWebPage` class now includes a `renderProcessTerminated` signal handler that will log:
- **Crash Type**: Normal/Abnormal/Crashed/Killed
- **Exit Code**: The process exit code (e.g., -1073741819 for access violation)
- **Current URL**: The URL being loaded when the crash occurred

### 2. JavaScript Console Logging
**Location**: `ambiance_qt_improved.py` lines 228-238

All JavaScript console messages are now captured and logged with:
- **Level**: INFO/WARNING/ERROR
- **Source File**: The JavaScript file that logged the message
- **Line Number**: Where the message was logged
- **Message**: The actual error or log message

### 3. Lifecycle Logging
**Location**: `ambiance_qt_improved.py` lines 2423-2468

Detailed logging throughout the Strudel activation process:
- When Strudel mode is toggled ON/OFF
- Checks for PyQtWebEngine availability
- Loading progress
- Container switching
- Any errors during activation

## Testing the Fix

### Step 1: Run the Application
```batch
start_ambiance_improved.bat
```

### Step 2: Click "Strudel Mode" Button
Watch the console output for detailed logging.

### Step 3: Check the Log
If it crashes, check `startup_error.log` for:

**Expected Log Sequence (Normal):**
```
INFO - Strudel mode toggled: ON
INFO - Activating Strudel mode - loading playground...
INFO - Loading Strudel from URL: http://127.0.0.1:XXXX/
INFO - Serving UNMODIFIED index.html for crash diagnosis
INFO - Setting Strudel URL...
INFO - Strudel load initiated successfully
INFO - Strudel page loaded successfully
INFO - Strudel mode activated successfully
```

**If Crash Occurs:**
```
CRITICAL - Qt WebEngine render process terminated: CrashedTerminationStatus, exit code: -1073741819
CRITICAL - Current URL: http://127.0.0.1:XXXX/index.html
[Strudel JS ERROR] /_astro/index.xyz.js:123 - TypeError: Cannot read property 'x' of undefined
```

## Current Testing Configuration

### Unmodified HTML Serving
The server is currently configured to serve **completely unmodified** `index.html` to isolate whether our modifications are causing the crash:

**Location**: `ambiance_qt_improved.py` lines 579-596

```python
# TESTING: Serve unmodified index.html to diagnose crashes
if self.path == '/index.html' or self.path == '/':
    index_path = root / 'index.html'
    if index_path.exists():
        logging.getLogger(__name__).info("Serving UNMODIFIED index.html for crash diagnosis")
        data = index_path.read_bytes()
        # ... serve raw file ...
```

This bypasses:
- Base URL rewriting
- Asset URL rewriting
- Polyfills (webkitStorageInfo, String.replaceAll)
- CSS injection

### Bridge Injection Disabled
The JavaScript bridge injection is temporarily disabled for testing:

**Location**: `ambiance_qt_improved.py` lines 2123-2126

```python
# Temporarily disable bridge injection to diagnose crashes
# self._ensure_strudel_channel()
# self._inject_strudel_bridge()
self.logger.info("Strudel load completed (bridge disabled for testing)")
```

## Next Steps Based on Results

### If Unmodified HTML Works:
Re-enable modifications one by one to find the culprit:
1. Re-enable base URL rewriting
2. Re-enable asset URL rewriting
3. Re-enable polyfills
4. Re-enable bridge injection

### If Unmodified HTML Still Crashes:
Investigate Qt WebEngine compatibility:
1. Check exit code in crash log (e.g., -1073741819 = access violation)
2. Look for missing DLLs in Qt installation
3. Try different PyQtWebEngine versions
4. Check Visual C++ Redistributables installation
5. Consider using Python 3.10 instead of 3.14

### Exit Code Reference:
- `0` = Normal termination
- `1` = General error
- `-1073741819` (0xC0000005) = Access violation (segfault)
- `-1073741515` (0xC0000135) = DLL not found
- `-1073740791` (0xC0000409) = Stack buffer overrun

## Files to Check

1. **Main Log**: `startup_error.log` (piped from stderr/stdout)
2. **Code**: `ambiance_qt_improved.py` (search for "Strudel")
3. **Documentation**: `AGENTS.md` (PyQtWebEngine Known Issues section)
4. **Fix Script**: `fix_pyqtwebengine.bat` (DLL repair script)

## Common Issues

### DLL Load Failure
```
DLL load failed while importing QtWebEngineWidgets: The specified module could not be found.
```

**Fix**: Run `fix_pyqtwebengine.bat` or install Visual C++ Redistributables

### Python Version Mismatch
```
PyQtWebEngine installed in Python 3.14 but script uses Python 3.10
```

**Fix**: Update `start_ambiance_improved.bat` to use consistent Python version

### JACK Errors (Safe to Ignore)
```
Cannot connect to named pipe \\.\pipe\server_jack_default_0
jack server is not running or cannot be started
```

**Status**: Expected - JACK is optional and not installed

## Success Criteria

The fix will be successful when:
1. Strudel mode loads without crashing
2. No "Qt WebEngine render process terminated" messages
3. JavaScript console shows normal Strudel initialization
4. Page displays without errors

## Additional Debugging Tools

### Enable Qt Message Handler
The application now captures all Qt warning/error messages via a custom message handler.

### JavaScript Debugging
All JavaScript console output is captured and logged with source file and line numbers.

### Crash Recovery
The crash detection logs the exact URL and JavaScript state when the crash occurs, making it easier to reproduce and fix.

---

**Last Updated**: 2025-10-30
**Status**: Testing with unmodified HTML
**Next Test**: Click Strudel Mode button and check logs
