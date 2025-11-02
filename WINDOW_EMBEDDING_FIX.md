# Window Embedding Safety Fix

## Critical Bug Fixed

**Date:** 2025-11-01
**File:** `ambiance_qt_improved.py`
**Lines:** 774-866

### What Was Wrong

The `_find_plugin_window()` function was **extremely dangerous** and would:

1. **Enumerate ALL visible windows** on the entire system (not just plugin windows)
2. **Match ANY window** with generic keywords like "plugin", "vst", or "carla" in the title
3. **Reparent those windows** into the Ambiance UI container
4. **Did NOT verify** the window belonged to the Carla process
5. **Made windows unrecoverable** by changing their parent and style

### Example of What Went Wrong

```python
# UNSAFE CODE (now disabled):
def enum_callback(hwnd, _):
    if user32.IsWindowVisible(hwnd):
        # ... get window title ...
        # BUG: This matches ANY window with these keywords!
        if any(keyword in title.lower() for keyword in ['carla', 'vst', 'plugin']):
            windows.append((hwnd, title))
```

This would grab:
- ❌ "Visual Studio Code" (matches "vs" in "vst")
- ❌ "My Plugin Manager" (matches "plugin")
- ❌ "Carla's Photo Editor" (matches "carla")
- ❌ ANY application with these common words

### The Fix

**Window embedding has been completely disabled** until a safe implementation can be created.

The functions now immediately return with a warning message:
- `_attempt_embed_plugin_ui()` - Returns immediately, logs safety warning
- `_find_plugin_window()` - Returns 0 (no window found), logs safety warning

**Result:** Plugin UIs now open in separate windows (the safe, normal behavior).

## How to Safely Implement Window Embedding

If you want to re-enable window embedding in the future, follow this approach:

### 1. Get Process ID Verification

```python
def _find_plugin_window_safe(self) -> int:
    """Safe implementation that only finds windows owned by Carla process."""
    if os.name != 'nt':
        return 0

    # Get the Carla process ID
    if not self.carla or not hasattr(self.carla, 'get_process_id'):
        return 0

    carla_pid = self.carla.get_process_id()
    if not carla_pid:
        return 0

    user32 = ctypes.windll.user32
    windows = []

    def enum_callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True

        # CRITICAL: Verify window belongs to Carla process
        proc_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
        if proc_id.value != carla_pid:
            return True  # Skip windows from other processes

        # Now it's safe to check the title
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value

            # More specific matching
            if 'plugin' in title.lower() or 'vst' in title.lower():
                windows.append((hwnd, title))
        return True

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(EnumWindowsProc(enum_callback), 0)

    return windows[0][0] if windows else 0
```

### 2. Add Window Class Verification

```python
# Also check the window class name (more reliable than title)
class_buffer = ctypes.create_unicode_buffer(256)
user32.GetClassNameW(hwnd, class_buffer, 256)
class_name = class_buffer.value

# Only embed windows with known plugin window classes
SAFE_WINDOW_CLASSES = [
    'CarlaPluginWindow',
    'VSTPluginWindow',
    # Add other known safe classes
]

if class_name not in SAFE_WINDOW_CLASSES:
    return True  # Skip this window
```

### 3. Add User Confirmation

```python
# Before embedding, ask user for confirmation
from qtpy.QtWidgets import QMessageBox

result = QMessageBox.question(
    self,
    "Embed Plugin UI?",
    f"Found plugin window: {title}\n\nEmbed into Ambiance UI?",
    QMessageBox.Yes | QMessageBox.No,
    QMessageBox.No
)

if result != QMessageBox.Yes:
    return  # User declined
```

### 4. Store Original Window State

```python
# Before reparenting, save the original state
self._original_parent = user32.GetParent(plugin_hwnd)
self._original_style = user32.GetWindowLongW(plugin_hwnd, GWL_STYLE)
self._original_exstyle = user32.GetWindowLongW(plugin_hwnd, GWL_EXSTYLE)

# Then when restoring:
user32.SetParent(plugin_hwnd, self._original_parent)
user32.SetWindowLongW(plugin_hwnd, GWL_STYLE, self._original_style)
user32.SetWindowLongW(plugin_hwnd, GWL_EXSTYLE, self._original_exstyle)
```

## Reference: Safe Implementation in carla_host.py

The `ambiance/src/ambiance/integrations/carla_host.py` file has a **safe** implementation:

- Line 2406: Gets current process ID
- Lines 2414-2417: **Verifies window ownership** using `GetWindowThreadProcessId`
- Only enumerates windows belonging to the same process

This is the model to follow.

## Testing Checklist

Before re-enabling window embedding, verify:

- [ ] Process ID verification is implemented
- [ ] Only windows from Carla process are considered
- [ ] Window class name is verified (not just title)
- [ ] User confirmation dialog is shown
- [ ] Original window state is saved before reparenting
- [ ] Window can be properly restored on unload
- [ ] No system windows are affected
- [ ] Test with multiple plugins loaded
- [ ] Test with non-plugin applications running

## Additional Safety Measures

1. **Whitelist Approach**: Only embed windows with explicitly allowed class names
2. **Timeout**: Don't search indefinitely - give up after 2-3 seconds
3. **Logging**: Log every window examined (for debugging)
4. **Recovery**: Provide a "Reset Window" button to restore if something goes wrong
5. **Disable by Default**: Make embedding opt-in via settings

## Status

- ✅ Unsafe code disabled
- ✅ Safety warnings added
- ✅ Documentation written
- ⏳ Safe implementation pending
- ⏳ User confirmation dialog pending
- ⏳ Settings toggle pending

## Notes

- Plugin UIs opening in separate windows is **normal and safe**
- Window embedding is a **nice-to-have feature**, not essential
- Don't rush to re-enable - get it right first
- Consider using Carla's built-in window management instead
