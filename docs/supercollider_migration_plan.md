# SuperCollider Migration – Architecture Plan

> Companion to `supercollider_migration_baseline.md`. This file captures the target design for replacing the Carla/JUCE hosts with SuperCollider + `vstplugin` while keeping Strudel and the rest of Ambiance functional.

## 1. Goals

1. Make SuperCollider (`sclang` + `scsynth` + `vstplugin`) the sole plugin host for both desktop preview and offline renders.
2. Keep Strudel, existing procedural sources/effects, and the browser-based UI intact—only the host backend changes.
3. Allow optional fallback to the current Carla/JUCE setup until SC hosting reaches feature parity.

## 2. High-Level Architecture

```
Browser (Plugin Studio)
        │ WebChannel + HTTP (/api/sc/*)
Qt Bridges (PluginStudioBridge et al.)
        │
Ambiance server (Python)
  ├─ SuperColliderService  ─┐
  │   - lifecycle mgmt      │ JSON/OSC
  │   - REST handlers       │
  └─ AudioEngine / Strudel  │
        │                   │
Node helper (tools/scbridge.js)
        │ launches
SuperCollider runtime (sclang + scsynth + vstplugin-master/sc)
```

## 3. Component Responsibilities

### 3.1 Node helper (`tools/scbridge.js`)
* Already boots `supercolliderjs`. Extend with:
  - Optional `mode` flag to choose audio device (dummy vs actual output).
  - Streaming of stdout/stderr severity (info/warn/error) to help UI logs.

### 3.2 Python service layer
* New module `ambiance/src/ambiance/integrations/supercollider_service.py`:
  - Wraps `SuperColliderBridge` / `VSTPluginBridge`.
  - Tracks loaded plugin metadata (name, parameters, state).
  - Provides helpers: `search_plugins`, `load_plugin`, `unload_plugin`, `set_parameter`, `open_gui`, `capture_audio`.
* HTTP server changes (`server.py`):
  - Add `/api/sc/plugins`, `/api/sc/plugins/load`, `/api/sc/plugins/unload`, `/api/sc/plugins/params`, `/api/sc/plugins/render`.
  - Keep legacy `/api/vst/*` endpoints but gate them behind host selection (config flag / query param).
  - Ensure Strudel proxy untouched.

### 3.3 Qt Bridges / Desktop
* `PluginStudioBridge` and `PluginUIBridge` gain a host selector (Carla vs SC). When SC is active:
  - Discovery: call new REST endpoints or a direct Python binding exposed over WebChannel.
  - Load/unload: call `scHost.load_plugin`.
  - Parameter updates: push to SC service, subscribe to SC events (optional polling until we wire OSC -> Qt).
* `DesktopBridge` exposes host state (active host, plugin status, SC logs) so UI can reflect errors.

### 3.4 Browser UI (resources/webdesktop/index.html)
* Replace existing `queuePluginLoad` interactions with fetches to `/api/sc/plugins/*` when SC host is selected.
* Parameter UI uses the SC descriptor shape (`VSTPluginController.parameters` -> {id, label, min, max}).
* Remove references to Carla-specific statuses (“Carla ready”, driver names, etc.) when SC host is active.
* Keep Strudel window functionality unchanged.

### 3.5 Audio Routing Strategy
* **Live Preview**: let scsynth output directly to the system device (controlled from SC bridge). For “type-to-play”, send MIDI/OSC from Ambiance (keyboard UI) into SC synth nodes.
* **Offline Render**: add a `render` command that asks SuperCollider to render N seconds of audio to a buffer/file (using `Server.render`). Python grabs the resulting WAV and merges it into Ambiance’s export path.
* Optional future enhancement: capture SC audio back into Python in real time via JACK/pipe if we need deterministic offline mixing per source.

## 4. API Sketch

