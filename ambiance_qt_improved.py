"""Ambiance - Improved Qt application (Plugin Rack shell).

This file provides a clean, minimal Qt application with a working Plugin Rack
UI backed by PluginRackManager and an optional Carla host for auditioning the
selected plugin. It’s structured to keep VS Code/Pylance happy and is easy to
extend.
"""

from __future__ import annotations

import os
import sys
import logging
import json
from collections import deque
from pathlib import Path, PurePosixPath
from typing import Optional, TYPE_CHECKING

os.environ.setdefault("JACK_NO_START_SERVER", "1")

if TYPE_CHECKING:
    from ambiance.integrations.carla_host import CarlaVSTHost
import threading
import http.server
import socketserver
from http import HTTPStatus
from functools import partial
import time
import base64
import mimetypes
import posixpath
from urllib.parse import urlparse, unquote, urljoin
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

os.environ.setdefault("QT_API", "pyqt6")

LOGGER = logging.getLogger("ambiance.ui")

STRUDEL_REMOTE_BASE = "https://strudel.cc/"
STRUDEL_PROXY_PREFIX = "/strudel-live"
STRUDEL_PROXY_TIMEOUT = 12
STRUDEL_PROXY_USER_AGENT = "AmbianceStrudelProxy/1.0"
STRUDEL_PROXY_HEADER_BLOCKLIST = {
    "content-encoding",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "upgrade",
    "x-frame-options",
    "content-security-policy",
    "strict-transport-security",
}
STRUDEL_PROXY_ASSET_PREFIXES = (
    "/_astro/",
    "/icons/",
    "/img/",
    "/fonts/",
    "/assets/",
)
STRUDEL_PROXY_ASSET_EXACT = (
    "/favicon.ico",
    "/manifest.webmanifest",
    "/robots.txt",
    "/rss.xml",
    "/make-scrollable-code-focusable.js",
)

from qtpy.QtCore import Qt, QTimer, QObject, Signal, Slot, QUrl, QPointF, QPoint
from qtpy.QtGui import QTextCursor, QWindow, QMouseEvent, QColor, QPalette, QPixmap, QBrush, QIcon, QFont
from qtpy.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QGroupBox,
    QFrame,
    QSizePolicy,
    QSlider,
    QTabWidget,
    QPlainTextEdit,
    QComboBox,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QMdiArea,
    QMdiSubWindow,
    QMessageBox,
)

# Windows-specific imports for window embedding
if os.name == 'nt':
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32

    # Windows API constants
    GWL_STYLE = -16
    WS_CHILD = 0x40000000
    WS_VISIBLE = 0x10000000
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010

# Make in-repo src importable without installation
_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "ambiance" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Plugin rack manager (required)
try:
    from ambiance.integrations.plugins import PluginRackManager  # type: ignore
except Exception as _e:  # pragma: no cover
    PluginRackManager = None  # type: ignore
    _PLUGINS_IMPORT_ERROR = str(_e)

# Optional Carla host
try:
    from ambiance.integrations.carla_host import CarlaVSTHost, CarlaHostError  # type: ignore
    CARLA_AVAILABLE = True
except Exception as _ce:  # pragma: no cover
    CarlaVSTHost = None  # type: ignore
    CarlaHostError = Exception  # type: ignore
    CARLA_AVAILABLE = False
    _CARLA_IMPORT_ERROR = str(_ce)

# Optional WebEngine (informational only here)
try:  # pragma: no cover
    from qtpy.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings  # type: ignore
    from qtpy.QtWebChannel import QWebChannel  # type: ignore
    WEBENGINE_AVAILABLE = True
except Exception as e:  # pragma: no cover
    QWebEngineView = None  # type: ignore
    QWebChannel = None  # type: ignore
    WEBENGINE_AVAILABLE = False
    WEBENGINE_IMPORT_ERROR = str(e)

from ambiance.theming import ThemeManager
from ambiance.strudel_proxy import StrudelProxy


