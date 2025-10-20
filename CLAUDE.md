# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Ambiance is a modular audio generation toolkit combining procedural synthesis with VST plugin hosting. The system uses Carla for native plugin integration and provides both a command-line renderer and an interactive web-based UI (Noisetown interface).

## Key Commands

### Development Environment

```bash
# Set up virtual environment and install
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -e .
```

### Testing

```bash
# Run all tests
pytest

# Run specific test file
pytest ambiance/tests/test_carla_host.py

# Run tests with verbose output
pytest -v
```

### Running the Application

```bash
# Navigate to the ambiance subdirectory first
cd ambiance

# Start the web server (default: http://127.0.0.1:8000/)
python -m ambiance.server

# Start with custom UI file
python -m ambiance.server --ui custom_interface.html

# Render audio from CLI
python -m ambiance.cli output.wav --duration 10

# Render with custom configuration
python -m ambiance.cli output.wav --config config.json
```

### Plugin Host

```bash
# Run standalone plugin host
python plugin_host.py

# Auto-load a plugin
python plugin_host.py --plugin "C:\path\to\plugin.vst3"

# Specify audio driver preferences
python plugin_host.py --driver DirectSound --driver ASIO
```

## Architecture

### Core Components

**AudioEngine** (`ambiance/src/ambiance/core/engine.py`)
- Combines multiple audio sources and applies effects in sequence
- Uses a mix-down algorithm that prevents clipping by normalizing peaks
- Configured via JSON or programmatically through the registry

**Registry System** (`ambiance/src/ambiance/core/registry.py`)
- Central registration for audio sources and effects using decorators
- Enables dynamic discovery: `@registry.register_source` and `@registry.register_effect`
- Classes are auto-discovered when imported

**Server** (`ambiance/src/ambiance/server.py`)
- Threading HTTP server serving both static UI and JSON endpoints
- Manages plugin rack assignments, VST hosting, and audio rendering
- Spawns external plugin host processes for desktop UI integration

### Plugin Integration

**CarlaVSTHost** (`ambiance/src/ambiance/integrations/carla_host.py`)
- Primary VST2/VST3 plugin host using Carla backend
- Requires PyQt5 for native plugin UIs
- Manages Qt application lifecycle via QtApplicationManager singleton
- Supports MIDI note-on/off, parameter control, and offline rendering
- Audio drivers configured via `configure_audio(preferred_drivers=[...])`

**Plugin Host Window** (`plugin_host.py`)
- Standalone PyQt5 application for VST plugin hosting
- Loads plugins with native UI and parameter synchronization
- Polls plugin parameters at 10Hz to reflect changes from native UI
- Uses CarlaVSTHost backend for plugin management

**JuceVST3Host** (`ambiance/src/ambiance/integrations/juce_vst3_host.py`)
- Alternative VST3 host using JUCE framework
- Spawns external C++ process for plugin UI
- Located in `ambiance/cpp/juce_host/`

**PluginRackManager** (`ambiance/src/ambiance/integrations/plugins.py`)
- Manages plugin assignments to stream lanes (A/B comparison)
- Workspace directory: `.cache/plugins` (auto-created)
- Tracks plugin metadata and lane assignments

### Audio Processing

**Sources** (`ambiance/src/ambiance/sources/`)
- `SineWaveSource`, `NoiseSource`, `ResonantInstrumentSource`, `VocalFormantSource`
- All implement `generate(duration, sample_rate) -> np.ndarray`

**Effects** (`ambiance/src/ambiance/effects/`)
- `ReverbEffect`, `DelayEffect`, `LowPassFilterEffect`
- All implement `apply(buffer, sample_rate) -> np.ndarray`

**Audio Utilities** (`ambiance/src/ambiance/utils/audio.py`)
- `write_wav()` - Write numpy array to WAV file
- `encode_wav_bytes()` - Encode to in-memory WAV for HTTP responses

## Important Implementation Details

### Carla Integration on Windows

The Carla binary is expected at:
- `C:\Ambiance2\Carla-main\Carla-2.5.10-win32\libcarla_standalone2.dll`
- Or via `CARLA_ROOT` environment variable

Audio driver priority (Windows):
1. DirectSound (default, most compatible)
2. WASAPI
3. MME
4. ASIO (lowest latency, requires ASIO4ALL or native support)
5. JACK (requires separate installation)
6. Dummy (no audio output)

### Qt Requirement for Plugin UIs

Native plugin editors require PyQt5:
```bash
pip install PyQt5
```

Without PyQt5:
- Plugins can still be loaded and controlled via parameters
- Native UIs will not be available
- System provides clear warnings in status responses

### NumPy Compatibility Layer

The codebase has a compatibility layer (`ambiance/src/ambiance/npcompat.py` and `simple_numpy.py`) to support operation with or without NumPy. When working with audio buffers, always use the `np` import from `npcompat`:

