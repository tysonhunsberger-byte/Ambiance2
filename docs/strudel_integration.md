# Integrating Strudel Patterns into Ambiance

This document collects the practical steps required to embed the [Strudel pattern environment](https://codeberg.org/uzu/strudel) inside the Ambiance desktop application.  It assumes you are comfortable running Python/Qt projects but new to browser build tooling, so each phase focuses on reproducible commands and clear integration touch points.

## 1. Understand the building blocks

Strudel ships as two cooperating projects:

- **`strudel-web`** – a Vite/TypeScript frontend that renders the live code editor, audio engine, and helper panels.  The repository lives under [`packages/web`](https://codeberg.org/uzu/strudel/src/branch/main/packages/web#strudel-web).
- **`@strudel/core`** – the shared parser, scheduler, and pattern runtime used by both the browser app and the Node.js REPL.

Ambiance only needs the compiled web bundle and a small message bridge so pattern events can reach the desktop audio engine.

## 2. Build the Strudel web assets

1. **Install Node.js 18+ and pnpm.**  On Windows, grab the LTS installer from <https://nodejs.org/> and then run `npm install -g pnpm`.
2. **Clone the Strudel repository** next to Ambiance:
   ```bash
   git clone https://codeberg.org/uzu/strudel.git
   cd strudel
   pnpm install
   ```
3. **Build + sync the bundle**:
   ```bash
   # from the Ambiance root
   python tools/sync_strudel.py --source ../strudel
   ```
   The helper script runs `pnpm --filter ./website build` for you (unless you pass `--no-build`) and copies `website/dist` into `resources/strudel/dist`.  If you already have a built `dist` folder, you can point `--source` directly to it and the script will simply copy the assets.  Add `--install` if the repo still needs `pnpm install`, and use `--pnpm C:\path\to\pnpm.exe` if pnpm is not on `PATH`.

## 3. Run the standalone Strudel proxy

The Qt shell no longer embeds Strudel through the legacy iframe hack.  Instead, Ambiance boots a lightweight HTTP proxy that serves `resources/strudel/dist` at `http://127.0.0.1:<port>/` and falls back to https://strudel.cc/ whenever a file is missing.  You can run the proxy manually while developing:

```bash
python -m ambiance.strudel_proxy --root resources/strudel/dist --port 58145
```

Key behaviors:

- **Local-first.**  Requests hit the built bundle inside `resources/strudel/dist`.  If you delete a file or haven’t synced yet, the proxy streams the live site instead so you can keep working.
- **Iframe-safe headers.**  Response headers that usually block embedding (`X-Frame-Options`, CSP, etc.) are stripped so the WebEngine view can display every page.
- **Zero config for the desktop.**  When the Qt shell starts, it autostarts the proxy on a random localhost port and points the Strudel window at it.  Killing the app shuts the proxy down.

You can adjust the remote fallback (e.g. to a staging build) via `--remote https://staging.strudel.cc/`.

## 3. Embed the UI in Qt

1. **Enable Qt WebEngine.**  Add `PyQt6-WebEngine` (or the PySide6 equivalent) to `requirements.txt` and update the Windows packaging scripts (`setup_and_start.bat`) so the module is installed alongside Ambiance.
2. **Create a dockable Strudel panel.**  Inside `ambiance_qt_improved.py`, add a `QWebEngineView` wrapped in a `QDockWidget` labelled “Pattern Lab.”  Point it to the local `dist/index.html` using `QUrl.fromLocalFile`.
3. **Handle first-run sandboxing.**  On Windows, `QWebEngineView` requires an application-level `QtWebEngine.initialize()` call before creating the widget.  Place it near the top of your `main()` function.

At this stage you can open the dock and interact with the Strudel playground exactly as in the browser.

## 4. Bridge pattern events to the audio engine

Strudel’s web app emits pattern events through the browser `postMessage` API.  We can use Qt’s `QWebChannel` to receive those messages in Python.

1. **Expose a Qt object to JavaScript.**  Create a `PatternBridge(QObject)` class with a `@pyqtSlot(str)` method, e.g. `receivePattern`.  Register it with the web view’s page via `page().setWebChannel(channel)`.
2. **Inject the bridge script.**  Load a small JavaScript snippet that connects Strudel’s scheduler to `window.qt_pattern_bridge.receivePattern(JSON.stringify(event))`.  You can add this to `packages/web/src/App.tsx` before building, or inject it at runtime with `runJavaScript`.
3. **Translate events into engine calls.**  Parse the JSON payload inside `PatternBridge.receivePattern` and schedule them on Ambiance’s `StreamController`.  For a minimum viable loop, turn each `event.start`/`event.duration` into timer callbacks that trigger `load_file`, `set_crossfade`, and other stream mutations.

## 5. Ship beginner-friendly presets

To keep Strudel approachable for newcomers:

- Seed the dock with example patterns (“ambient wash,” “granular scatter,” etc.) stored in `config/strudel_examples.json`.
- Display status toasts when patterns fail to parse, mirroring the cues in `docs/synthesis_getting_started.md`.
- Provide a toggle that snaps the Strudel transport to the same tempo as the desktop metronome so users hear both layers in sync.

## 6. Keep assets up to date

- Whenever Strudel releases a new version, rerun the build and replace the `dist` folder.  Note the commit hash in `docs/strudel_integration.md` so future updates remain traceable.
- Consider wrapping the steps above in a helper script (`scripts/update_strudel_assets.py`) that downloads the repo at a tagged version and copies the bundle automatically.

Following these steps lets Ambiance host the full Strudel playground inside its Qt shell while routing pattern playback through the existing audio engine, giving beginners a familiar live-coding surface without leaving the app.
