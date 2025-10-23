# Ambiance – Agent Instructions for GPT Codex

**Project Summary**: Modular audio generation toolkit combining procedural synthesis (sine waves, noise, resonant instruments, vocal formants) with VST/VST3 plugin hosting for creative sound design through a browser-based UI.

## Core Architecture

### Audio Engine (`src/ambiance/core/`)
- **`engine.py`**: Main `AudioEngine` class orchestrates sources and effects. Uses `mix()` to blend buffers with automatic clipping prevention.
- **`base.py`**: Abstract `AudioSource` and `AudioEffect` base classes. All sources implement `generate(duration, sample_rate)`, effects implement `apply(buffer, sample_rate)`.
- **`registry.py`**: Decorator-based registration system. Use `@registry.register_source` or `@registry.register_effect` on any class to auto-register.

### Procedural Sources (`src/ambiance/sources/`)
- **`basic.py`**: `SineWaveSource` (pure tone), `NoiseSource` (white noise with seed control)
- **`integrated.py`**: `ResonantInstrumentSource` (plucked modal tone), `VocalFormantSource` (formant-based vowel synthesis with vibrato)
- All sources are dataclasses with `to_dict()` for JSON serialization

### Effects (`src/ambiance/effects/`)
- **`spatial.py`**: `ReverbEffect` (Schroeder-style feedback delay network), `DelayEffect` (ping-pong delay), `LowPassFilterEffect` (one-pole IIR filter)
- Effects chain sequentially through engine

### Plugin Integration (`src/ambiance/integrations/`)
- **`carla_host.py`**: Wraps Carla's `libcarla_standalone2` for VST2/VST3 hosting. Searches `Carla-main/`, `%PROGRAMFILES%\Carla` on Windows.
- **`juce_vst3_host.py`**: Launches external JUCE host process for native plugin UIs (see `cpp/juce_host/`). Communicates via subprocess IPC.
- **`flutter_vst_host.py`**: Lightweight fallback shim with simulated echo/reverb when Carla unavailable.
- **`plugins.py`**: `PluginRackManager` handles plugin discovery, A/B lane routing, workspace management.

### HTTP Server (`src/ambiance/server.py`)
- Serves `noisetown_ADV_CHORD_PATCHED_v4g1_applyfix.html` at `http://127.0.0.1:8000/`
- Endpoints:
  - `POST /api/render` – Accepts JSON config, returns base64 WAV data URL
  - `GET /api/registry` – Lists all registered sources/effects
  - Plugin rack endpoints for VST management
- Uses `ThreadingMixIn` for concurrent requests

### CLI Renderer (`src/ambiance/cli.py`)
- `python -m ambiance.cli output.wav --duration 10 --sample-rate 44100 [--config config.json]`
- JSON config format:
```json
{
  "sources": [{"name": "sine", "frequency": 440, "amplitude": 0.3}],
  "effects": [{"name": "reverb", "decay": 0.5, "mix": 0.3}]
}
```

### Utilities (`src/ambiance/utils/`)
- **`audio.py`**: `write_wav()`, `encode_wav_bytes()`, `normalize()` for WAV I/O

## Browser UI (Noisetown)

**File**: `noisetown_ADV_CHORD_PATCHED_v4g1_applyfix.html`

### Signal Path Per Stream
```
[A/B Sample Buffers] → [Sample VCA (ADSR)] ──┐
                                               ├─→ [Pre-EQ] → [LPF] → [3-Band EQ] → [Split]
[Tone/Noise Generators] ──────────────────────┘                                          │
                                                                                          ├─→ [Dry]
                                                                                          ├─→ [FX: Shaper→Delay→Feedback]
                                                                                          └─→ [Spaces: Convolver Reverb]
                                                                                                        ↓
                                                                                          [Sum] → [Pan] → [Out] → [Block Bus]
```

### Web Audio Nodes
- **Per Stream**: `gA`, `gB` (A/B gains), `sampleVCA` (ADSR target), `genSum` (tone/noise path), `lpf`, `eqLow/Mid/High`, `shaper`, `delay`, `fb`, `convolver`, `spWet`, `pan`, `out`
- **Master**: `MASTER.pre`, `MASTER.limiter` (dynamics compressor)

### Modulation System
- **LFO**: Targets pan/vol/lpf/tempo/pitch/ab/apos/bpos with rate/depth control
- **ADSR Envelope**: Attack/Decay/Sustain/Release applied to sample VCA only (not generators)
- **Gate**: Modulates master output with depth control
- Implemented in `<script id="mods-core-v1">` and `<script id="mods-advanced-v1">`

### Plugin Rack UI
- **Desktop Plugin UI Bridge**: Launches JUCE host via `/api/juce_host/launch?plugin_path=...`
- **Live VST Host**: Carla integration with parameter control via `/api/carla_host/...`
- **A/B Lanes**: Each stream has independent A/B sample slots with crossfade

## JUCE Host (`cpp/juce_host/`)