```python
from ..npcompat import np
```

### HTTP API Endpoints

All endpoints are defined in `AmbianceRequestHandler`:

**Audio Rendering**
- `POST /api/render` - Render audio from procedural sources/effects

**Plugin Management**
- `GET /api/plugins` - List available plugins
- `POST /api/plugins/assign` - Assign plugin to stream/lane
- `POST /api/plugins/remove` - Remove plugin assignment
- `POST /api/plugins/toggle` - Switch active lane

**VST Control (Carla)**
- `POST /api/vst/load` - Load plugin (auto-shows UI if available)
- `POST /api/vst/unload` - Unload current plugin
- `POST /api/vst/parameter` - Set parameter value
- `POST /api/vst/render` - Render audio preview
- `POST /api/vst/midi/note-on` - Send MIDI note-on
- `POST /api/vst/midi/note-off` - Send MIDI note-off
- `POST /api/vst/midi/send` - Play note with duration
- `POST /api/vst/editor/open` - Show plugin UI
- `POST /api/vst/editor/close` - Hide plugin UI
- `GET /api/vst/status` - Get plugin status

**JUCE Integration**
- `POST /api/juce/open` - Launch JUCE host
- `POST /api/juce/close` - Terminate JUCE host
- `POST /api/juce/refresh` - Refresh JUCE executable path

### External Plugin Host Process

When a plugin is loaded via `/api/vst/load`, the server automatically spawns an external `plugin_host.py` process with the same audio driver configuration. This provides:
- Separate process isolation for plugin UIs
- Desktop window for native plugin editors
- Synchronized parameter control with web UI

The process is stored in `_plugin_host_process` and terminated on server shutdown or plugin unload.

## Testing Strategy

Tests are located in `ambiance/tests/`:
- `test_engine.py` - Core audio engine functionality
- `test_carla_host.py` - Carla integration (requires Carla binaries)
- `test_vst_host.py` - VST host wrapper tests
- `test_juce_host.py` - JUCE integration tests
- `test_plugins.py` - Plugin rack manager tests
- `test_server.py` - HTTP server endpoint tests

Pytest configuration in `pyproject.toml` excludes external dependencies:
```toml
norecursedirs = ["Carla-main", "jack2-1.9.22", "pycarla-master", "vsthost_1.16_source"]
```

## Common Development Patterns

### Adding a New Audio Source

```python
from ambiance.core.base import AudioSource
from ambiance.core.registry import registry
from ambiance.npcompat import np

@registry.register_source
class MyCustomSource(AudioSource):
    def __init__(self, param1: float = 1.0):
        self.param1 = param1

    def generate(self, duration: float, sample_rate: int) -> np.ndarray:
        num_samples = int(duration * sample_rate)
        # Generate audio buffer
        return np.zeros(num_samples, dtype=np.float32)

    def to_dict(self) -> dict:
        return {"type": "MyCustomSource", "param1": self.param1}
```

### Adding a New Effect

```python
from ambiance.core.base import AudioEffect
from ambiance.core.registry import registry
from ambiance.npcompat import np

@registry.register_effect
class MyCustomEffect(AudioEffect):
    def __init__(self, intensity: float = 0.5):
        self.intensity = intensity

    def apply(self, buffer: np.ndarray, sample_rate: int) -> np.ndarray:
        # Process buffer
        return buffer * self.intensity

    def to_dict(self) -> dict:
        return {"type": "MyCustomEffect", "intensity": self.intensity}
```

### Working with Carla Status

The Carla host provides detailed status including warnings:

```python
status = vst_host.status()
# Check availability
if not status['available']:
    print("Carla backend unavailable")
    for warning in status.get('warnings', []):
        print(f"  - {warning}")
    return

# Check Qt support
if not status.get('qt_available'):
    print("Qt not available - plugin UIs disabled")

# Check loaded plugin
if status.get('plugin'):
    plugin = status['plugin']
    print(f"Loaded: {plugin['metadata']['name']}")
    print(f"Parameters: {len(status.get('parameters', []))}")
```

## Audio Architecture & Real-Time Playback

### How Audio Flows Through the System

Ambiance uses **two different audio paths** depending on how you're using it:

#### Path 1: Procedural Audio Rendering (CLI & /api/render)
```
AudioEngine → Sources → Effects → Mix → WAV file or Base64-encoded audio
```
- Used by `python -m ambiance.cli output.wav`
- Used by `/api/render` endpoint
- Audio is rendered offline and returned to browser
- Browser plays audio via Web Audio API

