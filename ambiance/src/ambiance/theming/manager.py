from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Dict, Iterable, List, Optional, Tuple

from .config import (
    THEME_DESCRIPTORS,
    ThemeConversionConfig,
    ThemeDescriptor,
    ThemeTokens,
    ThemeMetrics,
)


_PLACEHOLDER_PATTERN = re.compile(r"\{([^}\n]+)\}")


@dataclass(frozen=True)
class ThemeDefinition:
    theme_id: str
    display_name: str
    stylesheet_path: Path
    source_css_path: Optional[Path]
    tokens: ThemeTokens
    metrics: Optional[ThemeMetrics]
    conversion: Optional[ThemeConversionConfig] = None

    @property
    def overlay_path(self) -> Path:
        generated_dir = self.stylesheet_path.parent / "generated"
        return generated_dir / f"{self.theme_id}.qss"


class ThemeManager:
    """Centralised theme loader and metadata provider."""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root
        self._definitions: Dict[str, ThemeDefinition] = {}
        self._load_definitions()
        if not self._definitions:
            raise RuntimeError("No theme descriptors resolved; ensure themes/ directory is present.")
        self._default_theme = "flat" if "flat" in self._definitions else next(iter(self._definitions.keys()))

    def _load_definitions(self) -> None:
        for descriptor in THEME_DESCRIPTORS.values():
            definition = self._create_definition(descriptor)
            if definition:
                self._definitions[definition.theme_id] = definition

    def _create_definition(self, descriptor: ThemeDescriptor) -> Optional[ThemeDefinition]:
        stylesheet_path = (self._project_root / descriptor.stylesheet).resolve()
        if not stylesheet_path.exists():
            print(f"[THEME] Warning: stylesheet missing for '{descriptor.theme_id}' ({stylesheet_path})")
            return None
        source_css_path: Optional[Path] = None
        if descriptor.source_css:
            candidate = (self._project_root / descriptor.source_css).resolve()
            if candidate.exists():
                source_css_path = candidate
            else:
                print(f"[THEME] Note: source CSS not found for '{descriptor.theme_id}' ({candidate})")
        return ThemeDefinition(
            theme_id=descriptor.theme_id,
            display_name=descriptor.display_name,
            stylesheet_path=stylesheet_path,
            source_css_path=source_css_path,
            tokens=descriptor.tokens,
            metrics=descriptor.metrics,
            conversion=descriptor.conversion,
        )

    @property
    def default_theme(self) -> str:
        return self._default_theme

    def theme_ids(self) -> Iterable[str]:
        return self._definitions.keys()

    def list_themes(self) -> List[ThemeDefinition]:
        return sorted(self._definitions.values(), key=lambda item: item.display_name.lower())

    def get_definition(self, theme_id: str) -> ThemeDefinition:
        if theme_id not in self._definitions:
            raise KeyError(f"Theme '{theme_id}' is not registered.")
        return self._definitions[theme_id]

    def tokens_for(self, theme_id: str) -> Optional[ThemeTokens]:
        definition = self._definitions.get(theme_id)
        return definition.tokens if definition else None

    def metrics_for(self, theme_id: str) -> Optional[ThemeMetrics]:
        definition = self._definitions.get(theme_id)
        return definition.metrics if definition else None

    def apply(self, theme_id: str, target_widget) -> str:
        definition = self.get_definition(theme_id)
        css_parts: List[str] = []
        base_css = self._resolve_placeholders(definition.stylesheet_path.read_text(encoding="utf-8"))
        css_parts.append(base_css)

        overlay_path = definition.overlay_path
        if definition.conversion and overlay_path.exists():
            overlay_css = self._resolve_placeholders(overlay_path.read_text(encoding="utf-8"))
            css_parts.append("/* Generated QSS overlay */\n" + overlay_css)

        combined = "\n\n".join(css_parts)
        target_widget.setStyleSheet(combined)
        return combined

    def _resolve_placeholders(self, css_text: str) -> str:
        def replacer(match: re.Match[str]) -> str:
            filename = match.group(1).strip()
            resolved = (self._project_root / filename).resolve()
            return resolved.as_posix()

        return _PLACEHOLDER_PATTERN.sub(replacer, css_text)
