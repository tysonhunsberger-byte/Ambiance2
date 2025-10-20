"""Carla-backed VST host integration with full native UI support.

This module manages Carla's Python backend, ensures Qt is initialised so
plugins can surface their native editors, and exposes a high-level facade
used across Ambiance. The implementation intentionally avoids any Flutter
fallback so that native UIs remain the primary experience.
"""

from __future__ import annotations

import atexit
from dataclasses import dataclass
import importlib.util
import os
import sys
import struct
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Sequence

if os.name == "nt":
    import ctypes
    from ctypes import wintypes
else:  # pragma: no cover - non-Windows environments skip Win32 helpers
    ctypes = None
    wintypes = None

if os.name == "nt":
    GWL_STYLE = -16
    GWL_EXSTYLE = -20
    GWL_HWNDPARENT = -8
    SW_SHOWNORMAL = 1
    SW_SHOW = 5
    WS_CHILD = 0x40000000
    WS_POPUP = 0x80000000
    WS_CAPTION = 0x00C00000
    WS_THICKFRAME = 0x00040000
    WS_EX_APPWINDOW = 0x00040000
    WS_EX_TOOLWINDOW = 0x00000080
else:  # pragma: no cover - non-Windows environments
    GWL_STYLE = GWL_EXSTYLE = GWL_HWNDPARENT = 0
    SW_SHOWNORMAL = SW_SHOW = 0
    WS_CHILD = WS_POPUP = WS_CAPTION = WS_THICKFRAME = 0
    WS_EX_APPWINDOW = WS_EX_TOOLWINDOW = 0


# Try to import PyQt5 for UI support
try:
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QTimer, QObject, pyqtSignal, pyqtSlot
    HAS_PYQT5 = True
except ImportError:
    HAS_PYQT5 = False
    QApplication = None
    QTimer = None
    QObject = None
    pyqtSignal = None
    pyqtSlot = None


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


if HAS_PYQT5:
    import queue

    class QtApplicationManager(QObject):
        """Manage Qt application instance for Carla UI support."""

        _instance = None
        _app = None
        _task_queue = None
        _timer = None

        @classmethod
        def get_instance(cls):
            """Get or create the Qt application instance."""
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

        def __init__(self):
            """Initialize Qt application if not already running."""
            super().__init__()

            # Thread-safe queue for cross-thread tasks
            self._task_queue = queue.Queue()

            # Check if QApplication already exists
            existing_app = QApplication.instance()
            if existing_app is None:
                # Create new QApplication
                self._app = QApplication(sys.argv if sys.argv else ['Ambiance'])
                self._app.setQuitOnLastWindowClosed(False)
            else:
                self._app = existing_app

            # Create a timer to poll the task queue (runs on main thread)
            # This MUST be created after QApplication exists
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._process_task_queue)
            self._timer.start(5)  # Poll every 5ms

        def _process_task_queue(self):
            """Process pending tasks from the queue (runs on Qt main thread)."""
            import logging
            try:
                # Process all available tasks in this iteration
                processed = 0
                while True:
                    try:
                        task = self._task_queue.get_nowait()
                        processed += 1
                        task()
                    except queue.Empty:
                        break
                if processed > 0:
                    logging.info(f"Processed {processed} Qt tasks on main thread")
            except Exception as e:
                # Log but don't crash the event loop
                logging.error(f"Error processing Qt task: {e}", exc_info=True)

        def is_available(self) -> bool:
            """Check if Qt is available and initialized."""
            return self._app is not None

        def invoke_on_main_thread(self, func, *args, **kwargs):
            """Execute a function on the Qt main thread.

            This is thread-safe and can be called from any thread.
            Returns the result of the function call.
            """
            import logging
            # Check if we're already on the main thread
            if threading.current_thread() is threading.main_thread():
                # Direct execution on main thread
                logging.info("Direct execution on main thread")
                return func(*args, **kwargs)

            # Create a holder for the result
            result_holder = {'result': None, 'exception': None, 'done': threading.Event()}

            def wrapper():
                try:
                    logging.info(f"Executing queued task on thread {threading.current_thread().name}")
                    result_holder['result'] = func(*args, **kwargs)
                except Exception as e:
                    result_holder['exception'] = e
                finally:
                    result_holder['done'].set()

            # Put task in queue (will be processed by timer on main thread)
            logging.info(f"Queuing task from thread {threading.current_thread().name}")
            self._task_queue.put(wrapper)

            # Wait for completion (with timeout to avoid infinite hang)
            logging.info("Waiting for task completion...")
            if not result_holder['done'].wait(timeout=30.0):
                logging.error("Task timed out after 30 seconds")
                raise TimeoutError("Operation on Qt main thread timed out after 30 seconds")

            logging.info("Task completed")
            # Re-raise exception if one occurred
            if result_holder['exception']:
                raise result_holder['exception']

            return result_holder['result']
