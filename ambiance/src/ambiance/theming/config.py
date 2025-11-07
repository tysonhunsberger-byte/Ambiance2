from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ThemeTokens:
    """High-level design tokens for a theme."""

    window: str
    base: str
    alt: str
    button: str
    text: str
    button_text: str
    highlight: str
    highlight_text: str
    font_family: str
    font_size: int


@dataclass(frozen=True)
class ThemeMetrics:
    """Fine-grained layout metrics for theming."""

    taskbar_height: int
    taskbar_margins: Tuple[int, int, int, int]
    start_button_height: int
    start_button_extra_css: str = ""
    preferred_resolution: Optional[Tuple[int, int]] = None
    ui_scale: float = 1.0


@dataclass(frozen=True)
class ThemeConversionConfig:
    """Metadata required to convert CSS variants into QSS."""

    selector_map: Dict[str, Sequence[str]]
    manual_variables: Dict[str, str]


@dataclass(frozen=True)
class ThemeDescriptor:
    """Compile-time description of a theme."""

    theme_id: str
    display_name: str
    stylesheet: str
    source_css: Optional[str]
    tokens: ThemeTokens
    metrics: Optional[ThemeMetrics] = None
    conversion: Optional[ThemeConversionConfig] = None


_BASE_SELECTOR_MAP: Dict[str, Sequence[str]] = {
    ".window": ("QMdiSubWindow",),
    ".window:before": ("QMdiSubWindow",),
    ".title-bar": ("QMdiSubWindow::title",),
    ".window.glass > .title-bar": ("QMdiSubWindow::title",),
    ".title-bar-text": ("QMdiSubWindow::title",),
    ".title-bar.active": ("QMdiSubWindow::title",),
    ".window.active .title-bar": ("QMdiSubWindow::title",),
    ".window.active .title-bar .title-bar-text": ("QMdiSubWindow::title",),
    ".window .title-bar .title-bar-text": ("QMdiSubWindow::title",),
    ".window-body": ("QMdiSubWindow QWidget#qt_scrollarea_viewport",),
    ".window.is-bright .window-body": ("QMdiSubWindow QWidget#qt_scrollarea_viewport",),
    ".title-bar-controls button": (
        "QMdiSubWindow::close-button",
        "QMdiSubWindow::minimize-button",
        "QMdiSubWindow::maximize-button",
    ),
    ".title-bar-controls button:hover": (
        "QMdiSubWindow::close-button:hover",
        "QMdiSubWindow::minimize-button:hover",
        "QMdiSubWindow::maximize-button:hover",
    ),
    ".title-bar-controls button:active": (
        "QMdiSubWindow::close-button:pressed",
        "QMdiSubWindow::minimize-button:pressed",
        "QMdiSubWindow::maximize-button:pressed",
    ),
    ".title-bar-controls button:disabled": (
        "QMdiSubWindow::close-button:disabled",
        "QMdiSubWindow::minimize-button:disabled",
        "QMdiSubWindow::maximize-button:disabled",
    ),
}


def _clone_selector_map() -> Dict[str, Sequence[str]]:
    return {selector: tuple(targets) for selector, targets in _BASE_SELECTOR_MAP.items()}


THEME_DESCRIPTORS: Dict[str, ThemeDescriptor] = {
    "flat": ThemeDescriptor(
        theme_id="flat",
        display_name="Flat Dark",
        stylesheet="themes/flat.css",
        source_css=None,
        tokens=ThemeTokens(
            window="#222222",
            base="#1a1a1a",
            alt="#2a2a2a",
            button="#303030",
            text="#f3f5fa",
            button_text="#f3f5fa",
            highlight="#3164ff",
            highlight_text="#ffffff",
            font_family="Inter",
            font_size=10,
        ),
        metrics=ThemeMetrics(
            taskbar_height=36,
            taskbar_margins=(0, 0, 6, 0),
            start_button_height=36,
            start_button_extra_css="",
            preferred_resolution=None,
            ui_scale=1.0,
        ),
    ),
    "win7": ThemeDescriptor(
        theme_id="win7",
        display_name="Windows 7 Aero",
        stylesheet="themes/win7.css",
        source_css="node_modules/7.css/dist/7.css",
        tokens=ThemeTokens(
            window="#edf1f8",
            base="#ffffff",
            alt="#f0f4fb",
            button="#dce6f5",
            text="#0d2142",
            button_text="#0d2142",
            highlight="#3164ff",
            highlight_text="#ffffff",
            font_family="Segoe UI",
            font_size=10,
        ),
        metrics=ThemeMetrics(
            taskbar_height=36,
            taskbar_margins=(0, 0, 6, 0),
            start_button_height=36,
            start_button_extra_css="",
            preferred_resolution=(1280, 800),
            ui_scale=1.0,
        ),
        conversion=None,
    ),
    "winxp": ThemeDescriptor(
        theme_id="winxp",
        display_name="Windows XP Luna",
        stylesheet="themes/winxp.css",
        source_css="node_modules/xp.css/dist/XP.css",
        tokens=ThemeTokens(
            window="#ece9d8",
            base="#ffffff",
            alt="#f6f3e6",
            button="#ede9dd",
            text="#000000",
            button_text="#000000",
            highlight="#316ac5",
            highlight_text="#ffffff",
            font_family="Tahoma",
            font_size=10,
        ),
        metrics=ThemeMetrics(
            taskbar_height=36,
            taskbar_margins=(0, 0, 8, 0),
            start_button_height=36,
            start_button_extra_css="",
            preferred_resolution=(1152, 864),
            ui_scale=0.95,
        ),
        conversion=ThemeConversionConfig(
            selector_map=_clone_selector_map(),
            manual_variables={},
        ),
    ),
    "win98": ThemeDescriptor(
        theme_id="win98",
        display_name="Windows 98 Classic",
        stylesheet="themes/win98.css",
        source_css="node_modules/98.css/dist/98.css",
        tokens=ThemeTokens(
            window="#c0c0c0",
            base="#ffffff",
            alt="#d6d6d6",
            button="#c0c0c0",
            text="#000000",
            button_text="#000000",
            highlight="#000080",
            highlight_text="#ffffff",
            font_family="MS Sans Serif",
            font_size=10,
        ),
        metrics=ThemeMetrics(
            taskbar_height=36,
            taskbar_margins=(0, 2, 6, 2),
            start_button_height=36,
            start_button_extra_css="margin-bottom: 2px;",
            preferred_resolution=(1024, 768),
            ui_scale=0.9,
        ),
    ),
}
