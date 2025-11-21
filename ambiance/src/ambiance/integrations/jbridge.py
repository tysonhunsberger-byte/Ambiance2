"""Optional helpers for integrating jBridge wrappers with Carla.

This module does **not** ship jBridge nor attempt to automate its UI driven
workflow.  Instead, it gives the Python host enough context to discover
wrappers that the user has already generated with jBridger.exe and to provide
actionable guidance when no wrapper is available.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class JBridgeUnavailableError(RuntimeError):
    """Raised when jBridge is requested but no installation could be found."""


@dataclass(slots=True)
class _MirrorRoot:
    source: Path
    destination: Path


class JBridgeManager:
    """Load-time helper that keeps track of wrapper DLLs produced by jBridge."""

    CONFIG_FILENAME = "jbridge.json"
    DEFAULT_WRAPPER_DIRNAME = "jbridge_wrappers"
    DEFAULT_INSTALL_HINTS: tuple[Path, ...] = (
        Path("C:/Program Files/JBridge"),
        Path("C:/Program Files (x86)/JBridge"),
        Path("C:/JBridge"),
    )

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)
        self._project_root = self._resolve_project_root()
        self.config_path = self.base_dir / "config" / self.CONFIG_FILENAME
        self._name_cache: dict[tuple[Path, str], Path | None] = {}
        self._config_data = self._load_config()
        self.wrapper_roots = self._build_wrapper_roots()
        self._mirror_roots = self._build_mirror_roots()
        self._manual_wrappers = self._build_manual_wrappers()
        self.jbridger_path = self._discover_jbridger()
        self.available = bool(
            self.wrapper_roots or self._mirror_roots or self._manual_wrappers or self.jbridger_path
        )

    # ------------------------------------------------------------------ #
    # Configuration                                                      #
    # ------------------------------------------------------------------ #
    def _load_config(self) -> dict:
        if not self.config_path.exists():
            return {}
        try:
            with self.config_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
        except Exception as exc:
            logging.warning("Failed to parse %s: %s", self.config_path, exc)
        return {}

    def _resolve_path(self, candidate: Path | str) -> Path:
        path = Path(candidate).expanduser()
        try:
            return path.resolve(strict=False)
        except OSError:
            return path

    def _resolve_project_root(self) -> Path:
        ancestors = list(self.base_dir.parents)
        search_order = list(reversed(ancestors)) + [self.base_dir]
        for candidate in search_order:
            if (candidate / "included_plugins").exists():
                return candidate
        return ancestors[-1] if ancestors else self.base_dir

    def _build_wrapper_roots(self) -> list[Path]:
        roots: list[Path] = []
        for entry in self._config_data.get("wrapper_roots", []):
            try:
                path = self._resolve_path(entry)
            except TypeError:
                continue
            if path not in roots:
                roots.append(path)

        preferred_defaults = [
            self._project_root / "included_plugins" / "Bridged32BitPlugins",
            self.base_dir / "deps" / self.DEFAULT_WRAPPER_DIRNAME,
        ]
        for default_root in preferred_defaults:
            if default_root not in roots:
                roots.append(default_root)
        return roots

    def _build_mirror_roots(self) -> list[_MirrorRoot]:
        mirrors: list[_MirrorRoot] = []
        for entry in self._config_data.get("mirrors", []):
            if not isinstance(entry, dict):
                continue
            source = entry.get("source_root")
            destination = entry.get("wrapper_root")
            if not source or not destination:
                continue
            try:
                src_path = self._resolve_path(source)
                dst_path = self._resolve_path(destination)
            except TypeError:
                continue
            mirrors.append(_MirrorRoot(src_path, dst_path))
        return mirrors

    def _build_manual_wrappers(self) -> dict[Path, Path]:
        wrappers: dict[Path, Path] = {}
        entries = self._config_data.get("wrappers", [])
        if not isinstance(entries, Iterable):
            return wrappers
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            source = entry.get("source")
            wrapper = entry.get("wrapper")
            if not source or not wrapper:
                continue
            source_path = self._resolve_path(source)
            wrapper_path = self._resolve_path(wrapper)
            wrappers[source_path] = wrapper_path
        return wrappers

    def _discover_jbridger(self) -> Path | None:
        configured = self._config_data.get("jbridger_path")
        if configured:
            candidate = self._resolve_path(configured)
            if candidate.exists():
                return candidate
        for hint in self.DEFAULT_INSTALL_HINTS:
            candidate = hint / "jBridger.exe"
            if candidate.exists():
                return candidate
        return None

    # ------------------------------------------------------------------ #
    # Wrapper discovery                                                  #
    # ------------------------------------------------------------------ #
    def resolve_wrapper(self, plugin_path: Path) -> Path | None:
        """Return a jBridge wrapper for ``plugin_path`` if one exists."""

        resolved = self._resolve_path(plugin_path)

        direct = self._manual_wrappers.get(resolved)
        if direct and direct.exists():
            return direct

        for mirror in self._mirror_roots:
            try:
                relative = resolved.relative_to(mirror.source)
            except ValueError:
                continue
            for candidate in self._expand_variants(mirror.destination / relative):
                if candidate.exists():
                    return candidate

        for candidate in self._expand_variants(resolved):
            if candidate.exists():
                return candidate

        for root in self.wrapper_roots:
            for candidate in self._expand_variants(root / resolved.name):
                if candidate.exists():
                    return candidate
            located = self._find_in_root(root, resolved.name)
            if located:
                return located

        return None

    def _expand_variants(self, path: Path) -> list[Path]:
        """Return alternate filenames that jBridge commonly emits."""

        candidates = [path]
        suffix = path.suffix
        stem = path.stem
        if suffix:
            variants = [
                f"{stem}.64{suffix}",
                f"{stem}_64{suffix}",
                f"{stem} (jBridge){suffix}",
                f"{stem}.jBridge{suffix}",
            ]
            for name in variants:
                candidates.append(path.with_name(name))
        return candidates

    def _find_in_root(self, root: Path, filename: str) -> Path | None:
        key = (root, filename.lower())
        cached = self._name_cache.get(key)
        if cached is not None:
            return cached
        try:
            for candidate in root.rglob(filename):
                self._name_cache[key] = candidate
                return candidate
        except OSError:
            pass
        self._name_cache[key] = None
        return None

    # ------------------------------------------------------------------ #
    # Diagnostics                                                        #
    # ------------------------------------------------------------------ #
    def hint_for(self, plugin_path: Path | None = None) -> str | None:
        """Return a human-readable hint describing how to enable jBridge."""

        lines: list[str] = []
        primary_root = self.wrapper_roots[0] if self.wrapper_roots else None
        if primary_root:
            lines.append(f"- jBridge wrappers directory: {primary_root}")

        if self.jbridger_path:
            lines.append(f"- Detected jBridger.exe at: {self.jbridger_path}")
        else:
            hints = ", ".join(str(hint / 'jBridger.exe') for hint in self.DEFAULT_INSTALL_HINTS)
            lines.append(
                "- jBridger.exe not found. Set 'jbridger_path' inside "
                f"{self.config_path} (common locations: {hints})."
            )

        if plugin_path is not None:
            lines.append(
                "- After wrapping "
                f"{Path(plugin_path).name}, drop the generated dll/vst3 into the wrappers directory "
                f"or list it under 'wrappers' in {self.config_path.name}."
            )
            lines.append(
                "- Need a wrapper? The jBridge demonstration version works fine—run jBridger.exe, "
                "target the plugin, and save the 64-bit bridge into Bridged32BitPlugins."
            )

        if not lines:
            return None
        return "\n".join(lines)

    def describe_environment(self) -> dict[str, list[str] | str | None]:
        """Return raw data useful for status endpoints."""

        return {
            "config": str(self.config_path),
            "wrapper_roots": [str(root) for root in self.wrapper_roots],
            "mirrors": [f"{entry.source} -> {entry.destination}" for entry in self._mirror_roots],
            "has_manual_wrappers": bool(self._manual_wrappers),
            "jbridger_path": str(self.jbridger_path) if self.jbridger_path else None,
        }
