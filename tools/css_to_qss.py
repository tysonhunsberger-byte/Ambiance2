"""Prototype converter to translate a subset of CSS rules into Qt Style Sheets (QSS).

This script demonstrates a pipeline that ingests a web-focused stylesheet (for example
7.css) and emits a trimmed QSS file we can load in Ambiance.  It intentionally handles
only a small slice of selectors and properties so we can evaluate feasibility before
investing in a full conversion.
"""

from __future__ import annotations

import argparse
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import math
import sys
from typing import Dict, List, Optional, Sequence, Tuple

import cssutils  # type: ignore


LOG = logging.getLogger("css_to_qss")
cssutils.log.setLevel(logging.CRITICAL)

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "ambiance" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ambiance.theming.config import THEME_DESCRIPTORS

_CONVERTIBLE_THEMES = sorted(
    theme_id for theme_id, descriptor in THEME_DESCRIPTORS.items() if descriptor.conversion is not None
)

# Properties we keep verbatim (after value normalisation).
PROPERTY_ALLOWLIST = {
    "background",
    "background-color",
    "border",
    "border-radius",
    "color",
    "font",
    "font-family",
    "font-size",
    "font-weight",
    "padding",
    "padding-top",
    "padding-bottom",
    "padding-left",
    "padding-right",
}

COLOR_RE = re.compile(r"^#([0-9a-fA-F]{3,8})$|^rgba?\(.*\)$")
VAR_RE = re.compile(r"var\((--[^)]+)\)")
IMPORTANT_RE = re.compile(r"\s*!important\s*$", re.IGNORECASE)
UNSUPPORTED_VALUE_PATTERNS = (
    "radial-gradient",
    "url(",
    "calc(",
    "box-shadow",
    "filter",
    "backdrop-filter",
    "-webkit-",
    "flex",
    "display",
)


@dataclass
class ConversionStats:
    used_selectors: Dict[str, int]
    skipped_selectors: Dict[str, str]
    skipped_properties: Dict[str, List[str]]

    def __init__(self) -> None:
        self.used_selectors = {}
        self.skipped_selectors = {}
        self.skipped_properties = {}

    def note_selector(self, css_selector: str) -> None:
        self.used_selectors[css_selector] = self.used_selectors.get(css_selector, 0) + 1

    def note_skipped_selector(self, css_selector: str, reason: str) -> None:
        self.skipped_selectors[css_selector] = reason

    def note_skipped_property(self, css_selector: str, prop: str) -> None:
        self.skipped_properties.setdefault(css_selector, []).append(prop)


def normalize_selector(selector: str) -> str:
    """Collapse whitespace so we have stable keys in SELECTOR_MAP."""
    # cssutils already normalises most whitespace but we double check for safety.
    parts = selector.strip().split()
    return " ".join(parts)


def extract_variables(
    sheet: cssutils.css.CSSStyleSheet,
    manual_fallbacks: Dict[str, str],
) -> Dict[str, str]:
    """Collect CSS custom properties defined in any :root rule."""
    variables: Dict[str, str] = {}
    for rule in sheet:
        if getattr(rule, "type", None) != rule.STYLE_RULE:
            continue
        selectors = [normalize_selector(sel.selectorText) for sel in rule.selectorList]
        if ":root" not in selectors:
            continue
        for prop in rule.style:
            name = prop.name.strip()
            if name.startswith("--"):
                value = prop.value.strip()
                value = IMPORTANT_RE.sub("", value).strip()
                variables[name] = value
    variables.update(manual_fallbacks)
    return variables


def resolve_value(value: str, variables: Dict[str, str]) -> str:
    """Replace CSS variables with literal values when possible."""

    def replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        return variables.get(key, match.group(0))

    resolved = value
    for _ in range(5):
        updated = VAR_RE.sub(replacer, resolved)
        if updated == resolved:
            break
        resolved = updated
    return IMPORTANT_RE.sub("", resolved).strip()


def is_supported_value(value: str) -> bool:
    return not any(token in value for token in UNSUPPORTED_VALUE_PATTERNS)


