# Ambiance

Ambiance is a modular audio generation toolkit that blends procedural synthesis with
a plugin rack for native sound design tools. Drop VST, VST3, Audio Unit, or mc.svt
devices into the workspace directory and the system exposes them inside the UI for
lane-based routing, A/B comparisons, and lightweight session management.

## Features

- **Composable audio engine** – Combine any number of sources and effects.
- **Plugin rack integration** – Drop plugins into the workspace directory and assign
  them to streams with dedicated A/B lanes.
- **Desktop plugin UI bridge** – Launch a JUCE-based host from the browser to open
  the real plugin editor while keeping the Ambiance routing UI intact.
- **Bundled Modalys starter** – A Modalys (Max) external is copied into the rack
  workspace automatically when the distribution is present, making it easy to begin
  experimenting with physical modelling textures.
- **In-rack management** – Route plugins to stream lanes, copy workspace paths, and
  switch lanes instantly for comparative listening.
- **Procedural audio sources** – Sine waves, noise beds, resonant instrument models,
  and formant-inspired vocal timbres.
- **Signal processing effects** – Reverb, ping-pong delay, and low-pass filtering.
- **Command line renderer** – Render ambience tracks directly to WAV files.
- **Upgradeable architecture** – New sources/effects can be registered by importing a
  class and annotating it with the registry decorators.

## Getting started

1. Create a virtual environment and install the project:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```

2. Render an ambience track using the default configuration:

   ```bash
   python -m ambiance.cli output.wav --duration 10
   ```

   The command renders using the built-in procedural sources. To hook in a native
   plugin, drop its files inside `.cache/plugins` (created on demand) and map them to
   streams through the plugin rack UI. When a Modalys distribution is present next to
   the project, the rack automatically stages the `Modalys (Max)` external for
   assignment so you can immediately explore its sound-design capabilities.

3. Launch the interactive UI server to use the Noisetown interface together with the
   Python engine:

   ```bash
   python -m ambiance.server
   ```

   The command serves the bundled `noisetown_ADV_CHORD_PATCHED_v4g1_applyfix.html`
   interface at `http://127.0.0.1:8000/`. The UI exposes the plugin rack, lets you
   assign plugins to stream lanes for instant A/B comparison, and renders ambience
   layers through the Python audio engine. The **Desktop Plugin UI Bridge** section
   explains how to open the JUCE host when you need the native editor (see
   `docs/vst3_hosting.md`). If you place a different HTML interface on disk, pass its
   path via `--ui`.

4. Provide a JSON configuration to customize the engine:

   ```json
   {
     "sources": [
       {"type": "SineWaveSource", "frequency": 523.25, "amplitude": 0.15},
       {"type": "VocalFormantSource", "vowel": "i", "amplitude": 0.2}
     ],
     "effects": [
       {"type": "ReverbEffect", "decay": 0.4, "mix": 0.25}
     ]
   }
   ```

   ```bash
   python -m ambiance.cli output.wav --config config.json
   ```

## Carla integration

Ambiance can host VST2 and VST3 plug-ins through an embedded Carla backend. The
integration automatically falls back to the Flutter shim when the Carla
runtime is unavailable. Windows users can follow `docs/carla_windows.md` for
MSYS2 build steps or instructions on reusing the official binary release.

## Development

- Run tests with `pytest`.
- Package metadata lives in `pyproject.toml`.
- External resources are kept at the repository root and extracted to `.cache/` when
  requested. The `.gitignore` prevents accidental commits of unpacked binaries.

## Upgrading

To add new audio engines or effects:

1. Create a subclass of `AudioSource` or `AudioEffect`.
2. Decorate the class with `@registry.register_source` or `@registry.register_effect`.
3. Drop the module anywhere under `src/ambiance/` and import it so registration happens.

The registry immediately makes the new feature available to the CLI and configuration
system without further wiring.
