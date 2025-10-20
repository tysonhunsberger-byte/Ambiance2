# Ambiance Plugin Host

Simple standalone VST plugin host with native UI support.

## Features
- Load VST3 and VST2 plugins
- Native plugin UI (opens automatically)
- Parameter controls with real-time sync
- Parameter changes in native UI reflected in host sliders
- Support for both 32-bit and 64-bit plugins (via Carla bridge)

## Quick Start

1. **Install dependencies:**
   ```
   pip install PyQt5
   ```

2. **Run the host:**
   ```
   start_plugin_host.bat
   ```
   Or directly: `python plugin_host.py`

3. **Load a plugin:**
   - Click "Load VST Plugin"
   - Select your .vst3 or .dll file
   - Native UI opens automatically

## Setup for 32-bit Plugin Support

The assertion error you saw is now fixed with better synchronization. For 32-bit DLL loading:

1. **Get Carla with bridge executables:**
   - Download: https://github.com/falkTX/Carla/releases
   - Get the Windows binary release (e.g., `Carla-2.5.8-win64.zip`)
   - Extract to `C:\Ambiance2\Carla-main` OR set `CARLA_ROOT` environment variable

2. **Verify bridge files exist:**
   The Carla binary release should contain:
   - `carla-bridge-win32.exe` (for 32-bit plugins)
   - `carla-bridge-win64.exe` (for 64-bit plugins)
   - `carla-bridge-native.exe`

3. **Check status in the host:**
   - Load the host and check the status label
   - Any warnings about missing bridges will be shown

## Audio Routing

Carla handles audio routing internally. To hear your plugins:

1. **On Windows:**
   - Plugins route through DirectSound/WASAPI by default
   - For lower latency, install ASIO4ALL or use JACK

2. **Start JACK (optional, for best performance):**
   ```
   scripts\start_jack.ps1
   ```
   Then restart the plugin host

## Troubleshooting

**"Carla assertion failure":**
- Fixed in latest version with better synchronization
- Restart the host if you see this

**"Cannot handle this binary":**
- Missing bridge executables for 32/64-bit conversion
- Download Carla binary release (not just source)
- Check warnings in status label

**Plugin UI won't open:**
- Ensure PyQt5 is installed: `pip install PyQt5`
- Some plugins don't have native UIs (VST2 legacy)
- Check status label for Qt availability

**No sound:**
- Check Windows audio settings
- Try different plugins to verify
- For instruments, MIDI routing needs additional work
- Effects process audio from Carla's internal generator

## Project Structure

```
C:\Ambiance2\
├── plugin_host.py              # Main host application
├── start_plugin_host.bat       # Quick launcher
├── ambiance\
│   └── src\
│       └── ambiance\
│           └── integrations\
│               └── carla_host.py   # Carla backend
└── Carla-main\                 # Carla installation (extract here)
```

## Known Limitations

- Full MIDI playback needs additional implementation
- Offline rendering requires more Carla integration  
- Audio is routed through Carla's real-time engine
- Some VST2 plugins may have compatibility issues

## Parameters

- **Sliders:** Adjust parameters in the host
- **Native UI:** Changes sync to host sliders automatically
- **Real-time:** Parameters update at 10Hz (100ms polling)
- **No feedback loops:** Updates from UI don't trigger host changes

Enjoy making sounds!
