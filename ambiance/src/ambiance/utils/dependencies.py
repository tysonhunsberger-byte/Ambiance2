from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
from typing import Iterable, Sequence, Tuple
from urllib.request import urlopen

CSS_TARGETS: Tuple[Tuple[str, str], ...] = (
    ("98.css", "node_modules/98.css/dist/98.css"),
    ("xp.css", "node_modules/xp.css/dist/XP.css"),
    ("7.css", "node_modules/7.css/dist/7.css"),
)

_NODE_INSTALL_ATTEMPTED = False
_CARLA_CHECKED = False
_CARLA_WIN64_CANDIDATES: Tuple[str, ...] = (
    "carla-bridge-win64.exe",
    "carla-bridge-native.exe",
    "libcarla_standalone2.dll",
)


def ensure_vendor_css(project_root: Path, targets: Iterable[Tuple[str, str]] | None = None) -> None:
    """
    Ensure CSS packages used by the desktop UI exist inside node_modules.

    Attempts to run `npm install` the first time missing assets are detected.
    Subsequent calls within the same process become no-ops.
    """

    resolved_targets: Sequence[Tuple[str, Path]] = tuple(
        (name, (project_root / rel).resolve())
        for name, rel in (tuple(targets) if targets is not None else CSS_TARGETS)
    )
    missing = [(name, path) for name, path in resolved_targets if not path.exists()]
    if not missing:
        return

    missing_names = ", ".join(name for name, _ in missing)
    print(f"[DEPS] Missing vendor CSS ({missing_names}); attempting npm install...")
    if not _run_npm_install(project_root):
        print("[DEPS] npm install skipped or failed; CSS assets may remain unavailable.")
        return

    still_missing = [(name, path) for name, path in resolved_targets if not path.exists()]
    if still_missing:
        for name, path in still_missing:
            print(f"[DEPS] Warning: {name} CSS still missing at {path}")
    else:
        print("[DEPS] Vendor CSS assets installed successfully.")


def _run_npm_install(project_root: Path) -> bool:
    global _NODE_INSTALL_ATTEMPTED
    if _NODE_INSTALL_ATTEMPTED:
        return False
    _NODE_INSTALL_ATTEMPTED = True

    package_json = project_root / "package.json"
    if not package_json.exists():
        print(f"[DEPS] package.json not found under {project_root}; skipping npm install.")
        return False

    npm_exe = shutil.which("npm")
    if npm_exe is None:
        print("[DEPS] npm executable not found in PATH; cannot install CSS dependencies.")
        return False

    try:
        subprocess.run(
            [
                npm_exe,
                "install",
                "--no-audit",
                "--no-fund",
            ],
            cwd=str(project_root),
            check=True,
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"[DEPS] npm install failed: {exc}")
        return False

    return True


def ensure_carla_win64(project_root: Path) -> bool:
    """
    Ensure the Carla 64-bit bridge executable is available on Windows hosts.

    Returns True when the binary exists after optional auto-download attempts.
    """

    if os.name != "nt":
        return True

    global _CARLA_CHECKED
    if _CARLA_CHECKED:
        return True

    try:
        from ambiance.integrations.carla_host import CARLA_WIN_RELEASES  # type: ignore
    except Exception as exc:
        print(f"[DEPS] Carla metadata import failed: {exc}")
        return False

    search_roots = list(_collect_carla_search_roots(project_root))
    existing, is_win64 = _locate_existing_bridge(search_roots)
    if existing and is_win64:
        _CARLA_CHECKED = True
        return True
    if existing and not is_win64:
        print(f"[DEPS] Carla binaries detected at {existing.parent} but appear to be 32-bit; looking for win64 build.")

    release = _select_win64_release(CARLA_WIN_RELEASES)
    if not release:
        print("[DEPS] No Carla release metadata available; cannot auto-install.")
        _CARLA_CHECKED = True
        return False

    deps_root = _resolve_carla_deps_root(project_root)
    destination = deps_root / str(release.get("name", "Carla-win64"))
    print(f"[DEPS] Carla installation detected but win64 bridge missing; downloading binaries into {deps_root} ...")
    try:
        _download_carla_archive(str(release.get("url")), destination)
    except Exception as exc:
        print(f"[DEPS] Failed to download Carla release: {exc}")
        _CARLA_CHECKED = True
        return False

    search_roots.extend(_expand_search_roots(destination))
    existing, is_win64 = _locate_existing_bridge(search_roots)
    if existing and is_win64:
        print(f"[DEPS] Carla bridge available at {existing.parent}")
        _CARLA_CHECKED = True
        return True

    if existing and not is_win64:
        print(f"[DEPS] Carla install at {existing.parent} lacks the 64-bit bridge binaries.")

    print(
        "[DEPS] Carla 64-bit bridge is still unavailable.\n"
        "       Download Carla-2.5.10-win64.zip from https://github.com/falkTX/Carla/releases\n"
        "       and extract it into deps/carla_binaries (or set CARLA_ROOT) so that "
        "Carla's bridge executable or libcarla_standalone2.dll is present."
    )
    _CARLA_CHECKED = True
    return False


