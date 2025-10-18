# VST Integration Fix - Checklist

Use this checklist to ensure everything is set up correctly.

## Pre-Fix Checklist

- [ ] Python 3.8 or higher installed
- [ ] Ambiance project at `C:\dev\ambiance`
- [ ] Carla directory exists at `C:\dev\ambiance\Carla-main`
- [ ] Can run Python scripts from command line

## Installation Checklist

### Automated Method
- [ ] Run `python fix_vst_integration.py`
- [ ] Accept PyQt5 installation if prompted
- [ ] Wait for backup creation
- [ ] Wait for fix application
- [ ] Review test results

### Manual Method
- [ ] Install PyQt5: `pip install -r requirements-vst.txt`
- [ ] Backup original: `copy carla_host.py carla_host.py.backup`
- [ ] Apply fix: `copy carla_host_fixed.py carla_host.py`
- [ ] Run tests: `python test_vst_integration.py`

## Verification Checklist

- [ ] No import errors when running tests
- [ ] PyQt5 shows as available
- [ ] Carla backend shows as available
- [ ] Qt shows as available
- [ ] Test script shows "SUCCESS: All tests passed! 🎉"

## Carla Installation Checklist

- [ ] `Carla-main` directory exists
- [ ] `Carla-main/Carla` subdirectory exists
- [ ] `libcarla_standalone2.dll` file exists in `Carla-main/Carla/`
- [ ] `carla_backend.py` exists in `Carla-main/source/frontend/`
- [ ] No DLL errors when initializing

### To verify Carla installation:
```bash
dir C:\dev\ambiance\Carla-main\Carla\libcarla_standalone2.dll
dir C:\dev\ambiance\Carla-main\source\frontend\carla_backend.py
```

Both should exist.

## PyQt5 Installation Checklist

- [ ] PyQt5 installed: `pip list | findstr PyQt5`
- [ ] Can import PyQt5: `python -c "import PyQt5; print('OK')"`
- [ ] Qt plugins available (automatic with PyQt5)

### To verify PyQt5:
```bash
python -c "import PyQt5; print('PyQt5 version:', PyQt5.QtCore.PYQT_VERSION_STR)"
```

Should print version number (e.g., 5.15.0).

## Plugin Testing Checklist

- [ ] At least one VST plugin available for testing
- [ ] Plugin placed in `.cache/plugins/` directory
- [ ] Plugin format supported (.dll, .vst, .vst3)
- [ ] Can load plugin without errors
- [ ] Parameters accessible
- [ ] UI opens if plugin has one

### Recommended test plugins:
- Any free VST synth with UI (e.g., Synth1, Dexed)
- Any simple effect with UI (e.g., free reverb/delay)

## Status Verification Checklist

Run this code and check all items:

```python
from ambiance.integrations.carla_host import CarlaVSTHost

host = CarlaVSTHost()
status = host.status()

# Should all be True:
print(f"Available: {status['available']}")        # Should be True
print(f"Qt Available: {status['qt_available']}")  # Should be True
print(f"Toolkit Path: {status['toolkit_path']}")  # Should show path
print(f"Engine Path: {status['engine_path']}")    # Should show path
print(f"Warnings: {status['warnings']}")          # Should be empty or informational
```

- [ ] `available: True`
- [ ] `qt_available: True`
- [ ] `toolkit_path` shows Carla directory
- [ ] `engine_path` shows DLL path
- [ ] No critical warnings

## Functional Testing Checklist

### Basic Functionality
- [ ] Can create CarlaVSTHost instance
- [ ] Can get status without errors
- [ ] Can load a plugin
- [ ] Can read plugin metadata
- [ ] Can read plugin parameters
- [ ] Can unload plugin cleanly
- [ ] Can shutdown host cleanly

### Parameter Control
- [ ] Can set parameter by ID
- [ ] Can set parameter by name
- [ ] Can read parameter current value
- [ ] Parameter changes persist
- [ ] Parameter validation works (min/max)