| Method | Endpoint | Payload | Notes |
|--------|----------|---------|-------|
| `GET` | `/api/sc/plugins` | – | Returns cached SC plugin descriptors (from `VSTPlugin.search`). |
| `POST` | `/api/sc/plugins/load` | `{ "path": "...", "channels": 2, "editor": true }` | Calls `bridge.load_plugin`. |
| `POST` | `/api/sc/plugins/unload` | – | Frees current plugin. |
| `POST` | `/api/sc/plugins/param` | `{ "index": n, "value": 0.5 }` | Sets parameter. |
| `POST` | `/api/sc/plugins/render` | `{ "duration": 4.0, "filename": "..." }` | Renders to WAV via scsynth. |
| `GET` | `/api/sc/status` | – | Bridge + plugin state (booted, plugin name, SC logs). |

Existing `/api/plugins/*` endpoints remain for non-SC hosts until sunset.

## 5. Strudel Considerations

* Strudel uses the same server process for proxying and WebChannel for UI toggles. Migrating the plugin host must not interfere with `/strudel-live` or the `StrudelState` code paths.
* Ensure SC helper runs in parallel; its stdout/stderr should be logged separately so Strudel logs stay readable.

## 6. Migration Phases

1. **Host Toggle & API groundwork** (Python only). Add config flag (`AMB_HOST=sc`), new endpoints, and path for SC logs.
2. **UI wiring**. Teach Plugin Studio to detect host type, call new endpoints, and display SC parameter sets. Keep Carla path available as fallback.
3. **Audio preview**. Connect keyboard + parameter automation to SC synth nodes so live play works entirely in SC.
4. **Offline render**. Hook `/api/render` into SC when plugins are present (or let SC render entire mix).
5. **Clean-up**. Remove Carla/JUCE references once SC host meets parity and is stable.

Document progress in both `supercollider_migration_baseline.md` (state of the world) and this plan file (design decisions). Update as architecture evolves.

## 7. Milestones & Deliverables

| Milestone | Scope | Key Deliverables |
|-----------|-------|------------------|
| **M1 – Bootstrapping** | Get SC runtime wired into the server without touching UI. | * Config flag/env var to pick host (`carla` vs `sc`).<br>* `SuperColliderService` module with `boot/search/load/unload/set_param` methods.<br>* REST endpoints `/api/sc/plugins*` (or equivalent) returning JSON compatible with Plugin Studio.<br>* Logging/health endpoint `/api/sc/status`. |
| **M2 – UI Integration** | Browser + Qt bridges adopt new endpoints while Carla stays available as fallback. | * `PluginState` aware of active host.<br>* UI buttons (`Load Plugin`, `Copy Path`, parameter controls) call SC endpoints when host=`sc`.<br>* Bridge classes emit SC state updates over WebChannel.<br>* Feature flag/toggle in UI to switch hosts at runtime. |
| **M3 – Live Preview** | SuperCollider handles real-time playback, parameter automation, and plugin GUI focus. | * Keyboard → SC MIDI/OSC wiring (type-to-play works after plugin UI focus changes).<br>* Parameter polling/feedback loops between SC and UI.<br>* Support for opening SC plugin GUI (`VSTPluginGui`) inside desktop window stack. |
| **M4 – Offline Render** | `/api/render` / CLI output leverages SC when plugin rows are present. | * Render orchestration that asks SC to produce WAV (either full mix or per-track) and merges with existing engine.<br>* Tests/fixtures verifying deterministic output.<br>* Switch to SC host for Strudel pattern playback when plugin nodes exist (optional). |
| **M5 – Sunset Legacy Hosts** | Retire Carla/JUCE code paths after parity proof. | * Remove unused endpoints/bridges, update docs/install guides.<br>* Document SC-specific prerequisites (node, `supercolliderjs`, `vstplugin` builds, sclang paths).<br>* Final QA checklist (focus handling, error logging, Strudel unaffected). |

## 8. Prerequisites & Open Questions

* Build `vstplugin` binaries for each platform (include instructions or artifacts).
* Confirm `supercolliderjs` install path and Node availability for end users.
* Decide whether SC renders entire mix or we round-trip buffers for individual plugin slots.
* Determine how to capture SC stdout/stderr for UI diagnostics.