**Build**:
```bash
cd cpp/juce_host
cmake -B build -DJUCE_ROOT=/path/to/JUCE -DCMAKE_BUILD_TYPE=Release
cmake --build build
export JUCE_VST3_HOST="$(pwd)/build/JucePluginHost_artefacts/Release/JucePluginHost"
```

**Usage**: Server launches host with `subprocess.Popen([host_path, plugin_path])` and monitors process.

## PyCarla Integration (`pycarla-master/`)

**Purpose**: Python bindings for JACK + Carla MIDI synthesis. Used as reference for Carla integration patterns.

**Key Concepts**:
- Freewheeling mode for offline rendering
- `AudioRecorder`/`MIDIPlayer` classes for session management
- Patchbay mode configuration (`ProcessMode=3` in Carla config)

## Code Patterns

### Adding New Source
```python
@dataclass
@registry.register_source
class MySource(AudioSource):
    name: str = "my-source"
    param1: float = 1.0
    
    def generate(self, duration: float, sample_rate: int) -> np.ndarray:
        t = np.linspace(0, duration, int(duration * sample_rate), endpoint=False)
        return (self.param1 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data.update({"param1": self.param1})
        return data
```

### Adding New Effect
```python
@dataclass
@registry.register_effect
class MyEffect(AudioEffect):
    name: str = "my-effect"
    intensity: float = 0.5
    
    def apply(self, buffer: np.ndarray, sample_rate: int) -> np.ndarray:
        return (buffer * self.intensity).astype(np.float32)
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data.update({"intensity": self.intensity})
        return data
```

### Signal Processing Rules
1. **Always return `np.float32`** – Web Audio API and WAV I/O expect float32
2. **Clip outputs to [-1.0, 1.0]** – Prevent digital clipping
3. **Use `np.linspace(0, duration, int(duration * sample_rate), endpoint=False)`** for time arrays
4. **Use `np.random.default_rng(seed)`** for reproducible noise
5. **Apply alpha smoothing for parameter changes** – Web Audio uses `setTargetAtTime(value, time, 0.02)`

### Buffer Mixing
```python
def mix(buffers: Iterable[np.ndarray]) -> np.ndarray:
    buffers = list(buffers)
    max_len = max(len(buffer) for buffer in buffers)
    mix_buffer = np.zeros(max_len, dtype=np.float32)
    for buffer in buffers:
        for idx in range(len(buffer)):
            mix_buffer[idx] += float(buffer[idx])
    max_abs = np.max(np.abs(mix_buffer)) or 1.0
    if max_abs > 1.0:
        mix_buffer /= max_abs  # Normalize to prevent clipping
    return mix_buffer
```

## File Organization

```
ambiance/
├── src/ambiance/
│   ├── core/               # Engine, base classes, registry
│   ├── sources/            # Procedural audio generators
│   ├── effects/            # Signal processing
│   ├── integrations/       # VST hosting (Carla, JUCE, Flutter fallback)
│   ├── utils/              # Audio I/O utilities
│   ├── cli.py              # Command-line renderer
│   ├── server.py           # HTTP server with JSON API
│   └── npcompat.py         # NumPy import shim
├── cpp/juce_host/          # JUCE VST3 host (C++)
│   ├── CMakeLists.txt
│   └── src/Main.cpp
├── pycarla-master/         # Reference Carla Python bindings
├── Carla-main/             # Bundled Carla source (requires build)
├── noisetown_ADV_CHORD_PATCHED_v4g1_applyfix.html  # Browser UI
├── tests/                  # Pytest suite
├── pyproject.toml          # Package metadata
└── README.md
```

## Dependencies

**Python**:
- No hard dependencies in `pyproject.toml` (pure Python engine)
- Optional: `numpy>=1.21` (install with `pip install -e .[numpy]`)
- Optional: `typer>=0.9.0` (CLI, install with `pip install -e .[cli]`)

**System**:
- JACK (for Carla integration): `jackd2` on Linux
- Carla: Build `libcarla_standalone2.dll/.so/.dylib` from `Carla-main/`
- JUCE: Download from juce.com, point `JUCE_ROOT` env var

## Testing

```bash
pytest tests/
```

Tests cover:
- Engine rendering with multiple sources/effects
- Registry decorator functionality
- Server endpoint responses
- Plugin host fallback behavior
- Buffer mixing edge cases

## Common Tasks

### Render Audio File
```bash
python -m ambiance.cli output.wav --duration 10
```

### Launch UI Server
```bash
python -m ambiance.server [--port 8080] [--ui custom.html]
```

### Register Custom Source
1. Create dataclass in `src/ambiance/sources/`
2. Add `@registry.register_source` decorator
3. Import in `src/ambiance/__init__.py`
4. Restart server – now available via `/api/render` and CLI `--config`

### Add VST Plugin
1. Drop `.vst3`/`.dll`/`.component` in `.cache/plugins/` or `data/vsts/`
2. Refresh plugin rack UI
3. Assign to A/B lane via "Load Selected" button

