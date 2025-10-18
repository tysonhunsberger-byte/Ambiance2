"""Carla-backed VST host integration.

This module embeds the Carla backend into the Ambiance runtime so real VST2 and
VST3 plug-ins can be discovered and manipulated from the Python process.  The
implementation favours a pure Python bridge using Carla's ``libcarla`` shared
library which ships with the Carla source tree bundled in this repository.

The goal is to expose an API compatible with :class:`FlutterVSTHost` so the
existing HTTP server and UI can control either implementation transparently.
If Carla is not available (because the shared library has not been built yet)
we fall back to the Flutter shim, ensuring the rest of Ambiance keeps working.
"""

from __future__ import annotations

import atexit
from dataclasses import dataclass
import importlib.util
import os
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any

from .flutter_vst_host import FlutterVSTHost


class CarlaHostError(RuntimeError):
    """Raised when the Carla backend cannot perform the requested action."""


@dataclass(frozen=True, slots=True)
class CarlaParameterSnapshot:
    """Lightweight representation of a Carla parameter."""

    identifier: int
    name: str
    display_name: str
    units: str
    default: float
    minimum: float
    maximum: float
    step: float
    value: float
    description: str = ""

    def to_status_entry(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "name": self.name,
            "display_name": self.display_name or self.name,
            "description": self.description,
            "units": self.units,
            "default": self.default,
            "min": self.minimum,
            "max": self.maximum,
            "step": self.step,
            "value": self.value,
        }

    def to_metadata_entry(self) -> dict[str, Any]:
        payload = self.to_status_entry()
        payload.pop("value", None)
        return payload


