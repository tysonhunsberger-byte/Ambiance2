# Quick Reference - VST Plugin Integration

## 🚀 Quick Fix (5 minutes)

```bash
cd C:\dev\ambiance
python fix_vst_integration.py
```

That's it! The script will:
1. Install PyQt5 if needed
2. Backup your file
3. Apply the fix
4. Run tests

## ✅ Verify It Works

```bash
python test_vst_integration.py
```

Should show: "SUCCESS: All tests passed! 🎉"

## 📦 What You Need

- **Required**: PyQt5 (`pip install PyQt5`)
- **Required**: Carla binary at `C:\dev\ambiance\Carla-main\Carla\libcarla_standalone2.dll`

## 🎵 Load a Plugin (Python)

```python
from ambiance.integrations.carla_host import CarlaVSTHost

host = CarlaVSTHost()
plugin = host.load_plugin("C:/path/to/plugin.vst3")

if plugin['capabilities']['editor']:
    host.show_ui()  # Opens plugin's native UI
```

## 🌐 Load a Plugin (HTTP)

```bash
# Load
curl -X POST http://localhost:8000/api/vst/load \
  -d '{"path": "C:/path/to/plugin.vst3"}'

# Show UI
curl -X POST http://localhost:8000/api/vst/editor/open
```

## ❓ Check Status

```python
status = host.status()
print(f"Available: {status['available']}")
print(f"Qt Ready: {status['qt_available']}")
print(f"Warnings: {status['warnings']}")
```

## 🔧 Common Fixes

| Problem | Solution |
|---------|----------|
| "PyQt5 not installed" | `pip install PyQt5` |
| "libcarla not found" | Ensure Carla binary exists in Carla-main/Carla/ |
| "Plugin UI won't show" | Check if plugin has UI: `capabilities['editor']` |
| "Qt not initialized" | Restart app (should auto-initialize) |

## 📁 Files Created

- `carla_host_fixed.py` - The fix
- `fix_vst_integration.py` - Auto-apply script
- `test_vst_integration.py` - Test suite
- `VST_INTEGRATION_FIX_GUIDE.md` - Full guide
- `FIX_SUMMARY.md` - Detailed summary
- `QUICK_REFERENCE.md` - This file

## 🎯 What Was Fixed

1. ✅ Qt application auto-initialization
2. ✅ PyQt5 detection and warnings
3. ✅ Better error messages
4. ✅ Improved DLL discovery
5. ✅ Status reporting

## 📊 Status Fields

```json
{
  "available": true,           // Carla loaded
  "qt_available": true,        // Qt working
  "engine_path": "...",        // DLL location
  "warnings": [],              // Issues found
  "capabilities": {
    "editor": true,            // Can show UI
    "instrument": false        // Is synth
  }
}
```

## 🎹 Plugin Capabilities

- `editor`: Plugin has native UI
- `instrument`: Plugin is a synth/instrument

## 🔍 Debug Steps

1. Run `python test_vst_integration.py`
2. Check `status['warnings']` array
3. Verify PyQt5: `python -c "import PyQt5; print('OK')"`
4. Verify Carla DLL exists
5. Try simple plugin first

## 📚 More Info

- **Full Guide**: `VST_INTEGRATION_FIX_GUIDE.md`
- **Summary**: `FIX_SUMMARY.md`
- **Carla Docs**: https://kx.studio/Applications:Carla

## 💡 Tips

- UI opens in separate window (native plugin interface)
- Qt event loop runs automatically at 60 FPS
- Multiple plugins can be loaded (one at a time)
- Works without PyQt5 (parameters only, no UI)

## 🐛 Still Broken?

Check detailed diagnostics:
```python
host = CarlaVSTHost()
for warning in host.status()['warnings']:
    print(warning)
```

Each warning explains the specific issue.

---

**Need help?** See the full guides in:
- `VST_INTEGRATION_FIX_GUIDE.md`
- `FIX_SUMMARY.md`
