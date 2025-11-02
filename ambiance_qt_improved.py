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
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ambiance.integrations.carla_host import CarlaVSTHost
import threading
import http.server
import socketserver
from functools import partial
import time

os.environ.setdefault("QT_API", "pyqt6")

from qtpy.QtCore import Qt, QTimer, QObject
from qtpy.QtGui import QTextCursor, QWindow, QMouseEvent
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
    from qtpy.QtWebEngineWidgets import QWebEngineView  # type: ignore
    WEBENGINE_AVAILABLE = True
except Exception as e:  # pragma: no cover
    QWebEngineView = None  # type: ignore
    WEBENGINE_AVAILABLE = False
    WEBENGINE_IMPORT_ERROR = str(e)


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

        # Add toolbar at top
        self.toolbar = self._create_toolbar()
        layout.addWidget(self.toolbar)

        # Desktop area with MDI (Multiple Document Interface)
        from qtpy.QtWidgets import QMdiArea
        self.desktop = QMdiArea()
        self.desktop.setObjectName("desktop")  # For stylesheet targeting
        self.desktop.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.desktop.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.desktop.setViewMode(QMdiArea.ViewMode.SubWindowView)  # SubWindow mode
        self.desktop.setAutoFillBackground(True)  # Enable custom background

        layout.addWidget(self.desktop)

        # Initialize Strudel state (will be loaded on demand)
        self._strudel_loaded = False
        self._strudel_window = None

        # Taskbar at bottom (will be populated after windows are created)
        self.taskbar = QWidget()
        self.taskbar.setObjectName("taskbar")  # For stylesheet targeting
        self.taskbar_layout = QHBoxLayout(self.taskbar)
        self.taskbar_layout.setContentsMargins(4, 4, 4, 4)
        self.taskbar_layout.setSpacing(4)
        self.taskbar.setFixedHeight(40)

        layout.addWidget(self.taskbar)

        # Store reference to plugin rack widget
        self.plugin_rack_widget = None
        if PluginRackManager is not None:
            self.plugin_rack_widget = PluginRackWidget(self)
            # Hide the main widget since we only use its children in MDI windows
            self.plugin_rack_widget.hide()

        # Apply initial theme
        self.current_theme = "flat"
        self._apply_theme(self.current_theme)

        # Create desktop windows after theme is applied
        self._create_desktop_windows()

        # Install application-level event filter to catch keyboard events
        QApplication.instance().installEventFilter(self)

        # Load Strudel on startup (hidden by default for no lag when user opens it)
        QTimer.singleShot(1000, self._load_strudel_window)

    def eventFilter(self, obj, event):
        """Catch keyboard events and forward to PluginRackWidget, also track window visibility."""
        # Handle keyboard events
        if event.type() == event.Type.KeyPress or event.type() == event.Type.KeyRelease:
            # Forward keyboard events to plugin rack widget if it exists and has a keyboard
            if self.plugin_rack_widget and self.plugin_rack_widget.keyboard.isVisible():
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

    def _scan_themes(self) -> dict:
        """Scan themes directory and return available themes."""
        themes_dir = _ROOT / "themes"
        themes = {}

        if themes_dir.exists():
            for css_file in sorted(themes_dir.glob("*.css")):
                # Theme name is filename without extension
                theme_id = css_file.stem
                # Display name: capitalize and replace hyphens/underscores with spaces
                display_name = theme_id.replace('-', ' ').replace('_', ' ').title()
                themes[theme_id] = {
                    'id': theme_id,
                    'name': display_name,
                    'path': css_file
                }

        return themes

    def _create_toolbar(self) -> QWidget:
        """Create the main toolbar similar to HTML UI."""
        toolbar = QWidget()
        # Removed inline stylesheet to allow theme control
        layout = QHBoxLayout(toolbar)
        layout.setSpacing(10)

        # Start Audio button (placeholder for future audio engine integration)
        self.start_audio_btn = QPushButton("Start Audio")
        self.start_audio_btn.setToolTip("Initialize audio engine")
        layout.addWidget(self.start_audio_btn)

        # Theme picker - dynamically populated from themes directory
        theme_label = QLabel("Theme:")
        layout.addWidget(theme_label)
        self.theme_combo = QComboBox()

        # Scan for available themes
        self.available_themes = self._scan_themes()
        for theme_id, theme_info in self.available_themes.items():
            self.theme_combo.addItem(theme_info['name'], theme_id)

        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        layout.addWidget(self.theme_combo)

        layout.addStretch()

        # Save/Load session buttons
        self.save_btn = QPushButton("Save Session")
        self.save_btn.setToolTip("Save current plugin rack and parameters")
        layout.addWidget(self.save_btn)

        self.load_btn = QPushButton("Load Session")
        self.load_btn.setToolTip("Load a saved session")
        layout.addWidget(self.load_btn)

        # Status label
        self.status_label = QLabel("Ready")
        # Removed inline stylesheet to allow theme control
        layout.addWidget(self.status_label)

        # Keyboard focus indicator
        self.focus_indicator = QLabel("⌨️ Press ESC to stop all notes")
        # Removed inline stylesheet to allow theme control
        layout.addWidget(self.focus_indicator)

        return toolbar

    def _on_theme_changed(self, index: int) -> None:
        """Handle theme selection change."""
        theme_id = self.theme_combo.itemData(index)
        if theme_id and theme_id in self.available_themes:
            self.current_theme = theme_id
            self._apply_theme(self.current_theme)

    def _apply_theme(self, theme: str) -> None:
        """Apply a visual theme to the application by loading CSS file."""
        # Check if theme exists
        if theme not in self.available_themes:
            print(f"[WARNING] Theme '{theme}' not found, using flat")
            theme = 'flat'

        theme_info = self.available_themes.get(theme)
        if not theme_info:
            print("[WARNING] No themes available!")
            return

        # Load CSS file
        css_path = theme_info['path']
        try:
            with open(css_path, 'r', encoding='utf-8') as f:
                css_content = f.read()

            # Replace variables in CSS
            # Scan for all {filename} patterns and replace with full paths
            import re
            def replace_path(match):
                filename = match.group(1)
                full_path = str(_ROOT / filename).replace("\\", "/")
                return full_path

            css_content = re.sub(r'\{([^}]+)\}', replace_path, css_content)

            # Apply stylesheet
            self.setStyleSheet(css_content)
            print(f"[THEME] Applied theme: {theme_info['name']}")

            # Debug: Print first 200 chars of CSS
            if len(css_content) > 200:
                print(f"[DEBUG] CSS preview: {css_content[:200]}...")
            else:
                print(f"[DEBUG] CSS content: {css_content}")

        except Exception as e:
            print(f"[ERROR] Error loading theme: {e}")
            import traceback
            traceback.print_exc()
            return

        # Force desktop background to refresh
        if hasattr(self, 'desktop'):
            self.desktop.update()
            self.desktop.repaint()

            # Refresh all MDI windows to update their styling
            for window in self.desktop.subWindowList():
                window.update()
                window.repaint()

    def _window_close_event_filter(self, window):
        """Event filter to intercept close button and minimize instead."""
        class WindowEventFilter(QObject):
            def __init__(self, parent_window):
                super().__init__()
                self.parent_window = parent_window

            def eventFilter(self, obj, event):
                if event.type() == event.Type.Close:
                    # Minimize instead of closing
                    self.parent_window.hide()
                    event.ignore()
                    return True
                return False

        filter_obj = WindowEventFilter(window)
        window.installEventFilter(filter_obj)
        # Store reference so it doesn't get garbage collected
        if not hasattr(self, '_window_filters'):
            self._window_filters = []
        self._window_filters.append(filter_obj)

    def _create_desktop_windows(self) -> None:
        """Create moveable windows on the desktop for each component."""
        from qtpy.QtWidgets import QMdiSubWindow

        if not self.plugin_rack_widget:
            return

        # Store window references for taskbar
        self.mdi_windows = {}

        # Plugin Studio Window (Plugin discovery and chain)
        plugin_studio_win = QMdiSubWindow()
        plugin_studio_win.setWidget(self.plugin_rack_widget.header_group)
        plugin_studio_win.setWindowTitle("Plugin Studio")
        plugin_studio_win.setGeometry(20, 20, 800, 400)
        plugin_studio_win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)  # Hide instead of close
        # Remove window flags that cause white boxes
        plugin_studio_win.setWindowFlags(
            Qt.WindowType.SubWindow | Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self._window_close_event_filter(plugin_studio_win)
        self.desktop.addSubWindow(plugin_studio_win)
        plugin_studio_win.show()
        self.mdi_windows["Plugin Studio"] = plugin_studio_win

        # Plugin UI Window
        plugin_ui_win = QMdiSubWindow()
        plugin_ui_win.setWidget(self.plugin_rack_widget.params_group)
        plugin_ui_win.setWindowTitle("Plugin UI")
        plugin_ui_win.setGeometry(840, 20, 500, 500)
        plugin_ui_win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)  # Hide instead of close
        # Remove window flags that cause white boxes
        plugin_ui_win.setWindowFlags(
            Qt.WindowType.SubWindow | Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self._window_close_event_filter(plugin_ui_win)
        self.desktop.addSubWindow(plugin_ui_win)
        plugin_ui_win.show()
        self.mdi_windows["Plugin UI"] = plugin_ui_win

        # Keyboard Window
        keyboard_win = QMdiSubWindow()
        keyboard_win.setWidget(self.plugin_rack_widget.keyboard)
        keyboard_win.setWindowTitle("Instrument Keyboard")
        keyboard_win.setGeometry(20, 440, 800, 375)  # Increased height by 50%
        keyboard_win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)  # Hide instead of close
        # Remove window flags that cause white boxes
        keyboard_win.setWindowFlags(
            Qt.WindowType.SubWindow | Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self._window_close_event_filter(keyboard_win)
        self.desktop.addSubWindow(keyboard_win)
        keyboard_win.show()
        self.keyboard_window = keyboard_win
        self.mdi_windows["Instrument Keyboard"] = keyboard_win

        # Console Log Window
        console_win = QMdiSubWindow()
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(4, 4, 4, 4)
        log_layout.addWidget(self.plugin_rack_widget.log_viewer)
        console_win.setWidget(log_widget)
        console_win.setWindowTitle("Console Log")
        console_win.setGeometry(840, 540, 500, 200)
        console_win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)  # Hide instead of close
        # Remove window flags that cause white boxes
        console_win.setWindowFlags(
            Qt.WindowType.SubWindow | Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self._window_close_event_filter(console_win)
        self.desktop.addSubWindow(console_win)
        console_win.show()
        self.mdi_windows["Console Log"] = console_win

        # Create taskbar buttons now that windows exist
        self._populate_taskbar()

    def _populate_taskbar(self) -> None:
        """Populate the taskbar with buttons for each window."""
        import time

        # Disconnect old signal connections if they exist
        if hasattr(self, '_taskbar_buttons'):
            for window, btn in self._taskbar_buttons.items():
                try:
                    window.windowStateChanged.disconnect()
                except:
                    pass

        # Clear existing taskbar contents
        while self.taskbar_layout.count():
            item = self.taskbar_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Store window-to-button mapping
        self._taskbar_buttons = {}

        # Add Start button (Windows-style)
        start_btn = QPushButton("Start")
        start_btn.setFixedWidth(80)
        start_btn.setToolTip("Start Menu")
        self.taskbar_layout.addWidget(start_btn)

        # Add separator
        self.taskbar_layout.addSpacing(8)

        # Add button for each window
        for window_name, window in self.mdi_windows.items():
            btn = QPushButton(window_name)
            btn.setMinimumWidth(120)
            btn.setCheckable(True)
            btn.setToolTip(f"Click to show/hide {window_name}")

            # Store button reference
            self._taskbar_buttons[window] = btn

            # Connect button to activate window
            btn.clicked.connect(lambda checked, w=window: self._activate_window(w))

            # Track window state changes - use a method instead of lambda
            window.windowStateChanged.connect(lambda old_state, new_state, w=window: self._on_window_state_changed(w, new_state))

            # Install event filter to catch hide/show events
            window.installEventFilter(self)

            self.taskbar_layout.addWidget(btn)

        # Add stretch to push clock to the right
        self.taskbar_layout.addStretch()

        # Add clock
        self.clock_label = QLabel(time.strftime("%H:%M"))
        self.clock_label.setFixedWidth(60)
        self.clock_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.taskbar_layout.addWidget(self.clock_label)

        # Update clock every minute
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(lambda: self.clock_label.setText(time.strftime("%H:%M")))
        self.clock_timer.start(60000)  # Update every minute

    def _activate_window(self, window) -> None:
        """Toggle window visibility when taskbar button is clicked."""
        # If window is active and visible, minimize/hide it
        if window.isVisible() and self.desktop.activeSubWindow() == window:
            window.hide()
        else:
            # Show and activate the window
            window.show()
            if window.isMinimized():
                window.showNormal()
            window.raise_()
            window.setFocus()
            self.desktop.setActiveSubWindow(window)

    def _on_window_state_changed(self, window, new_state) -> None:
        """Update taskbar button when window state changes."""
        from qtpy.QtCore import Qt
        # Look up the button for this window
        if hasattr(self, '_taskbar_buttons') and window in self._taskbar_buttons:
            btn = self._taskbar_buttons[window]
            try:
                # Button is checked if window is visible and not minimized
                is_active = window.isVisible() and new_state != Qt.WindowState.WindowMinimized
                btn.setChecked(is_active)
            except RuntimeError:
                # Button was deleted, ignore
                pass

    def _on_window_visibility_changed(self, window, visible) -> None:
        """Update taskbar button when window visibility changes."""
        if hasattr(self, '_taskbar_buttons') and window in self._taskbar_buttons:
            btn = self._taskbar_buttons[window]
            try:
                # Update button checked state based on visibility
                btn.setChecked(visible)
            except RuntimeError:
                # Button was deleted, ignore
                pass

    def _load_strudel_window(self) -> None:
        """Load Strudel in an MDI window."""
        if self._strudel_loaded:
            # If already loaded, just show the window
            if self._strudel_window:
                self._strudel_window.show()
                self._strudel_window.raise_()
                self.desktop.setActiveSubWindow(self._strudel_window)
            return

        try:
            from qtpy.QtWidgets import QMdiSubWindow

            # Create Strudel widget
            strudel_widget = StrudelViewWidget(self)

            # Create MDI window for Strudel
            strudel_win = QMdiSubWindow()
            strudel_win.setWidget(strudel_widget)
            strudel_win.setWindowTitle("Strudel Live Coding")
            strudel_win.setGeometry(100, 100, 1000, 600)

            # Prevent window from being deleted when closed - just hide it instead
            strudel_win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

            # Remove window flags that cause white boxes
            strudel_win.setWindowFlags(
                Qt.WindowType.SubWindow | Qt.WindowType.CustomizeWindowHint |
                Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowMinMaxButtonsHint
            )
            self._window_close_event_filter(strudel_win)

            self.desktop.addSubWindow(strudel_win)

            # Connect to window state changes to fix rendering issues
            strudel_win.windowStateChanged.connect(lambda old, new: self._on_strudel_state_changed(strudel_widget, new))

            # Don't show by default - user can open via menu/button
            # strudel_win.show()

            self._strudel_window = strudel_win
            self._strudel_widget = strudel_widget
            self._strudel_loaded = True

            # Add to taskbar if we want it visible
            if hasattr(self, 'mdi_windows'):
                self.mdi_windows["Strudel Live Coding"] = strudel_win
                self._populate_taskbar()

        except Exception as exc:
            QMessageBox.warning(self, "Strudel Error", f"Failed to load Strudel: {exc}")

    def _on_strudel_state_changed(self, strudel_widget, new_state) -> None:
        """Handle Strudel window state changes to fix rendering issues."""
        from qtpy.QtCore import Qt
        # Force a repaint when window is restored from minimized state
        if new_state != Qt.WindowState.WindowMinimized:
            if hasattr(strudel_widget, 'web') and strudel_widget.web:
                # Force WebEngine to repaint
                QTimer.singleShot(100, lambda: strudel_widget.web.update())
                QTimer.singleShot(200, lambda: strudel_widget.web.repaint())

    def _toggle_strudel_window(self) -> None:
        """Show or hide the Strudel window."""
        if not self._strudel_loaded:
            # Load if not loaded yet
            self._load_strudel_window()
            if self._strudel_window:
                self._strudel_window.show()
        elif self._strudel_window:
            # Toggle visibility
            if self._strudel_window.isVisible():
                self._strudel_window.hide()
            else:
                self._strudel_window.show()
                self._strudel_window.raise_()
                self.desktop.setActiveSubWindow(self._strudel_window)


class PluginRackWidget(QFrame):
    """Plugin Rack UI with A/B lanes and optional Carla auditioning."""

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
        top_row.addWidget(self.refresh_btn)

        self.host_status = QLabel("Ready")
        # Removed inline stylesheet to allow theme control
        top_row.addWidget(self.host_status)

        header_layout.addLayout(top_row)

        # Main content area: discovered plugins (left) and plugin chain (right)
        content_row = QHBoxLayout()
        header_layout.addLayout(content_row)

        # Left: discovered plugins
        discover_group = QGroupBox("Discovered Plugins")
        discover_group.setStyleSheet("QGroupBox { font-size: 16px; }")
        discover_layout = QVBoxLayout(discover_group)
        self.plugins_list = QListWidget()
        self.plugins_list.setStyleSheet("QListWidget { min-height: 200px; }")
        discover_layout.addWidget(self.plugins_list)

        add_btn_row = QHBoxLayout()
        self.add_plugin_btn = QPushButton("Add to Chain →")
        self.add_plugin_btn.clicked.connect(self.add_selected_to_chain)
        add_btn_row.addWidget(self.add_plugin_btn)
        discover_layout.addLayout(add_btn_row)

        content_row.addWidget(discover_group, 1)

        # Right: plugin chain
        chain_group = QGroupBox("Plugin Chain")
        chain_group.setStyleSheet("QGroupBox { font-size: 16px; }")
        chain_layout = QVBoxLayout(chain_group)
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

        content_row.addWidget(chain_group, 1)

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
        self.param_layout.setContentsMargins(4, 20, 4, 4)

        # Create a scrollable container for plugin UI
        self.plugin_ui_scroll = QScrollArea()
        self.plugin_ui_scroll.setWidgetResizable(True)
        self.plugin_ui_scroll.setMinimumHeight(400)
        # Removed inline stylesheet to allow theme control

        # Create a container widget that will host the external window
        self.plugin_ui_container = QWidget()
        self.plugin_ui_container.setMinimumSize(400, 400)
        # Removed inline stylesheet to allow theme control
        # Install event filter to handle resizing
        self.plugin_ui_container.installEventFilter(self)

        self.plugin_ui_scroll.setWidget(self.plugin_ui_container)
        self.param_layout.addWidget(self.plugin_ui_scroll)

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

        # Don't add keyboard to viewport_layout - it will be used in MDI window
        # viewport_layout.addWidget(self.keyboard)

        # Mouse drag state
        self._mouse_is_pressed = False
        self._current_drag_note = None
        self._last_note_time = 0  # For debouncing

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

        # Initial state
        self.refresh()
        # Defer Carla init until needed to avoid startup hangs
        self.host_status.setText(self.host_status.text() or "Carla idle")

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
        self._active_keyboard_notes = set()  # Track which notes are currently playing

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
        if key in self._key_to_note and self.keyboard.isVisible() and self.carla:
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
        if key in self._key_to_note and self.keyboard.isVisible():
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

    # Plugin chain data (simple list of plugin paths)
    @property
    def plugin_chain(self) -> list[str]:
        """Get current plugin chain from list widget."""
        return [
            self.chain_list.item(i).data(Qt.UserRole)
            for i in range(self.chain_list.count())
        ]

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

    def remove_selected_from_chain(self) -> None:
        """Remove selected plugin from the chain."""
        row = self.chain_list.currentRow()
        if row >= 0:
            # If this plugin is currently loaded, unload it
            item = self.chain_list.item(row)
            if item and item.data(Qt.UserRole) == self._current_loaded_path:
                self.unload_host()
            self.chain_list.takeItem(row)

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

                # Try to embed the plugin UI with retry
                self._embed_retry_count = 0
                self._start_embed_retry()

                # Show keyboard if plugin is an instrument
                try:
                    status = self.carla.status()
                    caps = status.get("capabilities", {})
                    is_instrument = caps.get("instrument", False) or caps.get("midi", False)
                    self.keyboard.setVisible(is_instrument)
                    self._log(f"Plugin is instrument: {is_instrument}")
                except Exception as e:
                    self._log(f"Error checking instrument: {e}")
                    self.keyboard.setVisible(False)
        except Exception as exc:
            self._log(f"Load error: {exc}")
            self.host_status.setText(f"Load error: {exc}")
            self.keyboard.setVisible(False)

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
            self.host_status.setText(f"Carla unavailable: {exc}")

    def _update_host_status(self) -> None:
        if not self.carla:
            if not CARLA_AVAILABLE:
                self.host_status.setText(
                    f"Carla not available: {globals().get('_CARLA_IMPORT_ERROR','import error')}"
                )
            return
        try:
            _ = self.carla.status(include_parameters=False)
            self.host_status.setText("Carla ready")
        except Exception as exc:
            self.host_status.setText(f"Carla error: {exc}")

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
            self.host_status.setText(f"Carla unavailable: {exc}")
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
            self.host_status.setText(f"Show UI error: {exc}")

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
            self.plugin_ui_scroll.setVisible(False)
            # Reset container size
            self.plugin_ui_container.setMinimumSize(400, 400)
            self._current_loaded_path = None
            self.keyboard.setVisible(False)
        except Exception as exc:
            self.host_status.setText(f"Unload error: {exc}")

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
            self.plugin_ui_scroll.setVisible(True)

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

    def _send_midi_note_off(self, note: int) -> None:
        """Send MIDI note-off to Carla immediately using fast path."""
        if not self.carla:
            return

        # Use fast path with velocity 0 = note off
        self._send_midi_fast(note, 0.0)

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


class StrudelPlaceholder(QWidget):
    """Lightweight placeholder to avoid loading WebEngine at startup."""

    def __init__(self, on_load, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        msg = QLabel("Strudel is not loaded. Click to load the embedded UI.")
        msg.setWordWrap(True)
        btn = QPushButton("Load Strudel")
        btn.clicked.connect(on_load)
        v.addWidget(msg)
        v.addWidget(btn)

class StrudelHTTPServer:
    """Simple HTTP server for serving Strudel files with proper CORS headers."""

    def __init__(self, directory: Path, port: int = 0):
        self.directory = directory
        self.port = port
        self.server = None
        self.thread = None
        self.actual_port = None

    def start(self) -> int:
        """Start the HTTP server in a background thread. Returns the port number."""
        if self.server is not None:
            return self.actual_port

        class CORSHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
            """HTTP handler with CORS headers enabled."""

            def __init__(self, *args, directory=None, **kwargs):
                super().__init__(*args, directory=str(directory), **kwargs)

            def end_headers(self):
                # Add CORS headers to allow Strudel to fetch resources
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', '*')
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
                super().end_headers()

            def log_message(self, format, *args):
                # Suppress HTTP server logs
                pass

        handler = partial(CORSHTTPRequestHandler, directory=self.directory)

        # Find an available port
        with socketserver.TCPServer(("127.0.0.1", self.port), handler) as test_server:
            self.actual_port = test_server.server_address[1]

        # Create the actual server
        self.server = socketserver.TCPServer(("127.0.0.1", self.actual_port), handler)
        self.server.allow_reuse_address = True

        # Start in background thread
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        return self.actual_port

    def stop(self):
        """Stop the HTTP server."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
            self.thread = None

# Global Strudel HTTP server instance
_strudel_http_server: Optional[StrudelHTTPServer] = None

class StrudelViewWidget(QWidget):
    """Embedded view for Strudel (bundled resources/strudel/dist)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        hdr = QLabel("Strudel (embedded)")
        hdr.setStyleSheet("font-size:16px; font-weight:600; margin:8px 0;")
        v.addWidget(hdr)

        if not WEBENGINE_AVAILABLE:
            msg = QLabel(
                "Qt WebEngine not available. Install PyQt6-WebEngine to enable the embedded browser UI."
            )
            msg.setWordWrap(True)
            v.addWidget(msg)
            return

        try:
            from qtpy.QtWebEngineWidgets import QWebEngineView  # type: ignore
            from qtpy.QtCore import QUrl
        except Exception as exc:  # pragma: no cover
            fallback = QLabel(f"WebEngine import failed: {exc}")
            fallback.setWordWrap(True)
            v.addWidget(fallback)
            return

        self.web = QWebEngineView(self)
        v.addWidget(self.web, 1)

        # Check if Strudel directory exists
        target = _ROOT / "resources" / "strudel" / "dist"
        if not target.exists():
            v.addWidget(QLabel("No local Strudel directory found."))
            return

        # Start HTTP server for Strudel
        global _strudel_http_server
        if _strudel_http_server is None:
            _strudel_http_server = StrudelHTTPServer(target)

        try:
            port = _strudel_http_server.start()
            url = f"http://127.0.0.1:{port}/"

            status = QLabel(f"Strudel server running on port {port}")
            status.setStyleSheet("color: #9aa; font-size: 11px;")
            v.insertWidget(1, status)

            self.web.load(QUrl(url))
        except Exception as exc:
            error_msg = QLabel(f"Failed to start Strudel server: {exc}")
            error_msg.setWordWrap(True)
            v.addWidget(error_msg)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO)
    app = QApplication(sys.argv if argv is None else argv)
    win = AmbianceMainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
