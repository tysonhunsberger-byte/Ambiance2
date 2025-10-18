"""Integration layer that bridges the Flutter VST3 toolkit into Ambiance.

The real Flutter toolkit ships Dart/C++ binaries that host VST3 plugins with a
Flutter driven UI.  Shipping and executing those binaries isn't possible inside
this environment, but we can still provide a faithful bridge that understands
the toolkit metadata, surfaces plugin parameters to the UI, and offers a
Python-side DSP shim so the rest of Ambiance can interact with the hosted
plugins in real time.

The goal of this module is therefore twofold:

* Discover the Flutter toolkit that ships with this repository and expose its
  plugin metadata (names, parameters, defaults, etc.).
* Provide a light-weight host that mimics the behaviour of the toolkit's
  example plugins so we can stream previews, drive parameter automation, and
  render the hosted effect inside Ambiance's audio engine.

The bridge intentionally mirrors the data structures described in the toolkit's
`plugin_metadata.json` files so that, when the native toolchain is present, the
same API shape can be used to drive a real host binary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import base64
import json
import os
from pathlib import Path
import threading
import zipfile
from typing import Any

from ..npcompat import np

from ..core.base import AudioEffect


# ---------------------------------------------------------------------------
# Metadata models


@dataclass(frozen=True)
class FlutterVSTParameter:
    """Description of a single plugin parameter."""

    id: int
    name: str
    display_name: str
    description: str
    default: float
    units: str = ""
    minimum: float = 0.0
    maximum: float = 1.0
    step: float = 0.01

    def to_dict(self, value: float | None = None) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "default": self.default,
            "units": self.units,
            "min": self.minimum,
            "max": self.maximum,
            "step": self.step,
        }
        if value is not None:
            payload["value"] = value
        return payload


@dataclass(frozen=True)
class FlutterVSTMetadata:
    """Container describing a Flutter generated plugin."""

    name: str
    vendor: str
    version: str
    category: str | None
    bundle_identifier: str | None
    parameters: tuple[FlutterVSTParameter, ...] = field(default_factory=tuple)

    def parameter_map(self) -> dict[int, FlutterVSTParameter]:
        return {param.id: param for param in self.parameters}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "vendor": self.vendor,
            "version": self.version,
            "category": self.category,
            "bundle_identifier": self.bundle_identifier,
            "parameters": [param.to_dict() for param in self.parameters],
        }


# ---------------------------------------------------------------------------
# Toolkit discovery


def _normalise_label(label: str) -> str:
    return label.replace(" ", "").replace("-", "").lower()


def _clamp(value: float, minimum: float, maximum: float) -> float:
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


class FlutterVSTToolkit:
    """Load and index metadata from the bundled Flutter VST3 toolkit."""

    def __init__(self, root: Path | None) -> None:
        self.root = Path(root) if root else None
        self._zip_path: Path | None = None
        if self.root and self.root.is_file() and self.root.suffix.lower() == ".zip":
            self._zip_path = self.root
            self.available = True
        else:
            self.available = bool(self.root and (self.root / "vsts").exists())
        self._metadata_index: dict[str, FlutterVSTMetadata] = {}
        self._ui_roots: list[Path] = []
        if self.available:
            if self._zip_path:
                self._load_metadata_from_zip()
            else:
                self._load_metadata_from_dir()

    # The toolkit is heavy to scan; cache the discovered instance at module
    # level so multiple hosts/effects share the same data.
    _DEFAULT_LOCK = threading.Lock()
    _DEFAULT_INSTANCE: "FlutterVSTToolkit | None" = None

    @classmethod
    def default(cls) -> "FlutterVSTToolkit":
        with cls._DEFAULT_LOCK:
            if cls._DEFAULT_INSTANCE is None:
                cls._DEFAULT_INSTANCE = cls.discover()
            return cls._DEFAULT_INSTANCE

    @classmethod
    def discover(cls, base_dir: Path | None = None) -> "FlutterVSTToolkit":
        candidates: list[Path] = []
        env = os.environ.get("FLUTTER_VST3_TOOLKIT")
        if env:
            candidates.append(Path(env))
        if base_dir is None:
            base_dir = Path(__file__).resolve().parents[2]
        candidates.extend(
            [
                base_dir / "flutter_vst3-main",
                base_dir / "flutter_vst3",
                base_dir / "third_party" / "flutter_vst3",
                base_dir / "flutter_vst3-main.zip",
            ]
        )
        metadata_dirs = [base_dir / "data" / "vsts"]
        ui_dirs = [base_dir / "data" / "vst_ui"]
        for candidate in candidates:
            if candidate.is_dir() and (candidate / "vsts").exists():
                toolkit = cls(candidate)
                toolkit.add_embedded_resources(metadata_dirs, ui_dirs)
                return toolkit
            if candidate.is_file() and candidate.suffix.lower() == ".zip":
                toolkit = cls(candidate)
                toolkit.add_embedded_resources(metadata_dirs, ui_dirs)
                return toolkit
        toolkit = cls(None)
        toolkit.add_embedded_resources(metadata_dirs, ui_dirs)
        return toolkit

    # ------------------------------------------------------------------
    # Metadata loading
    def _load_metadata_from_dir(self) -> None:
        assert self.root is not None
        vsts_dir = self.root / "vsts"
        self._scan_metadata_directory(vsts_dir)

    def _scan_metadata_directory(self, directory: Path) -> None:
        if not directory.exists():
            return
        for meta_file in directory.rglob("plugin_metadata.json"):
            if not meta_file.is_file():
                continue
            try:
                self._register_metadata(meta_file.read_text())
            except OSError:
                continue

    def _load_metadata_from_zip(self) -> None:
        assert self._zip_path is not None
        try:
            with zipfile.ZipFile(self._zip_path) as archive:
                for entry in archive.namelist():
                    if entry.endswith("plugin_metadata.json") and entry.count("/") >= 2:
                        try:
                            data = archive.read(entry).decode("utf-8")
                        except Exception:
                            continue
                        self._register_metadata(data)
        except zipfile.BadZipFile:
            self.available = False

    def _register_metadata(self, text: str) -> None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return
        metadata = self._build_metadata(data)
        self._metadata_index[_normalise_label(metadata.name)] = metadata
        if metadata.bundle_identifier:
            self._metadata_index[_normalise_label(metadata.bundle_identifier)] = metadata

    def _build_metadata(self, payload: dict[str, Any]) -> FlutterVSTMetadata:
        params: list[FlutterVSTParameter] = []
        for entry in payload.get("parameters", []):
            minimum = float(entry.get("minValue", 0.0))
            maximum = float(entry.get("maxValue", 1.0))
            default = float(entry.get("defaultValue", minimum))
            step = float(entry.get("step", 0.01))
            params.append(
                FlutterVSTParameter(
                    id=int(entry.get("id", len(params))),
                    name=str(entry.get("name", f"param{len(params)}")),
                    display_name=str(entry.get("displayName", entry.get("name", "Parameter"))),
                    description=str(entry.get("description", "")),
                    default=default,
                    units=str(entry.get("units", "")),
                    minimum=minimum,
                    maximum=maximum,
                    step=step,
                )
            )
        return FlutterVSTMetadata(
            name=str(payload.get("pluginName", "Flutter Plugin")),
            vendor=str(payload.get("vendor", "")),
            version=str(payload.get("version", "")),
            category=payload.get("category"),
            bundle_identifier=payload.get("bundleIdentifier"),
            parameters=tuple(params),
        )

    # ------------------------------------------------------------------
    # Embedded resources

    def add_embedded_resources(
        self,
        metadata_dirs: list[Path] | None,
        ui_dirs: list[Path] | None,
    ) -> None:
        for path in metadata_dirs or []:
            if path and path.exists():
                self._scan_metadata_directory(path)
        for ui_path in ui_dirs or []:
            if ui_path and ui_path.exists():
                self._ui_roots.append(ui_path)

    def _load_ui_schema(self, plugin_path: Path) -> dict[str, Any] | None:
        key = _normalise_label(plugin_path.stem)
        for root in self._ui_roots:
            candidate = root / f"{key}.json"
            if not candidate.exists():
                continue
            try:
                payload = json.loads(candidate.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            artwork = payload.get("artwork")
            if isinstance(artwork, dict):
                art_path = artwork.get("path")
                if art_path:
                    resolved = (candidate.parent / art_path).resolve()
                    if resolved.exists():
                        data = resolved.read_bytes()
                        mime = "image/svg+xml" if resolved.suffix.lower() == ".svg" else "image/png"
                        encoded = base64.b64encode(data).decode("ascii")
                        artwork["data_uri"] = f"data:{mime};base64,{encoded}"
            return payload
        return None

    def _build_default_ui(
        self,
        metadata: FlutterVSTMetadata,
        parameters: list[dict[str, Any]],
    ) -> dict[str, Any]:
        controls: list[dict[str, Any]] = []
        for param in parameters:
            controls.append(
                {
                    "param": param["name"],
                    "label": param.get("display_name") or param["name"],
                    "id": param["id"],
                    "type": "slider",
                    "min": param.get("min"),
                    "max": param.get("max"),
                    "step": param.get("step"),
                    "value": param.get("value", param.get("default")),
                    "units": param.get("units"),
                }
            )
        return {
            "title": metadata.name,
            "panels": [
                {
                    "title": "Parameters",
                    "layout": "grid",
                    "controls": controls,
                }
            ],
            "theme": {
                "background": "#101622",
                "accent": "#59a7ff",
                "accentSecondary": "#1d2435",
                "text": "#f8fafc",
                "panel": "#131a28",
                "panelStroke": "#59a7ff",
            },
        }

    def describe_ui(
        self,
        metadata: FlutterVSTMetadata,
        plugin_path: Path,
        parameter_values: dict[int, float] | None = None,
    ) -> dict[str, Any]:
        parameter_values = parameter_values or {}
        snapshot = []
        for param in metadata.parameters:
            value = parameter_values.get(param.id, param.default)
            snapshot.append(param.to_dict(value=value))
        descriptor = self._load_ui_schema(plugin_path)
        if descriptor is None:
            descriptor = self._build_default_ui(metadata, snapshot)
        else:
            descriptor = json.loads(json.dumps(descriptor))
            lookup = {
                _normalise_label(entry["name"]): entry for entry in snapshot
            }
            for panel in descriptor.get("panels", []):
                for control in panel.get("controls", []):
                    key = _normalise_label(control.get("param") or control.get("name", ""))
                    entry = lookup.get(key)
                    if not entry:
                        continue
                    control.setdefault("label", entry.get("display_name") or entry["name"])
                    control.setdefault("id", entry["id"])
                    control.setdefault("type", "slider")
                    control.setdefault("min", entry.get("min"))
                    control.setdefault("max", entry.get("max"))
                    control.setdefault("step", entry.get("step"))
                    control.setdefault("units", entry.get("units"))
                    control["value"] = entry.get("value", entry.get("default"))
        descriptor.setdefault("title", metadata.name)
        descriptor.setdefault("subtitle", metadata.vendor)
        descriptor.setdefault("keyboard", {"min_note": 48, "max_note": 72})
        descriptor["parameters"] = snapshot
        descriptor["plugin"] = metadata.to_dict()
        descriptor["capabilities"] = {
            "instrument": "instrument" in (metadata.category or "").lower(),
            "editor": False,
        }
        return descriptor

    # ------------------------------------------------------------------
    # Metadata lookup helpers
    def metadata_for_plugin_path(self, plugin_path: Path) -> FlutterVSTMetadata:
        if not self.available:
            return self._fallback_metadata(plugin_path)
        keys = [
            _normalise_label(plugin_path.stem),
            _normalise_label(plugin_path.name),
        ]
        for key in keys:
            if key in self._metadata_index:
                return self._metadata_index[key]
        return self._fallback_metadata(plugin_path)

    def _fallback_metadata(self, plugin_path: Path) -> FlutterVSTMetadata:
        display = plugin_path.stem or "Plugin"
        param = FlutterVSTParameter(
            id=0,
            name="gain",
            display_name="Gain",
            description="Output gain multiplier",
            default=1.0,
            units="x",
            minimum=0.0,
            maximum=2.0,
            step=0.01,
        )
        return FlutterVSTMetadata(
            name=display,
            vendor="Unknown",
            version="",
            category=None,
            bundle_identifier=None,
            parameters=(param,),
        )

    def instantiate(
        self,
        plugin_path: str | Path,
        *,
        parameter_overrides: dict[str, float] | None = None,
    ) -> "FlutterVSTInstance":
        path = Path(plugin_path).expanduser()
        metadata = self.metadata_for_plugin_path(path)
        instance = FlutterVSTInstance(plugin_path=path, metadata=metadata)
        if parameter_overrides:
            for name, value in parameter_overrides.items():
                instance.set_parameter(name, float(value))
        return instance

    def warnings(self) -> list[str]:
        if self.available:
            return []
        return [
            "Flutter VST3 toolkit not found. Install it or set FLUTTER_VST3_TOOLKIT",
            "Realtime hosting will use a lightweight gain shim until the toolkit is installed.",
        ]


# ---------------------------------------------------------------------------
# DSP shim / host instance


class FlutterVSTInstance(AudioEffect):
    """Simulated DSP block for a Flutter generated plugin."""

    name: str = "flutter_vst"

    def __init__(self, plugin_path: Path, metadata: FlutterVSTMetadata) -> None:
        self.plugin_path = Path(plugin_path)
        self.metadata = metadata
        self._param_lookup = metadata.parameter_map()
        self._parameters: dict[int, float] = {
            param.id: float(param.default) for param in metadata.parameters
        }
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {}
        category = (metadata.category or "").lower()
        self._is_instrument = "instrument" in category or "synth" in category

    # ------------------------------------------------------------------
    # Parameter helpers
    def parameter_snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                self._param_lookup[param_id].to_dict(value=value)
                for param_id, value in sorted(self._parameters.items())
            ]

    def parameter_values(self) -> dict[int, float]:
        with self._lock:
            return dict(self._parameters)

    def set_parameter(self, identifier: int | str, value: float) -> float:
        with self._lock:
            param_id = self._resolve_identifier(identifier)
            param = self._param_lookup[param_id]
            clamped = float(value)
            if clamped < param.minimum:
                clamped = param.minimum
            elif clamped > param.maximum:
                clamped = param.maximum
            self._parameters[param_id] = clamped
            # Reset state if a parameter fundamentally changes topology
            if param.name in {"delayTime", "roomSize"}:
                self._state.pop(param.name, None)
            return clamped

    def get_parameter(self, identifier: int | str) -> float:
        param_id = self._resolve_identifier(identifier)
        return self._parameters[param_id]

    def _safe_parameter_value(self, identifier: int | str, default: float) -> float:
        try:
            return float(self.get_parameter(identifier))
        except KeyError:
            return float(default)

    def _resolve_identifier(self, identifier: int | str) -> int:
        if isinstance(identifier, int):
            if identifier not in self._parameters:
                raise KeyError(f"Unknown parameter id {identifier}")
            return identifier
        key = _normalise_label(identifier)
        for param in self._param_lookup.values():
            if _normalise_label(param.name) == key:
                return param.id
        raise KeyError(f"Unknown parameter {identifier}")

    # ------------------------------------------------------------------
    # AudioEffect API
    def apply(self, buffer: np.ndarray, sample_rate: int) -> np.ndarray:  # pragma: no cover - alias
        return self.process(buffer, sample_rate)

    def process(self, buffer: np.ndarray, sample_rate: int) -> np.ndarray:
        name = _normalise_label(self.metadata.name)
        if "echo" in name:
            return self._process_echo(buffer, sample_rate)
        if "reverb" in name:
            return self._process_reverb(buffer, sample_rate)
        return self._process_gain(buffer)

    def _process_gain(self, buffer: np.ndarray) -> np.ndarray:
        gain = float(self._parameters.get(0, 1.0))
        out = (gain * buffer).astype(np.float32)
        return np.clip(out, -1.0, 1.0)

    def _process_echo(self, buffer: np.ndarray, sample_rate: int) -> np.ndarray:
        bypass = self._parameters.get(self._resolve_identifier("bypass"), 0.0)
        if bypass >= 0.5:
            return buffer.astype(np.float32)
        delay_value = self._parameters.get(self._resolve_identifier("delayTime"), 0.5)
        feedback = self._parameters.get(self._resolve_identifier("feedback"), 0.3)
        mix = self._parameters.get(self._resolve_identifier("mix"), 0.5)

        delay_seconds = float(_clamp(delay_value, 0.0, 1.0))
        feedback = float(_clamp(feedback, 0.0, 0.95))
        mix = float(_clamp(mix, 0.0, 1.0))

        delay_samples = max(1, int(delay_seconds * sample_rate))
        state_key = "echo_buffer"
        with self._lock:
            buf = self._state.get(state_key)
            idx = int(self._state.get("echo_index", 0))
            if buf is None or len(buf) != delay_samples:
                buf = np.zeros(delay_samples, dtype=np.float32)
                idx = 0
            output = np.zeros_like(buffer, dtype=np.float32)
            for i, sample in enumerate(buffer.astype(np.float32)):
                delayed = buf[idx]
                buf[idx] = sample + delayed * feedback
                output[i] = (1 - mix) * sample + mix * delayed
                idx = (idx + 1) % delay_samples
            self._state[state_key] = buf
            self._state["echo_index"] = idx
        return np.clip(output, -1.0, 1.0)

    def _process_reverb(self, buffer: np.ndarray, sample_rate: int) -> np.ndarray:
        room = self._parameters.get(self._resolve_identifier("roomSize"), 0.5)
        damping = self._parameters.get(self._resolve_identifier("damping"), 0.5)
        wet_level = self._parameters.get(self._resolve_identifier("wetLevel"), 0.3)
        dry_level = self._parameters.get(self._resolve_identifier("dryLevel"), 0.7)

        room = float(_clamp(room, 0.0, 1.0))
        damping = float(_clamp(damping, 0.0, 1.0))
        wet_level = float(_clamp(wet_level, 0.0, 1.0))
        dry_level = float(_clamp(dry_level, 0.0, 1.0))

        decay = 0.2 + room * 0.75
        mix = max(0.05, wet_level * (1.0 - 0.4 * damping))

        from ..effects.spatial import ReverbEffect  # Local import to avoid cycle

        effect = ReverbEffect(decay=decay, mix=1.0)
        wet = effect.apply(buffer.astype(np.float32), sample_rate)
        combined = dry_level * buffer.astype(np.float32) + wet_level * wet
        return np.clip(combined, -1.0, 1.0)

    # ------------------------------------------------------------------
    # Instrument helpers

    @property
    def is_instrument(self) -> bool:
        return self._is_instrument

    def play_note(
        self,
        note: int,
        *,
        velocity: float = 0.8,
        duration: float = 1.0,
        sample_rate: int = 44100,
    ) -> np.ndarray:
        if not self.is_instrument:
            raise RuntimeError("Plugin is not an instrument")
        velocity = float(_clamp(velocity, 0.0, 1.0))
        duration = max(0.1, float(duration))
        release = float(self._safe_parameter_value("release", 0.4))
        total_duration = duration + release
        samples = max(1, int(total_duration * sample_rate))
        t = np.linspace(0.0, total_duration, samples, endpoint=False).astype(np.float32)
        freq = 440.0 * (2.0 ** ((int(note) - 69) / 12.0))
        vibrato_rate = float(self._safe_parameter_value("vibratoRate", 3.0))
        vibrato_depth = float(self._safe_parameter_value("vibratoDepth", 0.1))
        vibrato = np.sin(2 * np.pi * vibrato_rate * t).astype(np.float32)
        phase_cycles = np.zeros(samples, dtype=np.float32)
        phase_acc = 0.0
        for i in range(samples):
            modulation = 1.0 + 0.02 * vibrato_depth * float(vibrato[i])
            phase_acc += (freq * modulation) / sample_rate
            phase_cycles[i] = phase_acc
        phase_radians = (2 * np.pi) * phase_cycles
        base = np.sin(phase_radians).astype(np.float32)
        brightness = float(self._safe_parameter_value("brightness", 0.5))
        harmonics = (
            0.45 * brightness * np.sin(2 * phase_radians).astype(np.float32)
            + 0.25 * brightness * np.sin(3 * phase_radians).astype(np.float32)
        )
        breath = float(self._safe_parameter_value("breath", 0.1))
        noise = np.zeros_like(base)
        if breath > 0:
            rng = np.random.default_rng()
            noise = rng.standard_normal(len(base))
            noise *= 0.25 * breath
            noise = noise.astype(np.float32)
        tone = base * (1.0 - brightness * 0.15) + harmonics + noise

        attack = float(self._safe_parameter_value("attack", 0.05))
        decay = float(self._safe_parameter_value("decay", 0.2))
        sustain = float(self._safe_parameter_value("sustain", 0.7))
        sustain = float(_clamp(sustain, 0.0, 1.0))

        attack_samples = max(1, int(attack * sample_rate))
        decay_samples = max(1, int(decay * sample_rate))
        release_samples = max(1, int(release * sample_rate))
        total_env = attack_samples + decay_samples + release_samples
        if total_env >= samples:
            scale = samples / (total_env + 1e-6)
            attack_samples = max(1, int(attack_samples * scale))
            decay_samples = max(1, int(decay_samples * scale))
            release_samples = max(1, int(release_samples * scale))
        sustain_samples = max(0, samples - (attack_samples + decay_samples + release_samples))
        env = np.zeros(samples, dtype=np.float32)
        idx = 0
        env[:attack_samples] = np.linspace(0.0, 1.0, attack_samples, endpoint=False).astype(np.float32)
        idx += attack_samples
        env[idx - 1] = 1.0
        env[idx: idx + decay_samples] = (
            np.linspace(1.0, sustain, decay_samples, endpoint=False).astype(np.float32)
        )
        idx += decay_samples
        if sustain_samples > 0:
            env[idx: idx + sustain_samples] = [sustain] * sustain_samples
            idx += sustain_samples
        tail = samples - idx
        if tail > 0:
            env[idx:] = (
                np.linspace(env[idx - 1] if idx else sustain, 0.0, tail, endpoint=False).astype(np.float32)
            )
        if len(env):
            env[-1] = 0.0
        expression = float(self._safe_parameter_value("expression", 1.0))
        dynamic = (velocity ** 1.1) * expression
        signal = np.zeros(samples, dtype=np.float32)
        for i in range(samples):
            signal[i] = float(tone[i]) * float(env[i]) * dynamic
        hall = float(self._safe_parameter_value("hallMix", 0.0))
        hall = float(_clamp(hall, 0.0, 0.95))
        if hall > 0.0:
            from ..effects.spatial import ReverbEffect

            decay_time = 1.2 + hall * 1.8
            reverb = ReverbEffect(decay=decay_time, mix=hall)
            signal = reverb.apply(signal.astype(np.float32), sample_rate)
        return np.clip(signal.astype(np.float32), -1.0, 1.0)

    # ------------------------------------------------------------------
    # Serialisation helpers
    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.plugin_path),
            "metadata": self.metadata.to_dict(),
            "parameters": self.parameter_snapshot(),
            "capabilities": {
                "instrument": self._is_instrument,
                "editor": False,
            },
        }


# ---------------------------------------------------------------------------
# Public host facade used by the HTTP server


class FlutterVSTHost:
    """Thread-safe manager that exposes a single hosted Flutter plugin."""

    def __init__(self, toolkit: FlutterVSTToolkit | None = None, base_dir: Path | None = None) -> None:
        if toolkit is None:
            if base_dir is None:
                base_dir = Path(__file__).resolve().parents[2]
            toolkit = FlutterVSTToolkit.discover(base_dir)
        self.toolkit = toolkit
        self._lock = threading.RLock()
        self._instance: FlutterVSTInstance | None = None

    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        with self._lock:
            payload: dict[str, Any] = {
                "available": self.toolkit.available,
                "toolkit_path": str(self.toolkit.root) if self.toolkit.root else None,
                "warnings": self.toolkit.warnings(),
                "ui_visible": False,
            }
            if self._instance is None:
                payload["plugin"] = None
                payload["parameters"] = []
                payload["capabilities"] = {"editor": False, "instrument": False}
            else:
                plugin_payload = self._instance.to_dict()
                payload["plugin"] = plugin_payload
                payload["parameters"] = plugin_payload.get("parameters", [])
                payload["capabilities"] = dict(plugin_payload.get("capabilities", {}))
            return payload

    def load_plugin(self, plugin_path: str | Path, parameters: dict[str, float] | None = None) -> dict[str, Any]:
        with self._lock:
            instance = self.toolkit.instantiate(plugin_path, parameter_overrides=parameters)
            self._instance = instance
            return instance.to_dict()

    def unload(self) -> None:
        with self._lock:
            self._instance = None

    def set_parameter(self, identifier: int | str, value: float) -> dict[str, Any]:
        with self._lock:
            if self._instance is None:
                raise RuntimeError("No plugin hosted")
            self._instance.set_parameter(identifier, value)
            return {
                "plugin": self._instance.to_dict(),
                "parameters": self._instance.parameter_snapshot(),
            }

    def render_preview(self, duration: float = 1.5, sample_rate: int = 44100) -> np.ndarray:
        with self._lock:
            if self._instance is None:
                raise RuntimeError("No plugin hosted")
            samples = max(1, int(duration * sample_rate))
            impulse = np.zeros(samples, dtype=np.float32)
            impulse[0] = 1.0
            return self._instance.process(impulse, sample_rate)

    def play_note(
        self,
        note: int,
        *,
        velocity: float = 0.8,
        duration: float = 1.0,
        sample_rate: int = 44100,
    ) -> np.ndarray:
        with self._lock:
            if self._instance is None:
                raise RuntimeError("No plugin hosted")
            return self._instance.play_note(
                note,
                velocity=velocity,
                duration=duration,
                sample_rate=sample_rate,
            )

    def describe_ui(self, plugin_path: str | Path | None = None) -> dict[str, Any]:
        with self._lock:
            if plugin_path is None:
                if self._instance is None:
                    raise RuntimeError("No plugin hosted")
                return self.toolkit.describe_ui(
                    self._instance.metadata,
                    self._instance.plugin_path,
                    self._instance.parameter_values(),
                )
            path = Path(plugin_path).expanduser()
            metadata = self.toolkit.metadata_for_plugin_path(path)
            defaults = {param.id: param.default for param in metadata.parameters}
            return self.toolkit.describe_ui(metadata, path, defaults)

    # Convenience used by the offline renderer / registry effect
    def create_effect(self, plugin_path: str | Path, parameters: dict[str, float] | None = None) -> FlutterVSTInstance:
        return self.toolkit.instantiate(plugin_path, parameter_overrides=parameters)


__all__ = [
    "FlutterVSTHost",
    "FlutterVSTToolkit",
    "FlutterVSTInstance",
    "FlutterVSTMetadata",
    "FlutterVSTParameter",
]
