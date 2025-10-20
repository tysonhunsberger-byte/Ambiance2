"""Serve the Noisetown UI alongside JSON endpoints for the audio engine."""

from __future__ import annotations

import argparse
import atexit
import base64
import json
import logging
import subprocess
import sys
import threading
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
import time
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any
from urllib.parse import parse_qs, urlparse

from .core.engine import AudioEngine
from .core.registry import registry
from .integrations.plugins import PluginRackManager
from .integrations.carla_host import CarlaVSTHost, CarlaHostError
from .integrations.juce_vst3_host import JuceVST3Host
from .utils.audio import encode_wav_bytes

# Set up logging
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

_plugin_host_process: subprocess.Popen | None = None


def _launch_plugin_host(plugin_path: Path, drivers: list[str], server_url: str = "http://127.0.0.1:8000") -> None:
    global _plugin_host_process
    script = Path(__file__).resolve().parents[3] / "plugin_host.py"
    if not script.exists():
        logger.error("plugin_host.py not found at %s", script)
        return

    args = [sys.executable, str(script), "--plugin", str(plugin_path), "--server", server_url]
    for driver in drivers:
        if driver:
            args.extend(["--driver", driver])

    try:
        if _plugin_host_process and _plugin_host_process.poll() is None:
            _plugin_host_process.terminate()
    except Exception:
        pass

    try:
        logger.info("Launching external plugin host: %s", " ".join(args))
        _plugin_host_process = subprocess.Popen(args)
        logger.info("Spawned external plugin host for %s (PID: %s)", plugin_path, _plugin_host_process.pid)
    except Exception as exc:
        logger.error("Failed to launch plugin host: %s", exc)


def _terminate_plugin_host() -> None:
    global _plugin_host_process
    if _plugin_host_process and _plugin_host_process.poll() is None:
        logger.info("Terminating external plugin host (PID: %s)", _plugin_host_process.pid)
        try:
            _plugin_host_process.terminate()
            try:
                _plugin_host_process.wait(timeout=3)
                logger.info("External plugin host terminated gracefully")
            except subprocess.TimeoutExpired:
                logger.warning("External plugin host did not terminate, killing forcefully")
                _plugin_host_process.kill()
                _plugin_host_process.wait(timeout=2)
                logger.info("External plugin host killed")
        except Exception as exc:
            logger.error("Failed to terminate plugin host: %s", exc)
    _plugin_host_process = None


def _build_engine(payload: dict[str, Any]) -> tuple[AudioEngine, float]:
    duration = float(payload.get("duration", 5.0))
    sample_rate = int(payload.get("sample_rate", 44100))
    engine = AudioEngine(sample_rate=sample_rate)

    for source_conf in payload.get("sources", []):
        config = dict(source_conf)
        name = config.pop("name", config.pop("type", None))
        if not name:
            raise ValueError("Source configuration missing 'name'")
        engine.add_source(registry.create_source(name, **config))

    for effect_conf in payload.get("effects", []):
        config = dict(effect_conf)
        name = config.pop("name", config.pop("type", None))
        if not name:
            raise ValueError("Effect configuration missing 'name'")
        engine.add_effect(registry.create_effect(name, **config))

    return engine, duration


def render_payload(payload: dict[str, Any]) -> dict[str, Any]:
    engine, duration = _build_engine(payload)
    buffer = engine.render(duration)
    audio = encode_wav_bytes(buffer, engine.sample_rate)
    encoded = base64.b64encode(audio).decode("ascii")
    return {
        "ok": True,
        "audio": f"data:audio/wav;base64,{encoded}",
        "duration": duration,
        "samples": len(buffer),
        "sample_rate": engine.sample_rate,
        "config": engine.configuration(),
    }


