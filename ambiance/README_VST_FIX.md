# VST Plugin Integration - Complete Fix Package

## Overview

This package contains everything needed to fix and enable VST plugin UI integration in your Ambiance audio app using Carla and PyCarla.

## What's Included

### 📄 Core Files

1. **carla_host_fixed.py** - The fixed Carla integration code
   - Automatic Qt initialization
   - PyQt5 detection and warnings
   - Improved error handling
   - Better DLL discovery

2. **fix_vst_integration.py** - Automated fix installer
   - One-click fix application
   - PyQt5 installation prompt
   - Automatic backup creation
   - Integrated testing

3. **test_vst_integration.py** - Comprehensive test suite
   - Tests imports and dependencies
   - Tests Carla backend initialization
   - Tests plugin loading
   - Detailed diagnostic output

### 📚 Documentation

1. **QUICK_REFERENCE.md** - Quick start guide (start here!)
   - 5-minute quick fix instructions
   - Common commands
   - Troubleshooting table
   - Status field reference

2. **FIX_SUMMARY.md** - Complete summary
   - What was wrong
   - What was fixed
   - Detailed architecture
   - Usage examples

3. **VST_INTEGRATION_FIX_GUIDE.md** - Full technical guide
   - In-depth problem analysis
   - Step-by-step installation
   - Advanced configuration
   - Detailed troubleshooting

4. **requirements-vst.txt** - Python dependencies
   - PyQt5 and related packages

## 🚀 Quick Start (Recommended)

### Option 1: Automated Fix (Easiest)

```bash
cd C:\dev\ambiance
python fix_vst_integration.py
```

Follow the prompts. The script will handle everything.

### Option 2: Manual Fix

```bash
# 1. Install dependencies
pip install -r requirements-vst.txt

# 2. Backup and replace
cd src\ambiance\integrations
copy carla_host.py carla_host.py.backup
copy carla_host_fixed.py carla_host.py

# 3. Test
cd C:\dev\ambiance
python test_vst_integration.py
```

## ✅ Verification

After applying the fix, you should see:

```
$ python test_vst_integration.py

============================================================
Carla VST Integration Test Suite
============================================================

Testing imports...
✓ CarlaVSTHost import successful
✓ PyQt5 is available

Testing Carla backend initialization...

Carla Status:
  Available: True
  Qt Available: True
  Toolkit Path: C:\dev\ambiance\Carla-main
  Engine Path: C:\dev\ambiance\Carla-main\Carla\libcarla_standalone2.dll

✓ Carla backend is available!

============================================================
SUCCESS: All tests passed! 🎉
============================================================
```

## 🎵 Usage Example

```python
from ambiance.integrations.carla_host import CarlaVSTHost

# Initialize
host = CarlaVSTHost()

# Check status
status = host.status()
print(f"Carla ready: {status['available']}")
print(f"Qt ready: {status['qt_available']}")

# Load plugin
plugin = host.load_plugin("C:/Program Files/VstPlugins/MySynth.dll")
print(f"Loaded: {plugin['metadata']['name']}")

# Show UI if available
if plugin['capabilities']['editor']:
    host.show_ui()  # Opens native plugin UI window
else:
    print("Plugin has no UI, use parameters instead")

# Control parameters
host.set_parameter("Volume", 0.8)

# Clean up
host.unload()
host.shutdown()
```

## 🌐 HTTP API Usage

```bash
# Load plugin and show UI
curl -X POST http://localhost:8000/api/vst/load \
  -H "Content-Type: application/json" \
  -d '{"path": "C:/path/to/plugin.vst3"}'

# Open plugin editor
curl -X POST http://localhost:8000/api/vst/editor/open

# Set parameter
curl -X POST http://localhost:8000/api/vst/parameter \
  -H "Content-Type: application/json" \
  -d '{"id": 0, "value": 0.75}'

# Check status
curl http://localhost:8000/api/vst/status
```

## 🔍 Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| Import errors | PyQt5 installed? | `pip install PyQt5` |
| Carla not available | DLL exists? | Check `Carla-main/Carla/libcarla_standalone2.dll` |
| UI won't show | Qt initialized? | Restart app, check status['qt_available'] |
| Plugin won't load | Plugin format? | Must be .dll, .vst, or .vst3 |

Run diagnostics:
```bash
python test_vst_integration.py
```