### Build JUCE Host (Windows)
```powershell
cd cpp/juce_host
cmake -S . -B build -G "Visual Studio 17 2022" -A x64 -DJUCE_ROOT=C:/dev/JUCE
cmake --build build --config Release
$env:JUCE_VST3_HOST = "$(pwd)\build\JucePluginHost_artefacts\Release\JucePluginHost.exe"
```

### Build Carla (Windows with MSYS2)
```bash
# In MSYS2 MinGW 64-bit shell
pacman -S make mingw-w64-x86_64-toolchain mingw-w64-x86_64-qt5
cd Carla-main
make win64
export CARLA_ROOT=$(pwd)
```

## Critical Implementation Notes

### NumPy Compatibility
- `src/ambiance/npcompat.py` provides fallback for environments without NumPy
- All audio buffers internally use `list[float]` when NumPy unavailable
- Use `.astype(np.float32)` on all return values

### Web Audio Constraints
- **No localStorage/sessionStorage** in Noisetown UI (Claude.ai restriction)
- All state stored in-memory via JavaScript variables
- Session export/import via JSON serialization to server

### Plugin Host Priority
1. **Carla** (if built and available) – Full VST2/VST3/LV2/AU support
2. **JUCE** (for native UIs only) – Launched externally, audio routed via OS
3. **Flutter shim** (always available) – Simulated echo/reverb fallback

### Carla Windows DLL Handling
- `CarlaBackend._prepare_environment()` registers DLL directories using `os.add_dll_directory()`
- Automatic discovery of Qt5 DLLs, JACK libraries, plugin dependencies
- Clears registrations in `_clear_dependency_directories()` on shutdown

### Signal Chain Latency
- **Browser UI**: Near-zero latency (Web Audio runs in audio thread)
- **Python Engine**: Offline rendering only (no real-time processing)
- **Carla Host**: Real-time capable (JACK backend) but requires external audio routing
- **JUCE Host**: Real-time with native audio device access

## Performance Considerations

1. **Buffer Mixing**: Iterative loop in `mix()` is NumPy-compatible but not vectorized. Optimize with `np.sum(buffers, axis=0)` if performance critical.
2. **Reverb FDN**: Simple Schroeder network trades quality for speed. Replace with Freeverb or convolution for higher fidelity.
3. **LowPass Filter**: One-pole IIR is fast but 6dB/octave rolloff. Use `scipy.signal.butter` for sharper cutoffs.
4. **Plugin Hosting**: Carla adds ~10-50ms latency depending on buffer size. JUCE host is lower latency but requires external process management.

## Security & Sandboxing

- Server runs on `127.0.0.1` only (no external network exposure)
- File I/O restricted to project workspace (`.cache/`, `data/`, `outputs/`)
- No shell command injection (all subprocess calls use list args)
- Plugin binaries execute with user permissions (untrusted plugins can compromise system)

## Debugging

### Enable Verbose Logging
```python
# In src/ambiance/server.py
logging.basicConfig(level=logging.DEBUG)
```

### Carla Backend Diagnostics
```python
from ambiance.integrations.carla_host import CarlaBackend
backend = CarlaBackend()
print(backend.warnings)  # List of initialization failures
print(backend.available)  # True if successfully loaded
```

### Web Audio Debugging
Open browser console, inspect `ACTX.state`, node connections:
```javascript
console.log(ACTX.currentTime, ACTX.sampleRate);
console.log(MASTER.pre, MASTER.limiter);
```

## Vision Alignment

**Goal**: Enable creative sound design through accessible, composable audio tools.

**Principles**:
1. **Modular** – Any source/effect combination works
2. **Extensible** – Registry system makes adding features trivial
3. **Hybrid** – Blend procedural synthesis with VST power
4. **Fun** – UI encourages experimentation with immediate feedback
5. **Portable** – Works offline, no cloud dependencies

**Non-Goals**:
- DAW replacement (use Reaper/Ableton for production)
- Real-time performance synthesis (offline rendering focus)
- Plugin development SDK (use existing VST/AU standards)
- Mobile support (desktop/browser only)

## Quick Reference

| Task | Command |
|------|---------|
| Render default config | `python -m ambiance.cli output.wav` |
| Render custom config | `python -m ambiance.cli out.wav --config cfg.json` |
| Start UI server | `python -m ambiance.server` |
| Run tests | `pytest tests/` |
| Build JUCE host | `cmake -B build && cmake --build build` |
| Build Carla (MSYS2) | `make win64` |
| List registered sources | `python -c "from ambiance.core.registry import registry; print(registry.list_sources())"` |
| List registered effects | `python -c "from ambiance.core.registry import registry; print(registry.list_effects())"` |

---

**When modifying code**: Preserve dataclass decorators, maintain `to_dict()` serialization, test with `pytest`, update registry if adding sources/effects.
