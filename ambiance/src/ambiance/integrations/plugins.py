"""Helpers for discovering and routing native audio plugins."""

from __future__ import annotations

import json
import os
import shutil
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator


PLUGIN_EXTENSIONS = {
    ".vst": "VST2",
    ".vst3": "VST3",
    ".dll": "VST (Windows)",
    ".component": "Audio Unit",
    ".mxo": "Max External",
    ".mxe": "Max External",
    ".mxe64": "Max External",
    ".svt": "SVT",
}

MODALYS_FILENAMES = {
    "mlys~.mxe64": "Modalys.mxe64",
    "mlys~.mxe": "Modalys.mxe",
    "mlys~.mxo": "Modalys.mxo",
}

LANES = ("A", "B")


@dataclass
class PluginRackManager:
    """Manage discovery and lightweight routing metadata for audio plugins."""

    base_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2])
    workspace_dir: Path | None = None
    config_filename: str = "rack.json"

    def __post_init__(self) -> None:
        self.base_dir = Path(self.base_dir)
        if self.workspace_dir is None:
            self.workspace_dir = self.base_dir / ".cache" / "plugins"
        else:
            self.workspace_dir = Path(self.workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._config_path = self.workspace_dir / self.config_filename
        self._hydrate_modalys_bundle()
        if not self._config_path.exists():
            self._save_config({"streams": {}})

    # ------------------------------------------------------------------
    # Workspace discovery
    def workspace_path(self) -> Path:
        return Path(self.workspace_dir)

    def _candidate_paths(self) -> Iterable[Path]:
        root = self.workspace_path()
        if not root.exists():
            return []

        def walker() -> Iterator[Path]:
            for dirpath, dirnames, filenames in os.walk(root):
                current = Path(dirpath)
                for dirname in list(dirnames):
                    candidate = current / dirname
                    if self._looks_like_plugin(candidate):
                        yield candidate
                        dirnames.remove(dirname)
                for filename in filenames:
                    candidate = current / filename
                    if self._looks_like_plugin(candidate):
                        yield candidate

        return walker()

    @staticmethod
    def _normalize_suffix(path: Path) -> str:
        name = path.name.lower()
        if name.endswith(".mc.svt"):
            return ".mc.svt"
        if name.endswith(".mcsvt"):
            return ".mcsvt"
        return path.suffix.lower()

    def _looks_like_plugin(self, path: Path) -> bool:
        if path.is_dir():
            suffix = self._normalize_suffix(path)
            return suffix in {".vst3", ".component"}
        suffix = self._normalize_suffix(path)
        if suffix in PLUGIN_EXTENSIONS or suffix in {".mc.svt", ".mcsvt"}:
            return True
        try:
            mode = path.stat().st_mode
        except OSError:
            return False
        return bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))

    def _describe_plugin(self, path: Path) -> dict[str, object] | None:
        if not self._looks_like_plugin(path):
            return None
        try:
            relative = path.relative_to(self.workspace_path())
            relative_text = str(relative)
        except ValueError:
            relative_text = ""
        suffix = self._normalize_suffix(path)
        name = path.name
        if suffix and name.lower().endswith(suffix):
            name = name[: -len(suffix)] or path.stem
        else:
            name = path.stem

        info: dict[str, object] = {
            "name": name,
            "path": str(path),
            "relative_path": relative_text,
            "type": "bundle" if path.is_dir() else "file",
            "format": self._format_for(path),
        }
        if path.is_file():
            try:
                info["size"] = path.stat().st_size
            except OSError:
                info["size"] = None
        metadata = self._load_plugin_metadata(path)
        if metadata:
            if metadata.get("name"):
                info["name"] = metadata["name"]
            if metadata.get("format"):
                info["format"] = metadata["format"]
            for key in ("display_name", "origin", "notes"):
                if key in metadata:
                    info[key] = metadata[key]
        return info

    def _format_for(self, path: Path) -> str:
        suffix = self._normalize_suffix(path)
        if suffix == ".mc.svt" or suffix == ".mcsvt":
            return "Max mc.svt"
        if suffix in {".mxe", ".mxe64"}:
            return "Max External"
        return PLUGIN_EXTENSIONS.get(suffix, suffix.lstrip("."))

    def discover_plugins(self, limit: int = 256) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        for candidate in self._candidate_paths():
            info = self._describe_plugin(candidate)
            if info is None:
                continue
            entries.append(info)
            if len(entries) >= limit:
                break
        modalys = self._modalys_descriptor()
        if modalys and all(entry.get("path") != modalys.get("path") for entry in entries):
            entries.append(modalys)
        entries.sort(key=lambda item: (item.get("relative_path") or item.get("path") or "").lower())
        return entries

    # ------------------------------------------------------------------
    # Configuration persistence
    def _load_config(self) -> dict[str, object]:
        if not self._config_path.exists():
            return {"streams": {}}
        try:
            return json.loads(self._config_path.read_text())
        except json.JSONDecodeError:
            return {"streams": {}}

    def _save_config(self, data: dict[str, object]) -> None:
        tmp_path = self._config_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True))
        tmp_path.replace(self._config_path)

    def _ensure_stream(self, config: dict[str, object], stream: str) -> dict[str, object]:
        streams = config.setdefault("streams", {})
        stream_cfg = streams.get(stream)
        if not stream_cfg:
            stream_cfg = {
                "active_lane": "A",
                "lanes": {lane: [] for lane in LANES},
            }
            streams[stream] = stream_cfg
        else:
            lanes = stream_cfg.setdefault("lanes", {})
            for lane in LANES:
                lanes.setdefault(lane, [])
            if stream_cfg.get("active_lane") not in LANES:
                stream_cfg["active_lane"] = "A"
        return stream_cfg

    def _assignment_payload(self, entry: dict[str, object], plugins: dict[str, dict[str, object]]) -> dict[str, object]:
        payload = dict(entry)
        plugin = plugins.get(entry.get("path", ""))
        if plugin:
            payload["plugin"] = plugin
        return payload

    # ------------------------------------------------------------------
    # Rack operations
    def assign_plugin(
        self,
        path: str | Path,
        *,
        stream: str = "Main",
        lane: str = "A",
        slot: int | None = None,
    ) -> dict[str, object]:
        plugin_path = Path(path).expanduser()
        if not plugin_path.exists():
            raise FileNotFoundError(f"Plugin not found: {plugin_path}")
        lane_key = lane.upper()
        if lane_key not in LANES:
            raise ValueError(f"Unsupported lane '{lane}'")

        config = self._load_config()
        stream_cfg = self._ensure_stream(config, stream)
        lane_entries: list[dict[str, object]] = stream_cfg["lanes"][lane_key]

        if slot is None:
            slot_numbers = {int(entry.get("slot", 0)) for entry in lane_entries}
            next_slot = 0
            while next_slot in slot_numbers:
                next_slot += 1
            slot_idx = next_slot
        else:
            slot_idx = int(slot)

        replaced = False
        for entry in lane_entries:
            if int(entry.get("slot", -1)) == slot_idx:
                entry["path"] = str(plugin_path)
                replaced = True
                break
        if not replaced:
            lane_entries.append({"slot": slot_idx, "path": str(plugin_path)})
        lane_entries.sort(key=lambda item: int(item.get("slot", 0)))

        self._save_config(config)
        descriptor = self._describe_plugin(plugin_path) or {
            "name": plugin_path.stem,
            "path": str(plugin_path),
            "relative_path": "",
            "type": "file" if plugin_path.is_file() else "bundle",
            "format": self._format_for(plugin_path),
        }
        return {
            "stream": stream,
            "lane": lane_key,
            "slot": slot_idx,
            "plugin": descriptor,
        }

    def remove_plugin(
        self,
        *,
        stream: str,
        lane: str = "A",
        slot: int | None = None,
        path: str | None = None,
    ) -> dict[str, object]:
        lane_key = lane.upper()
        if lane_key not in LANES:
            raise ValueError(f"Unsupported lane '{lane}'")

        config = self._load_config()
        stream_cfg = self._ensure_stream(config, stream)
        lane_entries: list[dict[str, object]] = stream_cfg["lanes"][lane_key]

        if slot is None and path is None:
            raise ValueError("Provide a slot or path to remove a plugin")

        removed: list[dict[str, object]] = []
        keep: list[dict[str, object]] = []
        for entry in lane_entries:
            entry_slot = int(entry.get("slot", -1))
            entry_path = entry.get("path")
            if slot is not None and entry_slot == int(slot):
                removed.append(entry)
            elif path is not None and Path(entry_path or "") == Path(path).expanduser():
                removed.append(entry)
            else:
                keep.append(entry)
        lane_entries[:] = keep
        self._save_config(config)
        return {
            "stream": stream,
            "lane": lane_key,
            "removed": removed,
        }

    def toggle_lane(self, stream: str) -> dict[str, object]:
        config = self._load_config()
        stream_cfg = self._ensure_stream(config, stream)
        current = stream_cfg.get("active_lane", "A").upper()
        next_lane = "B" if current == "A" else "A"
        stream_cfg["active_lane"] = next_lane
        self._save_config(config)
        return {"stream": stream, "active_lane": next_lane}

    # ------------------------------------------------------------------
    # Status reporting
    def status(self) -> dict[str, object]:
        plugins = self.discover_plugins()
        plugin_lookup = {item["path"]: item for item in plugins}
        config = self._load_config()
        streams: dict[str, object] = {}
        for stream, stream_cfg in config.get("streams", {}).items():
            active_lane = stream_cfg.get("active_lane", "A")
            lane_payload: dict[str, list[dict[str, object]]] = {}
            for lane in LANES:
                entries = [
                    self._assignment_payload(entry, plugin_lookup)
                    for entry in stream_cfg.get("lanes", {}).get(lane, [])
                ]
                entries.sort(key=lambda item: int(item.get("slot", 0)))
                lane_payload[lane] = entries
            streams[stream] = {
                "active_lane": active_lane,
                "lanes": lane_payload,
            }
        if not streams:
            streams["Main"] = {
                "active_lane": "A",
                "lanes": {lane: [] for lane in LANES},
            }
        notes = [
            "Drop VST, VST3, Audio Unit, or mc.svt plugins into this folder to load them into the rack.",
            "Assign plugins to lane A or B to build parallel chains and toggle them for instant A/B comparisons.",
        ]
        if any(plugin.get("origin") == "Bundled Modalys package" for plugin in plugins):
            notes.append(
                "Modalys (Max) is bundled for quick experiments. Route it through a lane to explore physical modelling textures."
            )
        return {
            "workspace": str(self.workspace_path()),
            "workspace_exists": self.workspace_path().exists(),
            "plugins": plugins,
            "streams": streams,
            "notes": notes,
        }

    # ------------------------------------------------------------------
    # Modalys helpers
    def _modalys_bundle_candidates(self) -> list[Path]:
        roots = [self.base_dir]
        seen: set[Path] = set()
        candidates: list[Path] = []
        for root in roots:
            root_path = Path(root)
            if not root_path.exists():
                continue
            try:
                entries = list(root_path.iterdir())
            except OSError:
                continue
            for entry in entries:
                if entry in seen:
                    continue
                if "modalys" not in entry.name.lower():
                    continue
                if entry == self.workspace_path():
                    continue
                if entry.is_dir() or entry.suffix.lower() == ".zip":
                    candidates.append(entry)
                    seen.add(entry)
        return sorted(candidates)

    def _modalys_target_dir(self) -> Path:
        return self.workspace_path() / "Modalys"

    def _modalys_already_installed(self, target_dir: Path) -> bool:
        try:
            return any(target_dir.glob("Modalys.*"))
        except OSError:
            return False

    def _hydrate_modalys_bundle(self) -> None:
        target_dir = self._modalys_target_dir()
        if self._modalys_already_installed(target_dir):
            return
        for candidate in self._modalys_bundle_candidates():
            try:
                if self._install_modalys_candidate(candidate, target_dir):
                    break
            except Exception:  # pragma: no cover - defensive guard
                continue

    def _install_modalys_candidate(self, candidate: Path, target_dir: Path) -> bool:
        target_dir.mkdir(parents=True, exist_ok=True)
        installed: list[Path] = []
        if candidate.is_dir():
            installed = self._copy_modalys_from_dir(candidate, target_dir)
        elif candidate.suffix.lower() == ".zip":
            installed = self._copy_modalys_from_zip(candidate, target_dir)
        if not installed:
            return False
        self._write_modalys_metadata(target_dir, candidate)
        return True

    def _copy_modalys_from_dir(self, source: Path, target_dir: Path) -> list[Path]:
        installed: list[Path] = []
        for root, _, files in os.walk(source):
            for filename in files:
                lower = filename.lower()
                alias = MODALYS_FILENAMES.get(lower)
                if not alias:
                    continue
                dest = target_dir / alias
                if dest.exists():
                    continue
                src_path = Path(root) / filename
                try:
                    shutil.copy2(src_path, dest)
                except OSError:
                    continue
                installed.append(dest)
        return installed

    def _copy_modalys_from_zip(self, archive: Path, target_dir: Path) -> list[Path]:
        installed: list[Path] = []
        try:
            with zipfile.ZipFile(archive) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    name = Path(info.filename).name
                    alias = MODALYS_FILENAMES.get(name.lower())
                    if not alias:
                        continue
                    dest = target_dir / alias
                    if dest.exists():
                        continue
                    try:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, dest.open("wb") as dst:
                            shutil.copyfileobj(src, dst)
                    except OSError:
                        continue
                    installed.append(dest)
        except zipfile.BadZipFile:
            return []
        return installed

    def _write_modalys_metadata(self, target_dir: Path, source: Path) -> None:
        metadata = {
            "name": "Modalys (Max)",
            "display_name": "Modalys (Max)",
            "origin": "Bundled Modalys package",
            "format": "Max External",
            "notes": [
                "Modalys ships as a Max external. Load it into Max or mc.svt hosts to experiment with physical modelling.",
                f"Installed from {source.name}",
            ],
        }
        meta_path = target_dir / ".ambiance_plugin.json"
        try:
            meta_path.write_text(json.dumps(metadata, indent=2))
        except OSError:
            pass

    def _load_plugin_metadata(self, path: Path) -> dict[str, object] | None:
        workspace = self.workspace_path()
        current = path if path.is_dir() else path.parent
        while True:
            try:
                current.relative_to(workspace)
            except ValueError:
                break
            meta_path = current / ".ambiance_plugin.json"
            if meta_path.exists():
                try:
                    return json.loads(meta_path.read_text())
                except (OSError, json.JSONDecodeError):
                    return None
            if current == workspace:
                break
            current = current.parent
        return None

    def _modalys_descriptor(self) -> dict[str, object] | None:
        workspace = self.workspace_path()
        candidates: list[Path] = []
        for pattern in ("Modalys.mxe64", "Modalys.mxe", "Modalys.mxo"):
            candidates.extend(workspace.rglob(pattern))
        if not candidates:
            return None
        plugin_path = min(candidates, key=lambda p: len(p.parts))
        descriptor = self._describe_plugin(plugin_path)
        if descriptor:
            descriptor.setdefault("name", "Modalys (Max)")
            descriptor.setdefault("display_name", descriptor["name"])
            descriptor.setdefault("origin", "Bundled Modalys package")
            descriptor.setdefault("format", "Max External")
        return descriptor
