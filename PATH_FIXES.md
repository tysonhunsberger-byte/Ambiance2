# Additional Path & Discovery Fixes

## Issues Fixed

### Issue #1: Carla Library Not Found

**Error Message:**
```
libcarla_standalone2 library not found; build carla first
```

**Root Cause:**
When running the server from `C:\Ambiance2\ambiance\`, the Carla discovery logic was looking for `Carla-main` as a child directory, but it's actually a sibling at `C:\Ambiance2\Carla-main\`.

**Fix Applied:**
- **File:** `ambiance/src/ambiance/integrations/carla_host.py` (lines 393-408)
- **Changes:**
  - Enhanced sibling directory search to explicitly check for `Carla-main` and `Carla` as siblings
  - Added direct path checks before falling back to glob patterns
  - Now correctly discovers Carla when running from `ambiance/` subdirectory

---

### Issue #2: Included Plugins Not Showing in Library

**Problem:**
The plugins in `C:\Ambiance2\included_plugins\` were not appearing in the Plugin Library in the web interface.

**Root Cause:**
The plugin discovery only scanned the `.cache/plugins/` workspace directory, not the `included_plugins` folder.

**Fixes Applied:**

1. **Carla Plugin Directories** (`carla_host.py` lines 834-839)
   - Added `included_plugins` folder to Carla's plugin search paths
   - Checks both `base_dir/included_plugins` and `base_dir.parent/included_plugins`
   - Now automatically scans VST2/VST3 plugins in included_plugins

2. **Plugin Rack Discovery** (`plugins.py` lines 60-89)
   - Enhanced `_candidate_paths()` to scan multiple root directories
   - Added `included_plugins` folder to the scan list
   - Plugins now appear in the web UI's Plugin Library

---

## Files Modified

1. **ambiance/src/ambiance/integrations/carla_host.py**
   - Enhanced Carla root discovery for sibling directories
   - Added `included_plugins` to default plugin search paths

2. **ambiance/src/ambiance/integrations/plugins.py**
   - Modified `_candidate_paths()` to scan `included_plugins` folder
   - Supports both `base_dir` and `base_dir.parent` for flexibility

3. **CLAUDE.md**
   - Updated running instructions to specify `cd ambiance` first

4. **FIXES_APPLIED.md**
   - Updated testing instructions to specify correct working directory

---

## Correct Usage

### Starting the Server

**✅ CORRECT:**
```bash
cd C:\Ambiance2\ambiance
python -m ambiance.server
```

**❌ INCORRECT:**
```bash
cd C:\Ambiance2
python -m ambiance.server  # Will fail to find Carla!
```

### Why?

The project structure is:
```
C:\Ambiance2\
├── ambiance/               ← Run from HERE
│   ├── src/
│   │   └── ambiance/
│   ├── tests/
│   └── pyproject.toml
├── Carla-main/            ← Carla source (sibling)
└── included_plugins/      ← Your plugins (sibling)
```

When you run from `ambiance/`, the code:
- Looks for `Carla-main` as a sibling (`../Carla-main`)
- Looks for `included_plugins` as a sibling (`../included_plugins`)
- Finds both correctly! ✅

---

## Verification

### Check Carla Discovery

Start the server and check the logs:
```bash
cd C:\Ambiance2\ambiance
python -m ambiance.server
```

You should see:
```
Starting Ambiance server on http://127.0.0.1:8000/
Carla backend available: True
Qt support available: True
```

**NOT:**
```
Carla backend available: False
libcarla_standalone2 library not found
```

### Check Plugin Discovery

Navigate to: `http://127.0.0.1:8000/api/plugins`

You should see your included plugins:
```json
{
  "ok": true,
  "plugins": [
    {
      "name": "Aspen Trumpet 1",
      "path": "C:\\Ambiance2\\included_plugins\\Aspen-Trumpet-1_64\\Aspen Trumpet 1.dll",
      "format": "VST (Windows)"
    },
    {
      "name": "Harmonical",
      "path": "C:\\Ambiance2\\included_plugins\\Harmonical\\Harmonical.dll",
      "format": "VST (Windows)"
    },
    {
      "name": "scrooo",
      "path": "C:\\Ambiance2\\included_plugins\\scrooo64\\scrooo.vst3",
      "format": "VST3"
    },
    {
      "name": "scrooo64",
      "path": "C:\\Ambiance2\\included_plugins\\scrooo64\\scrooo64.dll",
      "format": "VST (Windows)"
    }
  ]
}
```

---

## Troubleshooting

### "Carla backend available: False"

**Check:**
1. Are you running from `C:\Ambiance2\ambiance`? (not from `C:\Ambiance2`)
2. Does `C:\Ambiance2\Carla-main\source\frontend\carla_backend.py` exist?
3. Does `C:\Ambiance2\Carla-main\` contain the Carla source code?

**Try:**
```bash
cd C:\Ambiance2\ambiance
python -c "from ambiance.integrations.carla_host import CarlaVSTHost; h = CarlaVSTHost(); print(f'Available: {h.available}'); print(f'Root: {h.root}'); print(f'Library: {h.library_path}')"
```

This will show you where it's looking for Carla.

### "No plugins in library"

**Check:**
1. Does `C:\Ambiance2\included_plugins\` exist?
2. Are there `.vst3` or `.dll` files inside subfolders?

**Try:**
```bash
cd C:\Ambiance2
python -c "from pathlib import Path; plugins = list(Path('included_plugins').rglob('*.vst3')) + list(Path('included_plugins').rglob('*.dll')); print(f'Found {len(plugins)} plugins:'); [print(f'  - {p}') for p in plugins]"
```

### Environment Variable Alternative

If you can't run from the `ambiance/` folder, set the `CARLA_ROOT` environment variable:

**Windows PowerShell:**
```powershell
$env:CARLA_ROOT = "C:\Ambiance2\Carla-main"
python -m ambiance.server
```

**Windows CMD:**
```cmd
set CARLA_ROOT=C:\Ambiance2\Carla-main
python -m ambiance.server
```

---

## Summary

✅ **Carla discovery fixed** - Now finds Carla-main as a sibling directory
✅ **Plugin discovery fixed** - Now scans included_plugins folder
✅ **Documentation updated** - Instructions specify correct working directory

**Next steps:**
1. `cd C:\Ambiance2\ambiance`
2. `python -m ambiance.server`
3. Open `http://127.0.0.1:8000/`
4. Load a plugin and test the keyboard!
