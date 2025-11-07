"""Build generated QSS overlays for every convertible theme."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys
from typing import Iterable, List

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from css_to_qss import generate_qss  # type: ignore
from ambiance.theming.config import THEME_DESCRIPTORS


LOG = logging.getLogger("build_themes")


def iter_convertible_themes(selected: Iterable[str] | None = None) -> List[str]:
    convertible = []
    for theme_id, descriptor in THEME_DESCRIPTORS.items():
        if descriptor.conversion is None or descriptor.source_css is None:
            continue
        convertible.append(theme_id)
    if selected:
        convertible = [theme for theme in convertible if theme in selected]
    return sorted(convertible)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--theme",
        action="append",
        help="Build only the specified theme (can be repeated)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show conversion diagnostics from css_to_qss",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    project_root = Path(__file__).resolve().parents[1]
    out_dir = (project_root / "themes" / "generated").resolve()

    targets = iter_convertible_themes(args.theme)
    if not targets:
        LOG.warning("No themes matched selection; nothing to do.")
        return 0

    success = True
    for theme_id in targets:
        descriptor = THEME_DESCRIPTORS[theme_id]
        source_css = (project_root / descriptor.source_css).resolve()  # type: ignore[arg-type]
        output_path = out_dir / f"{theme_id}.qss"

        if not source_css.exists():
            LOG.error("Theme %s source CSS missing at %s", theme_id, source_css)
            success = False
            continue

        try:
            stats = generate_qss(source_css, output_path, theme_id, verbose=args.verbose)
            LOG.info("Built %s (%d selectors)", theme_id, len(stats.used_selectors))
        except Exception as exc:
            LOG.error("Failed to build %s: %s", theme_id, exc)
            success = False

    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