class AmbianceRequestHandler(SimpleHTTPRequestHandler):
    """Serve static assets and lightweight JSON APIs."""

    def __init__(
        self,
        *args: Any,
        directory: str,
        manager: PluginRackManager,
        ui_path: Path,
        vst_host: CarlaVSTHost,
        juce_host: JuceVST3Host | None,
        server_url: str = "http://127.0.0.1:8000",
        **kwargs: Any,
    ) -> None:
        self.manager = manager
        self.ui_path = ui_path
        self.vst_host = vst_host
        self.juce_host = juce_host
        self.server_url = server_url
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, format, *args):
        """Override to use our logger."""
        logger.info(format % args)

    # --- Response helpers -------------------------------------------
    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON payload") from exc

    # --- Routing -----------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        path = urlparse(self.path).path
        if path in {"/api/status", "/api/plugins"}:
            payload = self.manager.status()
            self._send_json(payload)
            return
        if path == "/api/vst/status":
            status = self.vst_host.status(include_parameters=False)
            self._send_json({"ok": True, "status": status})
            return
        if path == "/api/juce/status":
            status = self.juce_host.status().to_dict() if self.juce_host else {
                "available": False,
                "executable": None,
                "running": False,
                "plugin_path": None,
                "last_error": "JUCE host not initialised",
            }
            self._send_json({"ok": True, "status": status})
            return
        if path == "/api/vst/ui":
            query = parse_qs(urlparse(self.path).query)
            plugin_path = query.get("path", [None])[0]
            status_snapshot = self.vst_host.status(include_parameters=False)
            current_plugin = (status_snapshot.get("plugin") or {}).get("path")
            try:
                if plugin_path:
                    try:
                        requested = Path(plugin_path).expanduser().resolve()
                        current = Path(current_plugin).expanduser().resolve() if current_plugin else None
                    except Exception:
                        requested = None
                        current = None
                    if current_plugin and requested and requested == current:
                        descriptor = self.vst_host.describe_ui(include_parameters=False)
                    else:
                        descriptor = self.vst_host.describe_ui(plugin_path, include_parameters=False)
                else:
                    descriptor = self.vst_host.describe_ui(include_parameters=False)
            except FileNotFoundError as exc:
                logger.error(f"Plugin not found for UI descriptor: {exc}")
                self._send_json({"ok": False, "error": f"Plugin not found: {exc}"}, HTTPStatus.NOT_FOUND)
                return
            except Exception as exc:
                # Catch all exceptions including CarlaHostError (subclass of RuntimeError)
                logger.error(f"Failed to describe UI: {exc}")
                # Provide a fallback descriptor with basic keyboard enabled
                # This allows the UI to show even if descriptor generation fails
                fallback_descriptor = {
                    "title": "Unknown Plugin",
                    "subtitle": "Descriptor unavailable",
                    "keyboard": {"min_note": 24, "max_note": 96},
                    "panels": [],
                    "parameters": [],
                    "capabilities": {
                        "instrument": bool((status_snapshot.get("capabilities") or {}).get("instrument")),
                        "editor": False,
                        "midi": bool((status_snapshot.get("capabilities") or {}).get("midi")),
                    },
                    "error": str(exc),
                }
                if fallback_descriptor["capabilities"]["instrument"] or fallback_descriptor["capabilities"]["midi"]:
                    fallback_descriptor["subtitle"] = "Live play available"
                logger.warning(f"Returning fallback descriptor due to error: {exc}")
                self._send_json({"ok": True, "descriptor": fallback_descriptor, "warning": str(exc)})
                return
            self._send_json({"ok": True, "descriptor": descriptor})
            return
        if path == "/api/registry":
            payload = {"sources": list(registry.sources()), "effects": list(registry.effects())}
            self._send_json(payload)
            return
        if path in {"/", "", "/ui"}:
            self._serve_ui()
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        path = urlparse(self.path).path
        try:
            if path == "/api/render":
                payload = self._read_json()
                response = render_payload(payload)
                self._send_json(response)
                return
            if path == "/api/plugins/assign":
                payload = self._read_json()
                plugin_path = payload.get("path")
                if not plugin_path:
                    self._send_json({"ok": False, "error": "Missing 'path'"}, HTTPStatus.BAD_REQUEST)
                    return
                stream = payload.get("stream", "Main")
                lane = payload.get("lane", "A")
                slot = payload.get("slot")
                result = self.manager.assign_plugin(
                    plugin_path,
                    stream=stream,
                    lane=lane,
                    slot=slot,
                )
                self._send_json({"ok": True, "assignment": result, "status": self.manager.status()})
                return
            if path == "/api/plugins/remove":
                payload = self._read_json()
                stream = payload.get("stream")
                if not stream:
                    self._send_json({"ok": False, "error": "Missing 'stream'"}, HTTPStatus.BAD_REQUEST)
                    return
                lane = payload.get("lane", "A")
                slot = payload.get("slot")
                remove_path = payload.get("path")
                result = self.manager.remove_plugin(
                    stream=stream,
                    lane=lane,
                    slot=slot,
                    path=remove_path,
                )
                self._send_json({"ok": True, "removed": result, "status": self.manager.status()})
                return
            if path == "/api/plugins/toggle":
                payload = self._read_json()
                stream = payload.get("stream") or "Main"
                result = self.manager.toggle_lane(stream)
                self._send_json({"ok": True, "toggle": result, "status": self.manager.status()})
                return
            if path == "/api/vst/midi/note-on":
                payload = self._read_json()
                note_value = payload.get("note")
                if note_value is None:
                    self._send_json({"ok": False, "error": "Missing 'note'"}, HTTPStatus.BAD_REQUEST)
                    return
                try:
                    note = int(note_value)
                except (TypeError, ValueError):
                    self._send_json({"ok": False, "error": "Invalid 'note' value"}, HTTPStatus.BAD_REQUEST)
                    return
                try:
                    velocity = float(payload.get("velocity", 0.8))
                except (TypeError, ValueError):
                    self._send_json({"ok": False, "error": "Invalid 'velocity' value"}, HTTPStatus.BAD_REQUEST)
                    return
                try:
                    self.vst_host.note_on(note, velocity=velocity)
                except RuntimeError as exc:
                    logger.error(f"Failed to send MIDI note-on: {exc}")
                    self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
                self._send_json({"ok": True})
                return
            if path == "/api/vst/midi/note-off":
                payload = self._read_json()
                note_value = payload.get("note")
                if note_value is None:
                    self._send_json({"ok": False, "error": "Missing 'note'"}, HTTPStatus.BAD_REQUEST)
                    return
                try:
                    note = int(note_value)
                except (TypeError, ValueError):
                    self._send_json({"ok": False, "error": "Invalid 'note' value"}, HTTPStatus.BAD_REQUEST)
                    return
                try:
                    self.vst_host.note_off(note)
                except RuntimeError as exc:
                    logger.error(f"Failed to send MIDI note-off: {exc}")
                    self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
                self._send_json({"ok": True})
                return
            if path == "/api/vst/midi/send":
                payload = self._read_json()
                note_value = payload.get("note")
                if note_value is None:
                    self._send_json({"ok": False, "error": "Missing 'note'"}, HTTPStatus.BAD_REQUEST)
                    return
                try:
                    note = int(note_value)
                except (TypeError, ValueError):
                    self._send_json({"ok": False, "error": "Invalid 'note' value"}, HTTPStatus.BAD_REQUEST)
                    return
                try:
                    velocity = float(payload.get("velocity", 0.8))
                except (TypeError, ValueError):
                    self._send_json({"ok": False, "error": "Invalid 'velocity' value"}, HTTPStatus.BAD_REQUEST)
                    return
                try:
                    duration = float(payload.get("duration", 1.0))
                except (TypeError, ValueError):
                    self._send_json({"ok": False, "error": "Invalid 'duration' value"}, HTTPStatus.BAD_REQUEST)
                    return
                try:
                    self.vst_host.play_note(note, velocity=velocity, duration=duration)
                except RuntimeError as exc:
                    logger.error(f"Failed to trigger MIDI preview note: {exc}")
                    self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
                self._send_json({"ok": True})
                return
            if path == "/api/vst/load":
                payload = self._read_json()
                plugin_path = payload.get("path")
                parameters = payload.get("parameters") or None
                
                logger.info(f"Loading VST plugin: {plugin_path}")
                
                if not plugin_path:
                    logger.error("Missing plugin path in request")
                    self._send_json({"ok": False, "error": "Missing 'path'"}, HTTPStatus.BAD_REQUEST)
                    return
                
                start_time = time.perf_counter()
                logger.info("Loading plugin %s ...", plugin_path)
                try:
                    plugin = self.vst_host.load_plugin(plugin_path, parameters, show_ui=False)
                except Exception as load_exc:
                    logger.error(f"Failed to load plugin: {load_exc}", exc_info=True)
                    self._send_json({"ok": False, "error": str(load_exc)}, HTTPStatus.BAD_REQUEST)
                    return

                elapsed = (time.perf_counter() - start_time) * 1000.0
                plugin_name = plugin.get("metadata", {}).get("name", "Unknown")
                logger.info("Successfully loaded plugin %s in %.1f ms", plugin_name, elapsed)

                ui_opened = False
                ui_error: str | None = None
                status_snapshot = self.vst_host.status(include_parameters=False)
                engine_info = status_snapshot.get("engine", {}) or {}
                preferred = engine_info.get("preferred_drivers") or []
                current_driver = engine_info.get("driver")
                ordered_drivers: list[str] = []
                if current_driver:
                    ordered_drivers.append(current_driver)
                for candidate in preferred:
                    if candidate and candidate.lower() not in {
                        d.lower() for d in ordered_drivers
                    }:
                        ordered_drivers.append(candidate)
                if not ordered_drivers:
                    ordered_drivers = ["DirectSound", "ASIO", "JACK", "Dummy"]

                # NOTE: Don't spawn external plugin_host.py - the server's Carla instance
                # already opened the native UI on line 376. Spawning a separate process
                # creates a second Carla instance that isn't connected to the audio engine,
                # so parameter changes in that UI wouldn't affect the sound.
                # _launch_plugin_host(Path(plugin_path), ordered_drivers)

                response = {
                    "ok": True,
                    "plugin": plugin,
                    "status": status_snapshot,
                    "duration_ms": int(elapsed),
                    "ui_opened": ui_opened,
                    "desktop_host": {
                        "launched": False,  # No longer launching external host
                        "drivers": ordered_drivers,
                    },
                }
                if ui_error:
                    response["ui_error"] = ui_error
                if elapsed > 1500:
                    response["notice"] = (
                        "Plugin load took {:.1f} seconds; bridging or heavy initialisation may still be running."
                        .format(elapsed / 1000.0)
                    )
                self._send_json(response)
                return
                
            if path == "/api/vst/unload":
                self.vst_host.unload()
                self._send_json({"ok": True, "status": self.vst_host.status()})
                return
            if path == "/api/vst/parameter":
                payload = self._read_json()
                identifier = payload.get("id")
                value = payload.get("value")
                if identifier is None or value is None:
                    self._send_json(
                        {"ok": False, "error": "Missing 'id' or 'value'"}, HTTPStatus.BAD_REQUEST
                    )
                    return
                update = self.vst_host.set_parameter(identifier, float(value))
                self._send_json({"ok": True, "status": self.vst_host.status(), "update": update})
                return
            if path == "/api/vst/render":
                payload = self._read_json()
                duration = float(payload.get("duration", 1.5))
                sample_rate = int(payload.get("sample_rate", 44100))
                try:
                    preview = self.vst_host.render_preview(duration=duration, sample_rate=sample_rate)
                except RuntimeError as exc:
                    logger.error(f"Failed to render preview: {exc}")
                    self._send_json(
                        {"ok": False, "error": str(exc), "status": self.vst_host.status()},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
                audio = encode_wav_bytes(preview, sample_rate)
                encoded = base64.b64encode(audio).decode("ascii")
                self._send_json(
                    {
                        "ok": True,
                        "audio": f"data:audio/wav;base64,{encoded}",
                        "duration": duration,
                        "sample_rate": sample_rate,
                    }
                )
                return
            if path == "/api/vst/play":
                payload = self._read_json()
                note = int(payload.get("note", 60))
                velocity = float(payload.get("velocity", 0.8))
                duration = float(payload.get("duration", 1.0))
                sample_rate = int(payload.get("sample_rate", 44100))
                try:
                    audio = self.vst_host.play_note(
                        note,
                        velocity=velocity,
                        duration=duration,
                        sample_rate=sample_rate,
                    )
                except RuntimeError as exc:
                    logger.error(f"Failed to play note: {exc}")
                    self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
                wav = encode_wav_bytes(audio, sample_rate)
                encoded = base64.b64encode(wav).decode("ascii")
                self._send_json(
                    {
                        "ok": True,
                        "audio": f"data:audio/wav;base64,{encoded}",
                        "note": note,
                        "velocity": velocity,
                        "duration": duration,
                        "sample_rate": sample_rate,
                    }
                )
                return
            if path == "/api/vst/editor/open":
                # Show the native UI using the server's Carla instance
                # The Qt event loop running in main thread allows this to work
                try:
                    status = self.vst_host.show_ui()
                    logger.info("Opened native plugin UI in server process")
                    self._send_json({"ok": True, "status": status})
                except Exception as exc:
                    logger.error(f"Failed to show UI: {exc}", exc_info=True)
                    self._send_json(
                        {"ok": False, "error": str(exc), "status": self.vst_host.status()},
                        HTTPStatus.BAD_REQUEST,
                    )
                return
            if path == "/api/vst/editor/close":
                # Hide the native UI
                try:
                    status = self.vst_host.hide_ui()
                    logger.info("Closed native plugin UI")
                    self._send_json({"ok": True, "status": status})
                except Exception as exc:
                    logger.error(f"Failed to hide UI: {exc}", exc_info=True)
                    self._send_json(
                        {"ok": False, "error": str(exc), "status": self.vst_host.status()},
                        HTTPStatus.BAD_REQUEST,
                    )
                return
            if path == "/api/juce/open":
                if not self.juce_host:
                    self._send_json({"ok": False, "error": "JUCE host not configured"}, HTTPStatus.BAD_REQUEST)
                    return
                payload = self._read_json()
                plugin_path = payload.get("path")
                if not plugin_path:
                    self._send_json({"ok": False, "error": "Missing 'path'"}, HTTPStatus.BAD_REQUEST)
                    return
                status = self.juce_host.launch(plugin_path).to_dict()
                http_status = HTTPStatus.OK if status.get("running") else HTTPStatus.BAD_REQUEST
                self._send_json({"ok": status.get("running", False), "status": status}, http_status)
                return
            if path == "/api/juce/close":
                if not self.juce_host:
                    self._send_json({"ok": False, "error": "JUCE host not configured"}, HTTPStatus.BAD_REQUEST)
                    return
                status = self.juce_host.terminate().to_dict()
                self._send_json({"ok": True, "status": status})
                return
            if path == "/api/juce/refresh":
                if not self.juce_host:
                    self._send_json({"ok": False, "error": "JUCE host not configured"}, HTTPStatus.BAD_REQUEST)
                    return
                self.juce_host.refresh_executable()
                status = self.juce_host.status().to_dict()
                self._send_json({"ok": True, "status": status})
                return
        except Exception as exc:  # pylint: disable=broad-except
            logger.error(f"Unhandled exception in {path}: {exc}", exc_info=True)
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    # --- Static helpers ----------------------------------------------
    def _serve_ui(self) -> None:
        if not self.ui_path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "UI file missing")
            return
        data = self.ui_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def serve(host: str = "127.0.0.1", port: int = 8000, ui: Path | None = None) -> None:
    base_dir = Path(__file__).resolve().parents[2]
    directory = str(base_dir)
    ui_path = Path(ui) if ui else base_dir / "noisetown_ADV_CHORD_PATCHED_v4g1_applyfix.html"
    manager = PluginRackManager(base_dir=base_dir)
    vst_host = CarlaVSTHost(base_dir=base_dir)
    # Prefer JACK when available (user can start JACK via scripts/start_jack.ps1).
    # Fall back through ASIO/DirectSound/Dummy if JACK is not active.
    # On Windows prefer native drivers first so we don't require JACK.
    preferred_drivers = ["DirectSound", "WASAPI", "ASIO", "MME", "JACK", "Dummy"]
    if sys.platform.startswith("linux"):
        preferred_drivers = ["JACK", "ALSA", "PulseAudio", "Dummy"]
    elif sys.platform == "darwin":
        preferred_drivers = ["CoreAudio", "JACK", "Dummy"]
    vst_host.configure_audio(preferred_drivers=preferred_drivers)
    juce_host = JuceVST3Host(base_dir=base_dir)
    atexit.register(vst_host.shutdown)

    logger.info(f"Starting Ambiance server on http://{host}:{port}/")
    logger.info(f"Carla backend available: {vst_host.status()['available']}")
    logger.info(f"Qt support available: {vst_host.status().get('qt_available', False)}")

    def handler(*args: Any, **kwargs: Any) -> AmbianceRequestHandler:
        kwargs.setdefault("directory", directory)
        kwargs.setdefault("manager", manager)
        kwargs.setdefault("ui_path", ui_path)
        kwargs.setdefault("vst_host", vst_host)
        kwargs.setdefault("juce_host", juce_host)
        kwargs.setdefault("server_url", f"http://{host}:{port}")
        return AmbianceRequestHandler(*args, **kwargs)

    # Check if Qt is available for running plugin UIs
    try:
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import QTimer
        HAS_PYQT5 = True
    except ImportError:
        HAS_PYQT5 = False

    httpd = ThreadingHTTPServer((host, port), handler)

    # If PyQt5 is available, run HTTP server in a thread and Qt event loop in main thread
    if HAS_PYQT5:
        logger.info("PyQt5 available - running Qt event loop for responsive plugin UIs")

        # Get or create Qt application (MUST be before starting HTTP server)
        qt_app = QApplication.instance()
        if qt_app is None:
            qt_app = QApplication(sys.argv if sys.argv else ['Ambiance'])
        qt_app.setQuitOnLastWindowClosed(False)

        # Initialize QtApplicationManager on main thread BEFORE starting event loop
        # This ensures the QTimer is created on the main thread where the event loop runs
        try:
            from ambiance.integrations.carla_host import HAS_PYQT5 as CARLA_HAS_PYQT5
            if CARLA_HAS_PYQT5:
                from ambiance.integrations.carla_host import QtApplicationManager
                qt_mgr = QtApplicationManager.get_instance()
                logger.info("QtApplicationManager initialized on main thread")
            else:
                logger.warning("QtApplicationManager not available (carla_host HAS_PYQT5 is False)")
        except ImportError as exc:
            logger.warning(f"Failed to import QtApplicationManager: {exc}")
        except Exception as exc:
            logger.warning(f"Failed to initialize QtApplicationManager: {exc}")

        # Start HTTP server in daemon thread AFTER Qt is set up
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()

        print(f"Ambiance UI available at http://{host}:{port}/")
        print("Qt event loop running for plugin UIs. Press Ctrl+C to exit.")

        # Setup cleanup on exit
        def cleanup():
            logger.info("Shutting down server...")
            httpd.shutdown()
            httpd.server_close()

        import signal
        def signal_handler(sig, frame):
            logger.info("Received interrupt signal")
            cleanup()
            qt_app.quit()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Run Qt event loop (blocking)
        try:
            sys.exit(qt_app.exec_())
        finally:
            cleanup()
    else:
        # No PyQt5 - run HTTP server normally in main thread
        logger.warning("PyQt5 not available - plugin UIs may not be responsive")
        logger.warning("Install PyQt5 for better UI support: pip install PyQt5")

        with httpd:
            print(f"Ambiance UI available at http://{host}:{port}/")
            print("Press Ctrl+C to exit.")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                logger.info("Server stopped")
                httpd.shutdown()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Ambiance UI server")
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument("--ui", type=Path, help="Path to a custom UI HTML file")
    args = parser.parse_args(argv)
    serve(host=args.host, port=args.port, ui=args.ui)


if __name__ == "__main__":  # pragma: no cover - manual usage
    main()