"""Runtime coordination for the optional JUCE based VST3 host.

This module does *not* embed the JUCE host inside the Python process.  Instead
it provides a thin management layer that discovers an out-of-process JUCE
application and launches it when the user requests to see a plugin's native UI.

Why an external process?  Shipping the JUCE toolchain (and a fully fledged VST
host) inside this environment is not feasible: it requires a native compiler,
platform specific SDKs, and GPU access for many plugin editors.  The best we
can offer here is to wire Ambiance's browser UI to a desktop companion binary
that the user can build locally.  That companion is responsible for the actual
real-time audio processing and UI embedding.  The Python layer tracks its
availability so the browser can surface actionable guidance instead of failing
silently.

The corresponding JUCE application lives in ``cpp/juce_host``.  It mirrors the
behaviour of the JUCE "Audio Plugin Host" example in a drastically trimmed
form: it loads a single plugin specified on the command line, opens its native
editor, and wires the processor to the system's default audio and MIDI devices.
This module keeps tabs on whether that binary exists and provides convenience
helpers to launch or terminate it.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Any


def _search_for_host_binaries(root: Path, max_depth: int = 5) -> list[Path]:
    """Search ``root`` for executables that look like the JUCE host."""

    if not root.exists():
        return []

    matches: list[Path] = []
    stack: list[tuple[Path, int]] = [(root, 0)]

    while stack:
        current, depth = stack.pop()
        if depth > max_depth or not current.exists():
            continue

        if current.is_file():
            name = current.name.lower()
            looks_like_host = "pluginhost" in name or (
                "plugin" in name and "host" in name
            )
            if looks_like_host and (
                current.suffix in {"", ".exe"} or name.endswith(".app")
            ):
                matches.append(current)
            continue

        if not current.is_dir():
            continue

        try:
            entries = list(current.iterdir())
        except PermissionError:  # pragma: no cover - defensive on Windows paths
            continue

        for entry in entries:
            stack.append((entry, depth + 1))

    return matches


def _candidate_paths(base_dir: Path) -> list[Path]:
    """Return likely locations for the JUCE host executable."""

    roots = [
        Path("cpp") / "juce_host" / "build",
        Path("build") / "juce_host",
    ]
    binary_names = [
        Path("JucePluginHost"),
        Path("JucePluginHost.exe"),
        Path("juce_plugin_host"),
    ]

    # Visual Studio generators drop the executable in per-configuration
    # subdirectories (e.g. Release/JucePluginHost.exe).  Xcode places the
    # binary inside a .app bundle.  Collect all of these common variants so the
    # host is discovered regardless of the chosen toolchain.
    variants: list[Path] = []
    configs = ["Release", "Debug"]

    for root in roots:
        for name in binary_names:
            variants.append(base_dir / root / name)
            for config in configs:
                variants.append(base_dir / root / config / name)
                variants.append(base_dir / root / "JucePluginHost" / config / name)
            variants.append(base_dir / root / "JucePluginHost" / name)

        app_binary = Path("JucePluginHost.app") / "Contents" / "MacOS" / "JucePluginHost"
        variants.append(base_dir / root / app_binary)
        for config in configs:
            variants.append(base_dir / root / config / app_binary)
            variants.append(base_dir / root / "JucePluginHost" / config / app_binary)

    # Some toolchains (notably Visual Studio with default multi-config
    # generators) emit executables in nested "*_artefacts/Release/Standalone"
    # folders.  Fall back to a bounded search so we surface those layouts as
    # well without forcing the user to manually configure JUCE_VST3_HOST.
    for root in roots:
        root_path = base_dir / root
        variants.extend(_search_for_host_binaries(root_path))

    final_variants: list[Path] = []
    seen: set[Path] = set()

    for variant in variants:
        if variant not in seen:
            final_variants.append(variant)
            seen.add(variant)

    return final_variants


@dataclass(slots=True)
class JuceHostStatus:
    """Snapshot of the JUCE host availability and runtime state."""

    available: bool
    executable: str | None
    running: bool
    plugin_path: str | None
    last_error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "executable": self.executable,
            "running": self.running,
            "plugin_path": self.plugin_path,
            "last_error": self.last_error,
        }


class JuceVST3Host:
    """Lifecycle helper for the optional JUCE desktop host."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self._executable = self._discover_executable()
        self._process: subprocess.Popen[str] | None = None
        self._plugin_path: Path | None = None
        self._last_error: str | None = None

    # ------------------------------------------------------------------
    # Discovery helpers
    # ------------------------------------------------------------------
    def _discover_executable(self) -> Path | None:
        env = os.environ.get("JUCE_VST3_HOST")
        if env:
            candidate = Path(env)
            if candidate.exists() and candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
        for path in _candidate_paths(self.base_dir):
            if path.exists() and path.is_file() and os.access(path, os.X_OK):
                return path
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def status(self) -> JuceHostStatus:
        available = self._executable is not None
        running = self._process is not None and self._process.poll() is None
        if self._process is not None and not running:
            # Process exited – capture exit code for diagnostics and drop state
            code = self._process.poll()
            if code not in (0, None):
                self._last_error = f"JUCE host exited with code {code}"
            self._process = None
            self._plugin_path = None
        plugin_path = str(self._plugin_path) if self._plugin_path else None
        executable = str(self._executable) if self._executable else None
        return JuceHostStatus(
            available=available,
            executable=executable,
            running=running,
            plugin_path=plugin_path,
            last_error=self._last_error,
        )

    def refresh_executable(self) -> None:
        """Re-run discovery to pick up a newly built host binary."""

        self._executable = self._discover_executable()

    def launch(self, plugin_path: str | os.PathLike[str]) -> JuceHostStatus:
        """Launch the JUCE host process for a given plugin path."""

        plugin = Path(plugin_path)
        if not plugin.exists():
            self._last_error = f"Plugin path does not exist: {plugin}"
            return self.status()
        if self._process is not None and self._process.poll() is None:
            self._last_error = "JUCE host already running"
            return self.status()
        if self._executable is None:
            self._last_error = (
                "JUCE host binary not found. Build cpp/juce_host first or set "
                "JUCE_VST3_HOST to point at the executable."
            )
            return self.status()

        try:
            self._process = subprocess.Popen(
                [str(self._executable), str(plugin.resolve())],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._plugin_path = plugin
            self._last_error = None
        except OSError as exc:  # pragma: no cover - system dependent failure
            self._last_error = f"Failed to launch JUCE host: {exc}"
            self._process = None
            self._plugin_path = None
        return self.status()

    def terminate(self) -> JuceHostStatus:
        """Terminate the JUCE host if it is currently running."""

        if self._process is None:
            self._plugin_path = None
            return self.status()
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:  # pragma: no cover - rare
                self._process.kill()
                self._process.wait()
        self._process = None
        self._plugin_path = None
        return self.status()


__all__ = ["JuceVST3Host", "JuceHostStatus"]

