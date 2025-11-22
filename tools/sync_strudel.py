"""Sync the Strudel web bundle into resources/strudel/dist."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
import shlex
import shutil

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "resources" / "strudel" / "dist"
PNPM_FILTER = "./website"


def _candidate_sources() -> list[Path]:
    env_path = os.environ.get("STRUDEL_REPO")
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.extend(
        [
            REPO_ROOT / "strudel",
            REPO_ROOT / "resources" / "strudel",
            REPO_ROOT / "deps" / "strudel",
            REPO_ROOT.parent / "strudel",
        ]
    )
    return candidates


def _detect_source() -> Path | None:
    for candidate in _candidate_sources():
        if candidate.is_dir():
            return candidate
    return None


def _run(cmd: list[str], cwd: Path) -> None:
    print(f"[sync-strudel] $ {' '.join(cmd)} (cwd={cwd})")
    try:
        subprocess.run(cmd, cwd=str(cwd), check=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Failed to run {' '.join(cmd)} – is '{cmd[0]}' installed and on PATH?"
        ) from exc


def _classify_source(source: Path) -> str:
    if not source.exists():
        raise FileNotFoundError(f"Strudel source not found at {source}")
    if (source / "pnpm-workspace.yaml").exists() or (source / "packages" / "web").exists():
        return "repo"
    if (source / "_astro").exists() or (source / "index.html").exists():
        return "dist"
    raise FileNotFoundError(
        f"{source} does not look like a Strudel repository or built dist.\n"
        "If you intended to reference the repo, point --source to the checkout root.\n"
        "If you already have a built bundle, point --source to that dist directory."
    )


def sync_strudel(
    source: Path,
    dest: Path,
    *,
    pnpm_cmd: list[str],
    install: bool,
    build: bool,
) -> None:
    source_type = _classify_source(source)
    if source_type == "repo":
        repo_root = source
        if install:
            _run(pnpm_cmd + ["install"], cwd=repo_root)
        if build:
            # Ensure doc.json is generated before bundling the website.
            _run(pnpm_cmd + ["run", "jsdoc-json"], cwd=repo_root)
            _run(pnpm_cmd + ["--filter", PNPM_FILTER, "build"], cwd=repo_root)
        dist_src = repo_root / "website" / "dist"
        if not dist_src.exists():
            raise FileNotFoundError(
                f"{dist_src} missing after build. Did the Strudel build succeed?"
            )
    else:
        if install or build:
            print("[sync-strudel] Source looks like an already-built dist; skipping install/build steps.")
        dist_src = source

    dest = dest.resolve()
    dist_src = dist_src.resolve()
    if dest == dist_src:
        raise ValueError("Destination directory is the same as the source; nothing to copy.")

    if dest.exists():
        print(f"[sync-strudel] Removing existing {dest}")
        shutil.rmtree(dest)
    print(f"[sync-strudel] Copying {dist_src} -> {dest}")
    shutil.copytree(dist_src, dest)
    print("[sync-strudel] Done. Restart Ambiance to pick up the new bundle.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync the Strudel web bundle into Ambiance.")
    parser.add_argument(
        "--source",
        type=Path,
        help="Path to the Strudel repo or an already-built dist/ directory (default: auto-detect repo).",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Destination directory for the web bundle (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--pnpm",
        default="pnpm",
        help="pnpm command to run (default: 'pnpm'). Supports quotes, e.g. --pnpm \"corepack pnpm\".",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Run `pnpm install` before building.",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help=f"Skip `pnpm --filter {PNPM_FILTER} build` (assumes dist is already available).",
    )
    return parser.parse_args(argv)


def _prepare_pnpm_command(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw:
        raise ValueError("Invalid --pnpm command.")

    def _strip_quotes(value: str) -> str:
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            return value[1:-1]
        return value

    stripped = _strip_quotes(raw)
    candidate_path = Path(stripped)
    if candidate_path.exists():
        return [str(candidate_path)]

    parts = shlex.split(raw, posix=False)
    if not parts:
        raise ValueError("Invalid --pnpm command.")
    first_candidate = Path(parts[0].strip('"'))
    if first_candidate.exists():
        parts[0] = str(first_candidate)
        return parts

    def _resolve_windows_shim(cmd: str) -> str | None:
        if os.name != "nt":
            return None
        pathext = os.environ.get("PATHEXT", "").split(";")
        possible = [f"{cmd}{ext.lower()}" for ext in pathext if ext]
        for suffix in [".cmd", ".bat", ".exe"]:
            possible.append(cmd + suffix)
        for name in possible:
            path = shutil.which(name)
            if path:
                return path
        return None

    resolved_cmd = shutil.which(parts[0])
    if not resolved_cmd:
        resolved_cmd = _resolve_windows_shim(parts[0])

    if resolved_cmd:
        parts[0] = resolved_cmd
        return parts

    if parts[0] == "pnpm" and shutil.which("corepack"):
        print("[sync-strudel] 'pnpm' not found on PATH; using 'corepack pnpm'.")
        return ["corepack", "pnpm"] + parts[1:]

    raise FileNotFoundError(
        f"Unable to locate '{parts[0]}' on PATH. "
        "Install pnpm or pass --pnpm \"C:/path/to/pnpm.exe\" (or \"corepack pnpm\")."
    )
    return parts


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    source = args.source or _detect_source()
    if not source:
        print(
            "Unable to locate the Strudel repository. "
            "Specify --source or set STRUDEL_REPO to the checkout path.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        sync_strudel(
            source=source,
            dest=args.dest,
        pnpm_cmd=_prepare_pnpm_command(args.pnpm),
        install=args.install,
        build=not args.no_build,
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover - external command failure
        print(f"[sync-strudel] Command failed: {exc}", file=sys.stderr)
        sys.exit(exc.returncode or 1)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