def _select_win64_release(releases: Sequence[dict[str, object]]) -> dict[str, object] | None:
    for release in releases:
        name = str(release.get("name", "")).lower()
        if "win64" in name:
            return release
    return releases[0] if releases else None


def _download_carla_archive(url: str, destination: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        archive_path = tmp_path / "carla-release.zip"
        with urlopen(url) as response, archive_path.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(tmp_path)

        extracted_root: Path | None = None
        for child in tmp_path.iterdir():
            if child.is_dir():
                extracted_root = child
                if child.name == destination.name:
                    break
        if extracted_root is None:
            raise FileNotFoundError("Downloaded Carla archive did not contain a release folder")

        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(extracted_root), str(destination))


def _collect_carla_search_roots(project_root: Path) -> Iterable[Path]:
    seen: set[Path] = set()
    for candidate in _candidate_root_paths(project_root):
        for expanded in _expand_search_roots(candidate):
            if expanded in seen:
                continue
            seen.add(expanded)
            yield expanded


def _candidate_root_paths(project_root: Path) -> Iterable[Path]:
    entries = [
        os.environ.get("CARLA_ROOT"),
        os.environ.get("CARLA_HOME"),
    ]
    for entry in entries:
        if entry:
            yield Path(entry)

    guesses = [
        project_root / "Carla-main",
        project_root / "Carla",
        project_root / "ambiance" / "deps" / "carla_binaries",
        project_root / "deps" / "carla_binaries",
        project_root / "ambiance" / "deps",
        project_root / "deps",
        project_root,
    ]
    for guess in guesses:
        yield guess
        if guess.exists():
            for child in guess.glob("Carla*/"):
                yield child


def _expand_search_roots(path: Path) -> list[Path]:
    expanded: list[Path] = []
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = path
    candidates = [
        resolved,
        resolved / "Carla",
        resolved / "Carla" / "bin",
        resolved / "bin",
    ]
    for candidate in candidates:
        expanded.append(candidate)
    return expanded


def _locate_existing_bridge(search_roots: Iterable[Path]) -> Tuple[Path | None, bool]:
    fallback: Path | None = None
    for directory in search_roots:
        if not directory or not directory.exists():
            continue
        for filename in _CARLA_WIN64_CANDIDATES:
            candidate = directory / filename
            if candidate.exists():
                if _is_probably_win64_binary(candidate):
                    return candidate, True
                if fallback is None:
                    fallback = candidate
    return fallback, False


def _is_probably_win64_binary(candidate: Path) -> bool:
    """Heuristic to detect whether a Carla binary path refers to a 64-bit build."""
    markers = ("win64", "x64", "64bit", "64-bit")
    filename = candidate.name.lower()
    if any(marker in filename for marker in markers):
        return True
    parents = [part.lower() for part in candidate.parts]
    return any(marker in part for marker in markers for part in parents)


def _resolve_carla_deps_root(project_root: Path) -> Path:
    for candidate in (
        project_root / "ambiance" / "deps" / "carla_binaries",
        project_root / "deps" / "carla_binaries",
    ):
        if candidate.exists():
            return candidate
    return project_root / "ambiance" / "deps" / "carla_binaries"