### UI Functionality (if PyQt5 available)
- [ ] Can check if plugin has UI
- [ ] Can open plugin UI
- [ ] Plugin UI window appears
- [ ] Plugin UI is interactive
- [ ] Can close plugin UI
- [ ] UI closes cleanly

### HTTP API (if using server)
- [ ] Server starts without errors
- [ ] `/api/vst/status` returns valid JSON
- [ ] Can load plugin via POST `/api/vst/load`
- [ ] Can set parameters via POST `/api/vst/parameter`
- [ ] Can open UI via POST `/api/vst/editor/open`
- [ ] Can close UI via POST `/api/vst/editor/close`

## Troubleshooting Checklist

If something doesn't work:

- [ ] Checked test output for specific errors
- [ ] Reviewed warnings in `status['warnings']`
- [ ] Verified all file paths are correct
- [ ] Tried with different plugin
- [ ] Restarted Python/terminal
- [ ] Re-ran fix script
- [ ] Checked documentation in `VST_INTEGRATION_FIX_GUIDE.md`

## Common Issues Resolution

### "PyQt5 not installed"
- [ ] Run: `pip install PyQt5`
- [ ] Verify: `python -c "import PyQt5; print('OK')"`
- [ ] If fails: Check pip is up to date: `python -m pip install --upgrade pip`

### "Carla backend not available"
- [ ] Check DLL exists: `dir Carla-main\Carla\libcarla_standalone2.dll`
- [ ] Check Python file exists: `dir Carla-main\source\frontend\carla_backend.py`
- [ ] Check CARLA_ROOT environment variable
- [ ] Try setting: `set CARLA_ROOT=C:\dev\ambiance\Carla-main`

### "Qt not initialized"
- [ ] Restart application
- [ ] Check PyQt5 installed correctly
- [ ] Check no conflicts with other Qt apps
- [ ] Try clean Python interpreter

### "Plugin won't load"
- [ ] Check plugin path is correct
- [ ] Check plugin format supported
- [ ] Try different plugin
- [ ] Check plugin isn't corrupted
- [ ] Check 32-bit vs 64-bit compatibility

### "UI won't show"
- [ ] Verify PyQt5 installed
- [ ] Check `capabilities['editor']` is true
- [ ] Check `qt_available` is true
- [ ] Try with different plugin
- [ ] Check no conflicts with other windows

## Documentation Review Checklist

- [ ] Read `QUICK_REFERENCE.md` for quick start
- [ ] Read `FIX_SUMMARY.md` for overview
- [ ] Read `VST_INTEGRATION_FIX_GUIDE.md` for details
- [ ] Reviewed examples in `examples_vst_usage.py`

## Post-Fix Checklist

- [ ] All tests pass
- [ ] Can load at least one plugin
- [ ] Parameters work
- [ ] UI works (if plugin has one)
- [ ] No critical errors or warnings
- [ ] Documentation reviewed
- [ ] Backup of original file kept

## Success Criteria

All of these should be true:

✅ Test script reports: "SUCCESS: All tests passed! 🎉"  
✅ Can load VST plugins without errors  
✅ Plugin metadata displays correctly  
✅ Parameters can be read and modified  
✅ Plugin UIs open (if plugin has UI and PyQt5 installed)  
✅ No critical warnings in status  
✅ HTTP API endpoints work (if using server)  

## Final Verification

Run the comprehensive test:

```bash
cd C:\dev\ambiance
python test_vst_integration.py
python examples_vst_usage.py
```

If both complete successfully, your VST integration is working! 🎵

---

## Notes

- Keep `carla_host.py.backup` in case you need to revert
- Test with simple plugins first before complex ones
- Check status warnings for helpful diagnostic information
- Refer to documentation for advanced usage

## Need Help?

If items are not checking off:

1. Review error messages carefully
2. Check the specific section in `VST_INTEGRATION_FIX_GUIDE.md`
3. Run diagnostic: `python test_vst_integration.py`
4. Check status: `host.status()['warnings']`
