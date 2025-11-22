# Ambiance

Ambiance is a modular audio toolkit that blends procedural synthesis, Strudel live coding, and VST hosting (Carla/JUCE) inside a Windows-styled desktop shell. This README lists the prerequisites required to run every subsystem locally.

## Prerequisites

| **Python** | 3.10.x | Core services (`ambiance_qt_improved.py`, CLI, HTTP server) | Use the official 3.10 installer for Windows. Install Windows Installer(64bit) at https://www.python.org/downloads/release/python-31011/ Earlier 3.8 builds work, but 3.10 is the most stable with PyQtWebEngine. |
| **Node.js** | ≥ 18 (recommended 22.x) with npm | Installs UI vendor CSS (`7.css`, `98.css`, `xp.css`) and runs Strudel tooling. | Install from [nodejs.org](https://nodejs.org/) and ensure `npm` is on PATH. |
| **pnpm + Corepack** | pnpm 8+ | Builds the bundled Strudel site (`resources/strudel`). | 
Run `corepack enable` then `corepack prepare pnpm@8.15.8 --activate` |
| **Strudel source** | current main | Live-coding UI and docs served offline. | `tools/sync_strudel.py` clones/builds the Strudel monorepo into `resources/strudel/dist`. |
| **SuperCollider** | 3.13.0 | Provides the SuperCollider plugin host + scsynth runtime used for embedded synths/effects. | Install from [supercollider.github.io](https://supercollider.github.io) and add `scsynth` to PATH. |
| **sc3-plugins** | matching SC build | Optional SuperCollider plugin set (filters, reverbs) leveraged by advanced presets. | Install from the [official release](https://github.com/supercollider/sc3-plugins/releases); ensure the Extensions folder is discovered by SuperCollider. |
| **Carla** | 2.5.10 (Win64) | Primary VST2/VST3/LV2/AU host. Ambiance looks for `libcarla_standalone2.dll`, `carla-bridge-win64.exe`, etc. | Place the Carla release in `ambiance/deps/carla_binaries` or set `CARLA_ROOT`. |
| **JUCE VST3 Host** | JUCE 7+ build | Provides the external UI host used when Carla delegates to native plugin GUIs. | Build `cpp/juce_host` per JUCE instructions and set `JUCE_VST3_HOST`. |
| **Qt WebEngine dependencies** | PyQt6/PyQtWebEngine (bundled) | Required for the embedded browser shell (`ambiance_qt_improved.py`). | 

## Bootstrap Steps

1. **Python environment**
   ```powershell
   py -3.10 -m venv .venv
   .\.venv\Scripts\activate
   python -m pip install -r requirements.txt  # if present
   ```
2. **Vendor CSS / npm deps**
   ```powershell
   npm install
   ```
3. **Strudel bundle**
   ```powershell
   cd resources\strudel
   pnpm install
   pnpm --filter ./website build
   cd ..\..
   python tools\sync_strudel.py
   ```
4. **Carla binaries**
   - Extract `Carla-2.5.10-win64` into `ambiance/deps/carla_binaries/`.
   - Verify `carla-bridge-win64.exe` and `libcarla_standalone2.dll` exist.
5. **SuperCollider + sc3-plugins**
   - Install SuperCollider 3.13.0 and sc3-plugins.
   - Launch SuperCollider once to populate registry entries; confirm `scsynth.exe` runs.

After the prerequisites are satisfied, launch the desktop shell via:

```powershell
python ambiance_qt_improved.py
```

or run start_ambiance_improved.bat

For CLI rendering:

```powershell
python -m ambiance.cli output.wav --duration 10
```
## Troubleshooting
If during corepack and pnpm setup, strudel says that pnpm cannot be found, or asks if it is on path, open an elevated(Run as Administrator) terminal and run `corepack install -g pnpm` and `corepack prepare pnpm@8.15.8 --activate`