class CarlaBackend:
    """Thin wrapper around Carla's ``libcarla_standalone2`` shared library."""

    _PLUGIN_TYPE_LABELS = {
        5: "VST2",
        6: "VST3",
    }

    _PLUGIN_CATEGORY_LABELS = {
        0: "Unknown",
        1: "Synth",
        2: "Delay",
        3: "EQ",
        4: "Filter",
        5: "Distortion",
        6: "Dynamics",
        7: "Modulator",
        8: "Utility",
        9: "Other",
    }

    _PREFERRED_DRIVERS = (
        "Dummy",
        "JACK",
        "ALSA",
        "PulseAudio",
        "CoreAudio",
        "DirectSound",
        "WASAPI",
        "PortAudio",
    )

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parents[2]
        self.root = self._discover_root()
        self.library_path: Path | None = None
        self.module: ModuleType | None = None
        self.host: Any | None = None
        self.available = False
        self.warnings: list[str] = []
        self._engine_running = False
        self._engine_configured = False
        self._driver_name: str | None = None
        self._lock = threading.RLock()
        self._plugin_id: int | None = None
        self._plugin_path: Path | None = None
        self._parameters: list[CarlaParameterSnapshot] = []
        self._ui_visible = False
        self._idle_thread: threading.Thread | None = None
        self._idle_stop: threading.Event | None = None
        self._idle_interval = 1.0 / 120.0
        self._plugin_paths: dict[int, set[Path]] = {}

        if not self.root:
            self.warnings.append("Carla source tree not found – set CARLA_ROOT")
            return

        try:
            self.library_path = self._locate_library(self.root)
            self._prepare_environment(self.library_path)
        except FileNotFoundError as exc:  # pragma: no cover - depends on build artefacts
            self.warnings.append(str(exc))
            return

        try:
            self.module = self._load_backend_module(self.root)
        except Exception as exc:  # pragma: no cover - import errors surfaced to user
            self.warnings.append(f"Failed to import Carla backend: {exc}")
            return

        try:
            assert self.module is not None
            self.host = self.module.CarlaHostDLL(str(self.library_path), True)
        except Exception as exc:  # pragma: no cover - depends on shared library availability
            self.warnings.append(f"Failed to load libcarla: {exc}")
            self.host = None
            return

        self.available = True
        atexit.register(self.close)

    # ------------------------------------------------------------------
    # Discovery helpers
    def _discover_root(self) -> Path | None:
        env = (Path(p).expanduser() for p in (
            os.environ.get("CARLA_ROOT"),
            os.environ.get("CARLA_HOME"),
        ) if p)
        for candidate in env:
            if candidate.exists():
                return candidate
        default = self.base_dir / "Carla-main"
        if default.exists():
            return default
        if sys.platform.startswith("win"):
            program_dirs = [
                os.environ.get("PROGRAMFILES"),
                os.environ.get("PROGRAMFILES(X86)"),
                os.environ.get("ProgramW6432"),
            ]
            for prefix in program_dirs:
                if not prefix:
                    continue
                candidate = Path(prefix) / "Carla"
                if candidate.exists():
                    return candidate
        return None

    def _locate_library(self, root: Path) -> Path:
        names = (
            "libcarla_standalone2.so",
            "libcarla_standalone2.dylib",
            "libcarla_standalone2.dll",
        )
        search_roots = [root / "bin", root / "build", root]
        for directory in search_roots:
            for name in names:
                candidate = directory / name
                if candidate.exists():
                    return candidate
        for name in names:  # fallback to a bounded glob search
            matches = list(root.glob(f"**/{name}"))
            if matches:
                return matches[0]
        raise FileNotFoundError("libcarla_standalone2 library not found; build Carla first")

    def _prepare_environment(self, library: Path) -> None:
        if os.name != "nt":
            return
        dll_paths = {library.parent}
        dll_paths.update(self._windows_dependency_dirs())
        paths: list[str] = []
        for directory in dll_paths:
            if not directory or not directory.exists():
                continue
            directory_str = str(directory)
            paths.append(directory_str)
            add_dir = getattr(os, "add_dll_directory", None)
            if add_dir:
                try:
                    add_dir(directory_str)
                except (FileNotFoundError, OSError):  # pragma: no cover - platform specific
                    continue
        if paths:
            existing = os.environ.get("PATH", "")
            combined = os.pathsep.join(paths + [existing]) if existing else os.pathsep.join(paths)
            os.environ["PATH"] = combined

    def _windows_dependency_dirs(self) -> set[Path]:
        if not self.root:
            return set()
        candidates = {
            self.root / "bin",
            self.root / "build",
            self.root / "build" / "Release",
            self.root / "build" / "windows",
            self.root / "build" / "win64",
            self.root / "resources",
            self.root / "resources" / "windows",
            self.root / "resources" / "windows" / "lib",
        }
        # Include parents of the library in case dependencies sit next to it (MSVC builds)
        if self.library_path:
            for parent in self.library_path.parents:
                candidates.add(parent)
        return {path for path in candidates if path.exists()}

    def _load_backend_module(self, root: Path) -> ModuleType:
        frontend = root / "source" / "frontend"
        module_path = frontend / "carla_backend.py"
        if not module_path.exists():
            raise FileNotFoundError(f"carla_backend.py missing at {module_path}")
        sys.path.insert(0, str(frontend))
        try:
            spec = importlib.util.spec_from_file_location("ambiance_carla_backend", module_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Unable to load spec for {module_path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        finally:
            try:
                sys.path.remove(str(frontend))
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # Option helpers
    def _get_constant(self, name: str, default: int | None = None) -> int | None:
        if self.module is None:
            return default
        value = getattr(self.module, name, default)
        return int(value) if isinstance(value, int) else default

    def _set_engine_option(self, option_name: str, value: int, payload: str = "") -> None:
        if self.host is None or self.module is None:
            return
        option = getattr(self.module, option_name, None)
        if option is None:
            return
        try:
            self.host.set_engine_option(int(option), int(value), payload)
        except Exception as exc:  # pragma: no cover - backend specific failure
            self.warnings.append(f"Failed to apply {option_name}: {exc}")

    def _register_plugin_path(self, plugin_type: int | None, path: Path) -> None:
        if self.host is None or plugin_type is None:
            return
        candidate_path = Path(path).expanduser()
        try:
            resolved = candidate_path.resolve()
        except (OSError, RuntimeError):
            resolved = candidate_path
        if not resolved.exists():
            return
        paths = self._plugin_paths.setdefault(plugin_type, set())
        if resolved in paths:
            return
        paths.add(resolved)
        directories = os.pathsep.join(sorted(str(candidate) for candidate in paths))
        option = self._get_constant("ENGINE_OPTION_PLUGIN_PATH")
        if option is None:
            return
        try:
            self.host.set_engine_option(option, int(plugin_type), directories)
        except Exception as exc:  # pragma: no cover - backend specific failure
            self.warnings.append(f"Failed to register plugin directory {resolved}: {exc}")

    def _default_plugin_directories(self) -> dict[int, list[Path]]:
        mapping: dict[int, list[Path]] = {}

        def add(plugin_type: int | None, *candidates: Path | str | None) -> None:
            if plugin_type is None:
                return
            for candidate in candidates:
                if not candidate:
                    continue
                path = Path(candidate).expanduser()
                if path.exists():
                    mapping.setdefault(plugin_type, []).append(path)

        vst2 = self._get_constant("PLUGIN_VST2", 5)
        vst3 = self._get_constant("PLUGIN_VST3", 6)

        cache_root = self.base_dir / ".cache" / "plugins"
        data_root = self.base_dir / "data" / "vsts"
        add(vst2, cache_root, data_root)
        add(vst3, cache_root, data_root)

        if sys.platform.startswith("win"):
            program_files = Path(os.environ.get("PROGRAMFILES", "")).expanduser()
            program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", "")).expanduser()
            common_files = Path(os.environ.get("COMMONPROGRAMFILES", "")).expanduser()
            common_files_x86 = Path(os.environ.get("COMMONPROGRAMFILES(X86)", "")).expanduser()
            local_appdata = Path(os.environ.get("LOCALAPPDATA", "")).expanduser()

            add(vst2, program_files / "VstPlugins", program_files / "Steinberg" / "VstPlugins")
            add(vst2, program_files_x86 / "VstPlugins", program_files_x86 / "Steinberg" / "VstPlugins")

            add(vst3, common_files / "VST3", common_files_x86 / "VST3")
            add(vst3, local_appdata / "Programs" / "Common" / "VST3")
        else:
            home = Path.home()
            add(vst2, home / ".vst", Path("/usr/lib/vst"), Path("/usr/local/lib/vst"))
            add(vst3, home / ".vst3", Path("/usr/lib/vst3"), Path("/usr/local/lib/vst3"))
            if sys.platform == "darwin":
                add(vst2, home / "Library" / "Audio" / "Plug-Ins" / "VST")
                add(vst3, home / "Library" / "Audio" / "Plug-Ins" / "VST3")

        return mapping

    def _configure_engine_defaults(self) -> None:
        if self.host is None:
            return

        patchbay = self._get_constant("ENGINE_PROCESS_MODE_PATCHBAY")
        if patchbay is not None:
            self._set_engine_option("ENGINE_OPTION_PROCESS_MODE", patchbay)

        for option_name in (
            "ENGINE_OPTION_PREFER_PLUGIN_BRIDGES",
            "ENGINE_OPTION_PREFER_UI_BRIDGES",
            "ENGINE_OPTION_PREVENT_BAD_BEHAVIOUR",
            "ENGINE_OPTION_FORCE_STEREO",
        ):
            option = self._get_constant(option_name)
            if option is not None:
                self._set_engine_option(option_name, 1)

        binaries = self.root / "bin" if self.root else None
        if binaries and binaries.exists():
            self._set_engine_option("ENGINE_OPTION_PATH_BINARIES", 0, str(binaries))

        resources = self.root / "resources" if self.root else None
        if resources and resources.exists():
            self._set_engine_option("ENGINE_OPTION_PATH_RESOURCES", 0, str(resources))

        for plugin_type, directories in self._default_plugin_directories().items():
            for directory in directories:
                self._register_plugin_path(plugin_type, directory)

    # ------------------------------------------------------------------
    # Engine lifecycle
    def _ensure_engine(self) -> None:
        if not self.available or self.host is None:
            raise CarlaHostError("Carla backend is not available")
        if self._engine_running:
            return
        if not self._engine_configured:
            self._configure_engine_defaults()
            self._engine_configured = True
        driver = self._select_driver()
        if not driver:
            raise CarlaHostError("No usable Carla audio driver found")
        if not self.host.engine_init(driver, "AmbianceCarlaHost"):
            message = self.host.get_last_error() if hasattr(self.host, "get_last_error") else "unknown error"
            raise CarlaHostError(f"Failed to initialise Carla engine: {message}")
        self._driver_name = driver
        self._engine_running = True
        self._start_idle_thread()

    def _start_idle_thread(self) -> None:
        if self._idle_thread and self._idle_thread.is_alive():
            return
        if self.host is None:
            return

        stop_event = threading.Event()
        self._idle_stop = stop_event

        def _idle_loop() -> None:
            while not stop_event.is_set():
                try:
                    self.host.engine_idle()
                except Exception as exc:  # pragma: no cover - engine specific failures
                    self.warnings.append(f"Carla engine idle loop stopped: {exc}")
                    break
                time.sleep(self._idle_interval)

        self._idle_thread = threading.Thread(name="CarlaEngineIdle", target=_idle_loop, daemon=True)
        self._idle_thread.start()

    def _stop_idle_thread(self) -> None:
        if self._idle_stop:
            self._idle_stop.set()
        if self._idle_thread and self._idle_thread.is_alive():
            self._idle_thread.join(timeout=1.0)
        self._idle_thread = None
        self._idle_stop = None

    def _select_driver(self) -> str | None:
        assert self.host is not None
        try:
            count = int(self.host.get_engine_driver_count())
        except Exception as exc:  # pragma: no cover - depends on libcarla
            self.warnings.append(f"Unable to enumerate Carla drivers: {exc}")
            return None
        names: list[str] = []
        for index in range(count):
            try:
                name = self.host.get_engine_driver_name(index)
            except Exception:  # pragma: no cover - defensive
                continue
            if not isinstance(name, str):
                continue
            names.append(name)
        for preferred in self._PREFERRED_DRIVERS:
            for candidate in names:
                if candidate.lower() == preferred.lower():
                    return candidate
        return names[0] if names else None

    # ------------------------------------------------------------------
    # Public API
    def can_handle_path(self, plugin_path: Path) -> bool:
        suffix = plugin_path.suffix.lower()
        if suffix == ".vst3":
            return True
        if suffix in {".vst", ".dll", ".so", ".dylib"}:
            return True
        return False

    def status(self) -> dict[str, Any]:
        with self._lock:
            payload: dict[str, Any] = {
                "available": self.available,
                "toolkit_path": str(self.root) if self.root else None,
                "engine_path": str(self.library_path) if self.library_path else None,
                "warnings": list(self.warnings),
                "ui_visible": self._ui_visible,
            }
            if self._driver_name:
                payload["driver"] = self._driver_name
            payload["capabilities"] = {
                "editor": bool(self._plugin_id is not None and self._plugin_supports_custom_ui()),
                "instrument": bool(self._plugin_id is not None and self._plugin_is_instrument()),
            }
            if self._plugin_id is None:
                payload["plugin"] = None
                payload["parameters"] = []
            else:
                payload["plugin"] = self._plugin_payload()
                payload["parameters"] = [param.to_status_entry() for param in self._parameters]
            return payload

    def load_plugin(
        self,
        plugin_path: str | Path,
        parameters: dict[str, float] | None = None,
        *,
        show_ui: bool = False,
    ) -> dict[str, Any]:
        path = Path(plugin_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Plugin not found: {path}")
        with self._lock:
            if not self.can_handle_path(path):
                raise CarlaHostError(f"Unsupported plugin format: {path.suffix}")
            self._ensure_engine()
            assert self.host is not None
            self.host.remove_all_plugins()
            plugin_type = self._plugin_type_for(path)
            if plugin_type is None:
                raise CarlaHostError(f"Unsupported plugin type for {path}")
            self._register_plugin_path(plugin_type, path.parent)
            if path.suffix.lower() == ".vst3" and path.is_dir():
                self._register_plugin_path(plugin_type, path)
            binary_type = self.module.BINARY_NATIVE if self.module else 0
            options = getattr(self.module, "PLUGIN_OPTIONS_NULL", 0) if self.module else 0
            added = self.host.add_plugin(
                binary_type,
                plugin_type,
                str(path),
                None,
                path.stem,
                0,
                None,
                options,
            )
            if not added:
                message = self.host.get_last_error() if hasattr(self.host, "get_last_error") else "unknown"
                raise CarlaHostError(f"Failed to load plugin: {message}")
            self._plugin_id = 0
            self._plugin_path = path
            self._parameters = self._collect_parameters()
            self._ui_visible = False
            if parameters:
                for key, value in parameters.items():
                    try:
                        self.set_parameter(key, float(value))
                    except CarlaHostError:
                        continue
            if show_ui:
                try:
                    self._show_plugin_ui(True)
                except CarlaHostError as exc:
                    self.warnings.append(str(exc))
            return self._plugin_payload()

    def unload(self) -> None:
        with self._lock:
            if not self.available or self.host is None:
                return
            if self._plugin_id is not None:
                try:
                    self._show_plugin_ui(False)
                except CarlaHostError:
                    pass
                self.host.remove_all_plugins()
            self._plugin_id = None
            self._plugin_path = None
            self._parameters = []
            self._ui_visible = False

    def close(self) -> None:
        with self._lock:
            if not self.available or self.host is None:
                return
            self.unload()
            self._stop_idle_thread()
            if self._engine_running:
                try:
                    self.host.engine_close()
                except Exception as exc:  # pragma: no cover - engine specific shutdown
                    self.warnings.append(f"Failed to close Carla engine: {exc}")
            self._engine_running = False
            self._driver_name = None

    def set_parameter(self, identifier: int | str, value: float) -> dict[str, Any]:
        with self._lock:
            if self._plugin_id is None or self.host is None:
                raise CarlaHostError("No plugin hosted")
            param_id = self._resolve_parameter_identifier(identifier)
            self.host.set_parameter_value(self._plugin_id, param_id, float(value))
            for index, param in enumerate(self._parameters):
                if param.identifier == param_id:
                    self._parameters[index] = CarlaParameterSnapshot(
                        identifier=param.identifier,
                        name=param.name,
                        display_name=param.display_name,
                        units=param.units,
                        default=param.default,
                        minimum=param.minimum,
                        maximum=param.maximum,
                        step=param.step,
                        value=float(value),
                        description=param.description,
                    )
                    break
            return {
                "plugin": self._plugin_payload(),
                "parameters": [param.to_status_entry() for param in self._parameters],
            }

    def show_ui(self) -> dict[str, Any]:
        with self._lock:
            if self._plugin_id is None or self.host is None:
                raise CarlaHostError("No plugin hosted")
            self._show_plugin_ui(True)
            return self.status()

    def hide_ui(self) -> dict[str, Any]:
        with self._lock:
            if self._plugin_id is None or self.host is None:
                raise CarlaHostError("No plugin hosted")
            self._show_plugin_ui(False)
            return self.status()

    def describe_ui(self, plugin_path: str | Path | None = None) -> dict[str, Any]:
        with self._lock:
            if plugin_path is None:
                if self._plugin_id is None:
                    raise CarlaHostError("No plugin hosted")
                return self._build_descriptor()

            path = Path(plugin_path).expanduser()
            if not path.exists():
                raise FileNotFoundError(f"Plugin not found: {path}")
            if not self.can_handle_path(path):
                raise CarlaHostError(f"Unsupported plugin format: {path.suffix}")

            state = self._snapshot_state()
            try:
                self.load_plugin(path, show_ui=False)
                return self._build_descriptor()
            finally:
                self._restore_state(state)

    # ------------------------------------------------------------------
    # Internal helpers
    def _plugin_type_for(self, path: Path) -> int | None:
        suffix = path.suffix.lower()
        if suffix == ".vst3":
            return getattr(self.module, "PLUGIN_VST3", 6)
        if suffix in {".vst", ".dll", ".so", ".dylib"}:
            return getattr(self.module, "PLUGIN_VST2", 5)
        return None

    def _collect_parameters(self) -> list[CarlaParameterSnapshot]:
        assert self.host is not None
        if self._plugin_id is None:
            return []
        count = int(self.host.get_parameter_count(self._plugin_id))
        results: list[CarlaParameterSnapshot] = []
        for index in range(count):
            info = self.host.get_parameter_info(self._plugin_id, index)
            ranges = self.host.get_parameter_ranges(self._plugin_id, index)
            value = float(self.host.get_current_parameter_value(self._plugin_id, index))
            name = info.get("name") or f"Parameter {index}"
            display_name = info.get("symbol") or name
            units = info.get("unit") or ""
            results.append(
                CarlaParameterSnapshot(
                    identifier=index,
                    name=name,
                    display_name=display_name,
                    units=units,
                    default=float(ranges.get("def", 0.0)),
                    minimum=float(ranges.get("min", 0.0)),
                    maximum=float(ranges.get("max", 1.0)),
                    step=float(ranges.get("step", 0.01)),
                    value=value,
                    description=info.get("comment") or "",
                )
            )
        return results

    def _resolve_parameter_identifier(self, identifier: int | str) -> int:
        if isinstance(identifier, int):
            return identifier
        try:
            index = int(identifier)
        except (TypeError, ValueError):
            index = None
        for param in self._parameters:
            if identifier == param.name or identifier == param.display_name:
                return param.identifier
            if index is not None and param.identifier == index:
                return param.identifier
        raise CarlaHostError(f"Unknown parameter '{identifier}'")

    def _plugin_payload(self) -> dict[str, Any]:
        assert self.host is not None
        if self._plugin_id is None or self._plugin_path is None:
            raise CarlaHostError("No plugin hosted")
        info = self.host.get_plugin_info(self._plugin_id)
        metadata = {
            "name": info.get("name") or self._plugin_path.stem,
            "vendor": info.get("maker") or "",
            "version": "",
            "category": self._PLUGIN_CATEGORY_LABELS.get(info.get("category", 0), "Unknown"),
            "bundle_identifier": None,
            "parameters": [param.to_metadata_entry() for param in self._parameters],
            "format": self._PLUGIN_TYPE_LABELS.get(info.get("type", 0), "Unknown"),
        }
        payload = {
            "path": str(self._plugin_path),
            "metadata": metadata,
            "parameters": [param.to_status_entry() for param in self._parameters],
            "capabilities": {
                "instrument": self._plugin_is_instrument(),
                "editor": self._plugin_supports_custom_ui(),
            },
        }
        return payload

    def _build_descriptor(self) -> dict[str, Any]:
        plugin = self._plugin_payload()
        controls = []
        for param in self._parameters:
            control = {
                "id": param.identifier,
                "name": param.display_name or param.name,
                "label": param.display_name or param.name,
                "type": "slider",
                "min": param.minimum,
                "max": param.maximum,
                "step": param.step,
                "units": param.units,
                "value": param.value,
            }
            controls.append(control)
        descriptor = {
            "title": plugin["metadata"].get("name", plugin.get("path")),
            "subtitle": plugin["metadata"].get("vendor", ""),
            "keyboard": {"min_note": 36, "max_note": 84},
            "panels": [{"name": "Parameters", "controls": controls}],
            "parameters": [param.to_status_entry() for param in self._parameters],
            "plugin": plugin,
            "capabilities": {
                "instrument": self._plugin_is_instrument(),
                "editor": self._plugin_supports_custom_ui(),
            },
        }
        return descriptor

    def _plugin_is_instrument(self) -> bool:
        if self.host is None or self._plugin_id is None:
            return False
        info = self.host.get_plugin_info(self._plugin_id)
        hints = int(info.get("hints", 0))
        flag = getattr(self.module, "PLUGIN_IS_SYNTH", 0x004) if self.module else 0x004
        return bool(hints & flag)

    def _plugin_supports_custom_ui(self) -> bool:
        if self.host is None or self._plugin_id is None:
            return False
        info = self.host.get_plugin_info(self._plugin_id)
        hints = int(info.get("hints", 0))
        flag = getattr(self.module, "PLUGIN_HAS_CUSTOM_UI", 0x008) if self.module else 0x008
        return bool(hints & flag)

    def _show_plugin_ui(self, visible: bool) -> None:
        if self.host is None or self._plugin_id is None:
            self._ui_visible = False
            if visible:
                raise CarlaHostError("No plugin hosted")
            return
        if visible and not self._plugin_supports_custom_ui():
            raise CarlaHostError("Plugin does not expose a custom UI")
        try:
            self.host.show_custom_ui(self._plugin_id, bool(visible))
        except Exception as exc:  # pragma: no cover - depends on host implementation
            action = "show" if visible else "hide"
            raise CarlaHostError(f"Failed to {action} plugin UI: {exc}") from exc
        self._ui_visible = bool(visible)

    def _snapshot_state(self) -> dict[str, Any] | None:
        if self._plugin_id is None or self._plugin_path is None:
            return None
        return {
            "path": str(self._plugin_path),
            "parameters": {param.identifier: param.value for param in self._parameters},
            "ui_visible": self._ui_visible,
        }

    def _restore_state(self, state: dict[str, Any] | None) -> None:
        if state is None:
            self.unload()
            return
        try:
            self.load_plugin(state["path"], state.get("parameters"), show_ui=bool(state.get("ui_visible")))
        except Exception as exc:  # pragma: no cover - best effort restore
            self.warnings.append(f"Failed to restore Carla plugin state: {exc}")


class CarlaVSTHost:
    """Facade that prefers Carla but falls back to the Flutter shim."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parents[2]
        self._backend = CarlaBackend(base_dir=self.base_dir)
        self._lock = threading.RLock()
        self._fallback = FlutterVSTHost(base_dir=self.base_dir)
        self._active: str | None = None

    def shutdown(self) -> None:
        with self._lock:
            self._backend.close()
            self._fallback.unload()

    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        with self._lock:
            if self._active == "carla" or (self._backend.available and self._active is None):
                status = self._backend.status()
                if self._active != "carla" and status.get("plugin") is None:
                    status.setdefault("warnings", []).append("Carla backend idle")
                return status
            status = self._fallback.status()
            if not self._backend.available:
                status.setdefault("warnings", []).extend(self._backend.warnings)
            else:
                status.setdefault("warnings", []).append("Using Flutter fallback host")
            return status

    def load_plugin(self, plugin_path: str | Path, parameters: dict[str, float] | None = None) -> dict[str, Any]:
        with self._lock:
            path = Path(plugin_path).expanduser()
            if self._backend.available and self._backend.can_handle_path(path):
                try:
                    plugin = self._backend.load_plugin(path, parameters, show_ui=True)
                    self._fallback.unload()
                    self._active = "carla"
                    return plugin
                except (CarlaHostError, OSError) as exc:
                    self._backend.warnings.append(str(exc))
                    self._active = None
                    raise RuntimeError(str(exc)) from exc
            plugin = self._fallback.load_plugin(path, parameters)
            self._active = "flutter"
            return plugin

    def unload(self) -> None:
        with self._lock:
            if self._active == "carla":
                self._backend.unload()
            elif self._active == "flutter":
                self._fallback.unload()
            else:
                self._backend.unload()
                self._fallback.unload()
            self._active = None

    def set_parameter(self, identifier: int | str, value: float) -> dict[str, Any]:
        with self._lock:
            if self._active == "carla":
                return self._backend.set_parameter(identifier, value)
            if self._active == "flutter":
                return self._fallback.set_parameter(identifier, value)
            raise RuntimeError("No plugin hosted")

    def render_preview(self, duration: float = 1.5, sample_rate: int = 44100):
        with self._lock:
            if self._active == "carla":
                raise RuntimeError(
                    "Carla backend does not support offline rendering in this environment"
                )
            return self._fallback.render_preview(duration=duration, sample_rate=sample_rate)

    def play_note(
        self,
        note: int,
        *,
        velocity: float = 0.8,
        duration: float = 1.0,
        sample_rate: int = 44100,
    ):
        with self._lock:
            if self._active == "carla":
                raise RuntimeError(
                    "Carla backend does not expose MIDI playback in this environment"
                )
            return self._fallback.play_note(
                note,
                velocity=velocity,
                duration=duration,
                sample_rate=sample_rate,
            )

    def describe_ui(self, plugin_path: str | Path | None = None) -> dict[str, Any]:
        with self._lock:
            if plugin_path is not None:
                path = Path(plugin_path).expanduser()
                if self._backend.available and self._backend.can_handle_path(path):
                    try:
                        return self._backend.describe_ui(path)
                    except CarlaHostError as exc:
                        self._backend.warnings.append(str(exc))
                return self._fallback.describe_ui(plugin_path)
            if self._active == "carla":
                return self._backend.describe_ui()
            if self._active == "flutter":
                return self._fallback.describe_ui()
            raise RuntimeError("No plugin hosted")

    def show_ui(self) -> dict[str, Any]:
        with self._lock:
            if self._active != "carla":
                raise RuntimeError("Hosted plugin does not expose a native UI")
            try:
                return self._backend.show_ui()
            except CarlaHostError as exc:
                raise RuntimeError(str(exc)) from exc

    def hide_ui(self) -> dict[str, Any]:
        with self._lock:
            if self._active != "carla":
                raise RuntimeError("Hosted plugin does not expose a native UI")
            try:
                return self._backend.hide_ui()
            except CarlaHostError as exc:
                raise RuntimeError(str(exc)) from exc


__all__ = ["CarlaVSTHost", "CarlaHostError"]

