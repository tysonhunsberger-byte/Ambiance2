# Plugin UI Error Handling Improvements

This document describes the enhanced error handling implemented for the Ambiance plugin rack UI system.

## Overview

The plugin UI system now has comprehensive error handling that provides:
- **Clear, actionable error messages** with specific guidance for common issues
- **Better error recovery** with automatic retry logic for transient failures
- **Graceful degradation** when Qt or display servers are unavailable
- **Detailed diagnostic information** to help troubleshoot configuration issues

## Changes Made

### 1. Backend Error Handling (`carla_host.py`)

#### Enhanced Qt Initialization
- **Before**: Generic "Qt initialization failed" message
- **After**: Specific error types with detailed explanations:
  - Import errors with reinstallation suggestions
  - Configuration errors with troubleshooting steps
  - User-friendly symbols (✓, ⚠, ℹ) for quick status scanning

#### Improved `_show_plugin_ui` Method
The plugin UI display method now handles multiple failure modes:

**Plugin Capability Checks**:
```python
# Now includes plugin name in error
raise CarlaHostError(
    f"{plugin_name} does not provide a native UI editor. "
    "This plugin may only support parameter automation."
)
```

**Qt Availability Checks**:
```python
# Clear installation instructions
raise CarlaHostError(
    "PyQt5 is not installed. Plugin UIs require PyQt5. "
    "Install it with: pip install PyQt5"
)
```

**Qt Initialization Checks**:
```python
# Multi-point checklist for debugging
raise CarlaHostError(
    "Qt application failed to initialize. This may happen if: \n"
    "1. The display server is not available (headless environment)\n"
    "2. PyQt5 installation is incomplete\n"
    "3. There are Qt library conflicts\n"
    "Try reinstalling PyQt5 or check your display configuration."
)
```

**Runtime Error Handling**:
- `AttributeError`: Catches incompatible Carla versions
- `RuntimeError`: Handles plugin UI creation failures with diagnostic steps
- Generic `Exception`: Catch-all with error type reporting

### 2. Frontend Error Handling (`web_ui_error_handling.js`)

#### New Utility Functions

**`formatApiError(error, payload)`**
- Parses errors from API responses
- Adds contextual tips based on error patterns
- Recognizes common issues (Qt, Carla, display server, plugin loading)

**`withRetry(apiCall, options)`**
- Automatic retry with exponential backoff
- Configurable retry conditions
- Progress callbacks for user feedback

**`apiFetch(url, options)`**
- Enhanced fetch wrapper
- Handles both HTTP errors and API-level errors
- Provides detailed network failure messages

**`validatePluginUiRequirements(status, plugin)`**
- Pre-flight checks before showing UI
- Returns structured validation results
- Prevents unnecessary API calls

**`withHostStateLock(operation, state, render, log)`**
- Prevents concurrent operations
- Automatic state management
- Consistent error reporting

### 3. Error Message Patterns

The system now recognizes and provides specific guidance for:

| Pattern | Guidance |
|---------|----------|
| PyQt5/Qt errors | Installation instructions |
| Display server issues | Headless environment detection |
| Carla library missing | Build instructions and environment setup |
| Plugin load failures | File validation suggestions |
| No plugin hosted | Operation order guidance |
| No custom UI | Feature availability explanation |

## Usage Examples

### Python Backend

```python
try:
    host.show_ui()
except CarlaHostError as e:
    # Error message now includes:
    # - What went wrong
    # - Why it might have happened (checklist)
    # - How to fix it
    print(e)
```

### JavaScript Frontend

```javascript
// Using the enhanced API fetch
try {
    const result = await apiFetch('/api/vst/editor/open', {
        method: 'POST'
    });
    // Success handling
} catch (error) {
    // Error is already formatted with helpful context
    log('❌ ' + error.message);
}

// Using retry logic for transient failures
await withRetry(
    () => fetch('/api/vst/status').then(r => r.json()),
    {
        maxRetries: 3,
        onRetry: (attempt, max) => {
            log(`⏳ Retrying (${attempt}/${max})...`);
        }
    }
);

// Validating requirements before operation
const validation = validatePluginUiRequirements(hostState.status, plugin);
if (!validation.valid) {
    log('⚠️ ' + validation.reason);
    return;
}
```

## Error Categories

### 1. Configuration Errors
**Symptoms**: Qt not available, Carla not found
**Resolution**: Installation and environment setup
**User Impact**: Clear installation instructions provided

### 2. Plugin Compatibility Errors
**Symptoms**: Plugin has no UI, unsupported format
**Resolution**: User informed of plugin limitations
**User Impact**: Understands what the plugin can/cannot do

### 3. Runtime Errors
**Symptoms**: UI window creation failed, display connection failed
**Resolution**: Troubleshooting checklist provided
**User Impact**: Can diagnose environment issues

### 4. Transient Errors
**Symptoms**: Network timeouts, temporary server issues
**Resolution**: Automatic retry with exponential backoff
**User Impact**: Seamless recovery from temporary failures

## Testing Recommendations

### Manual Testing

1. **Qt Not Installed**:
   ```bash
   # Uninstall PyQt5 temporarily
   pip uninstall PyQt5 -y
   # Try to show plugin UI
   # Expected: Clear message with installation command
   ```

2. **Headless Environment**:
   ```bash
   # Remove display
   unset DISPLAY
   # Try to show plugin UI
   # Expected: Headless environment detected with explanation
   ```

3. **Plugin Without UI**:
   - Load a parameter-only plugin (no GUI)
   - Try to show UI
   - Expected: Message explaining plugin doesn't have UI

4. **Network Issues**:
   - Stop the backend server
   - Perform UI operation
   - Expected: Network error with server start instructions

### Automated Testing

```python
# Example test case
def test_show_ui_without_qt():
    """Verify helpful error when Qt unavailable"""
    # Mock HAS_PYQT5 = False
    host = CarlaBackend()
    host.load_plugin("test_plugin.vst3")
    
    with pytest.raises(CarlaHostError) as exc:
        host.show_ui()
    
    assert "PyQt5 is not installed" in str(exc.value)
    assert "pip install PyQt5" in str(exc.value)
```

## Future Improvements

1. **Error Analytics**: Track common errors to identify systemic issues
2. **Automatic Fixes**: Offer to install PyQt5 automatically when missing
3. **Environment Detection**: Auto-detect headless environments and suggest alternatives
4. **Plugin Database**: Maintain known-good/known-problematic plugins
5. **Visual Error Overlay**: Rich HTML error display in the UI instead of just text logs

## Related Files

- `src/ambiance/integrations/carla_host.py` - Backend error handling
- `src/ambiance/web_ui_error_handling.js` - Frontend utilities
- `noisetown_ADV_CHORD_PATCHED_v4g1_applyfix.html` - UI integration (uses utilities)

## Support

If you encounter errors not covered by these improvements:
1. Check the console output for detailed diagnostics
2. Review the plugin rack activity log in the UI
3. Verify Qt/PyQt5 installation: `python -c "from PyQt5.QtWidgets import QApplication"`
4. Check Carla availability: ensure `CARLA_ROOT` environment variable is set
5. Open an issue with the full error message and environment details
