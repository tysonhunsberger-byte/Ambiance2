"""Serve the Noisetown UI alongside JSON endpoints for the audio engine."""

from __future__ import annotations

import argparse
import atexit
import base64
import json
import logging
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any
from urllib.parse import parse_qs, urlparse

from .core.engine import AudioEngine
from .core.registry import registry
from .integrations.plugins import PluginRackManager
from .integrations.carla_host import CarlaVSTHost
from .integrations.juce_vst3_host import JuceVST3Host
from .utils.audio import encode_wav_bytes

# Set up logging
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


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
        **kwargs: Any,
    ) -> None:
        self.manager = manager
        self.ui_path = ui_path
        self.vst_host = vst_host
        self.juce_host = juce_host
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
            status = self.vst_host.status()
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
            try:
                descriptor = self.vst_host.describe_ui(plugin_path)
            except RuntimeError as exc:
                logger.error(f"Failed to describe UI: {exc}")
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
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
            if path == "/api/vst/load":
                payload = self._read_json()
                plugin_path = payload.get("path")
                parameters = payload.get("parameters") or None
                
                logger.info(f"Loading VST plugin: {plugin_path}")
                
                if not plugin_path:
                    logger.error("Missing plugin path in request")
                    self._send_json({"ok": False, "error": "Missing 'path'"}, HTTPStatus.BAD_REQUEST)
                    return
                
                try:
                    plugin = self.vst_host.load_plugin(plugin_path, parameters)
                    logger.info(f"Successfully loaded plugin: {plugin.get('metadata', {}).get('name', 'Unknown')}")
                    self._send_json({"ok": True, "plugin": plugin, "status": self.vst_host.status()})
                except Exception as load_exc:
                    logger.error(f"Failed to load plugin: {load_exc}", exc_info=True)
                    self._send_json({"ok": False, "error": str(load_exc)}, HTTPStatus.BAD_REQUEST)
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
                try:
                    status = self.vst_host.show_ui()
                    logger.info("Plugin UI opened successfully")
                except RuntimeError as exc:
                    logger.error(f"Failed to open plugin UI: {exc}")
                    self._send_json(
                        {"ok": False, "error": str(exc), "status": self.vst_host.status()},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json({"ok": True, "status": status})
                return
            if path == "/api/vst/editor/close":
                try:
                    status = self.vst_host.hide_ui()
                    logger.info("Plugin UI closed successfully")
                except RuntimeError as exc:
                    logger.error(f"Failed to close plugin UI: {exc}")
                    self._send_json(
                        {"ok": False, "error": str(exc), "status": self.vst_host.status()},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json({"ok": True, "status": status})
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
        return AmbianceRequestHandler(*args, **kwargs)

    with ThreadingHTTPServer((host, port), handler) as httpd:
        print(f"Ambiance UI available at http://{host}:{port}/")
        httpd.serve_forever()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Ambiance UI server")
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument("--ui", type=Path, help="Path to a custom UI HTML file")
    args = parser.parse_args(argv)
    serve(host=args.host, port=args.port, ui=args.ui)


if __name__ == "__main__":  # pragma: no cover - manual usage
    main()