def split_css_arguments(argument_string: str) -> List[str]:
    """Split a comma-separated argument list while respecting nested parentheses."""
    parts: List[str] = []
    depth = 0
    current: List[str] = []
    for char in argument_string:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue
        current.append(char)
    if current:
        part = "".join(current).strip()
        if part:
            parts.append(part)
    return parts


def parse_gradient_direction(token: str) -> Tuple[float, float, float, float]:
    """Translate CSS gradient directions to QSS coordinates."""
    mapping = {
        "to bottom": (0.0, 0.0, 0.0, 1.0),
        "to top": (0.0, 1.0, 0.0, 0.0),
        "to right": (0.0, 0.0, 1.0, 0.0),
        "to left": (1.0, 0.0, 0.0, 0.0),
        "to bottom right": (0.0, 0.0, 1.0, 1.0),
        "to top right": (0.0, 1.0, 1.0, 0.0),
        "to bottom left": (1.0, 0.0, 0.0, 1.0),
        "to top left": (1.0, 1.0, 0.0, 0.0),
    }
    token_norm = token.lower().strip()
    if token_norm in mapping:
        return mapping[token_norm]
    if token_norm.endswith("deg"):
        try:
            angle = float(token_norm.rstrip("deg"))
        except ValueError:
            return (0.0, 0.0, 0.0, 1.0)
        radians = math.radians(angle)
        dx = math.sin(radians)
        dy = -math.cos(radians)
        x1 = 0.5 - 0.5 * dx
        y1 = 0.5 - 0.5 * dy
        x2 = 0.5 + 0.5 * dx
        y2 = 0.5 + 0.5 * dy
        return (x1, y1, x2, y2)
    return (0.0, 0.0, 0.0, 1.0)


def _format_float(value: float) -> str:
    text = f"{value:.3f}"
    text = text.rstrip("0").rstrip(".")
    return text or "0"


def parse_gradient_stops(parts: List[str]) -> List[Tuple[str, float]]:
    """Convert `color [percent]` tokens into QSS stop tuples."""
    stops: List[Tuple[str, Optional[float]]] = []
    for index, raw in enumerate(parts):
        tokens = raw.split()
        if not tokens:
            continue
        color = tokens[0]
        offset: Optional[float] = None
        for token in tokens[1:]:
            if token.endswith("%"):
                try:
                    offset = max(0.0, min(1.0, float(token.rstrip("%")) / 100.0))
                except ValueError:
                    offset = None
                break
        stops.append((color, offset))

    if not stops:
        return []

    total = max(1, len(stops) - 1)
    parsed: List[Tuple[str, float]] = []
    for idx, (color, offset) in enumerate(stops):
        if offset is None:
            offset = idx / total
        parsed.append((color, offset))
    return parsed


def linear_gradient_to_qlinear(value: str) -> Optional[str]:
    """Convert a CSS linear-gradient to a QSS qlineargradient expression."""
    value = value.strip()
    if not value.lower().startswith("linear-gradient("):
        return None

    inner = value[value.find("(") + 1 : value.rfind(")")]
    arguments = split_css_arguments(inner)
    if not arguments:
        return None

    coords = (0.0, 0.0, 0.0, 1.0)
    stop_tokens = arguments
    first = arguments[0].lower()
    if first.startswith("to ") or first.endswith("deg"):
        coords = parse_gradient_direction(arguments[0])
        stop_tokens = arguments[1:]
    if not stop_tokens:
        return None

    stops = parse_gradient_stops(stop_tokens)
    if not stops:
        return None

    stop_parts = [f"stop:{_format_float(offset)} {color}" for color, offset in stops]
    x1, y1, x2, y2 = coords
    return (
        "qlineargradient("
        f"x1:{_format_float(x1)}, y1:{_format_float(y1)}, "
        f"x2:{_format_float(x2)}, y2:{_format_float(y2)}, "
        + ", ".join(stop_parts)
        + ")"
    )


def transform_property(name: str, value: str) -> tuple[str, str] | None:
    """Map CSS property names/values to QSS equivalents."""
    name = name.strip().lower()
    if name not in PROPERTY_ALLOWLIST:
        return None

    if name == "background":
        gradient = linear_gradient_to_qlinear(value)
        if gradient:
            return "background", gradient
        if COLOR_RE.match(value):
            return "background-color", value
        # Only colors translate cleanly; gradients need bespoke conversion.
        return None

    return name, value