class WallpaperMdiArea(QMdiArea):
    """QMdiArea subclass that manages wallpapers via background brushes."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._wallpaper_pixmap: Optional[QPixmap] = None
        self._wallpaper_color: QColor = QColor("#0f1218")
        self._needs_refresh = True
        self._wallpaper_offset = 0.5
        viewport = self.viewport()
        viewport.setObjectName("wallpaper_viewport")
        viewport.setAutoFillBackground(True)
        viewport.setBackgroundRole(QPalette.ColorRole.Window)
        viewport.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        viewport.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAutoFillBackground(False)

    def apply_wallpaper(self, image_path: Optional[Path], color: QColor) -> None:
        """Store wallpaper pixmap/color and update the background brush."""
        pixmap: Optional[QPixmap] = None
        if image_path:
            if image_path.exists():
                loaded = QPixmap(str(image_path))
                if not loaded.isNull():
                    pixmap = loaded
                else:
                    print(f"[WALLPAPER] Failed to load pixmap data from {image_path}")
            else:
                print(f"[WALLPAPER] Wallpaper path missing on disk: {image_path}")

        self._wallpaper_pixmap = pixmap
        self._wallpaper_color = color
        self._needs_refresh = True
        self._refresh_wallpaper_brush()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._needs_refresh = True
        self._refresh_wallpaper_brush()

    def _refresh_wallpaper_brush(self) -> None:
        """Apply the current wallpaper to the QMdiArea background."""
        if not self._needs_refresh:
            return

        viewport = self.viewport()
        size = viewport.size()

        if self._wallpaper_pixmap and not size.isEmpty():
            scaled = self._wallpaper_pixmap.scaled(
                size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            if scaled.height() > size.height() or scaled.width() > size.width():
                available_y = max(0, scaled.height() - size.height())
                top = int(max(0.0, min(1.0, self._wallpaper_offset)) * available_y)
                available_x = max(0, scaled.width() - size.width())
                left = available_x // 2
                cropped = scaled.copy(left, top, size.width(), size.height())
                self.setBackground(QBrush(cropped))
            else:
                self.setBackground(QBrush(scaled))
        else:
            self.setBackground(QBrush(self._wallpaper_color))

        viewport.update()
        self._needs_refresh = False

    def set_wallpaper_offset(self, offset: float) -> None:
        """Adjust vertical alignment (0=top, 1=bottom)."""
        self._wallpaper_offset = max(0.0, min(1.0, offset))
        self._needs_refresh = True
        self._refresh_wallpaper_brush()


class PluginStudioBridge(QObject):
    """Qt WebChannel bridge that exposes plugin data/operations to WebEngine UI."""

    stateUpdated = Signal(str)
    hostStatusChanged = Signal(str)

    def __init__(self, rack_widget: "PluginRackWidget") -> None:
        super().__init__()
        self._rack = rack_widget
        self._rack.stateChanged.connect(self._forward_state)
        self._rack.hostStatusChanged.connect(self.hostStatusChanged.emit)

    def _forward_state(self, state: dict) -> None:
        try:
            payload = json.dumps(state)
        except Exception as exc:  # pragma: no cover - defensive
            payload = json.dumps({"error": f"serialize_failed: {exc}"})
        try:
            plugins = state.get("plugins", [])
            print(f"[WEB] Plugin state -> {len(plugins)} plugins, chain={len(state.get('chain', []))}")
        except Exception:
            pass
        self.stateUpdated.emit(payload)

    @Slot()
    def requestInitialState(self) -> None:
        self._forward_state(self._rack.serialize_state())

    @Slot()
    def refreshPlugins(self) -> None:
        self._rack.refresh()

    @Slot(str)
    def addPluginByPath(self, path: str) -> None:
        self._rack.add_plugin_by_path(path)

    @Slot(int)
    def removeChainIndex(self, index: int) -> None:
        self._rack.remove_chain_index(index)

    @Slot(int)
    def loadChainIndex(self, index: int) -> None:
        self._rack.load_chain_index(index)

    @Slot(int)
    def focusChainIndex(self, index: int) -> None:
        self._rack.select_chain_index(index)

    @Slot()
    def saveSession(self) -> None:
        if hasattr(self._rack, "save_session"):
            self._rack.save_session()

    @Slot()
    def loadSession(self) -> None:
        if hasattr(self._rack, "load_session"):
            self._rack.load_session()


class PluginUIBridge(QObject):
    """Bridge that surfaces current plugin info + host controls to WebEngine UI."""

    stateUpdated = Signal(str)
    hostStatusChanged = Signal(str)
    pluginChanged = Signal(str)

    def __init__(self, rack_widget: "PluginRackWidget") -> None:
        super().__init__()
        self._rack = rack_widget
        self._rack.stateChanged.connect(self._forward_state)
        self._rack.hostStatusChanged.connect(self.hostStatusChanged.emit)
        self._rack.currentPluginChanged.connect(self._forward_plugin)

    def _forward_state(self, state: dict) -> None:
        try:
            payload = json.dumps(state)
        except Exception as exc:  # pragma: no cover
            payload = json.dumps({"error": f"serialize_failed: {exc}"})
        self.stateUpdated.emit(payload)

    def _forward_plugin(self, descriptor: dict) -> None:
        try:
            payload = json.dumps(descriptor)
        except Exception:
            payload = json.dumps({"path": descriptor or None})
        self.pluginChanged.emit(payload)

    @Slot()
    def requestInitialState(self) -> None:
        self._forward_state(self._rack.serialize_state())

    @Slot()
    def showNativeUI(self) -> None:
        self._rack.show_host_ui()

    @Slot()
    def unloadPlugin(self) -> None:
        self._rack.unload_host()

    @Slot(int)
    def loadChainIndex(self, index: int) -> None:
        self._rack.load_chain_index(index)


class DesktopBridge(QObject):
    """Bridge exposing desktop/theme state and receiving global commands."""

    stateUpdated = Signal(str)

    def __init__(self, window: "AmbianceMainWindow") -> None:
        super().__init__()
        self._window = window

    def emit_state(self) -> None:
        state = self._window._compose_desktop_state()
        try:
            payload = json.dumps(state)
        except Exception as exc:  # pragma: no cover
            payload = json.dumps({"error": f"desktop_state_failed: {exc}"})
        self.stateUpdated.emit(payload)

    @Slot()
    def requestInitialState(self) -> None:
        self.emit_state()

    @Slot(str)
    def setTheme(self, theme: str) -> None:
        self._window.apply_theme_from_bridge(theme)

    @Slot(float, float, float, float)
    def updateNativeViewport(self, x: float, y: float, width: float, height: float) -> None:
        self._window.update_native_viewport_geometry(x, y, width, height)

    @Slot()
    def emergencyStop(self) -> None:
        self._window._handle_emergency_stop()

    @Slot(str)
    def toggleWindow(self, window_id: str) -> None:
        self._window.toggle_window_from_bridge(window_id)

    @Slot(str)
    def focusWindow(self, window_id: str) -> None:
        self._window.focus_window(window_id)


class ConsoleBridge(QObject):
    """Bridge that streams log output to the Web desktop."""

    logLine = Signal(str)
    historyReady = Signal(str)

    def __init__(self, rack_widget: "PluginRackWidget") -> None:
        super().__init__()
        self._rack = rack_widget
        self._rack.logMessage.connect(self.logLine.emit)

    @Slot()
    def requestHistory(self) -> None:
        try:
            payload = json.dumps({"lines": self._rack.get_log_history()})
        except Exception as exc:
            payload = json.dumps({"error": f"log_history_failed: {exc}"})
        self.historyReady.emit(payload)


class KeyboardBridge(QObject):
    """Bridge that exposes MIDI keyboard controls to the Web desktop."""

    stateUpdated = Signal(str)

    def __init__(self, rack_widget: "PluginRackWidget") -> None:
        super().__init__()
        self._rack = rack_widget
        self._rack.keyboardStateChanged.connect(self._forward_state)

    def _forward_state(self, state: dict) -> None:
        try:
            payload = json.dumps(state)
        except Exception as exc:
            payload = json.dumps({"error": f"keyboard_state_failed: {exc}"})
        self.stateUpdated.emit(payload)

    @Slot(int)
    def noteOn(self, note: int) -> None:
        self._rack.trigger_note_on(int(note))

    @Slot(int)
    def noteOff(self, note: int) -> None:
        self._rack.trigger_note_off(int(note))

    @Slot(int)
    def setVelocity(self, value: int) -> None:
        self._rack.set_keyboard_velocity(value)

    @Slot(int)
    def setOctave(self, value: int) -> None:
        self._rack.set_keyboard_octave(value)

    @Slot()
    def requestState(self) -> None:
        self._forward_state(self._rack.serialize_keyboard_state())


class StrudelBridge(QObject):
    """Bridge controlling the Strudel web window."""

    stateUpdated = Signal(str)

    def __init__(self, window: "AmbianceMainWindow") -> None:
        super().__init__()
        self._window = window

    def emit_state(self, state: dict) -> None:
        try:
            payload = json.dumps(state)
        except Exception as exc:
            payload = json.dumps({"error": f"strudel_state_failed: {exc}"})
        self.stateUpdated.emit(payload)

    @Slot()
    def requestState(self) -> None:
        self._window._emit_strudel_state()

    @Slot()
    def open(self) -> None:
        self._window._show_strudel()

    @Slot()
    def close(self) -> None:
        self._window._hide_strudel()

    @Slot()
    def reload(self) -> None:
        self._window._reload_strudel()

    @Slot(str)
    def navigate(self, url: str) -> None:
        self._window._navigate_strudel(url)

class AmbianceMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Ambiance – Studio")
        self.resize(1200, 800)

        # Main container - Desktop environment
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Theme management
        self.theme_manager = ThemeManager(_ROOT)
        self.current_theme = self.theme_manager.default_theme

        # Add toolbar at top
        self.toolbar = self._create_toolbar()
        layout.addWidget(self.toolbar)

        # Desktop area with MDI (Multiple Document Interface)
        self.desktop = WallpaperMdiArea(self)
        self.desktop.setObjectName("desktop")  # For stylesheet targeting
        self.desktop.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.desktop.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.desktop.setViewMode(QMdiArea.ViewMode.SubWindowView)  # SubWindow mode
        self.desktop.setActivationOrder(QMdiArea.WindowOrder.ActivationHistoryOrder)  # Click to bring to front
        try:
            self.desktop.setOption(QMdiArea.Option.DontMaximizeSubWindowOnActivation, True)
        except Exception:
            pass

        layout.addWidget(self.desktop)

        # Initialize Strudel state (will be loaded on demand)
        self._strudel_loaded = False
        self._strudel_visible = False
        self._strudel_home_url = "https://strudel.cc/"
        self._strudel_url: Optional[str] = None
        self._strudel_remote_url: Optional[str] = self._strudel_home_url
        self._strudel_error: Optional[str] = None
        self._desktop_base_url: Optional[str] = None
        self._strudel_proxy_base: Optional[str] = None
        self._strudel_proxy_service: Optional[StrudelProxy] = None
        self._strudel_proxy_port: Optional[int] = None
        self._strudel_reload_token = 0

        # Virtual resolution + zoom handling
        self._theme_resolution: tuple[int, int] | None = None
        self._desktop_zoom_factor: float = 1.0

        # Taskbar/legacy UI placeholders (actual chrome lives in Web desktop)
        self.taskbar = None
        self.taskbar_layout = None
        self.start_button = None
        self.clock_label = None
        self.clock_timer = None
        self._taskbar_buttons: dict = {}
        self._monitored_windows: set[int] = set()
        self._window_state_monitors: set[int] = set()
        self._destroyed_monitors: set[int] = set()

        # Store reference to plugin rack widget
        self.plugin_rack_widget = None

        if PluginRackManager is not None:
            self.plugin_rack_widget = PluginRackWidget(self)
            # Hide the main widget since we only use its children in MDI windows
            self.plugin_rack_widget.hide()

        # Desktop bridge + plugin bridges
        self.desktop_bridge = DesktopBridge(self)
        self.plugin_studio_bridge = (
            PluginStudioBridge(self.plugin_rack_widget) if self.plugin_rack_widget else None
        )
        self.plugin_ui_bridge = (
            PluginUIBridge(self.plugin_rack_widget) if self.plugin_rack_widget else None
        )
        self.console_bridge = (
            ConsoleBridge(self.plugin_rack_widget) if self.plugin_rack_widget else None
        )
        self.keyboard_bridge = (
            KeyboardBridge(self.plugin_rack_widget) if self.plugin_rack_widget else None
        )
        self.strudel_bridge = StrudelBridge(self)
        self._desktop_wallpaper_state: dict[str, object] = {
            "image": None,
            "color": "#222222",
            "offset": 0.5,
        }
        self._theme_change_from_bridge = False
        self._carla_warmup_timer: QTimer | None = None
        self.web_desktop_active = False
        self._native_viewport_rect = (0.0, 0.0, 0.0, 0.0)

        self.plugin_studio_webview = None
        self.plugin_ui_webview = None

        # Apply initial theme
        self._apply_theme(self.current_theme)

        if self.plugin_rack_widget:
            self.plugin_rack_widget.apply_theme_titles(self.current_theme)

        # Create desktop windows after theme is applied
        self._create_desktop_windows()

        # Install application-level event filter to catch keyboard events
        QApplication.instance().installEventFilter(self)


    def eventFilter(self, obj, event):
        """Catch keyboard events and forward to PluginRackWidget, also track window visibility."""
        # Handle keyboard events
        if event.type() == event.Type.KeyPress or event.type() == event.Type.KeyRelease:
            # Forward keyboard events to plugin rack widget if keyboard mode is enabled
            if self.plugin_rack_widget and self.plugin_rack_widget.is_keyboard_enabled():
                if event.type() == event.Type.KeyPress:
                    self.plugin_rack_widget.keyPressEvent(event)
                    if event.isAccepted():
                        return True
                elif event.type() == event.Type.KeyRelease:
                    self.plugin_rack_widget.keyReleaseEvent(event)
                    if event.isAccepted():
                        return True

        # Handle window visibility changes for MDI windows
        if hasattr(self, '_taskbar_buttons') and obj in self._taskbar_buttons:
            if event.type() == event.Type.Show:
                self._on_window_visibility_changed(obj, True)
            elif event.type() == event.Type.Hide:
                self._on_window_visibility_changed(obj, False)

        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._refresh_desktop_zoom()

    def _scan_themes(self) -> dict:
        """Scan themes directory and return available themes."""
        themes = {}
        for definition in self.theme_manager.list_themes():
            themes[definition.theme_id] = {
                'id': definition.theme_id,
                'name': definition.display_name,
            }

        return themes

    def _create_toolbar(self) -> QWidget:
        """Create the main toolbar similar to HTML UI."""
        toolbar = QWidget()
        toolbar.setObjectName("toolbar")
        toolbar.setFixedHeight(26)
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(8, 1, 8, 1)
        layout.setSpacing(4)

        # Theme picker - dynamically populated from themes directory
        theme_label = QLabel("Theme:")
        layout.addWidget(theme_label)
        self.theme_combo = QComboBox()

        # Scan for available themes
        self.available_themes = self._scan_themes()
        for theme_id, theme_info in self.available_themes.items():
            self.theme_combo.addItem(theme_info['name'], theme_id)

        default_index = self.theme_combo.findData(self.current_theme)
        if default_index != -1:
            self.theme_combo.setCurrentIndex(default_index)

        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        layout.addWidget(self.theme_combo)

        self.strudel_btn = QPushButton("Strudel")
        self.strudel_btn.setObjectName("strudelButton")
        self.strudel_btn.setToolTip("Toggle Strudel live coding window")
        self.strudel_btn.setMaximumHeight(22)
        self.strudel_btn.clicked.connect(self._toggle_strudel_window)
        layout.addWidget(self.strudel_btn)

        layout.addStretch()

        self.emergency_btn = QPushButton("Emergency Stop")
        self.emergency_btn.setObjectName("emergencyStopButton")
        self.emergency_btn.setToolTip("Panic: send all-notes-off and reset plugin rack")
        self.emergency_btn.setMaximumHeight(22)
        self.emergency_btn.clicked.connect(self._handle_emergency_stop)
        layout.addWidget(self.emergency_btn)

        return toolbar

    def _on_theme_changed(self, index: int) -> None:
        """Handle theme selection change."""
        theme_id = self.theme_combo.itemData(index)
        if theme_id and theme_id in self.theme_manager.theme_ids():
            self.current_theme = theme_id
            self._apply_theme(self.current_theme)

    def _apply_theme(self, theme: str) -> None:
        """Apply a visual theme to the application by loading CSS file."""
        requested_theme = theme
        if theme not in self.theme_manager.theme_ids():
            print(f"[WARNING] Theme '{theme}' not found, using default")
            theme = self.theme_manager.default_theme
        self.current_theme = theme
        if theme != requested_theme and hasattr(self, "theme_combo"):
            index = self.theme_combo.findData(theme)
            if index != -1 and index != self.theme_combo.currentIndex():
                self.theme_combo.blockSignals(True)
                self.theme_combo.setCurrentIndex(index)
                self.theme_combo.blockSignals(False)

        try:
            css_content = self.theme_manager.apply(theme, self)
            definition = self.theme_manager.get_definition(theme)
            print(f"[THEME] Applied theme: {definition.display_name}")

            preview = css_content[:200]
            print(f"[DEBUG] CSS preview: {preview}..." if len(css_content) > 200 else f"[DEBUG] CSS content: {preview}")

        except Exception as exc:
            print(f"[ERROR] Error loading theme: {exc}")
            import traceback

            traceback.print_exc()
            return

        self._apply_theme_palette(theme)
        self._apply_theme_wallpaper(theme)
        self._apply_theme_resolution(theme)

        if hasattr(self, "desktop"):
            self.desktop.update()
            self.desktop.repaint()
            for window in self.desktop.subWindowList():
                window.update()
                window.repaint()

        self._update_start_button_style(self.current_theme)
        if self.plugin_rack_widget and hasattr(self.plugin_rack_widget, "apply_theme_titles"):
            self.plugin_rack_widget.apply_theme_titles(theme)

    def _handle_emergency_stop(self) -> None:
        """Send a quick panic to silence all plugins."""
        if self.plugin_rack_widget and hasattr(self.plugin_rack_widget, "_emergency_all_notes_off"):
            try:
                self.plugin_rack_widget._emergency_all_notes_off()
            except Exception as exc:  # pragma: no cover - safety net
                print(f"[PANIC] Emergency stop failed: {exc}")
        QApplication.beep()

    def _apply_theme_palette(self, theme: str) -> None:
        """Adjust the global palette so basic widgets inherit theme colors."""
        app = QApplication.instance()
        if app is None:
            return

        tokens = self.theme_manager.tokens_for(theme)
        if not tokens:
            return

        palette = app.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(tokens.window))
        palette.setColor(QPalette.ColorRole.Base, QColor(tokens.base))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(tokens.alt))
        palette.setColor(QPalette.ColorRole.Button, QColor(tokens.button))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(tokens.text))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(tokens.button_text))
        palette.setColor(QPalette.ColorRole.Text, QColor(tokens.text))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(tokens.highlight))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(tokens.highlight_text))
        app.setPalette(palette)
        if tokens.font_family:
            app.setFont(QFont(tokens.font_family, tokens.font_size))

    def _apply_theme_wallpaper(self, theme: str) -> None:
        """Configure wallpaper image and fallback color for the current theme."""
        if not isinstance(self.desktop, WallpaperMdiArea):
            return

        wallpapers_root = _ROOT / "resources" / "wallpapers"
        wallpaper_map = {
            "winxp": wallpapers_root / "bliss.jpg",
            "win7": wallpapers_root / "win7.jpg",
        }
        fallback_colors = {
            "winxp": "#70a0d0",
            "win7": "#c7dafa",
            "win98": "#008080",
            "flat": "#222222",
        }
        offset_map = {
            "winxp": 0.04,
            "win7": 0.12,
        }

        image_path: Optional[Path] = wallpaper_map.get(theme)
        if image_path and not image_path.exists():
            print(f"[THEME] Wallpaper file missing for {theme}: {image_path}")
            image_path = None

        color_name = fallback_colors.get(theme, fallback_colors["flat"])
        fill_color = QColor(color_name)

        if not self.web_desktop_active and isinstance(self.desktop, WallpaperMdiArea):
            self.desktop.set_wallpaper_offset(offset_map.get(theme, 0.5))
            self.desktop.apply_wallpaper(image_path, fill_color)

        wallpaper_url = None
        if image_path:
            base_url = getattr(self, "_desktop_base_url", None)
            if base_url:
                wallpaper_url = f"{base_url}wallpapers/{image_path.name}"
            else:
                wallpaper_url = self._encode_wallpaper_data(image_path)
        self._desktop_wallpaper_state = {
            "image": wallpaper_url,
            "color": color_name,
            "offset": offset_map.get(theme, 0.5),
        }
        self._notify_desktop_bridge()

    def _apply_theme_resolution(self, theme: str) -> None:
        metrics = self.theme_manager.metrics_for(theme)
        if metrics and metrics.preferred_resolution:
            width, height = metrics.preferred_resolution
            self._theme_resolution = (int(width), int(height))
        else:
            self._theme_resolution = None
        self._refresh_desktop_zoom()

    def _refresh_desktop_zoom(self) -> None:
        """Scale the web desktop instead of resizing the entire window."""
        target = getattr(self, "_theme_resolution", None)
        view = getattr(self, "web_desktop_view", None)
        if not target:
            self._desktop_zoom_factor = 1.0
            if view:
                view.setZoomFactor(1.0)
            return
        target_w, target_h = target
        if target_w <= 0 or target_h <= 0:
            return
        actual_w = max(1, self.width())
        actual_h = max(1, self.height())
        zoom = min(1.0, actual_w / target_w, actual_h / target_h)
        self._desktop_zoom_factor = zoom
        if view:
            view.setZoomFactor(zoom)

    def _ensure_desktop_http_server(self) -> Optional[str]:
        root_dir = _ROOT / "resources" / "webdesktop"
        if not root_dir.exists():
            return None

        mounts: dict[str, Path] = {}
        node_modules = _ROOT / "node_modules"
        if node_modules.exists():
            mounts["/vendor/"] = node_modules
        start_dir = _ROOT / "resources" / "start"
        if start_dir.exists():
            mounts["/start/"] = start_dir
        wallpapers_dir = _ROOT / "resources" / "wallpapers"
        if wallpapers_dir.exists():
            mounts["/wallpapers/"] = wallpapers_dir

        global _desktop_http_server
        if _desktop_http_server is None:
            _desktop_http_server = StaticHTTPServer(root_dir, mounts=mounts)

        try:
            port = _desktop_http_server.start()
        except Exception as exc:
            print(f"[WEB] Failed to start desktop HTTP server: {exc}")
            return None

        self._desktop_base_url = f"http://127.0.0.1:{port}/"
        return self._desktop_base_url

    def _collect_window_state(self) -> list[dict[str, object]]:
        windows: list[dict[str, object]] = []
        mdi_windows = getattr(self, "mdi_windows", {})
        plugin_ui = mdi_windows.get("Plugin UI") if isinstance(mdi_windows, dict) else None
        if plugin_ui is not None:
            visible = plugin_ui.isVisible()
            if hasattr(plugin_ui, "isMinimized"):
                try:
                    visible = visible and not plugin_ui.isMinimized()
                except Exception:
                    pass
            windows.append({
                "id": "plugin_ui",
                "name": "Plugin UI",
                "visible": bool(visible),
            })
        windows.append({
            "id": "strudel",
            "name": "Strudel",
            "visible": bool(self._strudel_visible),
        })
        return windows

    def _compose_desktop_state(self) -> dict[str, object]:
        return {
            "theme": self.current_theme,
            "wallpaper": self._desktop_wallpaper_state,
            "themes": [
                {"id": theme_id, "name": info["name"]}
                for theme_id, info in getattr(self, "available_themes", {}).items()
            ],
            "windows": self._collect_window_state(),
        }

    def _notify_desktop_bridge(self) -> None:
        if getattr(self, "desktop_bridge", None):
            self.desktop_bridge.emit_state()

    @staticmethod
    def _encode_wallpaper_data(image_path: Path) -> Optional[str]:
        try:
            data = image_path.read_bytes()
        except OSError:
            return None
        mime, _ = mimetypes.guess_type(str(image_path))
        mime = mime or "image/png"
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def apply_theme_from_bridge(self, theme: str) -> None:
        if not theme or theme == self.current_theme:
            return
        if theme not in self.theme_manager.theme_ids():
            return
        previous_flag = self._theme_change_from_bridge
        self._theme_change_from_bridge = True
        try:
            if hasattr(self, "theme_combo"):
                index = self.theme_combo.findText(theme)
                if index >= 0:
                    self.theme_combo.setCurrentIndex(index)
                    return
            self._apply_theme(theme)
        finally:
            self._theme_change_from_bridge = previous_flag

    def update_native_viewport_geometry(self, x: float, y: float, width: float, height: float) -> None:
        self._native_viewport_rect = (x, y, width, height)
        self._sync_native_ui_geometry()

    def _sync_native_ui_geometry(self) -> None:
        if not hasattr(self, "mdi_windows"):
            return
        plugin_window = self.mdi_windows.get("Plugin UI")
        if not plugin_window:
            return
        rect = getattr(self, "_native_viewport_rect", (0.0, 0.0, 0.0, 0.0))
        if not rect or rect[2] <= 0 or rect[3] <= 0:
            return

        parent_widget = plugin_window.parentWidget()
        view = getattr(self, "web_desktop_view", None)
        origin_x = 0
        origin_y = 0
        if parent_widget is not None and view is not None:
            top_left = view.mapTo(parent_widget, QPoint(0, 0))
            origin_x = top_left.x()
            origin_y = top_left.y()
        elif hasattr(self, "web_desktop_window") and self.web_desktop_window:
            g = self.web_desktop_window.geometry()
            origin_x = g.x()
            origin_y = g.y()

        x = int(origin_x + rect[0])
        y = int(origin_y + rect[1])
        w = max(200, int(rect[2]))
        h = max(150, int(rect[3]))
        plugin_window.setGeometry(x, y, w, h)
        if plugin_window.isVisible():
            plugin_window.raise_()
        if self.plugin_rack_widget:
            self.plugin_rack_widget.resize_plugin_viewport(w, h)

    def _set_plugin_ui_visible(self, visible: bool) -> None:
        if not hasattr(self, "mdi_windows"):
            return
        window = self.mdi_windows.get("Plugin UI")
        if not window:
            return
        try:
            from qtpy.QtWidgets import QMdiSubWindow  # Local import to avoid circular deps
        except Exception:  # pragma: no cover
            QMdiSubWindow = None  # type: ignore

        if QMdiSubWindow is not None and isinstance(window, QMdiSubWindow):
            if visible:
                window.show()
                if window.isMinimized():
                    window.showNormal()
                window.raise_()
                window.setFocus()
                self.desktop.setActiveSubWindow(window)
            else:
                window.hide()
        else:
            if visible:
                window.show()
                window.raise_()
                self._sync_native_ui_geometry()
            else:
                window.hide()
        self._notify_desktop_bridge()

    def _window_close_event_filter(self, window):
        """Event filter to intercept close button and minimize instead, and handle activation."""
        class WindowEventFilter(QObject):
            def __init__(self, parent_window, main_window):
                super().__init__()
                self.parent_window = parent_window
                self.main_window = main_window

            def eventFilter(self, obj, event):
                if event.type() == event.Type.Close:
                    # Minimize instead of closing
                    self.parent_window.hide()
                    if hasattr(self.main_window, "_notify_desktop_bridge"):
                        self.main_window._notify_desktop_bridge()
                    event.ignore()
                    return True
                elif event.type() == event.Type.MouseButtonPress:
                    # Bring window to front when clicked
                    self.main_window.desktop.setActiveSubWindow(self.parent_window)
                    self.parent_window.raise_()
                    return False  # Allow event to propagate
                return False

        filter_obj = WindowEventFilter(window, self)
        window.installEventFilter(filter_obj)
        # Store reference so it doesn't get garbage collected
        if not hasattr(self, '_window_filters'):
            self._window_filters = []
        self._window_filters.append(filter_obj)

    def _handle_web_console(self, level, message, line_number, source_id):
        """Forward WebEngine console output to stdout for easier debugging."""
        try:
            level_name = level.name  # Enum in Qt 6
        except AttributeError:
            try:
                level_name = str(int(level))
            except Exception:
                level_name = str(level)
        print(f"[WEB-CONSOLE][{level_name}] {message} ({source_id}:{line_number})")

    def _create_web_desktop_window(self):
        """Create the full-screen WebEngine-powered desktop subwindow."""
        from qtpy.QtWidgets import QMdiSubWindow, QWidget, QVBoxLayout

        if not (WEBENGINE_AVAILABLE and QWebEngineView and QWebChannel):
            return None

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        view = QWebEngineView(container)
        view.setObjectName("webDesktopView")
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        view.setAcceptDrops(False)
        try:
            settings = view.settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)
        except Exception:
            pass
        layout.addWidget(view)
        self.web_desktop_view = view
        self._refresh_desktop_zoom()

        channel = QWebChannel(view.page())
        if self.desktop_bridge:
            channel.registerObject("DesktopBridge", self.desktop_bridge)
        if self.plugin_studio_bridge:
            channel.registerObject("PluginStudioBridge", self.plugin_studio_bridge)
        if self.plugin_ui_bridge:
            channel.registerObject("PluginUIBridge", self.plugin_ui_bridge)
        if getattr(self, "console_bridge", None):
            channel.registerObject("ConsoleBridge", self.console_bridge)
        if getattr(self, "keyboard_bridge", None):
            channel.registerObject("KeyboardBridge", self.keyboard_bridge)
        if getattr(self, "strudel_bridge", None):
            channel.registerObject("StrudelBridge", self.strudel_bridge)
        view.page().setWebChannel(channel)
        try:
            view.page().javaScriptConsoleMessage.connect(self._handle_web_console)
        except Exception:
            pass

        base_url = self._ensure_desktop_http_server()
        html_path = _ROOT / "resources" / "webdesktop" / "index.html"
        if base_url:
            view.load(QUrl(f"{base_url}index.html"))
        elif html_path.exists():
            view.load(QUrl.fromLocalFile(str(html_path)))
        else:  # pragma: no cover - fallback
            view.setHtml("<h3>Missing webdesktop/index.html</h3>")

        outer = self

        class _StrudelWindow(QMdiSubWindow):
            def closeEvent(self, event):  # type: ignore[override]
                outer._hide_strudel()
                event.ignore()

        subwindow = _StrudelWindow()
        subwindow.setWidget(container)
        subwindow.setWindowTitle("")
        subwindow.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        subwindow.setWindowFlags(
            Qt.WindowType.SubWindow
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.FramelessWindowHint
        )
        subwindow.setStyleSheet("background: transparent; border: 0px;")
        self.desktop.addSubWindow(subwindow)
        subwindow.showMaximized()
        subwindow.lower()
        self.web_desktop_active = True
        if isinstance(self.desktop, WallpaperMdiArea):
            self.desktop.apply_wallpaper(None, QColor("#000000"))
        if getattr(self, "taskbar", None):
            self.taskbar.hide()
        if hasattr(self, "toolbar") and self.toolbar:
            self.toolbar.hide()
        if not self._strudel_loaded:
            self._ensure_strudel_server()
        self._notify_desktop_bridge()
        self._emit_strudel_state()
        return subwindow

    def _create_plugin_ui_widget(self) -> QWidget:
        """Return the QWidget used for the Plugin UI window."""
        if not self.plugin_rack_widget:
            return QWidget()
        return self.plugin_rack_widget.plugin_ui_holder

    def _create_plugin_ui_overlay(self) -> QWidget:
        """Create a frameless overlay that hosts the native plugin viewport."""
        plugin_widget = self._create_plugin_ui_widget()
        overlay_parent = self.desktop.viewport() if hasattr(self, "desktop") else self
        overlay = QWidget(overlay_parent)
        overlay.setObjectName("plugin_ui_overlay")
        overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        overlay.setStyleSheet("background: transparent; border: 0px;")
        layout = QVBoxLayout(overlay)
        layout.setContentsMargins(0, 0, 0, 0)
        plugin_widget.setParent(overlay)
        layout.addWidget(plugin_widget)
        overlay.hide()
        return overlay

    def _create_desktop_windows(self) -> None:
        """Create moveable windows on the desktop for each component."""
        if not self.plugin_rack_widget:
            return

        # Store window references for taskbar/state reporting
        self.mdi_windows = {}

        # Web desktop layer
        self.web_desktop_window = self._create_web_desktop_window()

        # Plugin UI overlay that mirrors the native viewport anchor
        plugin_ui_overlay = self._create_plugin_ui_overlay()
        self.plugin_ui_overlay = plugin_ui_overlay
        self.mdi_windows["Plugin UI"] = plugin_ui_overlay

        self._sync_native_ui_geometry()

        # Create taskbar buttons now that windows exist (legacy stub)
        self._populate_taskbar()
        self._notify_desktop_bridge()

    def _populate_taskbar(self) -> None:
        """Legacy stub: web desktop manages taskbar UI."""
        self._taskbar_buttons = {}

    def _update_start_button_style(self, theme: str) -> None:
        if not hasattr(self, "start_button") or self.start_button is None:
            return

        button = self.start_button
        theme = theme or "flat"
        button.setCursor(Qt.CursorShape.PointingHandCursor)

        metrics = self.theme_manager.metrics_for(theme)
        taskbar_height = metrics.taskbar_height if metrics else 36
        taskbar_margins = metrics.taskbar_margins if metrics else (0, 0, 6, 0)
        start_button_height = metrics.start_button_height if metrics else taskbar_height
        extra_css = metrics.start_button_extra_css if metrics else ""
        button.setIcon(QIcon())
        button.setStyleSheet("")
        button.setMinimumHeight(24)
        button.setMinimumWidth(90)
        button.setText("Start")


    def _activate_window(self, window) -> None:
        """Toggle window visibility when taskbar button is clicked."""
        if window is None or not hasattr(self, "desktop"):
            return

        # Remove stale references if the window has been closed
        try:
            windows = self.desktop.subWindowList()
        except Exception:
            windows = []
        if window not in windows and hasattr(self, "_taskbar_buttons"):
            self._on_window_destroyed(window)
            return

        plugin_window = None
        if hasattr(self, "mdi_windows"):
            plugin_window = self.mdi_windows.get("Plugin UI")
        is_visible = window.isVisible() and not window.isMinimized()
        is_active = self.desktop.activeSubWindow() == window

        if window is plugin_window:
            self._set_plugin_ui_visible(not (is_visible and is_active))
            return

        if is_visible and is_active:
            window.hide()
        elif is_visible and not is_active:
            window.raise_()
            window.setFocus()
            self.desktop.setActiveSubWindow(window)
        else:
            window.show()
            if window.isMinimized():
                window.showNormal()
            window.raise_()
            window.setFocus()
            self.desktop.setActiveSubWindow(window)

        self._set_taskbar_button_state(window)
        self._notify_desktop_bridge()

    def _on_window_state_changed(self, window, new_state) -> None:
        """Update taskbar button when window state changes."""
        self._set_taskbar_button_state(window)

    def _on_window_visibility_changed(self, window, visible) -> None:
        """Update taskbar button when window visibility changes."""
        self._set_taskbar_button_state(window)

    def _set_taskbar_button_state(self, window) -> None:
        if hasattr(self, '_taskbar_buttons') and window in self._taskbar_buttons:
            btn = self._taskbar_buttons[window]
            try:
                visible = window.isVisible() and not window.isMinimized()
                btn.setChecked(visible)
            except RuntimeError:
                pass

    def _on_taskbar_button_clicked(self, window, checked=False) -> None:
        """Respond to taskbar button clicks and toggle the associated window."""
        if window is None:
            return
        self._activate_window(window)

    def _handle_window_state_changed(self, old_state, new_state) -> None:
        """Normalize window state changes sent from QMdiSubWindow."""
        window = self.sender()
        if window is not None:
            self._on_window_state_changed(window, new_state)

    def _on_window_destroyed(self, window, obj=None) -> None:
        """Remove references when an MDI window is destroyed."""
        if hasattr(self, "_taskbar_buttons"):
            btn = self._taskbar_buttons.pop(window, None)
            if btn is not None:
                try:
                    btn.deleteLater()
                except Exception:
                    pass
        window_id = id(window)
        if hasattr(self, "_monitored_windows"):
            self._monitored_windows.discard(window_id)
        if hasattr(self, "_window_state_monitors"):
            self._window_state_monitors.discard(window_id)
        if hasattr(self, "_destroyed_monitors"):
            self._destroyed_monitors.discard(window_id)

    def _serialize_strudel_state(self) -> dict:
        return {
            "loaded": bool(self._strudel_loaded),
            "visible": bool(self._strudel_visible),
            "url": self._strudel_url,
            "displayUrl": self._strudel_remote_url or self._strudel_home_url,
            "error": self._strudel_error,
            "homeUrl": self._strudel_home_url,
            "proxyBase": self._strudel_proxy_base,
            "reloadToken": self._strudel_reload_token,
        }

    def _emit_strudel_state(self) -> None:
        if getattr(self, "strudel_bridge", None):
            self.strudel_bridge.emit_state(self._serialize_strudel_state())
        self._notify_desktop_bridge()

    def _ensure_strudel_server(self) -> Optional[str]:
        """Resolve Strudel URLs (prefer local bundle, fall back to hosted site)."""
        proxy_base = self._ensure_strudel_proxy()
        if proxy_base:
            self._strudel_proxy_base = proxy_base if proxy_base.endswith("/") else f"{proxy_base}/"
            self._strudel_url = self._build_strudel_proxy_url(self._strudel_home_url)
        else:
            self._strudel_proxy_base = None
            self._strudel_url = self._strudel_home_url
        self._strudel_remote_url = self._strudel_home_url
        self._strudel_loaded = True
        self._strudel_error = None
        return self._strudel_url

    def _ensure_strudel_proxy(self) -> Optional[str]:
        if self._strudel_proxy_service and self._strudel_proxy_port:
            return f"http://127.0.0.1:{self._strudel_proxy_port}/"
        root_dir = _ROOT / "resources" / "strudel" / "dist"
        if not root_dir.exists():
            LOGGER.warning("Strudel bundle missing at %s (falling back to remote content)", root_dir)
        try:
            proxy = StrudelProxy(root_dir=root_dir)
            port = proxy.start()
        except Exception as exc:  # pragma: no cover - startup failure
            LOGGER.error("Failed to start Strudel proxy: %s", exc)
            return None
        self._strudel_proxy_service = proxy
        self._strudel_proxy_port = port
        return f"http://127.0.0.1:{port}/"

    def _stop_strudel_proxy(self) -> None:
        if self._strudel_proxy_service:
            try:
                self._strudel_proxy_service.stop()
            except Exception as exc:  # pragma: no cover - shutdown failure
                LOGGER.warning("Error stopping Strudel proxy: %s", exc)
            finally:
                self._strudel_proxy_service = None
                self._strudel_proxy_port = None

    def _show_strudel(self) -> None:
        if not self._strudel_loaded:
            if not self._ensure_strudel_server():
                self._emit_strudel_state()
                return
        self._strudel_visible = True
        self._emit_strudel_state()

    def _hide_strudel(self) -> None:
        self._strudel_visible = False
        self._emit_strudel_state()

    def _reload_strudel(self) -> None:
        self._strudel_reload_token += 1
        self._emit_strudel_state()

    def _navigate_strudel(self, url: str) -> None:
        if not url:
            return
        self._strudel_remote_url = url
        self._strudel_url = self._build_strudel_proxy_url(url)
        self._strudel_reload_token += 1
        self._emit_strudel_state()

    def _build_strudel_proxy_url(self, url: Optional[str]) -> str:
        target = url or self._strudel_home_url
        if not self._strudel_proxy_base:
            return target
        parsed = urlparse(target)
        path = (parsed.path or "/").lstrip("/")
        query = f"?{parsed.query}" if parsed.query else ""
        base = self._strudel_proxy_base.rstrip("/")
        combined = f"{base}/{path}" if path else f"{base}/"
        return f"{combined}{query}"

    def _toggle_strudel_window(self) -> None:
        """Show or hide the Strudel window."""
        if self._strudel_visible:
            self._hide_strudel()
        else:
            self._show_strudel()

    def toggle_window_from_bridge(self, window_id: str) -> None:
        if window_id == "plugin_ui":
            current = self.mdi_windows.get("Plugin UI") if hasattr(self, "mdi_windows") else None
            if not current:
                return
            visible = current.isVisible()
            if hasattr(current, "isMinimized"):
                try:
                    visible = visible and not current.isMinimized()
                except Exception:
                    pass
            self._set_plugin_ui_visible(not visible)
        elif window_id == "strudel":
            self._toggle_strudel_window()

    def focus_window(self, window_id: str) -> None:
        if window_id == "plugin_ui":
            self._set_plugin_ui_visible(True)
            window = self.mdi_windows.get("Plugin UI") if hasattr(self, "mdi_windows") else None
            if window:
                window.show()
                window.raise_()
                window.activateWindow()
        elif window_id == "strudel":
            self._show_strudel()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._stop_strudel_proxy()
        super().closeEvent(event)


class PluginRackWidget(QFrame):
    """Plugin Rack UI with A/B lanes and optional Carla auditioning."""

    stateChanged = Signal(dict)
    hostStatusChanged = Signal(str)
    currentPluginChanged = Signal(dict)
    logMessage = Signal(str)
    keyboardStateChanged = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # Removed inline stylesheet to allow global theme to apply
        # Use a string forward reference to avoid evaluating the type at runtime
        self.carla = None  # type: ignore # type: Optional['CarlaVSTHost']

        self.manager = PluginRackManager()  # type: ignore[arg-type]
        self.param_sliders: dict[object, dict[str, object]] = {}
        self._updating_from_host = False
        self._current_loaded_path: Optional[str] = None
        self._log_history: deque[str] = deque(maxlen=500)
        self._keyboard_enabled = False

        # Window embedding state
        self._embedded_original_parent: Optional[int] = None
        self._embedded_original_style: Optional[int] = None

        # Scroll area for entire content
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        container = QWidget()
        scroll.setWidget(container)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(scroll)

        outer = QVBoxLayout(container)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(18)

        # Header section
        self.header_group = QGroupBox("Plugin Studio")
        # Removed inline stylesheet to allow theme control
        header_layout = QVBoxLayout(self.header_group)

        # Top row: workspace info and controls
        top_row = QHBoxLayout()
        self.workspace_label = QLabel()
        # Removed inline stylesheet to allow theme control
        self.workspace_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top_row.addWidget(self.workspace_label, 1)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        self.refresh_btn.setMaximumHeight(22)
        top_row.addWidget(self.refresh_btn)

        self.host_status = QLabel()
        self.host_status.setVisible(False)

        header_layout.addLayout(top_row)

        self._display_host_status("")

        # Main content area: discovered plugins (left) and plugin chain (right)
        content_row = QHBoxLayout()
        header_layout.addLayout(content_row)

        # Left: discovered plugins
        self.discover_group = QGroupBox("Discovered Plugins")
        self.discover_group.setStyleSheet("QGroupBox { font-size: 16px; }")
        discover_layout = QVBoxLayout(self.discover_group)
        self.plugins_list = QListWidget()
        self.plugins_list.setStyleSheet("QListWidget { min-height: 200px; }")
        discover_layout.addWidget(self.plugins_list)

        add_btn_row = QHBoxLayout()
        self.add_plugin_btn = QPushButton("Add to Chain →")
        self.add_plugin_btn.clicked.connect(self.add_selected_to_chain)
        add_btn_row.addWidget(self.add_plugin_btn)
        discover_layout.addLayout(add_btn_row)

        content_row.addWidget(self.discover_group, 1)

        # Right: plugin chain
        self.chain_group = QGroupBox("Plugin Chain")
        self.chain_group.setStyleSheet("QGroupBox { font-size: 16px; }")
        chain_layout = QVBoxLayout(self.chain_group)
        self.chain_list = QListWidget()
        self.chain_list.setStyleSheet("QListWidget { min-height: 200px; }")
        self.chain_list.currentRowChanged.connect(self._on_chain_selection)
        chain_layout.addWidget(self.chain_list)

        chain_btn_row = QHBoxLayout()
        self.load_plugin_btn = QPushButton("Load Selected")
        self.load_plugin_btn.clicked.connect(self._load_selected_plugin)
        chain_btn_row.addWidget(self.load_plugin_btn)

        self.remove_plugin_btn = QPushButton("Remove")
        self.remove_plugin_btn.clicked.connect(self.remove_selected_from_chain)
        chain_btn_row.addWidget(self.remove_plugin_btn)

        self.show_ui_btn = QPushButton("Show UI")
        self.show_ui_btn.clicked.connect(self.show_host_ui)
        chain_btn_row.addWidget(self.show_ui_btn)

        self.unload_btn = QPushButton("Unload")
        self.unload_btn.clicked.connect(self.unload_host)
        chain_btn_row.addWidget(self.unload_btn)

        chain_layout.addLayout(chain_btn_row)

        content_row.addWidget(self.chain_group, 1)

        self._groupbox_titles = {
            self.header_group: "Plugin Studio",
            self.discover_group: "Discovered Plugins",
            self.chain_group: "Plugin Chain",
        }

        # Don't add header_group to layout - it will be used in MDI window
        # outer.addWidget(self.header_group)

        # Plugin viewport / docking area (kept alive but not added to layout)
        self.viewport_group = QGroupBox("Plugin Viewport")
        # Removed inline stylesheet to allow theme control
        viewport_layout = QVBoxLayout(self.viewport_group)

        # Plugin UI embedding container
        self.params_group = QGroupBox("Plugin UI")
        # Removed inline stylesheet to allow theme control
        self.param_layout = QVBoxLayout(self.params_group)
        self._groupbox_titles[self.params_group] = "Plugin UI"
        self.param_layout.setContentsMargins(4, 20, 4, 4)

        # Create a container widget that will host the external window
        self.plugin_ui_container = QWidget()
        self.plugin_ui_container.setMinimumSize(400, 400)
        self.plugin_ui_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.plugin_ui_container.setStyleSheet("background: transparent; border: 0;")
        # Install event filter to handle resizing
        self.plugin_ui_container.installEventFilter(self)

        self.plugin_ui_holder = QWidget()
        self.plugin_ui_holder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        holder_layout = QVBoxLayout(self.plugin_ui_holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.setSpacing(0)
        holder_layout.addWidget(self.plugin_ui_container)
        self.param_layout.addWidget(self.plugin_ui_holder)

        # Label for when no plugin is loaded (in container, not param_layout)
        self.no_plugin_label = QLabel("No plugin loaded", self.plugin_ui_container)
        self.no_plugin_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Removed inline stylesheet to allow theme control
        self.no_plugin_label.setGeometry(0, 0, 400, 400)

        # Don't add params_group to viewport_layout - it will be used in MDI window
        # viewport_layout.addWidget(self.params_group)

        # Instrument keyboard (hidden by default)
        self.keyboard = InstrumentKeyboardWidget()
        self.keyboard.setVisible(False)
        # Connect keyboard keys to MIDI output
        for i, key in enumerate(self.keyboard.keys):
            midi_note = 48 + i  # Start from C3 (MIDI note 48)
            # Store the note number on the button for easy access
            key.setProperty("midi_note", midi_note)
            # Make buttons not accept focus to prevent interference
            key.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            # Connect click handler for mouse clicks
            key.pressed.connect(lambda n=midi_note: self._on_key_pressed(n))
            key.released.connect(lambda n=midi_note: self._on_key_released(n))

        # Enable mouse tracking on keyboard widget for drag support
        self.keyboard.setMouseTracking(True)
        self.keyboard.installEventFilter(self)

        # Also install on the inner keyboard widget container
        for child in self.keyboard.children():
            if isinstance(child, QWidget):
                child.setMouseTracking(True)
                child.installEventFilter(self)

        # Connect octave spinner to update keyboard mapping
        self.keyboard.octave_spin.valueChanged.connect(self._update_keyboard_mapping)
        self.keyboard.octave_spin.valueChanged.connect(lambda _value: self._emit_keyboard_state())
        self.keyboard.velocity_slider.valueChanged.connect(lambda _value: self._emit_keyboard_state())

        # Don't add keyboard to viewport_layout - it will be used in MDI window
        # viewport_layout.addWidget(self.keyboard)

        # Mouse drag state
        self._mouse_is_pressed = False
        self._current_drag_note = None
        self._last_note_time = 0  # For debouncing
        self._active_keyboard_notes: set[int] = set()

        self._emit_keyboard_state()

        # Console log viewer
        self.log_group = QGroupBox("Console Log")
        self.log_group.setStyleSheet("QGroupBox { font-size: 14px; }")
        log_layout = QVBoxLayout(self.log_group)
        self.log_viewer = QTextEdit()
        self.log_viewer.setReadOnly(True)
        self.log_viewer.setMaximumHeight(150)
        self.log_viewer.setStyleSheet("""
            QTextEdit {
                background: #0a0a0a;
                color: #0f0;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                border: 1px solid rgba(89, 167, 255, 0.35);
                border-radius: 8px;
                padding: 8px;
            }
        """)
        log_layout.addWidget(self.log_viewer)
        # Don't add log_group to viewport_layout - log_viewer will be used in MDI window
        # viewport_layout.addWidget(self.log_group)

        # Don't add viewport_group to layout - components are now in separate windows
        # outer.addWidget(viewport_group)

        # Plugin UI embedding state
        self._embedded_hwnd = None
        self._carla_warmup_started = False

        # Initial state
        self.refresh()
        # Defer Carla init until needed to avoid startup hangs
        self._display_host_status(self.host_status.text() or "Carla idle")

        # Embedding retry timer
        self._embed_retry_timer: Optional[QTimer] = None
        self._embed_retry_count = 0

        # Keyboard typing support - map keys to MIDI notes
        # Starting from C3 (MIDI 48) using home row and number row
        self._key_to_note = {
            # White keys (C D E F G A B C D E F G A B)
            Qt.Key.Key_Z: 48,   # C3
            Qt.Key.Key_X: 50,   # D3
            Qt.Key.Key_C: 52,   # E3
            Qt.Key.Key_V: 53,   # F3
            Qt.Key.Key_B: 55,   # G3
            Qt.Key.Key_N: 57,   # A3
            Qt.Key.Key_M: 59,   # B3
            Qt.Key.Key_Comma: 60,   # C4
            Qt.Key.Key_Period: 62,  # D4
            Qt.Key.Key_Slash: 64,   # E4

            # Black keys (C# D# F# G# A# C# D#)
            Qt.Key.Key_S: 49,   # C#3
            Qt.Key.Key_D: 51,   # D#3
            Qt.Key.Key_G: 54,   # F#3
            Qt.Key.Key_H: 56,   # G#3
            Qt.Key.Key_J: 58,   # A#3
            Qt.Key.Key_L: 61,   # C#4
            Qt.Key.Key_Semicolon: 63,  # D#4

            # Upper octave white keys
            Qt.Key.Key_Q: 60,   # C4
            Qt.Key.Key_W: 62,   # D4
            Qt.Key.Key_E: 64,   # E4
            Qt.Key.Key_R: 65,   # F4
            Qt.Key.Key_T: 67,   # G4
            Qt.Key.Key_Y: 69,   # A4
            Qt.Key.Key_U: 71,   # B4
            Qt.Key.Key_I: 72,   # C5
            Qt.Key.Key_O: 74,   # D5
            Qt.Key.Key_P: 76,   # E5

            # Upper octave black keys
            Qt.Key.Key_2: 61,   # C#4
            Qt.Key.Key_3: 63,   # D#4
            Qt.Key.Key_5: 66,   # F#4
            Qt.Key.Key_6: 68,   # G#4
            Qt.Key.Key_7: 70,   # A#4
            Qt.Key.Key_9: 73,   # C#5
            Qt.Key.Key_0: 75,   # D#5
        }

        # Enable keyboard input - make sure we can receive keyboard events
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus()  # Grab focus immediately


# StrudelViewWidget is defined later (after PluginRackWidget) to keep class
# scopes clean.

    # Event filter for container resize and keyboard drag
    def eventFilter(self, a0, a1):
        """Handle resize events for the plugin UI container and mouse drag for keys."""
        # Compatibility with PyQt6 type stubs: parameters are named a0, a1; map them to expected names.
        obj = a0
        event = a1

        # Handle container resize
        if obj == self.plugin_ui_container and event is not None and event.type() == event.Type.Resize:
            if self._embedded_hwnd:
                self._resize_embedded_window()
            return super().eventFilter(obj, event)

        # Handle mouse events on keyboard widget and its children
        is_keyboard_widget = False
        if hasattr(self, 'keyboard'):
            if obj == self.keyboard:
                is_keyboard_widget = True
            else:
                # Check if obj is a child of keyboard
                parent = obj
                while parent:
                    if parent == self.keyboard:
                        is_keyboard_widget = True
                        break
                    parent = parent.parent() if hasattr(parent, 'parent') else None

        if is_keyboard_widget:
            if event is not None and event.type() == event.Type.MouseButtonPress:
                mouse_event = event  # Event is already a QMouseEvent
                self._mouse_is_pressed = True
                # Find which key is under cursor
                mouse_event = event  # Event is already a QMouseEvent
                widget = self._get_key_at_pos(mouse_event.pos(), obj) # type: ignore
                if widget:
                    midi_note = widget.property("midi_note")
                    if midi_note is not None:
                        self._play_note_immediate(midi_note)
                        # Debug logging disabled for performance
                        # self._log(f"🖱️ Click note: {midi_note}")
                        return True  # Consume event to prevent double-triggering
                return False

            elif event is not None and event.type() == event.Type.MouseButtonRelease:
                self._mouse_is_pressed = False
                # Stop current note
                if self._current_drag_note is not None:
                    self._stop_note_immediate(self._current_drag_note)
                    # Debug logging disabled for performance
                    # self._log(f"🖱️ Release note: {self._current_drag_note}")
                    self._current_drag_note = None
                    return True  # Consume event
                return False

            elif event is not None and event.type() == event.Type.MouseMove:
                if self._mouse_is_pressed:
                    # Find which key is under cursor during drag
                    widget = self._get_key_at_pos(event.pos(), obj) # type: ignore
                    if widget:
                        midi_note = widget.property("midi_note")
                        if midi_note is not None and midi_note != self._current_drag_note:
                            # Switch to new note immediately (removed debounce as it was causing issues)
                            self._play_note_immediate(midi_note)
                            # Debug logging disabled for performance
                            # self._log(f"🎹 Drag to note: {midi_note}")
                    else:
                        # Mouse not over any key - stop current note
                        if self._current_drag_note is not None:
                            self._stop_note_immediate(self._current_drag_note)
                            self._current_drag_note = None
                return False

        return super().eventFilter(obj, event)

    def _get_key_at_pos(self, pos, source_widget):
        """Find which keyboard key widget is at the given position."""
        # Convert position to global coordinates
        global_pos = source_widget.mapToGlobal(pos)

        # Find widget at that position
        widget = QApplication.widgetAt(global_pos)

        # Check if it's one of our keyboard keys
        if widget and hasattr(widget, 'property') and widget.property("midi_note") is not None:
            return widget

        return None

    def _play_note_immediate(self, note: int) -> None:
        """Play a note immediately with bypass for latency, stopping current note first."""
        if not self.carla:
            return

        # Stop current note if different
        if self._current_drag_note is not None and self._current_drag_note != note:
            try:
                self._send_midi_fast(self._current_drag_note, 0)  # Note off
            except Exception:
                pass

        # Start new note
        self._current_drag_note = note
        try:
            velocity = self.keyboard.velocity_slider.value() / 127.0
            self._send_midi_fast(note, velocity)
        except Exception as e:
            self._log(f"⚠️ Note on error: {e}")

    def _stop_note_immediate(self, note: int) -> None:
        """Stop a note immediately with bypass for latency."""
        if not self.carla:
            return

        try:
            self._send_midi_fast(note, 0)  # Velocity 0 = note off
        except Exception:
            pass

    def _send_midi_fast(self, note: int, velocity: float) -> None:
        """Send MIDI directly, bypassing the slow waits in carla_host."""
        if not self.carla:
            return

        # Access the backend (CarlaVSTHost wraps CarlaBackend)
        if not hasattr(self.carla, '_backend'):
            return

        backend = self.carla._backend

        # Check if host is properly initialized
        if not hasattr(backend, 'host') or backend.host is None:
            return

        if not hasattr(backend, '_plugin_id') or backend._plugin_id is None:
            return

        try:
            # Convert velocity to MIDI range
            note = int(note)
            vel = max(0.0, min(1.0, float(velocity)))
            value = int(round(vel * 127.0))
            value = max(0, min(127, value))

            # Send MIDI directly, no waits!
            backend.host.send_midi_note(backend._plugin_id, 0, note, value)
            # self._log(f"✓ Fast: note={note} vel={value}")  # Debug logging disabled
        except Exception as e:
            self._log(f"❌ Fast MIDI failed: {e}")

    def _on_key_pressed(self, note: int) -> None:
        """Handle keyboard button press (mouse click)."""
        if not self.carla:
            return
        try:
            velocity = self.keyboard.velocity_slider.value() / 127.0
            self._send_midi_fast(note, velocity)
        except Exception as e:
            self._log(f"⚠️ Key click error: {e}")

    def _on_key_released(self, note: int) -> None:
        """Handle keyboard button release (mouse release)."""
        if not self.carla:
            return
        try:
            self._send_midi_fast(note, 0)  # Velocity 0 = note off
        except Exception as e:
            self._log(f"⚠️ Key release error: {e}")

    def keyPressEvent(self, event):
        """Handle keyboard input for playing notes."""
        # Ignore auto-repeat to prevent stuck notes
        if event.isAutoRepeat():
            event.accept()
            return

        key = event.key()

        # Emergency: Turn off all notes with Escape key
        if key == Qt.Key.Key_Escape:
            self._emergency_all_notes_off()
            event.accept()
            return

        # Check if this is a mapped piano key
        if key in self._key_to_note and self.is_keyboard_enabled() and self.carla:
            note = self._key_to_note[key]
            # Only send note-on if not already playing
            if note not in self._active_keyboard_notes:
                self._active_keyboard_notes.add(note)
                try:
                    self._send_midi_note_on(note)
                except Exception as e:
                    self._log(f"⚠️ Key press error: {e}")
                    self._active_keyboard_notes.discard(note)
            event.accept()
            return

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        """Handle keyboard release to stop notes."""
        # Ignore auto-repeat to prevent stuck notes
        if event.isAutoRepeat():
            event.accept()
            return

        key = event.key()

        # Check if this is a mapped piano key
        if key in self._key_to_note and self.is_keyboard_enabled():
            note = self._key_to_note[key]
            # Always send note-off, even if we think it's not playing
            if note in self._active_keyboard_notes:
                self._active_keyboard_notes.discard(note)
                try:
                    self._send_midi_note_off(note)
                except Exception as e:
                    self._log(f"⚠️ Key release error: {e}")
            event.accept()
            return

        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        """Turn off all notes when losing focus to prevent stuck notes."""
        self._emergency_all_notes_off()
        super().focusOutEvent(event)

    def _resize_embedded_window(self) -> None:
        """Resize the embedded plugin window to match container."""
        if not self._embedded_hwnd or os.name != 'nt':
            return
        try:
            rect = self.plugin_ui_container.rect()
            user32.SetWindowPos(
                self._embedded_hwnd,
                0,
                0, 0,
                rect.width(), rect.height(),
                SWP_NOZORDER | SWP_NOACTIVATE
            )
        except Exception as exc:
            self._log(f"⚠️ Error resizing embedded window: {exc}")

    def resize_plugin_viewport(self, width: int, height: int) -> None:
        """Ensure the plugin viewport matches the requested size."""
        width = max(200, int(width))
        height = max(150, int(height))
        self.plugin_ui_container.setMinimumSize(width, height)
        self.plugin_ui_container.resize(width, height)
        if hasattr(self, "plugin_ui_holder"):
            self.plugin_ui_holder.setMinimumSize(width, height + 8)
        if hasattr(self, "params_group"):
            margins = self.params_group.layout().contentsMargins()
            extra = margins.top() + margins.bottom() + 20
            self.params_group.setMinimumHeight(height + extra)
        if hasattr(self, "param_layout"):
            self.param_layout.invalidate()
        self._resize_embedded_window()

    # Plugin chain data (simple list of plugin paths)
    @property
    def plugin_chain(self) -> list[str]:
        """Get current plugin chain from list widget."""
        return [
            self.chain_list.item(i).data(Qt.UserRole)
            for i in range(self.chain_list.count())
        ]

    def serialize_state(self) -> dict:
        """Return a JSON-serialisable snapshot of plugin/card state."""
        workspace_label = getattr(self, "workspace_label", None)
        host_status_label = getattr(self, "host_status", None)
        workspace_text = workspace_label.text() if workspace_label else ""
        workspace = (workspace_text or "").replace("Workspace:", "").strip()
        state = {
            "workspace": workspace,
            "plugins": self._collect_plugins(),
            "chain": self._collect_chain(),
            "hostStatus": host_status_label.text() if host_status_label else "",
            "currentPluginPath": self._current_loaded_path,
        }
        return state

    def _collect_plugins(self) -> list[dict]:
        list_widget = getattr(self, "plugins_list", None)
        if list_widget is None:
            return []
        plugins: list[dict] = []
        for idx in range(list_widget.count()):
            item = list_widget.item(idx)
            data = item.data(Qt.UserRole) or {}
            entry = {
                "name": data.get("name") or item.text(),
                "format": data.get("format"),
                "path": str(data.get("path") or ""),
                "index": idx,
            }
            plugins.append(entry)
        return plugins

    def _collect_chain(self) -> list[dict]:
        chain_list = getattr(self, "chain_list", None)
        if chain_list is None:
            return []
        chain: list[dict] = []
        for idx in range(chain_list.count()):
            item = chain_list.item(idx)
            path_value = item.data(Qt.UserRole)
            chain.append({
                "label": item.text(),
                "path": str(path_value or ""),
                "index": idx,
                "active": str(path_value or "") == (self._current_loaded_path or ""),
            })
        return chain

    def _emit_state(self) -> None:
        try:
            state = self.serialize_state()
        except Exception as exc:  # pragma: no cover
            print(f"[PLUGIN STUDIO] Failed to serialize state: {exc}")
            return
        self.stateChanged.emit(state)

    def get_log_history(self) -> list[str]:
        return list(self._log_history)

    def serialize_keyboard_state(self) -> dict:
        return {
            "octave": self.keyboard.octave_spin.value(),
            "velocity": self.keyboard.velocity_slider.value(),
            "activeNotes": sorted(self._active_keyboard_notes),
            "enabled": bool(self._keyboard_enabled),
        }
    def _emit_keyboard_state(self) -> None:
        if not hasattr(self, "keyboard"):
            return
        self.keyboardStateChanged.emit(self.serialize_keyboard_state())

    def _set_keyboard_enabled(self, enabled: bool) -> None:
        """Enable/disable keyboard logic without surfacing the legacy widget."""
        self._keyboard_enabled = bool(enabled)
        if hasattr(self, "keyboard"):
            try:
                self.keyboard.setVisible(False)
            except Exception:
                pass
        self._emit_keyboard_state()

    def is_keyboard_enabled(self) -> bool:
        return bool(getattr(self, "_keyboard_enabled", False))

    def add_plugin_by_path(self, path: str) -> bool:
        """Add plugin to chain based on its absolute path."""
        if not path:
            return False
        for idx in range(self.plugins_list.count()):
            item = self.plugins_list.item(idx)
            data = item.data(Qt.UserRole) or {}
            if str(data.get("path")) == str(path):
                self.plugins_list.setCurrentRow(idx)
                self.add_selected_to_chain()
                return True
        self._log(f"Plugin path not found in discovery list: {path}")
        return False

    def remove_chain_index(self, index: int) -> bool:
        if 0 <= index < self.chain_list.count():
            self.chain_list.setCurrentRow(index)
            self.remove_selected_from_chain()
            return True
        return False

    def select_chain_index(self, index: int) -> bool:
        if 0 <= index < self.chain_list.count():
            self.chain_list.setCurrentRow(index)
            return True
        return False

    def load_chain_index(self, index: int) -> bool:
        if self.select_chain_index(index):
            self._load_selected_plugin()
            return True
        return False

    # --- Data ops
    def refresh(self) -> None:
        status = self.manager.status()  # type: ignore[union-attr]
        workspace = status.get('workspace', '(unknown)')
        self.workspace_label.setText(f"Workspace: {workspace}")
        self._log(f"Refreshing plugins from: {workspace}")

        # Discovered plugins
        self.plugins_list.clear()
        plugins = status.get("plugins", [])
        self._log(f"Found {len(plugins)} plugins")

        for item in plugins:
            name = item.get("name") or Path(item.get("path", "?"))
            name = name if isinstance(name, str) else name.name
            fmt = item.get("format", "?")
            path = item.get("path", "?")
            li = QListWidgetItem(f"{name} [{fmt}]")
            li.setToolTip(str(path))
            li.setData(Qt.UserRole, item)
            self.plugins_list.addItem(li)

        # Plugin chain is managed separately (not from manager status)
        # It's a simple ordered list maintained by add/remove operations

        self._update_host_status()
        self._emit_state()

    def add_selected_to_chain(self) -> None:
        """Add selected plugin from discovered list to the plugin chain."""
        item = self.plugins_list.currentItem()
        if not item:
            self._log("No plugin selected")
            return
        data = item.data(Qt.UserRole) or {}
        path = data.get("path")
        name = data.get("name") or Path(path).stem if path else "Unknown"
        fmt = data.get("format", "?")

        if not path:
            self._log("Plugin has no path")
            return

        # Add to chain list
        li = QListWidgetItem(f"{name} [{fmt}]")
        li.setToolTip(str(path))
        li.setData(Qt.UserRole, path)
        self.chain_list.addItem(li)
        self._log(f"Added to chain: {name}")
        self._emit_state()

    def remove_selected_from_chain(self) -> None:
        """Remove selected plugin from the chain."""
        row = self.chain_list.currentRow()
        if row >= 0:
            # If this plugin is currently loaded, unload it
            item = self.chain_list.item(row)
            if item and item.data(Qt.UserRole) == self._current_loaded_path:
                self.unload_host()
            self.chain_list.takeItem(row)
            self._emit_state()

    def _on_chain_selection(self, row: int) -> None:
        """Handle selection change in the plugin chain list."""
        # Could auto-preview the selected plugin here
        pass

    def _load_selected_plugin(self) -> None:
        """Load the currently selected plugin in the chain."""
        item = self.chain_list.currentItem()
        if not item:
            self._log("No plugin selected in chain")
            return
        path = item.data(Qt.UserRole)
        if not path:
            self._log("Selected plugin has no path")
            return

        if not self._ensure_carla():
            self._log("Carla not available")
            return

        try:
            # Unload current plugin if different
            if self._current_loaded_path != str(path):
                self._log(f"Loading plugin: {path}")
                try:
                    self.carla.unload()
                except Exception:
                    pass
                # Load and show UI (we'll embed it)
                self.carla.load_plugin(path, show_ui=True)
                self._current_loaded_path = str(path)
                self._log("Plugin loaded successfully")
                self._update_host_status()
                descriptor = {
                    "path": str(path),
                    "name": Path(str(path)).stem if path else "Plugin",
                }
                self.currentPluginChanged.emit(descriptor)
                self._emit_state()

                # Try to embed the plugin UI with retry
                self._embed_retry_count = 0
                self._start_embed_retry()

                # Show plugin UI window
                parent_window = self.parent()
                if parent_window and hasattr(parent_window, '_set_plugin_ui_visible'):
                    parent_window._set_plugin_ui_visible(True)

                # Enable MIDI keyboard if plugin exposes instrument capabilities
                try:
                    status = self.carla.status()
                    caps = status.get("capabilities", {})
                    is_instrument = caps.get("instrument", False) or caps.get("midi", False)
                    self._set_keyboard_enabled(is_instrument)
                    self._log(f"Plugin is instrument: {is_instrument}")
                except Exception as e:
                    self._log(f"Error checking instrument: {e}")
                    self._set_keyboard_enabled(False)
        except Exception as exc:
            self._log(f"Load error: {exc}")
            self._display_host_status(f"Load error: {exc}")
            self._set_keyboard_enabled(False)

    # --- Carla integration
    def _init_carla(self) -> None:
        if not CARLA_AVAILABLE:
            self.carla = None
            return
        try:
            self.carla = CarlaVSTHost()  # type: ignore[operator]
            self.carla.configure_audio(preferred_drivers=[
                "DirectSound", "WASAPI", "MME", "ASIO", "Dummy"
            ])
            self._update_host_status()
        except Exception as exc:
            self.carla = None
            self._display_host_status(f"Carla unavailable: {exc}")

    def _display_host_status(self, message: str) -> None:
        if hasattr(self, "host_status"):
            self.host_status.setText(message)
            self.host_status.setVisible(bool(message))
        self.hostStatusChanged.emit(message)
        self._emit_state()

    def _schedule_carla_warmup(self) -> None:
        if self._carla_warmup_started or not CARLA_AVAILABLE:
            return
        self._carla_warmup_started = True

        def _warmup() -> None:
            try:
                if not self._ensure_carla():
                    return
                assert self.carla is not None
                self.carla.warm_up_engine()
                self._log("Carla backend warmed (engine ready)")
            except Exception as exc:
                self._log(f"Carla warmup failed: {exc}")
            finally:
                self._carla_warmup_timer = None

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(_warmup)
        timer.start(500)
        self._carla_warmup_timer = timer

    def apply_theme_titles(self, theme: str) -> None:
        blank = theme == "win7"
        for group_box, title in self._groupbox_titles.items():
            group_box.setTitle("" if blank else title)

    def _update_host_status(self) -> None:
        if not self.carla:
            if not CARLA_AVAILABLE:
                self._display_host_status(
                    f"Carla not available: {globals().get('_CARLA_IMPORT_ERROR','import error')}"
                )
            return
        try:
            _ = self.carla.status(include_parameters=False)
            self._display_host_status("Carla ready")
        except Exception as exc:
            self._display_host_status(f"Carla error: {exc}")

    def _ensure_carla(self) -> bool:
        if self.carla:
            return True
        if not CARLA_AVAILABLE:
            return False
        try:
            self.carla = CarlaVSTHost()  # type: ignore[operator]
            self.carla.configure_audio(preferred_drivers=[
                "DirectSound", "WASAPI", "MME", "ASIO", "Dummy"
            ])
            self._update_host_status()
            return True
        except Exception as exc:
            self.carla = None
            self._display_host_status(f"Carla unavailable: {exc}")
            return False


    # --- Host UI helpers
    def show_host_ui(self) -> None:
        if not self.carla:
            return
        try:
            self.carla.show_ui()
            # Try to embed after showing with retry
            self._embed_retry_count = 0
            self._start_embed_retry()
        except Exception as exc:
            self._display_host_status(f"Show UI error: {exc}")

    def unload_host(self) -> None:
        if not self.carla:
            return
        try:
            # Turn off all notes first
            self._all_notes_off()

            # Stop any pending embedding attempts
            if self._embed_retry_timer:
                self._embed_retry_timer.stop()
                self._embed_retry_timer = None
            self._embed_retry_count = 0

            # Unembed first
            self._unembed_plugin_ui()
            self.carla.unload()
            self._update_host_status()
            self.no_plugin_label.setVisible(True)
            # Reset container size
            self.plugin_ui_container.setMinimumSize(400, 400)
            self._current_loaded_path = None
            self._set_keyboard_enabled(False)
            self.currentPluginChanged.emit({})
            self._emit_state()

            # Hide plugin UI and keyboard windows when unloading
            parent_window = self.parent()
            if parent_window and hasattr(parent_window, '_set_plugin_ui_visible'):
                parent_window._set_plugin_ui_visible(False)
        except Exception as exc:
            self._display_host_status(f"Unload error: {exc}")

    # --- Plugin UI Embedding
    def _start_embed_retry(self) -> None:
        """Start or restart the embedding retry timer."""
        if self._embed_retry_timer:
            self._embed_retry_timer.stop()
        self._embed_retry_timer = QTimer()
        self._embed_retry_timer.setSingleShot(True)
        self._embed_retry_timer.timeout.connect(self._attempt_embed_plugin_ui)
        self._embed_retry_timer.start(300)  # Try after 300ms

    def _attempt_embed_plugin_ui(self) -> None:
        """Attempt to embed the plugin's native UI window into our container.

        Uses CarlaVSTHost's safe get_plugin_window_handle() method which:
        - Only searches windows in the Carla process
        - Verifies window ownership using GetWindowThreadProcessId
        - Stores original window state for restoration
        """
        if os.name != 'nt':
            self._log("UI embedding only supported on Windows")
            return

        if not self.carla:
            return

        # Check if already embedded
        if self._embedded_hwnd:
            return

        try:
            # Use Carla's safe window detection (searches own process only)
            plugin_hwnd = self.carla.get_plugin_window_handle(attempts=3)
            if not plugin_hwnd:
                # Retry if we haven't exceeded max attempts
                self._embed_retry_count += 1
                if self._embed_retry_count < 10:  # Max 10 retries (3 seconds total)
                    self._log(f"⏳ Plugin window not ready yet, retrying... ({self._embed_retry_count}/10)")
                    self._start_embed_retry()
                else:
                    self._log("⚠️ Could not find plugin window after multiple attempts")
                    self._log("   Plugin UI may open in a separate window")
                return

            # Found the window, proceed with embedding
            self._embed_retry_count = 0  # Reset counter

            # Get our container's window handle
            container_hwnd = int(self.plugin_ui_container.winId())

            self._log(f"🔧 Embedding plugin window {plugin_hwnd} into container {container_hwnd}")

            # Store original state before modifying
            self._embedded_hwnd = plugin_hwnd
            self._embedded_original_parent = user32.GetParent(plugin_hwnd)
            self._embedded_original_style = user32.GetWindowLongW(plugin_hwnd, GWL_STYLE)

            # Get plugin window size before reparenting
            rect_struct = wintypes.RECT()
            user32.GetWindowRect(plugin_hwnd, ctypes.byref(rect_struct))
            plugin_width = rect_struct.right - rect_struct.left
            plugin_height = rect_struct.bottom - rect_struct.top

            self._log(f"📐 Plugin window size: {plugin_width}x{plugin_height}")

            # Reparent the plugin window
            user32.SetParent(plugin_hwnd, container_hwnd)

            # Change window style to WS_CHILD
            new_style = (self._embedded_original_style | WS_CHILD | WS_VISIBLE)
            user32.SetWindowLongW(plugin_hwnd, GWL_STYLE, new_style)

            # Resize container to match plugin size (with some padding)
            container_width = max(plugin_width, 400)
            container_height = max(plugin_height, 400)
            self.plugin_ui_container.setMinimumSize(container_width, container_height)
            self.plugin_ui_container.resize(container_width, container_height)

            # Position plugin window at top-left of container
            user32.SetWindowPos(
                plugin_hwnd,
                0,  # HWND_TOP
                0, 0,  # x, y
                plugin_width, plugin_height,  # Keep original size
                SWP_NOZORDER | SWP_NOACTIVATE
            )

            # Show the window
            user32.ShowWindow(plugin_hwnd, 1)  # SW_SHOWNORMAL

            self.no_plugin_label.setVisible(False)

            self._log("✅ Plugin UI embedded successfully")

        except Exception as exc:
            self._log(f"❌ Failed to embed plugin UI: {exc}")
            import traceback
            self._log(traceback.format_exc())

    def _unembed_plugin_ui(self) -> None:
        """Restore the plugin window to its original state."""
        if os.name != 'nt' or not self._embedded_hwnd:
            return

        try:
            # Restore original parent and style
            if hasattr(self, '_embedded_original_parent') and self._embedded_original_parent:
                user32.SetParent(self._embedded_hwnd, self._embedded_original_parent)
            else:
                user32.SetParent(self._embedded_hwnd, 0)  # Make top-level

            if hasattr(self, '_embedded_original_style'):
                user32.SetWindowLongW(self._embedded_hwnd, GWL_STYLE, self._embedded_original_style)

            self._embedded_hwnd = None
            self._embedded_original_parent = None
            self._embedded_original_style = None
            self._log("🔓 Plugin UI unembedded and restored")
        except Exception as exc:
            self._log(f"❌ Error unembedding: {exc}")


    # --- MIDI helpers
    def _make_midi_note_on_handler(self, note: int):
        """Create a MIDI note-on handler with proper closure."""
        def handler():
            self._send_midi_note_on(note)
        return handler

    def _make_midi_note_off_handler(self, note: int):
        """Create a MIDI note-off handler with proper closure."""
        def handler():
            self._send_midi_note_off(note)
        return handler

    def _send_midi_note_on(self, note: int) -> None:
        """Send MIDI note-on to Carla immediately using fast path."""
        if not self.carla:
            return

        # Get velocity from slider (0-127)
        velocity = self.keyboard.velocity_slider.value()
        # Normalize to 0.0-1.0 range
        velocity_normalized = velocity / 127.0

        # Use fast path to bypass latency
        self._send_midi_fast(note, velocity_normalized)
        self._active_keyboard_notes.add(int(note))
        self._emit_keyboard_state()

    def _send_midi_note_off(self, note: int) -> None:
        """Send MIDI note-off to Carla immediately using fast path."""
        if not self.carla:
            return

        # Use fast path with velocity 0 = note off
        self._send_midi_fast(note, 0.0)
        self._active_keyboard_notes.discard(int(note))
        self._emit_keyboard_state()

    def _emergency_all_notes_off(self) -> None:
        """Emergency: Turn off all currently playing notes."""
        if not self.carla:
            return

        # Only turn off notes we're actually tracking (not all 128!)
        all_notes = set()
        all_notes.update(self._active_keyboard_notes)
        if self._current_drag_note is not None:
            all_notes.add(self._current_drag_note)

        for note in all_notes:
            try:
                self.carla.note_off(note)
            except Exception:
                pass

        # Clear our tracking
        self._active_keyboard_notes.clear()
        self._current_drag_note = None
        self._mouse_is_pressed = False
        self._emit_keyboard_state()

    def trigger_note_on(self, note: int) -> None:
        if not self.carla:
            return
        self._send_midi_note_on(int(note))

    def trigger_note_off(self, note: int) -> None:
        if not self.carla:
            return
        self._send_midi_note_off(int(note))

    def set_keyboard_velocity(self, value: int) -> None:
        clamped = max(0, min(127, int(value)))
        self.keyboard.velocity_slider.setValue(clamped)
        self._emit_keyboard_state()

    def set_keyboard_octave(self, value: int) -> None:
        clamped = max(self.keyboard.octave_spin.minimum(), min(self.keyboard.octave_spin.maximum(), int(value)))
        self.keyboard.octave_spin.setValue(clamped)
        self._emit_keyboard_state()

    # --- Session stubs
    def save_session(self) -> None:
        self._log("Session save not implemented yet.")

    def load_session(self) -> None:
        self._log("Session load not implemented yet.")

        self._log("🛑 All notes off (emergency)")

    def _update_keyboard_mapping(self, new_octave: int) -> None:
        """Update keyboard mapping to start at the specified octave."""
        # The keyboard always spans 2 octaves starting from new_octave
        # Calculate the MIDI note number for C at the specified octave
        # Middle C (C4) = MIDI 60, so C at any octave = 12 + octave * 12
        base_note = 12 + new_octave * 12

        # Home row starts at the base octave
        # QWERTY row starts one octave higher
        self._key_to_note = {
            # White keys (C D E F G A B C D E)
            Qt.Key.Key_Z: base_note + 0,    # C
            Qt.Key.Key_X: base_note + 2,    # D
            Qt.Key.Key_C: base_note + 4,    # E
            Qt.Key.Key_V: base_note + 5,    # F
            Qt.Key.Key_B: base_note + 7,    # G
            Qt.Key.Key_N: base_note + 9,    # A
            Qt.Key.Key_M: base_note + 11,   # B
            Qt.Key.Key_Comma: base_note + 12,   # C (next octave)
            Qt.Key.Key_Period: base_note + 14,  # D
            Qt.Key.Key_Slash: base_note + 16,   # E

            # Black keys (C# D# F# G# A# C# D#)
            Qt.Key.Key_S: base_note + 1,    # C#
            Qt.Key.Key_D: base_note + 3,    # D#
            Qt.Key.Key_G: base_note + 6,    # F#
            Qt.Key.Key_H: base_note + 8,    # G#
            Qt.Key.Key_J: base_note + 10,   # A#
            Qt.Key.Key_L: base_note + 13,   # C#
            Qt.Key.Key_Semicolon: base_note + 15,  # D#

            # Upper octave white keys (one octave higher)
            Qt.Key.Key_Q: base_note + 12,   # C
            Qt.Key.Key_W: base_note + 14,   # D
            Qt.Key.Key_E: base_note + 16,   # E
            Qt.Key.Key_R: base_note + 17,   # F
            Qt.Key.Key_T: base_note + 19,   # G
            Qt.Key.Key_Y: base_note + 21,   # A
            Qt.Key.Key_U: base_note + 23,   # B
            Qt.Key.Key_I: base_note + 24,   # C
            Qt.Key.Key_O: base_note + 26,   # D
            Qt.Key.Key_P: base_note + 28,   # E

            # Upper octave black keys
            Qt.Key.Key_2: base_note + 13,   # C#
            Qt.Key.Key_3: base_note + 15,   # D#
            Qt.Key.Key_5: base_note + 18,   # F#
            Qt.Key.Key_6: base_note + 20,   # G#
            Qt.Key.Key_7: base_note + 22,   # A#
            Qt.Key.Key_9: base_note + 25,   # C#
            Qt.Key.Key_0: base_note + 27,   # D#
        }

        self._log(f"⌨️ Keyboard mapping updated to octave {new_octave}")

    def _all_notes_off(self) -> None:
        """Turn off all notes (called on cleanup)."""
        self._emergency_all_notes_off()

    def _log(self, message: str) -> None:
        """Add message to console log viewer."""
        self.log_viewer.append(message)
        # Auto-scroll to bottom
        cursor = self.log_viewer.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_viewer.setTextCursor(cursor)
        self._log_history.append(message)
        self.logMessage.emit(message)


class InstrumentKeyboardWidget(QGroupBox):
    """Digital piano keyboard for MIDI input, similar to HTML UI."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Instrument Keyboard", parent)
        # Removed inline stylesheet to allow theme control

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # Header row
        header = QHBoxLayout()
        subtitle = QLabel("Play notes using the digital keyboard")
        # Removed inline stylesheet to allow theme control
        header.addWidget(subtitle)
        header.addStretch()

        # Octave controls
        octave_label = QLabel("Octave:")
        # Removed inline stylesheet to allow theme control
        header.addWidget(octave_label)
        self.octave_spin = QSpinBox()
        self.octave_spin.setRange(-2, 8)
        # Set initial value to 3 to match the default keyboard mapping (C3-E5)
        self.octave_spin.setValue(3)
        self.octave_spin.valueChanged.connect(self._on_octave_changed)
        # Removed inline stylesheet to allow theme control
        header.addWidget(self.octave_spin)

        layout.addLayout(header)

        # Keyboard container (scrollable)
        keyboard_scroll = QScrollArea()
        keyboard_scroll.setWidgetResizable(True)
        keyboard_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        keyboard_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        keyboard_scroll.setMinimumHeight(180)
        # Removed inline stylesheet to allow theme control

        # Use a custom widget with absolute positioning for proper key overlap
        keyboard_widget = QWidget()
        keyboard_widget.setMinimumHeight(170)
        keyboard_widget.setMinimumWidth(700)  # Enough for 2 octaves
        # Removed inline stylesheet to allow theme control

        self.keys = []
        self.first_c_key = None  # Reference to first C key for label updates
        white_key_width = 36  # Thinner white keys
        black_key_width = 22  # Wider black keys (relative to white)
        white_key_height = 145
        black_key_height = 95

        x_pos = 10  # Starting position

        # Pattern for 2 octaves: C D E F G A B (x2)
        # Black keys are between: C-D, D-E, F-G, G-A, A-B
        for octave in range(2):  # 2 octaves
            octave_num = octave + self.octave_spin.value()  # Base octave from spinner
            white_notes = ["C", "D", "E", "F", "G", "A", "B"]

            for i, note in enumerate(white_notes):
                # Only label the very first C key
                is_first_c = (octave == 0 and note == "C")
                key_label = f"C{octave_num}" if is_first_c else ""

                # Create white key without label (or with label for first C)
                key = QPushButton(key_label, keyboard_widget)
                key.setGeometry(x_pos, 10, white_key_width, white_key_height)

                # Store reference to first C key
                if is_first_c:
                    self.first_c_key = key
                key.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 #ffffff, stop:0.9 #f0f0f0, stop:1 #d8d8d8);
                        color: #333;
                        border: 1px solid #666;
                        border-top: none;
                        border-radius: 0 0 5px 5px;
                        font-weight: bold;
                        font-size: 10px;
                        padding-bottom: 8px;
                    }
                    QPushButton:hover {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 #fff, stop:0.9 #f8f8f8, stop:1 #e0e0e0);
                    }
                    QPushButton:pressed {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 #ff8c42, stop:1 #e87022);
                        color: #fff;
                        border-color: #c55a11;
                    }
                """)
                self.keys.append(key)

                # Create black key if needed (not after E or B)
                if note not in ["E", "B"]:
                    black_key = QPushButton("", keyboard_widget)  # No label
                    # Position black key between white keys
                    black_x = x_pos + white_key_width - (black_key_width // 2)
                    black_key.setGeometry(black_x, 10, black_key_width, black_key_height)
                    black_key.setStyleSheet("""
                        QPushButton {
                            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #2a2a2a, stop:0.8 #1a1a1a, stop:1 #0a0a0a);
                            color: #aaa;
                            border: 1px solid #000;
                            border-top: none;
                            border-radius: 0 0 3px 3px;
                            font-weight: bold;
                            font-size: 8px;
                            padding-bottom: 4px;
                        }
                        QPushButton:hover {
                            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #3a3a3a, stop:0.8 #2a2a2a, stop:1 #1a1a1a);
                            color: #ccc;
                        }
                        QPushButton:pressed {
                            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #ff8c42, stop:1 #c55a11);
                            color: #fff;
                            border-color: #a04a09;
                        }
                    """)
                    black_key.raise_()  # Bring black keys to front
                    self.keys.append(black_key)

                x_pos += white_key_width

        keyboard_scroll.setWidget(keyboard_widget)
        layout.addWidget(keyboard_scroll, 1)

        # Footer row
        footer = QHBoxLayout()
        velocity_label = QLabel("Velocity:")
        # Removed inline stylesheet to allow theme control
        footer.addWidget(velocity_label)
        self.velocity_slider = QSlider(Qt.Horizontal)
        self.velocity_slider.setRange(0, 127)
        self.velocity_slider.setValue(80)
        self.velocity_slider.setMaximumWidth(150)
        # Removed inline stylesheet to allow theme control
        footer.addWidget(self.velocity_slider)
        self.velocity_value = QLabel("80")
        # Removed inline stylesheet to allow theme control
        self.velocity_slider.valueChanged.connect(lambda v: self.velocity_value.setText(str(v)))
        footer.addWidget(self.velocity_value)
        footer.addStretch()
        layout.addLayout(footer)

    def _on_octave_changed(self, new_octave: int) -> None:
        """Called when the octave spinner value changes."""
        # Update the first C key's label to show the new octave
        if self.first_c_key:
            self.first_c_key.setText(f"C{new_octave}")

        # Note: Keyboard mapping is updated via direct signal connection in PluginRackWidget

class StaticHTTPServer:
    """Simple HTTP server for serving local assets (web desktop, Strudel, etc.)."""

    def __init__(self, root: Path, mounts: Optional[dict[str, Path]] = None, fallback: Optional[Path] = None, port: int = 0):
        self.root = Path(root).resolve()
        self.mounts = self._normalize_mounts(mounts or {})
        self.fallback = Path(fallback).resolve() if fallback else None
        self.port = port
        self.strudel_proxy_prefix = STRUDEL_PROXY_PREFIX
        self.strudel_remote_base = STRUDEL_REMOTE_BASE
        self.strudel_proxy_timeout = STRUDEL_PROXY_TIMEOUT
        self.strudel_proxy_user_agent = STRUDEL_PROXY_USER_AGENT
        self.strudel_asset_prefixes = STRUDEL_PROXY_ASSET_PREFIXES
        self.strudel_asset_exact = STRUDEL_PROXY_ASSET_EXACT
        self.server: socketserver.TCPServer | None = None
        self.thread: threading.Thread | None = None
        self.actual_port: int | None = None

    @staticmethod
    def _normalize_mounts(mounts: dict[str, Path]) -> dict[str, Path]:
        normalized: dict[str, Path] = {}
        for prefix, directory in mounts.items():
            clean = prefix.strip("/")
            if not clean:
                continue
            normalized[f"/{clean}/"] = Path(directory).resolve()
        return normalized

    def start(self) -> int:
        """Start the HTTP server in a background thread. Returns the port number."""
        if self.server is not None and self.actual_port is not None:
            return self.actual_port

        root = self.root
        mounts = self.mounts
        fallback = self.fallback
        strudel_proxy_prefix = self.strudel_proxy_prefix
        strudel_remote_base = self.strudel_remote_base
        strudel_proxy_timeout = self.strudel_proxy_timeout
        strudel_proxy_user_agent = self.strudel_proxy_user_agent
        strudel_asset_prefixes = self.strudel_asset_prefixes
        strudel_asset_exact = self.strudel_asset_exact

        class MultiRootHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                self._root = root
                self._mounts = mounts
                self._fallback = fallback
                self._strudel_proxy_prefix = strudel_proxy_prefix
                self._strudel_remote_base = strudel_remote_base
                self._strudel_proxy_timeout = strudel_proxy_timeout
                self._strudel_proxy_user_agent = strudel_proxy_user_agent
                self._strudel_asset_prefixes = strudel_asset_prefixes
                self._strudel_asset_exact = strudel_asset_exact
                super().__init__(*args, directory=str(root), **kwargs)

            def do_GET(self):
                if self._handle_strudel_proxy():
                    return
                super().do_GET()

            def translate_path(self, path: str) -> str:
                parsed = urlparse(path)
                clean_path = unquote(parsed.path or "/")
                if not clean_path.startswith("/"):
                    clean_path = "/" + clean_path
                for prefix, directory in self._mounts.items():
                    if clean_path == prefix[:-1] or clean_path.startswith(prefix):
                        rel = clean_path[len(prefix):].lstrip("/")
                        return str((directory / rel).resolve())
                rel = clean_path.lstrip("/")
                candidate = (self._root / rel).resolve()
                if candidate.exists():
                    return str(candidate)
                if self._fallback:
                    fallback_candidate = (self._fallback / rel).resolve()
                    if fallback_candidate.exists():
                        return str(fallback_candidate)
                return str(candidate)

            def _handle_strudel_proxy(self) -> bool:
                prefix = (self._strudel_proxy_prefix or "").rstrip("/")
                if not prefix:
                    return False
                if not prefix.startswith("/"):
                    prefix = f"/{prefix}"
                parsed = urlparse(self.path)
                path = parsed.path or "/"
                if path == prefix or path == f"{prefix}/":
                    self._proxy_strudel_request("/", parsed.query)
                    return True
                if path.startswith(f"{prefix}/"):
                    relative = path[len(prefix):] or "/"
                    self._proxy_strudel_request(relative, parsed.query)
                    return True
                if self._is_strudel_asset_path(path):
                    self._proxy_strudel_request(path, parsed.query)
                    return True
                referer = self.headers.get("Referer", "")
                host_header = self.headers.get("Host")
                default_host = self.server.server_address[0]
                default_port = self.server.server_address[1]
                origin = f"http://{host_header or f'{default_host}:{default_port}'}"
                referer_prefix = f"{origin}{prefix}/"
                if not referer.startswith(referer_prefix):
                    return False
                accept = self.headers.get("Accept", "")
                if self._should_redirect_to_prefix(path, accept):
                    target = self._build_prefixed_path(path, parsed.query, prefix)
                    self.send_response(HTTPStatus.FOUND)
                    self.send_header("Location", target)
                    self.end_headers()
                    return True
                self._proxy_strudel_request(path, parsed.query)
                return True

            def _is_strudel_asset_path(self, path: str) -> bool:
                for prefix in self._strudel_asset_prefixes:
                    if path.startswith(prefix):
                        return True
                return path in self._strudel_asset_exact

            @staticmethod
            def _should_redirect_to_prefix(path: str, accept: str) -> bool:
                suffix = PurePosixPath(path).suffix.lower()
                if not suffix:
                    return True
                if suffix in {".html", ".htm"}:
                    return True
                if "text/html" in accept:
                    return True
                return False

            @staticmethod
            def _build_prefixed_path(path: str, query: str, prefix: str) -> str:
                base = prefix.rstrip("/")
                suffix = path.lstrip("/")
                proxied = f"{base}/" if not suffix else f"{base}/{suffix}"
                if query:
                    return f"{proxied}?{query}"
                return proxied

            def _proxy_strudel_request(self, remote_path: str, query: str) -> None:
                clean = remote_path or "/"
                if not clean.startswith("/"):
                    clean = f"/{clean}"
                upstream = urljoin(self._strudel_remote_base, clean)
                if query:
                    upstream = f"{upstream}?{query}"
                self._stream_remote(upstream)

            def _stream_remote(self, remote_url: str) -> None:
                request = Request(
                    remote_url,
                    headers={
                        "User-Agent": self._strudel_proxy_user_agent,
                        "Accept": "*/*",
                        "Accept-Encoding": "identity",
                    },
                )
                try:
                    with urlopen(request, timeout=self._strudel_proxy_timeout) as response:
                        data = response.read()
                        status = getattr(response, "status", response.getcode())
                        self._write_proxy_response(status, response.headers, data)
                except HTTPError as exc:
                    body = exc.read()
                    self._write_proxy_response(exc.code, exc.headers, body)
                except URLError as exc:
                    reason = getattr(exc, "reason", exc)
                    print(f"[STRUDEL] Proxy fetch failed for {remote_url}: {reason}")
                    self.send_error(HTTPStatus.BAD_GATEWAY, f"Strudel proxy failed: {reason}")

            def _write_proxy_response(self, status: int, headers, body: bytes) -> None:
                self.send_response(status)
                content_type = headers.get("Content-Type", "application/octet-stream") if headers else "application/octet-stream"
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                cache_control = headers.get("Cache-Control") if headers else None
                self.send_header("Cache-Control", cache_control or "no-store")
                if headers:
                    for key, value in headers.items():
                        lowered = key.lower()
                        if lowered in STRUDEL_PROXY_HEADER_BLOCKLIST:
                            continue
                        if lowered in {"content-type", "content-length"}:
                            continue
                        self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:
                pass

        handler = partial(MultiRootHandler)

        class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
            allow_reuse_address = True

        bind_port = self.port or 0
        self.server = ThreadedTCPServer(("127.0.0.1", bind_port), handler)
        self.actual_port = self.server.server_address[1]

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        return self.actual_port

    def stop(self) -> None:
        """Stop the HTTP server."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None
        self.actual_port = None


_desktop_http_server: Optional[StaticHTTPServer] = None



def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO)
    app = QApplication(sys.argv if argv is None else argv)
    win = AmbianceMainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())