else:
    # Stub class when PyQt5 is not available
    class QtApplicationManager:
        """Stub manager when PyQt5 is not available."""

        _instance = None

        @classmethod
        def get_instance(cls):
            return None

        def is_available(self) -> bool:
            return False


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

    if sys.platform.startswith("win"):
        _PREFERRED_DRIVERS = (
            "DirectSound",
            "WASAPI",
            "MME",
            "ASIO",
            "Dummy",
            "JACK",
            "PortAudio",
        )
    elif sys.platform == "darwin":
        _PREFERRED_DRIVERS = (
            "CoreAudio",
            "JACK",
            "Dummy",
        )
    else:
        _PREFERRED_DRIVERS = (
            "JACK",
            "ALSA",
            "PulseAudio",
            "Dummy",
            "PortAudio",
        )

    @staticmethod
    def _clean_driver_name(name: Any | None) -> str | None:
        if name is None:
            return None
        value = name if isinstance(name, str) else str(name)
        cleaned = value.strip()
        return cleaned or None

    @classmethod
    def _normalise_driver_names(cls, names: Sequence[str] | None) -> list[str]:
        result: list[str] = []
        if not names:
            return result
        seen: set[str] = set()
        for entry in names:
            cleaned = cls._clean_driver_name(entry)
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            result.append(cleaned)
        return result

    def _compose_driver_order(self) -> list[str]:
        order: list[str] = []
        seen: set[str] = set()

        def append(name: str | None) -> None:
            if not name:
                return
            lowered = name.lower()
            if lowered in seen:
                return
            seen.add(lowered)
            order.append(name)

        append(self._forced_driver)
        for candidate in self._user_preferred_drivers:
            append(candidate)
        for candidate in self._PREFERRED_DRIVERS:
            append(candidate)
        return order

    def _available_drivers(self) -> list[str]:
        if self.host is None:
            return []
        drivers: list[str] = []
        seen: set[str] = set()
        try:
            count = int(self.host.get_engine_driver_count())
        except Exception as exc:
            self.warnings.append(f"Unable to enumerate Carla drivers: {exc}")
            return drivers
        for index in range(count):
            try:
                name = self.host.get_engine_driver_name(index)
            except Exception:
                continue
            if not isinstance(name, str):
                continue
            lowered = name.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            drivers.append(name)
        return drivers

    def __init__(
        self,
        base_dir: Path | None = None,
        *,
        preferred_drivers: Sequence[str] | None = None,
        forced_driver: str | None = None,
        sample_rate: int | None = None,
        buffer_size: int | None = None,
        client_name: str | None = None,
    ) -> None:
        default_base = Path(__file__).resolve().parents[3]
        self.base_dir = Path(base_dir) if base_dir else default_base
        self._binary_hints: set[Path] = set()
        self._release_binary_dirs: set[Path] = set()
        self._client_name = client_name or "AmbianceCarlaHost"
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
        self._qt_manager: QtApplicationManager | None = None
        self._note_timers: dict[int, threading.Timer] = {}
        self._supports_midi = False
        self._midi_routed = False
        self._audio_routed = False
        self._audio_warning_emitted = False
        self._patch_lock = threading.RLock()
        self._patch_clients: dict[int, dict[str, Any]] = {}
        self._patch_ports: dict[int, dict[int, dict[str, Any]]] = {}
        self._patch_connections: set[tuple[int, int, int, int]] = set()
        self._plugin_patch_groups: dict[int, int] = {}
        self._patch_connection_ids: dict[int, tuple[int, int, int, int]] = {}
        self._engine_callback_registered = False
        self._patch_update_event = threading.Event()
        self._midi_warning_emitted = False
        self._user_preferred_drivers: list[str] = self._normalise_driver_names(preferred_drivers)
        self._forced_driver = self._clean_driver_name(forced_driver)
        self._preferred_drivers = self._compose_driver_order()
        self._engine_sample_rate = int(sample_rate) if sample_rate else None
        self._engine_buffer_size = int(buffer_size) if buffer_size else None
        self._host_window_hwnd: int | None = None
        self._plugin_window_hwnd: int | None = None
        self._plugin_window_parent_hwnd: int | None = None
        self._plugin_window_style: int | None = None
        self._plugin_window_exstyle: int | None = None

        if not self.root:
            self.warnings.append(
                "Carla source tree not found. Set CARLA_ROOT or place the Carla "
                "checkout inside the project."
            )
            return

        self._harvest_release_directories()

        try:
            self.library_path = self._locate_library(self.root)
        except FileNotFoundError as exc:
            fallback_library = self._locate_release_library()
            if fallback_library is None:
                self.warnings.append(str(exc))
                return
            self.library_path = fallback_library

        try:
            self._prepare_environment(self.library_path)
        except Exception as exc:
            self.warnings.append(f"Failed to prepare Carla environment: {exc}")
            return

        try:
            self.module = self._load_backend_module(self.root)
        except Exception as exc:
            self.warnings.append(f"Failed to import Carla backend: {exc}")
            return

        self._init_engine_constants()

        try:
            assert self.module is not None
            self.host = self.module.CarlaHostDLL(str(self.library_path), True)
        except Exception as exc:
            self.warnings.append(f"Failed to load libcarla: {exc}")
            self.host = None
            return

        try:
            self._register_engine_callback()
        except Exception as exc:
            self.warnings.append(f"Failed to register Carla engine callback: {exc}")

        # Initialize Qt support for UI
        if HAS_PYQT5:
            try:
                self._qt_manager = QtApplicationManager.get_instance()
                if not (self._qt_manager and self._qt_manager.is_available()):
                    self.warnings.append(
                        "Qt initialisation failed; plugin UIs may not open. "
                        "Ensure a display server is available and PyQt5 is installed "
                        "correctly."
                    )
            except ImportError as exc:
                self.warnings.append(
                    f"PyQt5 import failed: {exc}. Try reinstalling PyQt5 to enable "
                    "plugin editors."
                )
            except Exception as exc:
                self.warnings.append(
                    f"Qt initialisation error: {type(exc).__name__}: {exc}. "
                    "Plugin UIs may be unavailable."
                )
        else:
            self.warnings.append(
                "PyQt5 not installed. Install it with 'pip install PyQt5' to enable "
                "plugin editors."
            )

        self.available = True
        atexit.register(self.close)

    # ------------------------------------------------------------------
    # Discovery helpers
    def _discover_root(self) -> Path | None:
        """Find Carla installation directory."""

        def consider(path: Path | str | None) -> Path | None:
            if not path:
                return None
            candidate = Path(path).expanduser()
            try:
                resolved = candidate.resolve(strict=False)
            except OSError:
                resolved = candidate
            if not resolved.exists():
                return None

            # Record potential binary locations for later bridge discovery.
            self._binary_hints.add(resolved)
            maybe_carla_dir = resolved / "Carla"
            if maybe_carla_dir.exists():
                self._binary_hints.add(maybe_carla_dir)

            attempts = [resolved] + list(resolved.parents)[:2]
            for attempt in attempts:
                if attempt and (attempt / "source" / "frontend" / "carla_backend.py").exists():
                    return attempt
            return None

        # Check environment variables
        for env_path in (os.environ.get("CARLA_ROOT"), os.environ.get("CARLA_HOME")):
            root = consider(env_path)
            if root:
                return root

        # Check bundled locations
        bundled = [
            self.base_dir / "Carla-main" / "Carla",
            self.base_dir / "Carla-main",
            self.base_dir / "Carla",
        ]
        for candidate in bundled:
            root = consider(candidate)
            if root:
                return root

        # Search siblings (e.g. ../Carla/Carla-<ver>/Carla)
        # This is important when running from ambiance/ subdirectory
        sibling_root = self.base_dir.parent
        if sibling_root:
            # Try sibling directories first
            for candidate_name in ("Carla-main", "Carla", "Carla-main/Carla"):
                candidate = sibling_root / candidate_name
                root = consider(candidate)
                if root:
                    return root
            # Then try glob patterns
            for pattern in ("Carla*/Carla", "Carla*"):
                for path in sibling_root.glob(pattern):
                    root = consider(path)
                    if root:
                        return root

        # Windows system installs
        if sys.platform.startswith("win"):
            for prefix in (
                os.environ.get("PROGRAMFILES"),
                os.environ.get("PROGRAMFILES(X86)"),
                os.environ.get("ProgramW6432"),
            ):
                if not prefix:
                    continue
                root = consider(Path(prefix) / "Carla")
                if root:
                    return root

        return None

    def _locate_library(self, root: Path) -> Path:
        """Find libcarla_standalone2 library."""
        names = (
            "libcarla_standalone2.so",
            "libcarla_standalone2.dylib",
            "libcarla_standalone2.dll",
        )
        
        # Search in common build directories
        search_roots = [
            root / "bin",
            root / "build",
            root / "build" / "Release",
            root / "build" / "Debug",
            root / "Carla",  # Windows binary distribution
            root,
        ]
        
        for directory in search_roots:
            if not directory.exists():
                continue
            for name in names:
                candidate = directory / name
                if candidate.exists():
                    self._binary_hints.add(candidate.parent)
                    self._binary_hints.add(directory)
                    return candidate
        
        # Fallback: recursive search
        for name in names:
            matches = list(root.glob(f"**/{name}"))
            if matches:
                candidate = matches[0]
                self._binary_hints.add(candidate.parent)
                return candidate
        
        raise FileNotFoundError(
            f"libcarla_standalone2 library not found in {root}. "
            "Please build Carla first or download the binary distribution."
        )

    def _prepare_environment(self, library: Path) -> None:
        """Prepare environment for loading Carla library."""
        if os.name != "nt":
            return
        
        # On Windows, add DLL directories to PATH
        dll_paths = {library.parent}
        dll_paths.update(self._windows_dependency_dirs())
        
        paths: list[str] = []
        for directory in dll_paths:
            if not directory or not directory.exists():
                continue
            directory_str = str(directory)
            paths.append(directory_str)
            
            # Use os.add_dll_directory if available (Python 3.8+)
            add_dir = getattr(os, "add_dll_directory", None)
            if add_dir:
                try:
                    add_dir(directory_str)
                except (FileNotFoundError, OSError):
                    continue
        
        if paths:
            existing = os.environ.get("PATH", "")
            combined = os.pathsep.join(paths + [existing]) if existing else os.pathsep.join(paths)
            os.environ["PATH"] = combined

    def _windows_dependency_dirs(self) -> set[Path]:
        """Get Windows dependency directories."""
        if not self.root:
            return set()
        
        candidates = {
            self.root / "bin",
            self.root / "build",
            self.root / "build" / "Release",
            self.root / "build" / "Debug",
            self.root / "build" / "windows",
            self.root / "build" / "win64",
            self.root / "Carla",
            self.root / "resources",
            self.root / "resources" / "windows",
            self.root / "resources" / "windows" / "lib",
        }
        
        # Include parents of the library
        if self.library_path:
            for parent in self.library_path.parents[:3]:  # Up to 3 levels
                candidates.add(parent)

        for release_dir in self._release_binary_dirs:
            candidates.add(release_dir)
            candidates.add(release_dir.parent)
            candidates.add(release_dir / "resources")
            candidates.add(release_dir / "resources" / "windows")

        return {path for path in candidates if path.exists()}

    def _load_backend_module(self, root: Path) -> ModuleType:
        """Load Carla backend Python module."""
        frontend = root / "source" / "frontend"
        module_path = frontend / "carla_backend.py"
        
        if not module_path.exists():
            raise FileNotFoundError(
                f"carla_backend.py not found at {module_path}. "
                "Ensure Carla source is complete."
            )
        
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

    def _init_engine_constants(self) -> None:
        """Cache Carla engine callback and patchbay constant values."""

        def const(name: str, default: int) -> int:
            if self.module is None:
                return default
            value = getattr(self.module, name, default)
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        self._cb_patchbay_client_added = const("ENGINE_CALLBACK_PATCHBAY_CLIENT_ADDED", 20)
        self._cb_patchbay_client_removed = const("ENGINE_CALLBACK_PATCHBAY_CLIENT_REMOVED", 21)
        self._cb_patchbay_client_renamed = const("ENGINE_CALLBACK_PATCHBAY_CLIENT_RENAMED", 22)
        self._cb_patchbay_client_changed = const("ENGINE_CALLBACK_PATCHBAY_CLIENT_DATA_CHANGED", 23)
        self._cb_patchbay_port_added = const("ENGINE_CALLBACK_PATCHBAY_PORT_ADDED", 24)
        self._cb_patchbay_port_removed = const("ENGINE_CALLBACK_PATCHBAY_PORT_REMOVED", 25)
        self._cb_patchbay_port_changed = const("ENGINE_CALLBACK_PATCHBAY_PORT_CHANGED", 26)
        self._cb_patchbay_connection_added = const("ENGINE_CALLBACK_PATCHBAY_CONNECTION_ADDED", 27)
        self._cb_patchbay_connection_removed = const("ENGINE_CALLBACK_PATCHBAY_CONNECTION_REMOVED", 28)
        self._patch_port_is_input = const("PATCHBAY_PORT_IS_INPUT", 0x01)
        self._patch_port_type_audio = const("PATCHBAY_PORT_TYPE_AUDIO", 0x02)
        self._patch_port_type_midi = const("PATCHBAY_PORT_TYPE_MIDI", 0x08)

    def _register_engine_callback(self) -> None:
        """Subscribe to engine callbacks so we can keep track of patchbay state."""
        if self.host is None or self._engine_callback_registered:
            return

        def _engine_callback(  # type: ignore[override]
            _handle,
            opcode,
            plugin_id,
            value1,
            value2,
            value3,
            valuef,
            value_str,
        ) -> None:
            try:
                text = value_str.decode("utf-8") if value_str else ""
            except Exception:
                text = ""
            try:
                self._handle_engine_callback(
                    int(opcode),
                    int(plugin_id),
                    int(value1),
                    int(value2),
                    int(value3),
                    float(valuef),
                    text,
                )
            except Exception as exc:
                # Avoid raising inside the callback thread; record the issue instead.
                self.warnings.append(f"Engine callback error: {exc}")

        self.host.set_engine_callback(_engine_callback)
        self._engine_callback_registered = True

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
        except Exception as exc:
            self.warnings.append(f"Failed to apply {option_name}: {exc}")

    def _candidate_binary_dirs(self) -> list[Path]:
        """Return candidate directories that hold Carla bridge binaries."""
        candidates: list[Path] = []
        
        # Add all binary hints first
        for hint in list(self._binary_hints):
            try:
                resolved = hint.resolve(strict=False)
            except OSError:
                resolved = hint
            if resolved.exists() and resolved not in candidates:
                candidates.append(resolved)
        
        if self.root:
            # Check common directories in Carla tree
            for relative in ("Carla", "bin", "build", "build/Release", "build/Debug", ""):
                base_path = self.root / relative if relative else self.root
                try:
                    path = base_path.resolve(strict=False)
                except OSError:
                    continue
                if path.exists() and path not in candidates:
                    candidates.append(path)
            
            # Include bundled binary releases like Carla-*-win*/Carla
            for pattern in ("Carla-*-win*/Carla", "Carla-*/Carla", "Carla"):
                for extra_bundle in self.root.parent.glob(pattern):
                    try:
                        resolved = extra_bundle.resolve(strict=False)
                    except OSError:
                        resolved = extra_bundle
                    if resolved.exists() and resolved not in candidates:
                        candidates.append(resolved)
        
        if self.library_path:
            try:
                parent = self.library_path.parent.resolve(strict=False)
            except OSError:
                parent = self.library_path.parent
            if parent.exists() and parent not in candidates:
                candidates.append(parent)
            
            # Search parent directories more thoroughly
            for ancestor in list(parent.parents)[:5]:
                try:
                    resolved = ancestor.resolve(strict=False)
                except OSError:
                    resolved = ancestor
                if resolved.exists() and resolved not in candidates:
                    candidates.append(resolved)
                
                # Also check for Carla subdirectories
                for subdir in ("Carla", "bin", "build"):
                    sub_path = ancestor / subdir
                    if sub_path.exists() and sub_path not in candidates:
                        candidates.append(sub_path)

        for release_dir in sorted(self._release_binary_dirs):
            try:
                resolved = release_dir.resolve(strict=False)
            except OSError:
                resolved = release_dir
            if resolved.exists() and resolved not in candidates:
                candidates.append(resolved)
            parent = resolved.parent
            if parent.exists() and parent not in candidates:
                candidates.append(parent)

        return candidates

    def _candidate_resource_dirs(self) -> list[Path]:
        """Return candidate directories that hold Carla resource files."""
        candidates: list[Path] = []
        bases = [self.root, self.library_path.parent if self.library_path else None]
        for base in bases:
            if not base:
                continue
            for relative in ("resources", "resources/windows", "../resources"):
                try:
                    path = (base / relative).resolve(strict=False)
                except OSError:
                    continue
                if path.exists() and path not in candidates:
                    candidates.append(path)
        for release_dir in sorted(self._release_binary_dirs):
            for relative in ("resources", "resources/windows"):
                try:
                    path = (release_dir / relative).resolve(strict=False)
                except OSError:
                    continue
                if path.exists() and path not in candidates:
                    candidates.append(path)
        return candidates

    def _harvest_release_directories(self) -> None:
        """Record bundled Carla binary releases for bridge discovery."""

        search_roots: set[Path] = {self.base_dir}
        parent = self.base_dir.parent
        if parent != self.base_dir:
            search_roots.add(parent)
        if self.root:
            search_roots.add(self.root)
            root_parent = self.root.parent
            if root_parent != self.root:
                search_roots.add(root_parent)

        patterns = ("Carla*/Carla", "Carla-*/Carla")
        for root in list(search_roots):
            if not root:
                continue
            try:
                glob = root.glob
            except AttributeError:
                continue
            try:
                for pattern in patterns:
                    for directory in glob(pattern):
                        try:
                            resolved = directory.resolve(strict=False)
                        except OSError:
                            resolved = directory
                        if not resolved.exists():
                            continue
                        self._release_binary_dirs.add(resolved)
                        self._binary_hints.add(resolved)
                        parent_dir = resolved.parent
                        if parent_dir.exists():
                            self._binary_hints.add(parent_dir)
            except OSError:
                continue

        # Some packaged builds place bridge executables in a nested bin directory.
        for release_dir in list(self._release_binary_dirs):
            for bridge_name in ("carla-bridge-win32.exe", "carla-bridge-win64.exe", "carla-bridge-native.exe"):
                if (release_dir / bridge_name).exists():
                    continue
                candidate = release_dir / "bin" / bridge_name
                if candidate.exists():
                    container = candidate.parent
                    self._binary_hints.add(container)
                    self._release_binary_dirs.add(container)

    def _locate_release_library(self) -> Path | None:
        """Search bundled Carla binary releases for the standalone library."""

        for release_dir in sorted(self._release_binary_dirs):
            try:
                return self._locate_library(release_dir)
            except FileNotFoundError:
                continue
        return None

    def _find_pe_image(self, path: Path) -> Path | None:
        """Locate a Windows PE binary for the given plugin path."""
        if path.is_file():
            return path
        for pattern in ("*.vst3", "*.dll", "*.exe"):
            try:
                candidate = next(path.rglob(pattern), None)
            except (OSError, RuntimeError):
                candidate = None
            if candidate:
                return candidate
        return None

    def _detect_pe_architecture(self, image: Path | None) -> int | None:
        """Return 32 or 64 for Windows PE images, or None if unknown."""
        if image is None or not image.exists():
            return None
        try:
            with image.open("rb") as handle:
                header = handle.read(64)
                if len(header) < 64 or header[:2] != b"MZ":
                    return None
                handle.seek(60)
                offset = struct.unpack("<I", handle.read(4))[0]
                handle.seek(offset + 4)
                machine = struct.unpack("<H", handle.read(2))[0]
        except (OSError, struct.error):
            return None
        if machine == 0x8664:
            return 64
        if machine == 0x014C:
            return 32
        return None

    def _binary_type_for(
        self,
        path: Path,
        plugin_type: int,
        *,
        image_path: Path | None = None,
        arch_bits: int | None = None,
    ) -> int:
        """Determine the Carla binary type constant for the given plugin."""
        if self.module is None:
            return 0
        binary_type = getattr(self.module, "BINARY_NATIVE", 0)
        if not sys.platform.startswith("win"):
            return binary_type
        image = image_path or self._find_pe_image(path)
        bits = arch_bits if arch_bits is not None else self._detect_pe_architecture(image)
        if bits == 32:
            return getattr(self.module, "BINARY_WIN32", binary_type)
        if bits == 64:
            return getattr(self.module, "BINARY_WIN64", binary_type)
        return binary_type

    def configure_audio(
        self,
        *,
        forced_driver: str | None = None,
        preferred_drivers: Sequence[str] | None = None,
        sample_rate: int | None = None,
        buffer_size: int | None = None,
    ) -> None:
        with self._lock:
            update_preferences = False
            if forced_driver is not None:
                self._forced_driver = self._clean_driver_name(forced_driver)
                update_preferences = True
            if preferred_drivers is not None:
                self._user_preferred_drivers = self._normalise_driver_names(preferred_drivers)
                update_preferences = True
            if update_preferences or not getattr(self, '_preferred_drivers', None):
                self._preferred_drivers = self._compose_driver_order()

            if sample_rate is not None:
                value = int(sample_rate)
                self._engine_sample_rate = value if value > 0 else None
            if buffer_size is not None:
                value = int(buffer_size)
                self._engine_buffer_size = value if value > 0 else None

            if self._engine_running and self.host is not None:
                self._stop_idle_thread()
                try:
                    self.host.engine_close()
                except Exception as exc:
                    self.warnings.append(f"Failed to reconfigure Carla engine: {exc}")
                self._engine_running = False
                self._driver_name = None

            self._engine_configured = False

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
        except Exception as exc:
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

        # Add included_plugins folder (check both base_dir and parent for sibling folder)
        included_plugins = self.base_dir / "included_plugins"
        included_plugins_parent = self.base_dir.parent / "included_plugins"

        add(vst2, cache_root, data_root, included_plugins, included_plugins_parent)
        add(vst3, cache_root, data_root, included_plugins, included_plugins_parent)

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

        patchbay_mode = self._get_constant("ENGINE_PROCESS_MODE_PATCHBAY")
        if patchbay_mode is None:
            patchbay_mode = self._get_constant("ENGINE_PROCESS_MODE_CONTINUOUS_RACK")
        if patchbay_mode is None:
            patchbay_mode = self._get_constant("ENGINE_PROCESS_MODE_MULTIPLE_CLIENTS")
        if patchbay_mode is not None:
            self._set_engine_option("ENGINE_OPTION_PROCESS_MODE", patchbay_mode)

        for option_name in (
            "ENGINE_OPTION_PREFER_PLUGIN_BRIDGES",
            "ENGINE_OPTION_PREFER_UI_BRIDGES",
            "ENGINE_OPTION_PREVENT_BAD_BEHAVIOUR",
            "ENGINE_OPTION_FORCE_STEREO",
        ):
            option = self._get_constant(option_name)
            if option is not None:
                self._set_engine_option(option_name, 1)

        binary_paths = [path for path in self._candidate_binary_dirs() if path.exists()]
        binary_dirs = [str(path) for path in binary_paths]
        if binary_dirs:
            payload = os.pathsep.join(dict.fromkeys(binary_dirs))
            self._set_engine_option("ENGINE_OPTION_PATH_BINARIES", 0, payload)

            # Log bridge executable search for debugging
            bridge_found = False
            has_win32_bridge = False
            for path in binary_paths:
                for bridge_name in ("carla-bridge-win32.exe", "carla-bridge-win64.exe",
                                   "carla-bridge-native.exe", "carla-bridge-native"):
                    if (path / bridge_name).exists():
                        bridge_found = True
                        if bridge_name == "carla-bridge-win32.exe":
                            has_win32_bridge = True
                        break

            if not bridge_found and sys.platform.startswith("win"):
                self.warnings.append(
                    f"Bridge executables not found in {len(binary_dirs)} directories. "
                    "32-bit plugin loading may fail. Download Carla binary release or build from source."
                )
            elif sys.platform.startswith("win") and not has_win32_bridge:
                self.warnings.append(
                    "carla-bridge-win32.exe not found alongside the Carla installation. "
                    "Install the 32-bit Carla runtime or copy the Win32 bridge into the Carla folder to enable "
                    "32-bit VST2 plugins."
                )

        resource_dirs = [str(path) for path in self._candidate_resource_dirs()]
        if resource_dirs:
            payload = os.pathsep.join(dict.fromkeys(resource_dirs))
            self._set_engine_option("ENGINE_OPTION_PATH_RESOURCES", 0, payload)

        for plugin_type, directories in self._default_plugin_directories().items():
            for directory in directories:
                self._register_plugin_path(plugin_type, directory)

    # ------------------------------------------------------------------
    # Engine lifecycle
    def _wait_for_engine_idle(self, timeout: float = 1.0) -> None:
        """Wait for engine to process pending actions."""
        if not self.host or not self._engine_running:
            return
        
        import time
        start = time.time()
        idle_count = 0
        while time.time() - start < timeout:
            try:
                self.host.engine_idle()
                time.sleep(0.016)  # ~60Hz
                idle_count += 1
                # Ensure we've processed enough idle cycles
                if idle_count >= 10:
                    break
            except:
                break
    
    def _ensure_engine(self) -> None:
        if not self.available or self.host is None:
            raise CarlaHostError("Carla backend is not available")
        if self._engine_running:
            return
        if not self._engine_configured:
            self._configure_engine_defaults()
            self._engine_configured = True
        available = self._available_drivers()
        if not available:
            raise CarlaHostError("No usable Carla audio drivers reported by Carla")

        attempt_order: list[str] = []
        if self._forced_driver:
            if self._forced_driver not in available:
                raise CarlaHostError(
                    f"Requested audio driver '{self._forced_driver}' not available. "
                    f"Detected drivers: {', '.join(available)}"
                )
            attempt_order.append(self._forced_driver)

        for preferred in self._preferred_drivers:
            if preferred in available and preferred not in attempt_order:
                attempt_order.append(preferred)

        for name in available:
            if name not in attempt_order:
                attempt_order.append(name)

        errors: list[str] = []
        driver: str | None = None
        for candidate in attempt_order:
            try:
                if self.host.engine_init(candidate, self._client_name):
                    driver = candidate
                    break
                message = self.host.get_last_error() if hasattr(self.host, "get_last_error") else "unknown error"
                errors.append(f"{candidate}: {message}")
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")

        if driver is None:
            detail = ', '.join(errors) if errors else 'no drivers tried'
            raise CarlaHostError(f"Failed to initialise Carla engine. Attempts: {detail}")

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
                except Exception as exc:
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

    # ------------------------------------------------------------------
    # Patchbay helpers
    def _handle_engine_callback(
        self,
        opcode: int,
        client_id: int,
        value1: int,
        value2: int,
        value3: int,
        valuef: float,
        value_str: str,
    ) -> None:
        if opcode == self._cb_patchbay_client_added:
            self._handle_patchbay_client_added(client_id, value1, value2, value_str)
        elif opcode == self._cb_patchbay_client_removed:
            self._handle_patchbay_client_removed(client_id)
        elif opcode == self._cb_patchbay_client_renamed:
            self._handle_patchbay_client_renamed(client_id, value_str)
        elif opcode == self._cb_patchbay_client_changed:
            self._handle_patchbay_client_changed(client_id, value1, value2)
        elif opcode == self._cb_patchbay_port_added:
            self._handle_patchbay_port_added(client_id, value1, value2, value3, value_str)
        elif opcode == self._cb_patchbay_port_removed:
            self._handle_patchbay_port_removed(client_id, value1)
        elif opcode == self._cb_patchbay_port_changed:
            self._handle_patchbay_port_added(client_id, value1, value2, value3, value_str)
        elif opcode == self._cb_patchbay_connection_added:
            self._handle_patchbay_connection_added(client_id, value_str)
        elif opcode == self._cb_patchbay_connection_removed:
            self._handle_patchbay_connection_removed(client_id)

    def _handle_patchbay_client_added(self, client_id: int, icon: int, plugin_id: int, name: str) -> None:
        with self._patch_lock:
            self._patch_clients[client_id] = {
                "name": name or "",
                "icon": icon,
                "plugin_id": plugin_id,
            }
            if plugin_id >= 0:
                self._plugin_patch_groups[plugin_id] = client_id
            self._patch_update_event.set()

    def _handle_patchbay_client_removed(self, client_id: int) -> None:
        with self._patch_lock:
            removed = self._patch_clients.pop(client_id, None)
            self._patch_ports.pop(client_id, None)
            for plugin, group in list(self._plugin_patch_groups.items()):
                if group == client_id:
                    self._plugin_patch_groups.pop(plugin, None)
            for connection_id, key in list(self._patch_connection_ids.items()):
                if key[0] == client_id or key[2] == client_id:
                    self._patch_connection_ids.pop(connection_id, None)
                    self._patch_connections.discard(key)
            if removed is not None:
                self._patch_update_event.set()

    def _handle_patchbay_client_renamed(self, client_id: int, name: str) -> None:
        with self._patch_lock:
            client = self._patch_clients.get(client_id)
            if client is None:
                client = {"name": name or "", "icon": 0, "plugin_id": -1}
                self._patch_clients[client_id] = client
            else:
                client["name"] = name or client.get("name", "")
            self._patch_update_event.set()

    def _handle_patchbay_client_changed(self, client_id: int, icon: int, plugin_id: int) -> None:
        with self._patch_lock:
            client = self._patch_clients.get(client_id)
            if client is None:
                client = {"name": "", "icon": icon, "plugin_id": plugin_id}
                self._patch_clients[client_id] = client
            else:
                client["icon"] = icon
                client["plugin_id"] = plugin_id
            if plugin_id >= 0:
                self._plugin_patch_groups[plugin_id] = client_id
            else:
                for existing, group in list(self._plugin_patch_groups.items()):
                    if group == client_id:
                        self._plugin_patch_groups.pop(existing, None)
            self._patch_update_event.set()

    def _handle_patchbay_port_added(
        self,
        client_id: int,
        port_id: int,
        hints: int,
        group_id: int,
        name: str,
    ) -> None:
        info = {
            "name": name or "",
            "hints": hints,
            "group_id": group_id,
            "is_input": bool(hints & self._patch_port_is_input),
            "is_audio": bool(hints & self._patch_port_type_audio),
            "is_midi": bool(hints & self._patch_port_type_midi),
        }
        with self._patch_lock:
            self._patch_ports.setdefault(client_id, {})[port_id] = info
            self._patch_update_event.set()

    def _handle_patchbay_port_removed(self, client_id: int, port_id: int) -> None:
        with self._patch_lock:
            ports = self._patch_ports.get(client_id)
            if not ports:
                return
            if port_id in ports:
                ports.pop(port_id, None)
                if not ports:
                    self._patch_ports.pop(client_id, None)
                for connection_id, key in list(self._patch_connection_ids.items()):
                    if key[0] == client_id and key[1] == port_id or key[2] == client_id and key[3] == port_id:
                        self._patch_connection_ids.pop(connection_id, None)
                        self._patch_connections.discard(key)
                self._patch_update_event.set()

    def _handle_patchbay_connection_added(self, connection_id: int, payload: str) -> None:
        try:
            parts = [int(piece) for piece in payload.split(":")]
        except ValueError:
            return
        if len(parts) != 4:
            return
        key = tuple(parts)  # type: ignore[var-annotated]
        with self._patch_lock:
            self._patch_connections.add(key)  # type: ignore[arg-type]
            self._patch_connection_ids[connection_id] = key  # type: ignore[assignment]
            self._patch_update_event.set()

    def _handle_patchbay_connection_removed(self, connection_id: int) -> None:
        with self._patch_lock:
            key = self._patch_connection_ids.pop(connection_id, None)
            if key:
                self._patch_connections.discard(key)
                self._patch_update_event.set()

    def _refresh_patchbay_state(self, timeout: float = 0.5) -> None:
        if self.host is None:
            return
        with self._patch_lock:
            self._patch_clients.clear()
            self._patch_ports.clear()
            self._patch_connections.clear()
            self._patch_connection_ids.clear()
            self._plugin_patch_groups.clear()
        self._patch_update_event.clear()
        try:
            self.host.patchbay_refresh(False)
        except Exception as exc:
            self.warnings.append(f"Failed to refresh Carla patchbay: {exc}")
            return
        self._wait_for_engine_idle(timeout)

    def _midi_source_sort_key(
        self,
        client: dict[str, Any],
        port: dict[str, Any],
        group_id: int,
    ) -> tuple[int, int]:
        score = 0
        name = f"{client.get('name', '')} {port.get('name', '')}".lower()
        plugin_id = int(client.get("plugin_id", -1))
        if plugin_id < 0:
            score += 40
        if "carla" in name or "rack" in name or "host" in name:
            score += 20
        if "midi" in name:
            score += 10
        if "out" in name or "output" in name:
            score += 5
        if "keyboard" in name:
            score += 2
        if plugin_id >= 0:
            score -= 10
        return (score, -group_id)

    def _select_midi_sources(self) -> list[tuple[int, int]]:
        candidates: list[tuple[int, int, dict[str, Any], dict[str, Any]]] = []
        with self._patch_lock:
            for group_id, ports in self._patch_ports.items():
                client = self._patch_clients.get(group_id, {})
                for port_id, port in ports.items():
                    if port.get("is_input"):
                        continue
                    if not port.get("is_midi"):
                        continue
                    candidates.append((group_id, port_id, client, port))
        candidates.sort(
            key=lambda entry: self._midi_source_sort_key(entry[2], entry[3], entry[0]),
            reverse=True,
        )
        return [(group_id, port_id) for group_id, port_id, _, _ in candidates]

    def _audio_target_sort_key(
        self,
        client: dict[str, Any],
        port: dict[str, Any],
        group_id: int,
    ) -> tuple[int, int]:
        score = 0
        name = f"{client.get('name', '')} {port.get('name', '')}".lower()
        if "audio" in name or "speaker" in name:
            score += 30
        if "playback" in name or "output" in name or "out" in name:
            score += 20
        if "carla" in name or "master" in name:
            score += 10
        return (score, -group_id)

    def _select_audio_targets(self) -> list[tuple[int, int]]:
        candidates: list[tuple[int, int, dict[str, Any], dict[str, Any]]] = []
        with self._patch_lock:
            for group_id, ports in self._patch_ports.items():
                client = self._patch_clients.get(group_id, {})
                if int(client.get("plugin_id", -1)) >= 0:
                    continue
                for port_id, port in ports.items():
                    if not port.get("is_input"):
                        continue
                    if not port.get("is_audio"):
                        continue
                    candidates.append((group_id, port_id, client, port))
        candidates.sort(
            key=lambda entry: self._audio_target_sort_key(entry[2], entry[3], entry[0]),
            reverse=True,
        )
        return [(group_id, port_id) for group_id, port_id, _, _ in candidates]

    def _ensure_midi_routing(self) -> None:
        if self._midi_routed:
            return
        if self.host is None or self._plugin_id is None or not self._supports_midi:
            return

        plugin_group: int | None = None
        midi_inputs: list[tuple[int, dict[str, Any]]] = []
        for attempt in range(3):
            with self._patch_lock:
                plugin_group = self._plugin_patch_groups.get(self._plugin_id)
                if plugin_group is not None:
                    ports = self._patch_ports.get(plugin_group, {})
                    midi_inputs = [
                        (pid, pdata)
                        for pid, pdata in ports.items()
                        if pdata.get("is_input") and pdata.get("is_midi")
                    ]
                    if any(conn[2] == plugin_group for conn in self._patch_connections):
                        self._midi_routed = True
                        return
            if plugin_group is not None and midi_inputs:
                break
            self._refresh_patchbay_state()
        else:
            return

        if plugin_group is None or not midi_inputs:
            return

        sources = self._select_midi_sources()
        if not sources:
            return

        success = False
        for source_group, source_port in sources:
            if source_group == plugin_group:
                continue
            for port_id, _ in midi_inputs:
                with self._patch_lock:
                    if (source_group, source_port, plugin_group, port_id) in self._patch_connections:
                        continue
                try:
                    if self.host.patchbay_connect(False, source_group, source_port, plugin_group, port_id):
                        success = True
                except Exception as exc:
                    self.warnings.append(
                        f"Failed to connect MIDI port {source_group}:{source_port} -> {plugin_group}:{port_id}: {exc}"
                    )
        if success:
            # Allow callbacks to populate the cached graph and mark routing as ready.
            self._wait_for_engine_idle(0.1)
            self._midi_routed = True
            self._midi_warning_emitted = False
        elif not self._midi_warning_emitted:
            self.warnings.append(
                "Unable to find an internal MIDI source to connect to the hosted plugin automatically."
            )
            self._midi_warning_emitted = True

    def _ensure_audio_routing(self) -> None:
        import logging
        if self._audio_routed:
            logging.info("🔊 Audio already routed")
            return
        if self.host is None or self._plugin_id is None:
            logging.warning("⚠️ Cannot route audio: no plugin loaded")
            return

        logging.info("🔌 Setting up audio routing...")
        plugin_group: int | None = None
        audio_outputs: list[tuple[int, dict[str, Any]]] = []
        for attempt in range(3):
            with self._patch_lock:
                plugin_group = self._plugin_patch_groups.get(self._plugin_id)
                if plugin_group is not None:
                    ports = self._patch_ports.get(plugin_group, {})
                    audio_outputs = [
                        (pid, pdata)
                        for pid, pdata in ports.items()
                        if not pdata.get("is_input") and pdata.get("is_audio")
                    ]
                    if audio_outputs and any(
                        conn[0] == plugin_group
                        and self._patch_ports.get(conn[2], {}).get(conn[3], {}).get("is_audio")
                        for conn in self._patch_connections
                    ):
                        self._audio_routed = True
                        logging.info(f"✓ Audio already connected (found {len(audio_outputs)} outputs)")
                        return
            if plugin_group is not None and audio_outputs:
                break
            self._refresh_patchbay_state()
        else:
            return

        if plugin_group is None or not audio_outputs:
            return

        targets = self._select_audio_targets()
        if not targets:
            if not self._audio_warning_emitted:
                self.warnings.append("No audio output target found for Carla patchbay.")
                self._audio_warning_emitted = True
            return

        audio_outputs.sort(key=lambda item: item[0])
        connections = min(len(audio_outputs), len(targets), 2)
        logging.info(f"🔌 Connecting {connections} audio channels: plugin_group={plugin_group}")
        success = False
        for index in range(connections):
            source_port = audio_outputs[index][0]
            target_group, target_port = targets[index]
            with self._patch_lock:
                if (plugin_group, source_port, target_group, target_port) in self._patch_connections:
                    logging.info(f"  ✓ Channel {index}: already connected")
                    continue
            try:
                if self.host.patchbay_connect(False, plugin_group, source_port, target_group, target_port):
                    logging.info(f"  ✓ Channel {index}: connected port {source_port} → {target_group}:{target_port}")
                    success = True
                else:
                    logging.warning(f"  ✗ Channel {index}: connection failed (returned False)")
            except Exception as exc:
                logging.error(f"  ✗ Channel {index}: connection error: {exc}")
                self.warnings.append(
                    f"Failed to connect audio port {source_port} -> {target_group}:{target_port}: {exc}"
                )
        if success:
            self._wait_for_engine_idle(0.1)
            self._audio_routed = True
            self._audio_warning_emitted = False
            logging.info("✓ Audio routing complete")
        elif not self._audio_warning_emitted:
            logging.warning("⚠️ Audio routing failed - no audio will be heard")
            self.warnings.append("Unable to connect plugin audio outputs; audio may be muted.")
            self._audio_warning_emitted = True

    def _select_driver(self) -> str | None:
        assert self.host is not None
        try:
            count = int(self.host.get_engine_driver_count())
        except Exception as exc:
            self.warnings.append(f"Unable to enumerate Carla drivers: {exc}")
            return None

        names: list[str] = []
        seen: set[str] = set()
        for index in range(count):
            try:
                name = self.host.get_engine_driver_name(index)
            except Exception:
                continue
            if not isinstance(name, str):
                continue
            lowered = name.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            names.append(name)

        if not names:
            return None

        if self._forced_driver:
            forced = self._forced_driver.lower()
            for candidate in names:
                if candidate.lower() == forced:
                    return candidate
            raise CarlaHostError(
                f"Requested Carla audio driver '{self._forced_driver}' not available. "
                f"Detected drivers: {', '.join(names)}"
            )

        for preferred in self._preferred_drivers:
            preferred_lower = preferred.lower()
            for candidate in names:
                if candidate.lower() == preferred_lower:
                    return candidate

        return names[0]

    def _available_drivers(self) -> list[str]:
        if self.host is None:
            return []
        names: list[str] = []
        seen: set[str] = set()
        try:
            count = int(self.host.get_engine_driver_count())
        except Exception as exc:
            self.warnings.append(f"Unable to enumerate Carla drivers: {exc}")
            return names
        for index in range(count):
            try:
                name = self.host.get_engine_driver_name(index)
            except Exception:
                continue
            if not isinstance(name, str):
                continue
            lowered = name.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            names.append(name)
        return names

    def _fallback_driver(self, failed: str) -> str | None:
        for candidate in self._preferred_drivers:
            if candidate.lower() == failed.lower():
                continue
            if self.host and getattr(self.host, "is_engine_driver_available", None):
                try:
                    if self.host.is_engine_driver_available(candidate):
                        return candidate
                except Exception:
                    continue
            else:
                return candidate
        return None

    # ------------------------------------------------------------------
    # Public API
    def can_handle_path(self, plugin_path: Path) -> bool:
        suffix = plugin_path.suffix.lower()
        return suffix in {".vst3", ".vst", ".dll"}

    def status(self, include_parameters: bool = True) -> dict[str, Any]:
        with self._lock:
            qt_available = bool(
                HAS_PYQT5 and self._qt_manager and self._qt_manager.is_available()
            )
            payload: dict[str, Any] = {
                "available": self.available,
                "toolkit_path": str(self.root) if self.root else None,
                "engine_path": str(self.library_path) if self.library_path else None,
                "warnings": list(self.warnings),
                "ui_visible": self._ui_visible,
                "qt_available": qt_available,
                "engine": {
                    "running": self._engine_running,
                    "driver": self._driver_name,
                    "forced_driver": self._forced_driver,
                    "preferred_drivers": list(self._preferred_drivers),
                    "sample_rate": self._engine_sample_rate,
                    "buffer_size": self._engine_buffer_size,
                },
            }
            if self._driver_name:
                payload["driver"] = self._driver_name
            payload["capabilities"] = {
                "editor": bool(
                    self._plugin_id is not None
                    and self._plugin_supports_custom_ui()
                    and qt_available
                ),
                "instrument": bool(
                    self._plugin_id is not None and self._plugin_is_instrument()
                ),
                "midi": bool(self._supports_midi),
                "midi_routed": bool(self._midi_routed),
                "audio_routed": bool(self._audio_routed),
            }
            if self._plugin_id is None:
                payload["plugin"] = None
                payload["parameters"] = []
            else:
                payload["plugin"] = self._plugin_payload(include_parameters=include_parameters)
                payload["parameters"] = [
                    param.to_status_entry() for param in self._parameters
                ] if include_parameters else []
            if not include_parameters and payload.get("plugin"):
                payload["plugin"]["metadata"]["parameters"] = []
                payload["plugin"]["parameters"] = []
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

            self._cancel_all_note_timers()

            # Critical: Ensure engine is completely idle before operations
            self._wait_for_engine_idle(timeout=1.5)

            # Clear existing plugins with synchronization
            if self._plugin_id is not None:
                try:
                    self.host.remove_plugin(self._plugin_id)
                    self._wait_for_engine_idle(timeout=1.0)
                except Exception:
                    pass
                self._plugin_id = None

            try:
                self.host.remove_all_plugins()
                self._wait_for_engine_idle(timeout=1.0)
            except Exception as exc:
                self.warnings.append(f"Failed to clear existing plugins before load: {exc}")
            plugin_type = self._plugin_type_for(path)
            if plugin_type is None:
                raise CarlaHostError(f"Unsupported plugin type for {path}")
            self._register_plugin_path(plugin_type, path.parent)
            if path.suffix.lower() == ".vst3" and path.is_dir():
                self._register_plugin_path(plugin_type, path)
            image_path = self._find_pe_image(path) if sys.platform.startswith("win") else None
            arch_bits = self._detect_pe_architecture(image_path) if sys.platform.startswith("win") else None
            binary_type = (
                self._binary_type_for(path, plugin_type, image_path=image_path, arch_bits=arch_bits)
                if self.module
                else 0
            )
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
            
            # Wait for plugin to fully initialize with longer timeout
            self._wait_for_engine_idle(timeout=2.0)
            
            if not added:
                message = self.host.get_last_error() if hasattr(self.host, "get_last_error") else "unknown"
                if isinstance(message, str) and "cannot handle this binary" in message.lower():
                    hints: list[str] = []
                    if arch_bits:
                        hints.append(f"Detected plugin architecture: {arch_bits}-bit")
                    host_bits = struct.calcsize("P") * 8
                    hints.append(f"Host process architecture: {host_bits}-bit")
                    bridge_dirs = [str(dir_path) for dir_path in self._candidate_binary_dirs()]
                    if bridge_dirs:
                        hints.append(f"Bridge search path: {os.pathsep.join(bridge_dirs)}")
                    hints.append("Install the matching architecture of the plugin or ensure Carla bridge executables are available.")
                    message = f"{message} ({'; '.join(hints)})"
                raise CarlaHostError(f"Failed to load plugin: {message}")
            self._plugin_id = 0
            self._plugin_path = path
            self._parameters = self._collect_parameters()
            self._ui_visible = False
            try:
                self.host.set_active(self._plugin_id, True)
                # Give plugin time to fully activate
                self._wait_for_engine_idle(timeout=0.5)
            except Exception as exc:
                self.warnings.append(f"Failed to activate plugin: {exc}")
            self._supports_midi = self._plugin_accepts_midi()
            self._midi_routed = False
            self._midi_warning_emitted = False
            self._audio_routed = False
            self._audio_warning_emitted = False
            self._cancel_all_note_timers()
            self._refresh_patchbay_state()
            self._ensure_audio_routing()
            if self._supports_midi:
                self._ensure_midi_routing()
            # Final engine idle to ensure all routing is complete
            try:
                self.host.engine_idle()
            except Exception:
                pass
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
                removed = False
                try:
                    result = self.host.remove_all_plugins()
                    removed = bool(result) if result is not None else True
                except Exception as exc:
                    self.warnings.append(f"Failed to remove all plugins: {exc}")
                if not removed:
                    try:
                        self.host.remove_plugin(self._plugin_id)
                        removed = True
                    except Exception as exc:
                        self.warnings.append(f"Failed to remove plugin {self._plugin_id}: {exc}")
                if not removed and hasattr(self.host, "get_last_error"):
                    last_error = self.host.get_last_error() or ""
                    if last_error:
                        self.warnings.append(f"Carla reported during unload: {last_error}")
                try:
                    self.host.engine_idle()
                except Exception:
                    pass
            self._plugin_id = None
            self._plugin_path = None
            self._parameters = []
            self._ui_visible = False
            self._supports_midi = False
            self._midi_routed = False
            self._midi_warning_emitted = False
            self._audio_routed = False
            self._audio_warning_emitted = False
            self._cancel_all_note_timers()

    def close(self) -> None:
        with self._lock:
            if not self.available or self.host is None:
                return
            self.unload()
            self._stop_idle_thread()
            if self._engine_running:
                try:
                    self.host.engine_close()
                except Exception as exc:
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

    def _cancel_note_timer(self, note: int) -> None:
        timer = self._note_timers.pop(note, None)
        if timer is not None:
            timer.cancel()

    def _cancel_all_note_timers(self) -> None:
        for note, timer in list(self._note_timers.items()):
            timer.cancel()
            self._note_timers.pop(note, None)

    def _send_midi_note(self, note: int, velocity: float) -> None:
        import logging
        with self._lock:
            if self.host is None or self._plugin_id is None:
                raise CarlaHostError("No plugin hosted")
            if not self._supports_midi:
                raise CarlaHostError("Hosted plugin does not accept MIDI input")
            if not self._midi_routed:
                logging.info("🎹 MIDI not routed, calling _ensure_midi_routing()")
                self._ensure_midi_routing()
            if not self._audio_routed:
                logging.warning("⚠️ Audio not routed! Calling _ensure_audio_routing()")
                self._ensure_audio_routing()

            note = int(note)
            vel = max(0.0, min(1.0, float(velocity)))
            value = int(round(vel * 127.0))
            value = max(0, min(127, value))

            logging.info(f"🎹 Sending MIDI: note={note} (C4=60), velocity={value}, audio_routed={self._audio_routed}, midi_routed={self._midi_routed}")
            self.host.send_midi_note(self._plugin_id, 0, note, value)
            logging.info(f"✓ MIDI sent successfully for note {note}")

            # Give engine time to process the MIDI action to avoid assertion failures
            # "pData->nextAction.opcode == kEnginePostActionNull"
            import time
            time.sleep(0.002)  # 2ms delay
            try:
                self.host.engine_idle()
            except Exception:
                pass  # Ignore idle errors

    def note_on(self, note: int, velocity: float = 0.8) -> None:
        with self._lock:
            self._cancel_note_timer(note)
        self._send_midi_note(note, velocity)

    def note_off(self, note: int) -> None:
        with self._lock:
            self._cancel_note_timer(note)
        try:
            self._send_midi_note(note, 0.0)
        except CarlaHostError:
            pass

    def play_note(self, note: int, velocity: float = 0.8, duration: float = 1.0) -> None:
        self.note_on(note, velocity)
        if duration <= 0:
            return
        timer = threading.Timer(duration, lambda: self.note_off(note))
        timer.daemon = True
        with self._lock:
            self._cancel_note_timer(note)
            self._note_timers[note] = timer
        timer.start()

    # ------------------------------------------------------------------
    # Plugin UI window helpers (Windows only)
    def register_host_window(self, hwnd: int | None) -> None:
        if os.name != "nt":  # pragma: no cover - Windows specific behaviour
            self._host_window_hwnd = None
            return
        self._host_window_hwnd = int(hwnd) if hwnd else None

    def _windows_available(self) -> bool:
        return os.name == "nt" and ctypes is not None

    def _get_window_long(self, hwnd: int, index: int) -> int:
        user32 = ctypes.windll.user32
        if hasattr(user32, "GetWindowLongPtrW"):
            return user32.GetWindowLongPtrW(hwnd, index)
        return user32.GetWindowLongW(hwnd, index)

    def _set_window_long(self, hwnd: int, index: int, value: int) -> int:
        user32 = ctypes.windll.user32
        if hasattr(user32, "SetWindowLongPtrW"):
            return user32.SetWindowLongPtrW(hwnd, index, value)
        return user32.SetWindowLongW(hwnd, index, value)

    def _is_window(self, hwnd: int | None) -> bool:
        if not self._windows_available() or not hwnd:
            return False
        return bool(ctypes.windll.user32.IsWindow(int(hwnd)))

    def _enumerate_process_windows(self) -> list[tuple[int, str]]:
        if not self._windows_available():  # pragma: no cover - Windows specific behaviour
            return []

        handles: list[tuple[int, str]] = []
        pid = os.getpid()
        user32 = ctypes.windll.user32

        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            proc_id = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
            if proc_id.value != pid:
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                title = buffer.value.strip()
            else:
                title = ""
            handles.append((int(hwnd), title))
            return True

        user32.EnumWindows(EnumWindowsProc(callback), 0)
        return handles

    def _store_plugin_window(self, hwnd: int) -> None:
        if not self._windows_available():  # pragma: no cover - Windows specific behaviour
            return
        user32 = ctypes.windll.user32
        self._plugin_window_hwnd = int(hwnd)
        self._plugin_window_parent_hwnd = user32.GetParent(hwnd)
        self._plugin_window_style = self._get_window_long(hwnd, GWL_STYLE)
        self._plugin_window_exstyle = self._get_window_long(hwnd, GWL_EXSTYLE)

    def _reset_plugin_window_snapshot(self) -> None:
        self._plugin_window_hwnd = None
        self._plugin_window_parent_hwnd = None
        self._plugin_window_style = None
        self._plugin_window_exstyle = None

    def _detect_plugin_window(self, attempts: int = 15, delay: float = 0.05) -> int | None:
        if not self._windows_available():
            return None

        name_hint = ""
        if self.host is not None and self._plugin_id is not None:
            try:
                info = self.host.get_plugin_info(self._plugin_id)
            except Exception:
                info = {}
            fallback = self._plugin_path.stem if self._plugin_path else ""
            name_hint = str(info.get("name") or fallback).strip().lower()

        for _ in range(max(1, attempts)):
            for hwnd, title in self._enumerate_process_windows():
                if self._host_window_hwnd and hwnd == self._host_window_hwnd:
                    continue
                if name_hint and title.lower().find(name_hint) == -1:
                    continue
                self._store_plugin_window(hwnd)
                return hwnd
            # Fallback to any other process window if hint not found
            for hwnd, title in self._enumerate_process_windows():
                if self._host_window_hwnd and hwnd == self._host_window_hwnd:
                    continue
                self._store_plugin_window(hwnd)
                return hwnd
            if delay > 0:
                time.sleep(delay)
        return None

    def get_plugin_window_handle(self, attempts: int = 1) -> int | None:
        if not self._windows_available():
            return None
        if self._plugin_window_hwnd and not self._is_window(self._plugin_window_hwnd):
            self._reset_plugin_window_snapshot()
        if self._plugin_window_hwnd is None and self._ui_visible:
            return self._detect_plugin_window(attempts=attempts)
        return self._plugin_window_hwnd

    def _restore_plugin_window_parent(self) -> None:
        if not self._windows_available():
            self._reset_plugin_window_snapshot()
            return
        hwnd = self._plugin_window_hwnd
        if not self._is_window(hwnd):
            self._reset_plugin_window_snapshot()
            return
        user32 = ctypes.windll.user32
        if self._plugin_window_parent_hwnd is not None:
            user32.SetParent(hwnd, self._plugin_window_parent_hwnd)
        if self._plugin_window_style is not None:
            self._set_window_long(hwnd, GWL_STYLE, self._plugin_window_style)
        if self._plugin_window_exstyle is not None:
            self._set_window_long(hwnd, GWL_EXSTYLE, self._plugin_window_exstyle)
        # Refresh snapshot so future embeds have the correct baseline
        self._plugin_window_parent_hwnd = user32.GetParent(hwnd)
        self._plugin_window_style = self._get_window_long(hwnd, GWL_STYLE)
        self._plugin_window_exstyle = self._get_window_long(hwnd, GWL_EXSTYLE)

    def focus_plugin_window(self) -> bool:
        if not self._windows_available():
            return False
        hwnd = self.get_plugin_window_handle(attempts=5)
        if not self._is_window(hwnd):
            return False
        user32 = ctypes.windll.user32
        show_flag = SW_SHOW if SW_SHOW else SW_SHOWNORMAL
        user32.ShowWindow(hwnd, show_flag)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
        return True

    def ensure_plugin_window_taskbar(self) -> bool:
        if not self._windows_available():
            return False
        hwnd = self.get_plugin_window_handle(attempts=5)
        if not self._is_window(hwnd):
            return False
        exstyle = self._get_window_long(hwnd, GWL_EXSTYLE)
        new_exstyle = (exstyle | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
        if new_exstyle != exstyle:
            self._set_window_long(hwnd, GWL_EXSTYLE, new_exstyle)
        owner = self._get_window_long(hwnd, GWL_HWNDPARENT)
        if owner != 0:
            self._set_window_long(hwnd, GWL_HWNDPARENT, 0)
        ctypes.windll.user32.ShowWindow(hwnd, SW_SHOW)
        return True

    def embed_plugin_window(self, parent_hwnd: int | None) -> bool:
        if not self._windows_available():
            return False
        hwnd = self.get_plugin_window_handle(attempts=10)
        if not self._is_window(hwnd):
            return False
        user32 = ctypes.windll.user32
        if parent_hwnd:
            parent = int(parent_hwnd)
            if self._plugin_window_parent_hwnd is None:
                self._plugin_window_parent_hwnd = user32.GetParent(hwnd)
            if self._plugin_window_style is None:
                self._plugin_window_style = self._get_window_long(hwnd, GWL_STYLE)
            if self._plugin_window_exstyle is None:
                self._plugin_window_exstyle = self._get_window_long(hwnd, GWL_EXSTYLE)
            child_style = (self._plugin_window_style | WS_CHILD) & ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME)
            self._set_window_long(hwnd, GWL_STYLE, child_style)
            child_exstyle = self._plugin_window_exstyle & ~WS_EX_APPWINDOW
            self._set_window_long(hwnd, GWL_EXSTYLE, child_exstyle)
            user32.SetParent(hwnd, parent)
            user32.ShowWindow(hwnd, SW_SHOW)
        else:
            self._restore_plugin_window_parent()
        return True

    def show_ui(self) -> dict[str, Any]:
        import logging
        logging.info("🪟 show_ui() called")
        with self._lock:
            logging.info("🪟 Acquired lock")
            if self._plugin_id is None or self.host is None:
                raise CarlaHostError("No plugin hosted")
            if not HAS_PYQT5:
                raise CarlaHostError("PyQt5 not installed - cannot show plugin UI. Install with: pip install PyQt5")

            # Call show_custom_ui directly on current thread (like plugin_host.py does)
            # Carla handles Qt threading internally - DON'T create our own background thread!
            logging.info(f"🪟 Calling show_custom_ui(plugin_id={self._plugin_id}) on current thread")
            try:
                self.host.show_custom_ui(self._plugin_id, True)
                logging.info("🪟 show_custom_ui returned successfully")
                self._ui_visible = True
            except Exception as e:
                logging.error(f"🪟 Failed to show UI: {e}", exc_info=True)
                raise CarlaHostError(f"Failed to show plugin UI: {e}") from e

            return self.status()

    def hide_ui(self) -> dict[str, Any]:
        with self._lock:
            if self._plugin_id is None or self.host is None:
                raise CarlaHostError("No plugin hosted")

            # Call Carla's show_custom_ui directly - it handles threading internally
            self._show_plugin_ui(False)
            return self.status()

    def describe_ui(
        self,
        plugin_path: str | Path | None = None,
        *,
        include_parameters: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            if plugin_path is None:
                if self._plugin_id is None:
                    raise CarlaHostError("No plugin hosted")
                return self._build_descriptor(include_parameters=include_parameters)

            path = Path(plugin_path).expanduser()
            if not path.exists():
                raise FileNotFoundError(f"Plugin not found: {path}")
            if not self.can_handle_path(path):
                raise CarlaHostError(f"Unsupported plugin format: {path.suffix}")

            state = self._snapshot_state()
            try:
                self.load_plugin(path, show_ui=False)
                return self._build_descriptor(include_parameters=include_parameters)
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

    def _plugin_payload(self, include_parameters: bool = True) -> dict[str, Any]:
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
            "parameters": [param.to_metadata_entry() for param in self._parameters] if include_parameters else [],
            "format": self._PLUGIN_TYPE_LABELS.get(info.get("type", 0), "Unknown"),
        }
        payload = {
            "path": str(self._plugin_path),
            "metadata": metadata,
            "parameters": [param.to_status_entry() for param in self._parameters] if include_parameters else [],
            "capabilities": {
                "instrument": self._plugin_is_instrument(),
                "editor": self._plugin_supports_custom_ui() and HAS_PYQT5,
                "midi": self._supports_midi,
            },
        }
        return payload

    def _build_descriptor(self, include_parameters: bool = True) -> dict[str, Any]:
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

        # Ensure MIDI capability is properly detected so the keyboard can show.
        is_instrument = self._plugin_is_instrument()
        accepts_midi = self._plugin_accepts_midi()
        supports_midi = self._supports_midi or accepts_midi

        descriptor = {
            "title": plugin["metadata"].get("name", plugin.get("path")),
            "subtitle": plugin["metadata"].get("vendor", ""),
            "keyboard": {"min_note": 0, "max_note": 96},
            "panels": [{"name": "Parameters", "controls": controls}],
            "parameters": [param.to_status_entry() for param in self._parameters] if include_parameters else [],
            "plugin": plugin,
            "capabilities": {
                "instrument": is_instrument,
                "editor": self._plugin_supports_custom_ui() and HAS_PYQT5,
                "midi": supports_midi,
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

    def _plugin_accepts_midi(self) -> bool:
        if self.host is None or self._plugin_id is None:
            return False
        try:
            info = self.host.get_midi_port_count_info(self._plugin_id)
        except Exception:
            return False
        ins = info.get('ins') if isinstance(info, dict) else None
        return bool(ins and int(ins) > 0)

    def _show_plugin_ui(self, visible: bool) -> None:
        """Show or hide the plugin's native UI with comprehensive error handling."""
        import logging
        logging.info(f"🪟 _show_plugin_ui called: visible={visible}")

        if self.host is None or self._plugin_id is None:
            self._ui_visible = False
            if visible:
                raise CarlaHostError("No plugin hosted - load a plugin before showing UI")
            return

        # Check plugin capabilities
        if visible and not self._plugin_supports_custom_ui():
            plugin_name = self._plugin_path.stem if self._plugin_path else "Plugin"
            raise CarlaHostError(
                f"{plugin_name} does not provide a native UI editor. "
                "This plugin may only support parameter automation."
            )

        # Check Qt availability
        if visible and not HAS_PYQT5:
            raise CarlaHostError(
                "PyQt5 is not installed. Plugin UIs require PyQt5. "
                "Install it with: pip install PyQt5"
            )

        # Check Qt initialization
        if visible and (not self._qt_manager or not self._qt_manager.is_available()):
            raise CarlaHostError(
                "Qt application failed to initialize. This may happen if: \n"
                "1. The display server is not available (headless environment)\n"
                "2. PyQt5 installation is incomplete\n"
                "3. There are Qt library conflicts\n"
                "Try reinstalling PyQt5 or check your display configuration."
            )

        # Attempt to show/hide UI
        action = "show" if visible else "hide"
        logging.info(f"🪟 About to call host.show_custom_ui(plugin_id={self._plugin_id}, visible={visible})")
        try:
            self.host.show_custom_ui(self._plugin_id, bool(visible))
            logging.info(f"🪟 host.show_custom_ui returned successfully")
        except AttributeError as exc:
            # Method doesn't exist - likely a Carla version issue
            raise CarlaHostError(
                f"Failed to {action} plugin UI: show_custom_ui method not available. "
                "This may indicate an incompatible Carla version. "
                f"Error: {exc}"
            ) from exc
        except RuntimeError as exc:
            # Runtime error from Carla - plugin UI couldn't be created
            plugin_name = self._plugin_path.stem if self._plugin_path else "Plugin"
            raise CarlaHostError(
                f"Failed to {action} {plugin_name} UI: The plugin's UI window could not be created. "
                "This may happen if: \n"
                "1. The plugin's UI library is missing or incompatible\n"
                "2. Display server connection failed\n"
                "3. The plugin crashed during UI initialization\n"
                f"Technical details: {exc}"
            ) from exc
        except Exception as exc:
            # Catch-all for unexpected errors
            plugin_name = self._plugin_path.stem if self._plugin_path else "Plugin"
            raise CarlaHostError(
                f"Unexpected error while trying to {action} {plugin_name} UI: {type(exc).__name__}: {exc}"
            ) from exc

        self._ui_visible = bool(visible)
        logging.info(f"🪟 UI visibility updated to: {self._ui_visible}")
        logging.info(f"🪟 After UI change - audio_routed={self._audio_routed}, midi_routed={self._midi_routed}")
        if visible:
            self._detect_plugin_window(attempts=30, delay=0.05)
        else:
            self._restore_plugin_window_parent()
            self._reset_plugin_window_snapshot()

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
        except Exception as exc:
            self.warnings.append(f"Failed to restore Carla plugin state: {exc}")


class CarlaVSTHost:
    """High-level facade over CarlaBackend with native UI focus."""

    def __init__(
        self,
        base_dir: Path | None = None,
        *,
        preferred_drivers: Sequence[str] | None = None,
        forced_driver: str | None = None,
        sample_rate: int | None = None,
        buffer_size: int | None = None,
        client_name: str | None = None,
    ) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parents[2]
        self._backend = CarlaBackend(
            base_dir=self.base_dir,
            preferred_drivers=preferred_drivers,
            forced_driver=forced_driver,
            sample_rate=sample_rate,
            buffer_size=buffer_size,
            client_name=client_name,
        )
        self._lock = threading.RLock()

    def configure_audio(
        self,
        *,
        forced_driver: str | None = None,
        preferred_drivers: Sequence[str] | None = None,
        sample_rate: int | None = None,
        buffer_size: int | None = None,
    ) -> None:
        with self._lock:
            self._backend.configure_audio(
                forced_driver=forced_driver,
                preferred_drivers=preferred_drivers,
                sample_rate=sample_rate,
                buffer_size=buffer_size,
            )

    def shutdown(self) -> None:
        with self._lock:
            self._backend.close()

    def status(self, include_parameters: bool = True) -> dict[str, Any]:
        with self._lock:
            return self._backend.status(include_parameters=include_parameters)

    def ensure_available(self) -> None:
        if self._backend.available:
            return
        message = (
            "; ".join(self._backend.warnings)
            if self._backend.warnings
            else "Carla backend is not available."
        )
        raise CarlaHostError(message)

    def load_plugin(
        self,
        plugin_path: str | Path,
        parameters: dict[str, float] | None = None,
        *,
        show_ui: bool = True,
    ) -> dict[str, Any]:
        path = Path(plugin_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Plugin not found: {path}")
        with self._lock:
            self.ensure_available()
            if not self._backend.can_handle_path(path):
                raise CarlaHostError(f"Unsupported plugin format: {path.suffix}")
            return self._backend.load_plugin(path, parameters, show_ui=show_ui)

    def unload(self) -> None:
        with self._lock:
            self._backend.unload()

    def set_parameter(self, identifier: int | str, value: float) -> dict[str, Any]:
        with self._lock:
            return self._backend.set_parameter(identifier, value)

    def render_preview(self, duration: float = 1.5, sample_rate: int = 44100):
        raise CarlaHostError(
            "Offline preview rendering is not implemented for the Carla backend. "
            "Use a dedicated rendering pipeline (for example the JUCE host) to audition "
            "audio."
        )

    def play_note(
        self,
        note: int,
        *,
        velocity: float = 0.8,
        duration: float = 1.0,
        sample_rate: int = 44100,
    ) -> None:
        with self._lock:
            self.ensure_available()
            self._backend.play_note(int(note), velocity=float(velocity), duration=float(duration))

    def note_on(self, note: int, *, velocity: float = 0.8) -> None:
        with self._lock:
            self.ensure_available()
            self._backend.note_on(int(note), float(velocity))

    def note_off(self, note: int) -> None:
        with self._lock:
            self.ensure_available()
            self._backend.note_off(int(note))

    def describe_ui(
        self,
        plugin_path: str | Path | None = None,
        *,
        include_parameters: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            self.ensure_available()
            return self._backend.describe_ui(plugin_path, include_parameters=include_parameters)

    def register_host_window(self, hwnd: int | None) -> None:
        with self._lock:
            self._backend.register_host_window(hwnd)

    def get_plugin_window_handle(self, attempts: int = 1) -> int | None:
        with self._lock:
            return self._backend.get_plugin_window_handle(attempts=attempts)

    def focus_plugin_window(self) -> bool:
        with self._lock:
            return self._backend.focus_plugin_window()

    def ensure_plugin_window_taskbar(self) -> bool:
        with self._lock:
            return self._backend.ensure_plugin_window_taskbar()

    def embed_plugin_window(self, parent_hwnd: int | None) -> bool:
        with self._lock:
            return self._backend.embed_plugin_window(parent_hwnd)

    def show_ui(self) -> dict[str, Any]:
        with self._lock:
            self.ensure_available()
            return self._backend.show_ui()

    def hide_ui(self) -> dict[str, Any]:
        with self._lock:
            self.ensure_available()
            return self._backend.hide_ui()


_exports = ["CarlaVSTHost", "CarlaHostError", "HAS_PYQT5"]
if HAS_PYQT5:
    _exports.append("QtApplicationManager")
__all__ = _exports