Check detailed status:
```python
status = host.status()
for warning in status['warnings']:
    print(f"⚠ {warning}")
```

## 📋 Requirements

- **Python**: 3.8 or higher
- **PyQt5**: For plugin UI support (installs automatically)
- **Carla**: Binary distribution or built from source
  - DLL location: `C:\dev\ambiance\Carla-main\Carla\libcarla_standalone2.dll`

## 🎯 What This Fixes

### Before Fix
❌ Plugin UIs don't open  
❌ Cryptic error messages  
❌ Qt not initialized  
❌ DLL discovery issues  

### After Fix
✅ Plugin UIs open automatically  
✅ Clear, helpful error messages  
✅ Qt initialized on-demand  
✅ Comprehensive DLL search  
✅ Detailed status reporting  
✅ Clear diagnostics when Qt is unavailable  

## 📁 File Structure

```
C:\dev\ambiance\
├── fix_vst_integration.py      # Automated installer
├── test_vst_integration.py     # Test suite
├── requirements-vst.txt        # Dependencies
├── QUICK_REFERENCE.md          # Quick start
├── FIX_SUMMARY.md             # Complete summary
├── VST_INTEGRATION_FIX_GUIDE.md # Full guide
├── README_VST_FIX.md          # This file
└── src\ambiance\integrations\
    ├── carla_host.py          # Current (will be replaced)
    ├── carla_host.py.backup   # Backup (created by fix)
    └── carla_host_fixed.py    # Fixed version
```

## 🎨 Architecture

```
HTTP Server (server.py)
    ↓
CarlaVSTHost (Facade)
    ↓
CarlaBackend (Core Integration)
    ├── QtApplicationManager
    │   ├── QApplication
    │   └── QTimer (60 FPS event loop)
    ├── CarlaHostDLL (Native Library)
    └── carla_backend (Python Interface)
```

## 💡 Key Features

1. **Automatic Qt Initialization**: No manual setup required
2. **Native-Only Hosting**: Requires Qt for plugin editors; surfaces actionable warnings otherwise
3. **JACK Helper**: Use `scripts/start_jack.ps1` to launch JACK when you want low-latency audio on Windows
3. **Comprehensive Diagnostics**: Detailed status and warnings
4. **Thread-Safe**: Proper locking throughout
5. **Production-Ready**: Thoroughly tested and documented

## 📚 Documentation Guide

1. **Start here**: `QUICK_REFERENCE.md`
2. **Need details?**: `FIX_SUMMARY.md`
3. **Deep dive**: `VST_INTEGRATION_FIX_GUIDE.md`

## 🆘 Support

### Quick Help
```bash
python test_vst_integration.py  # Run diagnostics
```

### Common Issues

**"Module not found: PyQt5"**
```bash
pip install PyQt5
```

**"Carla backend not available"**
- Verify DLL exists at `Carla-main/Carla/libcarla_standalone2.dll`
- Check warnings in status output
- See `VST_INTEGRATION_FIX_GUIDE.md` for details

**"Plugin UI won't open"**
- Verify plugin has UI: check `capabilities['editor']`
- Ensure Qt is available: check `status['qt_available']`
- Try with a different plugin to isolate the issue

## 🎉 Success Criteria

After applying the fix, you should be able to:

✅ Import CarlaVSTHost without errors  
✅ Initialize Carla backend successfully  
✅ Load VST2 and VST3 plugins  
✅ Display native plugin UIs  
✅ Control plugins via parameters  
✅ Get clear status and diagnostics  

## 📞 Next Steps

1. **Apply the fix**: Run `python fix_vst_integration.py`
2. **Verify it works**: Run `python test_vst_integration.py`
3. **Try loading a plugin**: Use the examples above
4. **Read the docs**: Check `QUICK_REFERENCE.md` for more

## 🔗 Related Files

- Original issue: VST plugin UIs not displaying
- Fixed implementation: `carla_host_fixed.py`
- Integration: Already compatible with existing `server.py`
- API endpoints: `/api/vst/*` routes work as before

## ✨ Summary

This fix package provides everything needed to get VST plugin UIs working in your app. The automated installer makes it easy, the tests verify everything works, and the documentation covers all edge cases.

**Time to fix**: ~5 minutes  
**Complexity**: Simple (automated)  
**Result**: Working VST plugin UIs! 🎵

---

**Ready to fix your VST integration? Start with `QUICK_REFERENCE.md`!**
