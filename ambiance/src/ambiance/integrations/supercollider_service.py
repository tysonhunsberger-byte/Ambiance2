"""High-level service wrapper for the SuperCollider/vstplugin bridge."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Iterable

from .supercollider_host import SuperColliderBridgeError
from .vstplugin_bridge import VSTPluginBridge


class SuperColliderServiceError(RuntimeError):
    """Raised when SuperCollider interaction fails."""


class SuperColliderService:
    """Coordinate SuperCollider plugin hosting for the Ambiance server."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        base_dir: Path | None = None,
        auto_boot: bool = False,
        discovery_mode: str | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parents[2]
        self._lock = threading.Lock()
        self._booted = False
        self._boot_error: str | None = None
        self._current_plugin: dict[str, Any] | None = None
        self._bridge: VSTPluginBridge | None = VSTPluginBridge() if self.enabled else None
        env_mode = os.environ.get("SC_PLUGIN_DISCOVERY", "").strip().lower()
        supplied_mode = (discovery_mode or "").strip().lower()
        self.discovery_mode = supplied_mode or env_mode or "filesystem"
        if self.enabled and auto_boot:
            try:
                self._ensure_booted()
            except SuperColliderServiceError:
                # error stored in self._boot_error; caller can inspect status
                pass

    # ------------------------------------------------------------------
    def _ensure_booted(self) -> None:
        if not self.enabled:
            raise SuperColliderServiceError("SuperCollider host is disabled")
        assert self._bridge is not None
        if self._booted:
            return
        with self._lock:
            if self._booted:
                return
        try:
            self._bridge.boot(include_paths=self._sc_extension_paths())
            self._booted = True
            self._boot_error = None
        except Exception as exc:  # pylint: disable=broad-except
            self._boot_error = str(exc)
            raise SuperColliderServiceError(f"Failed to boot SuperCollider: {exc}") from exc

    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "booted": self._booted,
            "error": self._boot_error,
            "plugin": self._current_plugin,
        }

    # ------------------------------------------------------------------
    def list_plugins(self, search_paths: Iterable[str] | None = None) -> list[dict[str, str]]:
        all_paths = list(str(p) for p in (search_paths or []))
        plugin_dirs = self._plugin_roots()
        for path in plugin_dirs:
            path_str = str(path)
            if path_str not in all_paths:
                all_paths.append(path_str)

        discovery_mode = self.discovery_mode
        discovery_mode = discovery_mode if discovery_mode in {"filesystem", "server", "auto"} else "filesystem"
        filesystem_listing: list[dict[str, str]] = []
        if discovery_mode in {"filesystem", "auto"}:
            filesystem_listing = self._filesystem_plugins(all_paths)
            if discovery_mode == "filesystem":
                return filesystem_listing

        # At this point we're either in "server" mode or "auto" with a filesystem fallback prepared.
        self._ensure_booted()
        assert self._bridge is not None
        try:
            return self._bridge.list_plugins(all_paths)
        except SuperColliderBridgeError as exc:
            self._boot_error = str(exc)
            self._booted = False
            if discovery_mode == "server":
                raise SuperColliderServiceError(f"Failed to list VST plugins: {exc}") from exc
            # auto mode: fall back to filesystem enumeration
            return filesystem_listing

    def load_plugin(
        self,
        plugin_path: str | Path,
        *,
        channels: int = 2,
        editor: bool = True,
    ) -> dict[str, Any]:
        if not plugin_path:
            raise SuperColliderServiceError("Plugin path is required")
        self._ensure_booted()
        assert self._bridge is not None
        resolved = Path(plugin_path).expanduser().resolve()
        if not resolved.exists():
            raise SuperColliderServiceError(f"Plugin not found: {resolved}")
        try:
            self._bridge.load_plugin(resolved, channels=max(1, int(channels)), open_editor=bool(editor))
        except SuperColliderBridgeError as exc:
            raise SuperColliderServiceError(f"Failed to load plugin: {exc}") from exc
        self._current_plugin = {
            "path": str(resolved),
            "channels": max(1, int(channels)),
            "editor": bool(editor),
        }
        return dict(self._current_plugin)

    def unload_plugin(self) -> None:
        if not self._current_plugin:
            return
        self._ensure_booted()
        assert self._bridge is not None
        try:
            self._bridge.close_plugin()
        except SuperColliderBridgeError as exc:
            raise SuperColliderServiceError(f"Failed to close plugin: {exc}") from exc
        self._current_plugin = None

    def set_parameter(self, index: int, value: float) -> dict[str, Any]:
        if index is None:
            raise SuperColliderServiceError("Parameter index is required")
        self._ensure_booted()
        assert self._bridge is not None
        try:
            self._bridge.set_parameter(int(index), float(value))
        except SuperColliderBridgeError as exc:
            raise SuperColliderServiceError(f"Failed to set parameter {index}: {exc}") from exc
        return {"index": int(index), "value": float(value)}

    def send_midi(self, status: int, data1: int, data2: int) -> None:
        self._ensure_booted()
        assert self._bridge is not None
        try:
            self._bridge.send_midi(int(status), int(data1), int(data2))
        except SuperColliderBridgeError as exc:
            raise SuperColliderServiceError(f"Failed to send MIDI: {exc}") from exc

    def note_on(self, note: int, velocity: int) -> None:
        vel = max(0, min(127, int(velocity)))
        self.send_midi(0x90, int(note), vel)

    def note_off(self, note: int, velocity: int = 0) -> None:
        vel = max(0, min(127, int(velocity)))
        self.send_midi(0x80, int(note), vel)

    def show_editor(self) -> None:
        self._ensure_booted()
        assert self._bridge is not None
        try:
            self._bridge.show_editor()
        except SuperColliderBridgeError as exc:
            raise SuperColliderServiceError(f"Failed to show editor: {exc}") from exc

    def _filesystem_plugins(self, roots: Iterable[str]) -> list[dict[str, str]]:
        """Enumerate plugin files directly from disk as a fallback discovery mode."""
        results: list[dict[str, str]] = []
        seen: set[Path] = set()
        for entry in roots:
            if not entry:
                continue
            root = Path(entry).expanduser()
            if not root.exists():
                continue
            if root.is_file():
                candidates = [root]
            else:
                try:
                    candidates = (
                        entry
                        for pattern in ("*.dll", "*.DLL", "*.vst3", "*.VST3")
                        for entry in root.rglob(pattern)
                    )
                except OSError:
                    continue
            for candidate in candidates:
                suffix = candidate.suffix.lower()
                if suffix not in {".dll", ".vst3"}:
                    continue
                resolved = candidate.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                results.append(
                    {
                        "name": resolved.stem,
                        "path": str(resolved),
                        "format": "vst3" if suffix == ".vst3" else "vst2",
                    }
                )
        results.sort(key=lambda item: item["name"].lower())
        return results

    def _plugin_roots(self) -> list[Path]:
        """Return directories that mirror PluginRackManager discovery."""
        roots: list[Path] = []
        # Consider multiple workspace locations (module dir, package root, repo root)
        workspace_candidates: list[Path | None] = [
            self.base_dir / ".cache" / "plugins",
            self.base_dir.parent / ".cache" / "plugins",
            self.base_dir.parents[1] / ".cache" / "plugins" if len(self.base_dir.parents) > 1 else None,
        ]
        for candidate in workspace_candidates:
            if candidate and candidate.exists():
                roots.append(candidate)

        def _extend_included(base: Path | None) -> None:
            if not base:
                return
            included_dir = base / "included_plugins"
            if included_dir.exists():
                roots.append(included_dir)
                for child in included_dir.iterdir():
                    if child.is_dir():
                        roots.append(child)

        _extend_included(self.base_dir)
        _extend_included(self.base_dir.parent)
        if len(self.base_dir.parents) > 1:
            _extend_included(self.base_dir.parents[1])
        return [path for path in roots if path.exists()]

    def _sc_extension_paths(self) -> list[str]:
        """Include SuperCollider extension directories if applicable."""
        paths: list[str] = []
        sc_ext_env = os.environ.get("SC_EXTENSIONS_PATH")
        if sc_ext_env:
            paths.extend(p for p in sc_ext_env.split(os.pathsep) if p)
        default = Path.home() / "AppData" / "Local" / "SuperCollider" / "Extensions"
        if default.exists():
            paths.append(str(default))
        return paths
