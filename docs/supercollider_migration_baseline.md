# SuperCollider Migration – Baseline Audit (Nov 2025)

This document captures the current plugin-hosting architecture so we can methodically replace it with a SuperCollider/vstplugin-based pipeline without breaking other parts of Ambiance (especially Strudel).

## 1. Existing Plugin Hosting Stack

### 1.1 Python backends
| Component | File(s) | Purpose |
|-----------|---------|---------|
| `CarlaVSTHost` | `ambiance/src/ambiance/integrations/carla_host.py` | Primary in-process host: plugin discovery, metadata, parameter polling, audio rendering, launching embedded GUIs (via PyQt/jack). |
| `JuceVST3Host` | `ambiance/src/ambiance/integrations/juce_vst3_host.py` | Fires an external JUCE process to show native plugin windows when Carla can’t provide a UI. |
| `FlutterVSTHost` | `ambiance/src/ambiance/integrations/flutter_vst_host.py` | Fallback shim (echo/reverb simulation) when no native host is available. |
| `PluginRackManager` | `ambiance/src/ambiance/integrations/plugins.py` | Scans `workspace/.cache/plugins` + `included_plugins`, persists A/B lane assignments (`rack.json`), feeds `/api/plugins`. |
| `plugin_host.py` | root | Standalone PyQt Carla GUI driver (loads a single plugin, renders audio, exposes parameter sliders). Spawned optionally via `_launch_plugin_host()` in `server.py`. |

### 1.2 HTTP server orchestration
`ambiance/src/ambiance/server.py`
* Exposes `/api/plugins`, `/api/vst/status`, `/api/vst/ui`, `/api/render`, plugin assignment endpoints, etc.
* Keeps singleton instances: `self.manager` (`PluginRackManager`), `self.vst_host` (`CarlaVSTHost`), `self.juce_host`.
* Handles plugin load requests (`/api/vst/load`): calls `self.vst_host.load_plugin(...)`, logs success, returns metadata to UI.
* Launches `plugin_host.py` on demand (currently commented out when server already runs Carla internally).
* Also proxies Strudel assets via `/strudel-live/*` so Strudel keeps working regardless of plugin host changes.

### 1.3 Browser UI (“Plugin Studio”)
`resources/webdesktop/index.html`
* Maintains `PluginState` (plugins list, chain entries, `hostStatus`, `currentPluginPath`, workspace path). Populated through WebChannel signals `handlePluginStudioState` & `handlePluginDescriptor`.
* UI actions call Qt bridges (`Bridges.pluginStudio.addPluginByPath`, `loadChainIndex`, `removeChainIndex`, etc.), which in turn talk to Carla:
  - Buttons “Load Plugin/Remove/Show Native UI/Unload” target these bridges.
* Parameter UI and status read from `/api/vst/ui` descriptors.
* Original toolbar had “Open Sequencer/Strudel/Reload”; now trimmed but no behavior change relevant to plugins.

### 1.4 Qt Bridges
`ambiance_qt_improved.py`
* Defines `PluginStudioBridge`, `PluginUIBridge`, `DesktopBridge`, etc. `PluginStudioBridge` pushes Carla state into the UI and forwards add/remove/load requests down to `PluginRackWidget` (Carla-backed).
* Strudel integration also runs here: `StrudelWebPage`, proxy server, etc. Strudel depends only on `server.py` and Qt, not on plugin hosts.

### 1.5 Audio render path
* Offline renders (`/api/render`) use `AudioEngine` + registered sources/effects. Plugins are not yet part of the offline engine (Carla is used for live plugin previews/UI).
* `plugin_host.py` provides ad-hoc audio playback for the currently loaded VST via PyQt audio APIs.

## 2. Newly Added SuperCollider Bridge (current state)
| Component | File | Notes |
|-----------|------|-------|
| Node helper | `tools/scbridge.js` | Boots `sclang` + `scsynth` via `supercolliderjs`, listens for JSON commands (`boot`, `eval`, `send`, `shutdown`). |
| Python shim | `ambiance/src/ambiance/integrations/supercollider_host.py` | Manages the Node subprocess, request/response queues, evaluation helpers. |
| VST bridge | `ambiance/src/ambiance/integrations/vstplugin_bridge.py` | Uses `SuperColliderBridge` to boot `vstplugin` SC extensions (source lives in `vstplugin-master/sc`). Provides helpers: `load_plugin`, `close_plugin`, `set_parameter`, `list_plugins`, etc. |
| Assets | `supercolliderjs-develop/`, `vstplugin-master/` | Full upstream source trees checked into the repo for reference/building. |

**Important:** These files are *not* yet wired into the server or UI—no endpoints call `SuperColliderBridge`. Carla/JUCE remain the active hosts.

## 3. Strudel Baseline
* Served by `server.py` under `/strudel-live` proxy and exposed in the desktop via `resources/webdesktop/index.html` (Strudel window).  
* Completely independent of plugin hosts. Any migration must keep Strudel’s proxy + WebChannel hooks untouched.

## 4. Touchpoints To Replace When Moving to SuperCollider
1. **State propagation** – `PluginStudioBridge` currently mirrors Carla `PluginRackWidget` state. Needs equivalent data from SC (`VSTPluginBridge`) once we swap hosts.
2. **REST endpoints** – `/api/vst/*`, `/api/plugins/*`, plugin load/unload handlers inside `server.py` are Carla-specific.
3. **External `plugin_host.py`** – redundant once SC handles UI + rendering; determine whether to retire or repurpose as an SC-specific inspector.
4. **UI parameter/control descriptors** – `/api/vst/ui` builds descriptors via Carla. We’ll need SC to emit parameter metadata (name/index/min/max) so the existing UI components keep working.
5. **Audio routing** – currently, plugin audio doesn’t run through the offline engine. Decide whether SC renders the entire mix or just plugin inserts, and how to capture its output for previews + exports.
6. **Keyboard focus** – plugin UIs (native windows) currently steal focus. Switching to SC’s Qt GUI (via `VSTPluginGui`) must still coordinate with Ambiance so “type-to-play” recovers.

## 5. Constraints / Prereqs for Migration
* `node` runtime + `supercolliderjs` npm dependencies must exist on user systems (already checked into repo for development but need install instructions for users).
* SuperCollider binaries (sclang/scsynth) must be installed and discoverable on each platform; `SuperColliderBridge.boot()` currently relies on default paths (see `supercollider_host.py`).
* The `vstplugin-master` build artifacts (UGen binaries) must be compiled for each target platform. Present repo only includes sources.
* Strudel must continue functioning; migration should not touch `/strudel-live` proxy or Strudel window wiring.

## 6. Next Steps (beyond audit)
* Decide on API surface: expose new `/api/sc/plugins/*` endpoints or reuse existing ones with a host switch.
* Bridge UI actions (`queuePluginLoad`, `copyPluginPath`, etc.) to SC instead of Carla.
* Determine audio render strategy and align offline engine with SC output before removing Carla/JUCE integrations.

This document should be updated as we progress through the SuperCollider migration to reflect new responsibilities and retirements.