def convert_rules(
    sheet: cssutils.css.CSSStyleSheet,
    variables: Dict[str, str],
    selector_map: Dict[str, Sequence[str]],
) -> tuple[OrderedDict[str, OrderedDict[str, str]], ConversionStats]:
    """Convert recognised selectors into QSS rules."""
    rules: OrderedDict[str, OrderedDict[str, str]] = OrderedDict()
    stats = ConversionStats()

    for rule in sheet:
        if getattr(rule, "type", None) != rule.STYLE_RULE:
            continue

        selectors = [
            normalize_selector(sel.selectorText)
            for sel in rule.selectorList
        ]
        for selector in selectors:
            mapped_targets = selector_map.get(selector)
            if not mapped_targets:
                stats.note_skipped_selector(selector, "selector not mapped")
                continue

            properties: List[tuple[str, str]] = []
            for prop in rule.style.getProperties(all=True):
                raw_value = resolve_value(prop.value, variables)
                if not raw_value or not is_supported_value(raw_value):
                    stats.note_skipped_property(selector, prop.name)
                    continue

                transformed = transform_property(prop.name, raw_value)
                if not transformed:
                    stats.note_skipped_property(selector, prop.name)
                    continue

                properties.append(transformed)

            if not properties:
                continue

            stats.note_selector(selector)

            for target in mapped_targets:
                bucket = rules.setdefault(target, OrderedDict())
                for name, value in properties:
                    bucket[name] = value

    return rules, stats


def serialise_qss(rules: OrderedDict[str, OrderedDict[str, str]]) -> str:
    """Render QSS from the collected selector/property mapping."""
    lines: List[str] = [
        "/* Generated from CSS via css_to_qss.py (prototype). */",
        "",
    ]
    for selector, props in rules.items():
        if not props:
            continue
        lines.append(f"{selector} {{")
        for name, value in props.items():
            lines.append(f"    {name}: {value};")
        lines.append("}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_stats(stats: ConversionStats) -> None:
    LOG.info("Converted selectors: %s", ", ".join(sorted(stats.used_selectors)))
    if stats.skipped_selectors:
        for selector, reason in sorted(stats.skipped_selectors.items()):
            LOG.debug("Skipped selector '%s': %s", selector, reason)
    if stats.skipped_properties:
        for selector, props in stats.skipped_properties.items():
            LOG.debug("Skipped properties for '%s': %s", selector, ", ".join(props))


def generate_qss(css_path: Path, output_path: Path, theme_id: str, verbose: bool = False) -> ConversionStats:
    descriptor = THEME_DESCRIPTORS.get(theme_id)
    if descriptor is None:
        raise ValueError(f"Unknown theme preset '{theme_id}'")
    if descriptor.conversion is None:
        raise ValueError(f"Theme '{theme_id}' does not have conversion metadata defined.")

    if not css_path.exists():
        raise FileNotFoundError(f"CSS file {css_path} does not exist")

    conversion = descriptor.conversion
    sheet = cssutils.parseFile(str(css_path))
    variables = extract_variables(sheet, conversion.manual_variables)
    rules, stats = convert_rules(sheet, variables, conversion.selector_map)
    qss_text = serialise_qss(rules)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(qss_text, encoding="utf-8")

    if verbose:
        write_stats(stats)
    return stats


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("css", type=Path, help="Input CSS file (e.g. 7.css)")
    parser.add_argument(
        "output",
        type=Path,
        help="Where to write the generated QSS prototype",
    )
    parser.add_argument(
        "--theme",
        choices=_CONVERTIBLE_THEMES,
        default="win7",
        help="Theme preset defining selector mapping and variable fallbacks",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Emit detailed debug logs for skipped selectors/properties",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    try:
        stats = generate_qss(args.css, args.output, args.theme, verbose=args.verbose)
    except Exception as exc:
        LOG.error("Failed to generate QSS: %s", exc)
        return 1

    if not args.verbose:
        write_stats(stats)
    LOG.info("Wrote %s", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