#### Path 2: Real-Time VST Plugin Hosting (Carla)
```
Browser → /api/vst/midi/note-on → Carla Engine → Plugin → Audio Driver → Speakers/Headphones
```
- Used by Noisetown digital keyboard interface
- **Audio bypasses the browser entirely**
- Carla routes audio directly to your system audio device
- MIDI events are sent from the browser, but audio output is native

### Why You Don't Hear Plugin Audio in the Browser

**This is expected behavior!** When you load a VST plugin and use the digital keyboard:

1. The browser sends MIDI note-on/off messages via `/api/vst/midi/*` endpoints
2. Carla receives the MIDI and passes it to the plugin
3. The plugin generates audio in real-time
4. **Carla outputs audio directly to your system audio device (DirectSound/WASAPI/ASIO)**
5. You hear the audio through your speakers/headphones, **not through the browser**

The Web Audio API cannot access Carla's real-time audio stream because:
- Carla is a separate native process with direct system audio access
- Browser security restrictions prevent accessing system audio streams
- Real-time audio processing requires native APIs (DirectSound, ASIO, JACK)

### Digital Keyboard Display

The on-screen keyboard appears when:
1. A plugin is loaded via `/api/vst/load`
2. The plugin's capabilities include `midi: true` or `instrument: true`
3. The `/api/vst/ui` endpoint successfully returns a descriptor

If the keyboard doesn't appear, check:
- Plugin is properly loaded (check `/api/vst/status`)
- Plugin supports MIDI input (instrument or MIDI effect)
- No errors in browser console from `/api/vst/ui` request

### Troubleshooting Audio Issues

**"I can't hear anything when I press keyboard keys"**

Check these in order:
1. **Is Carla engine running?**
   - Check `/api/vst/status` - look for `"engine": {"running": true}`
   - Look for `"available": true` in the response

2. **Is the plugin loaded?**
   - `/api/vst/status` should show `"plugin": {...}` with plugin details
   - Not `"plugin": null`

3. **Is MIDI routing connected?**
   - Check `"capabilities": {"midi_routed": true}` in status
   - If false, Carla is still connecting MIDI paths

4. **Is your system audio working?**
   - Test with another audio application
   - Check Windows audio settings / Sound Control Panel
   - Ensure the correct audio device is selected

5. **Which audio driver is Carla using?**
   - Check `"engine": {"driver": "DirectSound"}` in status
   - DirectSound is most compatible on Windows
   - Try forcing a driver: `vst_host.configure_audio(forced_driver="DirectSound")`

6. **Is the plugin actually an instrument?**
   - Some plugins are effects, not instruments
   - Effects need an audio input to process
   - Check `"capabilities": {"instrument": true}` in plugin metadata

**"The keyboard doesn't show up"**

1. Check browser console for errors from `/api/vst/ui?path=...`
2. Verify plugin has MIDI capabilities: `"capabilities": {"midi": true}` in `/api/vst/status`
3. Ensure the instrument panel isn't hidden due to JavaScript errors

### Preview vs. Real-Time

The "Preview" button (future feature) will:
- Render a short audio clip offline via `/api/vst/render`
- Encode it as WAV and send to browser
- Play through Web Audio API

This is different from real-time keyboard playback which goes directly to system audio.

## Known Issues & Workarounds

### VST Integration Fix Status

Several documentation files (`FIX_SUMMARY.md`, `VST_INTEGRATION_FIX_GUIDE.md`, `START_HERE.md`) describe fixes for Carla/Qt integration. The main integration file is `carla_host.py`, with `carla_host_fixed.py` containing an updated version. Check git status to see which version is active.

### Parameter Synchronization

The plugin host polls parameters at 100ms intervals to sync with native UI changes. Avoid feedback loops by using the `updating_from_plugin` flag pattern when implementing parameter updates.

### Audio Driver Selection

On Windows, if no audio is heard:
1. Check Carla's selected driver via status endpoint
2. Try forcing DirectSound: `vst_host.configure_audio(forced_driver="DirectSound")`
3. For ASIO, ensure ASIO4ALL or native ASIO drivers are installed
4. Check Windows audio device settings
5. Verify the plugin is actually an instrument (not an effect)

## File Locations

- **Main source**: `ambiance/src/ambiance/`
- **Tests**: `ambiance/tests/`
- **UI interface**: `ambiance/noisetown_ADV_CHORD_PATCHED_v4g1_applyfix.html`
- **Plugin workspace**: `.cache/plugins/` (created on demand)
- **Carla binaries**: `Carla-main/Carla-2.5.10-win32/`
- **JUCE host**: `ambiance/cpp/juce_host/`

## Dependencies

Core dependencies:
- Python 3.9+
- PyQt5 (for plugin UIs)

Optional dependencies:
- NumPy (faster audio processing; falls back to pure Python)
- Typer (for enhanced CLI features)

External components:
- Carla (VST hosting)
- JUCE (alternative VST3 hosting)
