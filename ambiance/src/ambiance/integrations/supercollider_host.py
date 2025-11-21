"""Bridge to SuperCollider via the `supercolliderjs` Node runtime."""

from __future__ import annotations

import json
import os
import queue
import socket
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


class SuperColliderBridgeError(RuntimeError):
    """Raised when communication with the SuperCollider bridge fails."""


class SuperColliderBridge:
    """Spawn a Node helper that boots sclang/scsynth through supercolliderjs."""

    def __init__(
        self,
        *,
        node_executable: str | os.PathLike[str] = "node",
        script_path: str | os.PathLike[str] | None = None,
        request_timeout: float = 45.0,
        sclang_path: str | os.PathLike[str] | None = None,
        scsynth_path: str | os.PathLike[str] | None = None,
    ) -> None:
        root = Path(__file__).resolve().parents[4]
        default_script = root / "tools" / "scbridge.js"
        self.script_path = Path(script_path) if script_path else default_script
        self.node_executable = str(node_executable)
        self.request_timeout = request_timeout
        self.repo_root = root
        self.node_modules_path = self.repo_root / "node_modules"
        self._explicit_sclang_path = Path(sclang_path) if sclang_path else None
        self._explicit_scsynth_path = Path(scsynth_path) if scsynth_path else None
        self._process: subprocess.Popen[str] | None = None
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._pending_lock = threading.Lock()
        self._next_id = 1
        self._booted = False
        self._log_path = self.repo_root / "last_sc_log.txt"
        self._log_lock = threading.Lock()

    # ------------------------------------------------------------------
    def _reset_sc_log(self) -> None:
        try:
            with self._log_lock:
                self._log_path.write_text('{"status": "starting"}\n', encoding="utf-8")
        except OSError:
            pass

    def _append_sc_log(self, text: str) -> None:
        if not text:
            return
        try:
            with self._log_lock:
                with self._log_path.open("a", encoding="utf-8") as handle:
                    handle.write(text)
                    if not text.endswith("\n"):
                        handle.write("\n")
        except OSError:
            pass

    # ------------------------------------------------------------------
    def _ensure_process(self) -> None:
        if self._process and self._process.poll() is None:
            return
        if not self.script_path.exists():
            raise SuperColliderBridgeError(f"Bridge script not found: {self.script_path}")
        env = os.environ.copy()
        if self.node_modules_path.exists():
            existing = env.get("NODE_PATH")
            node_path_value = str(self.node_modules_path)
            if existing:
                node_path_value = os.pathsep.join([node_path_value, existing])
            env["NODE_PATH"] = node_path_value
        env.setdefault("SC_JACK_DEFAULT_SERVER", "")
        env.setdefault("SC_JACK_DEFAULT_DEVICE", "")
        self._reset_sc_log()
        self._process = subprocess.Popen(
            [self.node_executable, str(self.script_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        assert self._process.stdout is not None
        assert self._process.stderr is not None
        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread = threading.Thread(
            target=self._forward_stderr,
            args=(self._process.stderr,),
            daemon=True,
        )
        self._stderr_thread.start()

    def _forward_stderr(self, stream: Any) -> None:
        for line in stream:
            try:
                message = line.rstrip()
                if not message:
                    continue
                decoded = message
                if message.startswith("{") and "type" in message:
                    try:
                        data = json.loads(message)
                        if isinstance(data, dict) and data.get("type") == "Buffer" and isinstance(data.get("data"), list):
                            decoded = bytes(int(b) & 0xFF for b in data["data"]).decode("utf-8", errors="replace")
                    except json.JSONDecodeError:
                        decoded = message
                if decoded:
                    print(f"[SCBridge] {decoded}")
                    self._append_sc_log(decoded)
            except Exception:
                continue

    def _read_stdout(self) -> None:
        assert self._process and self._process.stdout
        for raw in self._process.stdout:
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            request_id = payload.get("id")
            if request_id is None:
                continue
            with self._pending_lock:
                waiter = self._pending.get(int(request_id))
            if waiter:
                waiter.put(payload)
            self._append_sc_log(f"[RESPONSE] {payload}")
            for key in ("stdout", "stderr"):
                text = payload.get(key)
                if text:
                    self._append_sc_log(str(text))

    def _request(self, command: str, payload: Optional[Dict[str, Any]] = None) -> dict[str, Any]:
        self._ensure_process()
        assert self._process and self._process.stdin
        payload = payload or {}
        self._append_sc_log(f"[REQUEST] {command}: {payload}")
        with self._pending_lock:
            request_id = self._next_id
            self._next_id += 1
            waiter: queue.Queue[dict[str, Any]] = queue.Queue()
            self._pending[request_id] = waiter
        message = {"id": request_id, "command": command, **payload}
        try:
            self._process.stdin.write(json.dumps(message) + "\n")
            self._process.stdin.flush()
        except BrokenPipeError as exc:
            raise SuperColliderBridgeError("SC bridge process is not available") from exc
        try:
            response = waiter.get(timeout=self.request_timeout)
        except queue.Empty as exc:
            raise SuperColliderBridgeError(f"Timeout waiting for response to '{command}'") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
        if not response.get("ok", True):
            message = response.get("message", "bridge error")
            extras = []
            for key in ("stack", "stdout", "stderr", "code"):
                value = response.get(key)
                if value:
                    extras.append(f"{key}: {value}")
            if extras:
                message = f"{message}\n" + "\n".join(extras)
            raise SuperColliderBridgeError(message)
        return response

    # ------------------------------------------------------------------
    def boot(
        self,
        *,
        include_paths: Iterable[str] | None = None,
        sclang_path: str | os.PathLike[str] | None = None,
        server_options: Optional[Dict[str, Any]] = None,
        lang_options: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Boot sclang + scsynth via the Node helper."""
        server_options = self._apply_server_env_overrides(server_options)
        lang_options = self._apply_lang_env_overrides(lang_options)
        request_payload: dict[str, Any] = {
            "options": {
                "includePaths": list(include_paths or []),
                "server": server_options or {},
                "lang": lang_options or {},
            }
        }
        resolved_sclang = self._resolve_sclang_path(sclang_path)
        if resolved_sclang:
            request_payload["options"]["sclang"] = resolved_sclang
        else:
            raise SuperColliderBridgeError(
                "Unable to locate sclang.exe. Install SuperCollider or set the SCLANG_PATH environment variable."
            )
        server_override = None
        if server_options:
            server_override = server_options.pop("scsynth", None) or server_options.pop("scsynth_path", None)
        resolved_scsynth = self._resolve_scsynth_path(server_override)
        if resolved_scsynth:
            request_payload["options"]["server"] = dict(server_options or {}, scsynth=resolved_scsynth)
        else:
            raise SuperColliderBridgeError(
                "Unable to locate scsynth.exe. Install SuperCollider or set the SCSYNTH_PATH environment variable."
            )
        self._request("boot", request_payload)
        self._booted = True

    def evaluate(self, code: str, *, as_string: bool = False) -> Any:
        """Evaluate SuperCollider code via sclang."""
        if not self._booted:
            raise SuperColliderBridgeError("Bridge has not been booted")
        response = self._request("eval", {"code": code, "asString": as_string})
        return response.get("result")

    def send_osc(self, address: str, *args: Any) -> None:
        """Send a raw OSC message to scsynth."""
        if not self._booted:
            raise SuperColliderBridgeError("Bridge has not been booted")
        self._request("send", {"address": address, "args": list(args)})

    def shutdown(self) -> None:
        """Terminate the bridge process."""
        if not self._process or self._process.poll() is not None:
            return
        try:
            self._request("shutdown", {})
        except SuperColliderBridgeError:
            pass
        finally:
            with self._pending_lock:
                self._pending.clear()
            self._booted = False

    def __del__(self) -> None:
        try:
            self.shutdown()
        except Exception:
            pass

    def _resolve_sclang_path(self, override: str | os.PathLike[str] | None) -> str | None:
        candidates: list[Path] = []
        if override:
            candidates.append(Path(override))
        if self._explicit_sclang_path:
            candidates.append(self._explicit_sclang_path)
        env_value = os.environ.get("SCLANG_PATH")
        if env_value:
            candidates.append(Path(env_value))
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        candidates.append(Path(program_files) / "SuperCollider" / "sclang.exe")
        candidates.append(Path(program_files_x86) / "SuperCollider" / "sclang.exe")
        for base in [program_files, program_files_x86]:
            if not base:
                continue
            base_path = Path(base)
            if base_path.exists():
                try:
                    for candidate_dir in base_path.glob("SuperCollider*"):
                        exe = candidate_dir / "sclang.exe"
                        if exe.exists():
                            candidates.append(exe)
                except OSError:
                    continue
        for candidate in candidates:
            if not candidate:
                continue
            try:
                if candidate.exists():
                    return str(candidate)
            except OSError:
                continue
        return None

    def _resolve_scsynth_path(self, override: str | os.PathLike[str] | None) -> str | None:
        candidates: list[Path] = []
        if override:
            candidates.append(Path(override))
        if self._explicit_scsynth_path:
            candidates.append(self._explicit_scsynth_path)
        env_value = os.environ.get("SCSYNTH_PATH")
        if env_value:
            candidates.append(Path(env_value))
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        candidates.append(Path(program_files) / "SuperCollider" / "scsynth.exe")
        candidates.append(Path(program_files_x86) / "SuperCollider" / "scsynth.exe")
        for base in [program_files, program_files_x86]:
            if not base:
                continue
            base_path = Path(base)
            if not base_path.exists():
                continue
            try:
                for candidate_dir in base_path.glob("SuperCollider*"):
                    exe = candidate_dir / "scsynth.exe"
                    if exe.exists():
                        candidates.append(exe)
            except OSError:
                continue
        for candidate in candidates:
            if not candidate:
                continue
            try:
                if candidate.exists():
                    return str(candidate)
            except OSError:
                continue
        return None

    def _apply_server_env_overrides(self, server_options: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge server options with environment-driven overrides."""
        merged: Dict[str, Any] = {}
        if server_options:
            merged.update(server_options)
        env_device = os.environ.get("SC_AUDIO_DEVICE")
        if env_device and "device" not in merged and "inDevice" not in merged and "outDevice" not in merged:
            merged["device"] = env_device
        env_in_device = os.environ.get("SC_AUDIO_INPUT_DEVICE")
        if env_in_device and "inDevice" not in merged:
            merged["inDevice"] = env_in_device
        env_out_device = os.environ.get("SC_AUDIO_OUTPUT_DEVICE")
        if env_out_device and "outDevice" not in merged:
            merged["outDevice"] = env_out_device
        env_host = os.environ.get("SC_SERVER_HOST")
        if env_host and "host" not in merged:
            merged["host"] = env_host
        env_port = os.environ.get("SC_SERVER_PORT")
        if env_port and "serverPort" not in merged:
            merged["serverPort"] = str(env_port)
        env_protocol = os.environ.get("SC_SERVER_PROTOCOL")
        if env_protocol and "protocol" not in merged:
            merged["protocol"] = env_protocol
        env_driver = os.environ.get("SC_SERVER_AUDIO_DRIVER")
        if env_driver and "driver" not in merged:
            merged["driver"] = env_driver
        if "serverPort" not in merged:
            merged["serverPort"] = str(self._pick_free_udp_port())
        return merged

    def _apply_lang_env_overrides(self, lang_options: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        if lang_options:
            merged.update(lang_options)
        env_port = os.environ.get("SC_LANG_PORT")
        if env_port and "langPort" not in merged:
            try:
                merged["langPort"] = int(env_port)
            except ValueError:
                pass
        if "langPort" not in merged:
            merged["langPort"] = self._pick_free_udp_port()
        return merged

    def _pick_free_udp_port(self) -> int:
        """Find an available UDP port to avoid clashes with stale scsynth instances."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]
