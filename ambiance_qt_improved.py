"""Ambiance - Improved Qt application with plugin chaining and UI fixes."""

import sys
import json
import logging
import os
from pathlib import Path
from collections import deque
from typing import Optional, List, Dict, Any, Tuple, Deque, cast
from dataclasses import dataclass, field
from datetime import datetime
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from string import Template
from textwrap import dedent

try:
    import winsound  # Windows-only fallback tone generator
except ImportError:  # pragma: no cover - non-Windows systems
    winsound = None

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QScrollArea,
    QSlider, QFrame, QMessageBox, QComboBox, QTabWidget, QCheckBox,
    QPlainTextEdit, QToolButton, QSizePolicy, QStackedWidget
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, pyqtSlot, QObject, QEvent, QUrl, QSize
from PyQt5.QtGui import (
    QPainter,
    QColor,
    QPen,
    QBrush,
    QPalette,
    QFont,
    QPaintEvent,
    QResizeEvent,
    QMouseEvent,
    QKeyEvent,
    QCloseEvent,
    QWindow,
)

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings
    from PyQt5.QtWebChannel import QWebChannel
except ImportError:  # pragma: no cover - optional dependency
    QWebEngineView = None  # type: ignore
    QWebEngineSettings = None  # type: ignore
    QWebChannel = None  # type: ignore

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

sys.path.insert(0, str(Path(__file__).parent / "ambiance" / "src"))

from ambiance.integrations.carla_host import CarlaVSTHost, CarlaHostError
from ambiance.audio_engine import AudioEngine
from ambiance.widgets import BlocksPanel

# Color scheme
COLORS = {
    'bg': '#121212',
    'panel': '#1e1e1e',
    'card': '#222',
    'text': '#f0f0f0',
    'muted': '#bbb',
    'accent': '#59a7ff',
    'border': '#444',
    'success': '#4caf50',
    'warning': '#ff9800',
    'error': '#f44336'
}

THEME_PRESETS = {
    "flat": {
        "colors": {
            'bg': '#10141d',
            'panel': '#19202b',
            'card': '#202835',
            'text': '#f4f6fb',
            'muted': '#aeb7c9',
            'accent': '#4da3ff',
            'border': '#2f3b4c',
            'success': '#36c16b',
            'warning': '#ffb547',
            'error': '#ff5f5f'
        },
        "dark": True
    },
    "win98": {
        "colors": {
            'bg': '#c6c6c6',
            'panel': '#dcdcdc',
            'card': '#ffffff',
            'text': '#202020',
            'muted': '#4f4f4f',
            'accent': '#2a4cff',
            'border': '#7a7a7a',
            'success': '#0f7a0f',
            'warning': '#ba7b00',
            'error': '#b00020'
        },
        "dark": False
    },
    "winxp": {
        "colors": {
            'bg': '#0c1a33',
            'panel': '#13315c',
            'card': '#18406f',
            'text': '#f3f6ff',
            'muted': '#c0d2f1',
            'accent': '#3fa0ff',
            'border': '#21538f',
            'success': '#60d860',
            'warning': '#ffcc66',
            'error': '#ff6666'
        },
        "dark": True
    }
}

STRUDEL_REMOTE_URL = "https://strudel.tidalcycles.org/"


@dataclass(eq=False)
class PluginChainSlot:
    """Represents a plugin slot in the chain."""
    index: int
    plugin_path: Optional[Path] = None
    host: Optional[CarlaVSTHost] = None
    enabled: bool = True
    ui_visible: bool = False
    parameters: Dict[int, float] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)
    supports_midi: bool = False



class StrudelPatternBridge(QObject):
    """Bridge object exposed to Strudel via QWebChannel."""

    patternReceived = pyqtSignal(dict)

    def __init__(self, window: "AmbianceQtImproved") -> None:
        super().__init__()
        self._window = window
        self.patternReceived.connect(window.on_strudel_pattern)

    @pyqtSlot(str)
    def receivePattern(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            logging.getLogger(__name__).warning("Invalid Strudel bridge payload: %s", payload)
            return
        self.patternReceived.emit(data)


class StrudelStaticServer:
    """Minimal HTTP server that serves the bundled Strudel assets with proper MIME types."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.port: Optional[int] = None

    def start(self) -> None:
        if self._httpd is not None:
            return

        root = self.root
        server_instance = self  # Capture reference for use in Handler

        class Handler(SimpleHTTPRequestHandler):  # type: ignore[misc, valid-type]
            # Set MIME types for JavaScript modules and other assets
            # This is the correct way to configure MIME types in SimpleHTTPRequestHandler
            extensions_map = {
                **SimpleHTTPRequestHandler.extensions_map,
                '.js': 'application/javascript',
                '.mjs': 'application/javascript',
                '.json': 'application/json',
                '.css': 'text/css',
                '.html': 'text/html',
                '.svg': 'image/svg+xml',
                '.wasm': 'application/wasm',
                '': 'application/octet-stream',
            }

            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(root), **kwargs)  # type: ignore[arg-type]

            def do_GET(self):
                # Intercept index.html to fix base href
                if self.path == '/index.html' or self.path == '/':
                    try:
                        index_path = root / "index.html"
                        if index_path.exists():
                            content = index_path.read_text(encoding='utf-8')
                            # Fix the empty base href to use the server's URL
                            base_url = server_instance.base_url or "/"
                            content = content.replace('<base href="">', f'<base href="{base_url}/">')

                            # Send the modified content
                            content_bytes = content.encode('utf-8')
                            self.send_response(200)
                            self.send_header('Content-Type', 'text/html; charset=utf-8')
                            self.send_header('Content-Length', str(len(content_bytes)))
                            self.end_headers()
                            self.wfile.write(content_bytes)
                            return
                    except Exception as e:
                        logging.getLogger(__name__).warning(f"Failed to modify index.html: {e}")
                # Fall back to default behavior for all other files
                super().do_GET()

            def end_headers(self):
                # Add CORS headers to allow cross-origin requests
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', '*')
                super().end_headers()

            def log_message(self, format: str, *args: Any) -> None:  # pragma: no cover - reduces console noise
                logging.getLogger(__name__).debug("Strudel static server: " + format, *args)

        try:
            self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        except Exception:
            self._httpd = None
            raise

        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="StrudelStaticServer",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is None:
            return
        try:
            self._httpd.shutdown()
        except Exception:
            pass
        try:
            self._httpd.server_close()
        except Exception:
            pass
        thread = self._thread
        self._httpd = None
        self.port = None
        self._thread = None
        if thread and thread.is_alive():
            try:
                thread.join(timeout=0.5)
            except Exception:
                pass

    @property
    def base_url(self) -> Optional[str]:
        if self.port is None:
            return None
        return f"http://127.0.0.1:{self.port}"


class PianoKeyboard(QWidget):
    """Enhanced virtual piano keyboard with extended range."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(160)
        self.setMaximumHeight(180)
        
        # Extended keyboard settings
        self.octaves = 5  # Expanded from 2 to 5 octaves
        self.start_note = 36  # C2 instead of C3
        self.white_key_width = 28  # Narrower keys to fit more octaves
        self.white_key_height = 140
        self.black_key_width = 18
        self.black_key_height = 95
        
        # Display settings
        self.show_note_names = True
        self.highlight_c_notes = True
        
        # State
        self.pressed_keys = set()
        self.mouse_down_note = None
        self.white_key_rects: Dict[int, Tuple[int, int, int, int]] = {}
        self.black_key_rects: Dict[int, Tuple[int, int, int, int]] = {}
        
        # Callbacks
        self.note_on_callback = None
        self.note_off_callback = None
        
        self.setMouseTracking(True)
        self.setStyleSheet(f"""
            QWidget {{
                background-color: rgba(9, 12, 18, 0.9);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 14px;
                padding: 18px 14px;
            }}
        """)

    def set_callbacks(self, note_on, note_off):
        self.note_on_callback = note_on
        self.note_off_callback = note_off

    def release_all_keys(self) -> None:
        """Clear any pressed key state without emitting callbacks."""
        self.pressed_keys.clear()
        self.mouse_down_note = None
        self.update()

    def _compute_key_rects(self) -> Tuple[Dict[int, Tuple[int, int, int, int]], Dict[int, Tuple[int, int, int, int]]]:
        """Compute the rectangles for white and black keys."""
        white_rects: Dict[int, Tuple[int, int, int, int]] = {}
        black_rects: Dict[int, Tuple[int, int, int, int]] = {}
        x = 10
        for i in range(self.octaves * 12):
            note = self.start_note + i
            if note % 12 in [0, 2, 4, 5, 7, 9, 11]:
                white_rects[note] = (x, 10, self.white_key_width, self.white_key_height)
                x += self.white_key_width
        for i in range(self.octaves * 12):
            note = self.start_note + i
            if note % 12 in [1, 3, 6, 8, 10]:
                base_rect = white_rects.get(note - 1)
                if not base_rect:
                    continue
                base_x = base_rect[0]
                rect_x = base_x + self.white_key_width - self.black_key_width // 2
                black_rects[note] = (rect_x, 10, self.black_key_width, self.black_key_height)
        return white_rects, black_rects
    
    def paintEvent(self, event: QPaintEvent) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        white_rects, black_rects = self._compute_key_rects()
        self.white_key_rects = white_rects
        self.black_key_rects = black_rects

        # Draw white keys
        for note in sorted(white_rects):
            is_pressed = note in self.pressed_keys
            is_c = (note % 12 == 0)
            rect = white_rects[note]
            
            if is_pressed:
                color = QColor('#f97316')
            elif is_c and self.highlight_c_notes:
                color = QColor(225, 227, 235)
            else:
                color = QColor(245, 247, 255)
            
            painter.fillRect(*rect, color)
            painter.setPen(QPen(QColor(0, 0, 0, 150), 2))
            painter.drawRect(*rect)
            
            # Draw note names
            if self.show_note_names and is_c:
                painter.setPen(QPen(QColor(100, 100, 100), 1))
                font = QFont("Arial", 8)
                painter.setFont(font)
                octave = (note - 12) // 12
                painter.drawText(rect[0] + 8, rect[1] + rect[3] - 4, f"C{octave}")
        
        # Draw black keys
        for note in sorted(black_rects):
            rect = black_rects[note]
            is_pressed = note in self.pressed_keys
            color = QColor('#f97316') if is_pressed else QColor(15, 18, 24)
            painter.fillRect(*rect, color)
            painter.setPen(QPen(QColor(17, 17, 17), 2))
            painter.drawRect(*rect)
    
    def get_note_at_position(self, x, y):
        """Get note at mouse position."""
        if not (self.white_key_rects and self.black_key_rects):
            self.white_key_rects, self.black_key_rects = self._compute_key_rects()
        if y < 10 or y > 10 + self.white_key_height:
            return None
        
        # Check black keys first (they're on top)
        for note, (rx, ry, rw, rh) in self.black_key_rects.items():
            if rx <= x < rx + rw and ry <= y < ry + rh:
                return note
        
        # Check white keys
        for note, (rx, ry, rw, rh) in self.white_key_rects.items():
            if rx <= x < rx + rw and ry <= y < ry + rh:
                return note
        
        return None
    
    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        note = self.get_note_at_position(event.x(), event.y())
        if note is not None:
            self.mouse_down_note = note
            if note not in self.pressed_keys:
                self.pressed_keys.add(note)
                self.update()
                if self.note_on_callback:
                    self.note_on_callback(note)
    
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self.mouse_down_note is not None:
            if self.mouse_down_note in self.pressed_keys:
                self.pressed_keys.remove(self.mouse_down_note)
                self.update()
                if self.note_off_callback:
                    self.note_off_callback(self.mouse_down_note)
            self.mouse_down_note = None
    
    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self.mouse_down_note is not None:
            current_note = self.get_note_at_position(event.x(), event.y())
            if current_note != self.mouse_down_note:
                # Release old note
                if self.mouse_down_note in self.pressed_keys:
                    self.pressed_keys.remove(self.mouse_down_note)
                    if self.note_off_callback:
                        self.note_off_callback(self.mouse_down_note)
                
                # Press new note
                if current_note is not None:
                    self.mouse_down_note = current_note
                    if current_note not in self.pressed_keys:
                        self.pressed_keys.add(current_note)
                        if self.note_on_callback:
                            self.note_on_callback(current_note)
                else:
                    self.mouse_down_note = None

                self.update()


class PluginEditorContainer(QFrame):
    """Container that can host a native plugin editor window."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("PluginEditorContainer")
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self._window_container: Optional[QWidget] = None
        self._window: Optional[QWindow] = None
        self._base_minimum_height = 320
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(self._base_minimum_height)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(0)

        self.placeholder = QLabel("Dock the plugin UI to keep it pinned above the keyboard.")
        self.placeholder.setObjectName("PluginEditorPlaceholder")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        layout.addWidget(self.placeholder, 1)

    def embed_handle(self, hwnd: int | None) -> None:
        """Embed a native window handle inside the container."""

        self.clear_container()
        if not hwnd:
            return

        window = QWindow.fromWinId(int(hwnd))
        window.setFlags(Qt.FramelessWindowHint)
        container = QWidget.createWindowContainer(window, self)
        container.setFocusPolicy(Qt.StrongFocus)
        container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.layout().addWidget(container)
        self._window_container = container
        self._window = window
        try:
            window.widthChanged.connect(self._on_window_dimension_changed)  # type: ignore[attr-defined]
            window.heightChanged.connect(self._on_window_dimension_changed)  # type: ignore[attr-defined]
        except Exception:
            pass
        self._apply_window_size(window.size())
        self.placeholder.hide()

    def clear_container(self) -> None:
        """Remove any embedded plugin editor from the container."""

        if self._window_container is not None:
            self._window_container.setParent(None)
            self._window_container.deleteLater()
            self._window_container = None
        if self._window is not None:
            try:
                self._window.widthChanged.disconnect(self._on_window_dimension_changed)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                self._window.heightChanged.disconnect(self._on_window_dimension_changed)  # type: ignore[attr-defined]
            except Exception:
                pass
            self._window.setParent(None)
            self._window = None
        self.placeholder.show()
        self.setMinimumHeight(self._base_minimum_height)
        self.setMinimumWidth(0)
        self.updateGeometry()

    def resizeEvent(self, event: QResizeEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._window is None:
            return
        size = event.size()
        if size.isValid():
            try:
                self._window.resize(size)
            except Exception:
                pass

    def _apply_window_size(self, size: QSize) -> None:
        if not size.isValid():
            return
        margins = self.layout().contentsMargins()
        width = max(size.width(), 320)
        height = max(size.height(), self._base_minimum_height)
        if self._window_container is not None:
            self._window_container.setMinimumSize(size)
            self._window_container.resize(size)
        self.setMinimumSize(
            width + margins.left() + margins.right(),
            height + margins.top() + margins.bottom(),
        )
        self.updateGeometry()

    def _on_window_dimension_changed(self, _value: int) -> None:
        if self._window is None:
            return
        self._apply_window_size(self._window.size())

    def paintEvent(self, event: QPaintEvent) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(event.rect(), self.palette().color(QPalette.Window))
        super().paintEvent(event)


class CollapsibleSection(QFrame):
    """Simple collapsible container with a toggle button."""

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("CollapsibleSection")

        self.toggle_button = QToolButton()
        self.toggle_button.setObjectName("SectionToggle")
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.DownArrow)
        self.toggle_button.setText(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(True)
        self.toggle_button.toggled.connect(self._on_toggled)
        self.toggle_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.content_area = QFrame()
        self.content_area.setObjectName("CollapsibleSectionContent")
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(12, 12, 12, 12)
        self.content_layout.setSpacing(0)

        wrapper_layout = QVBoxLayout(self)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(6)
        wrapper_layout.addWidget(self.toggle_button)
        wrapper_layout.addWidget(self.content_area)

        self.content_area.setVisible(self.toggle_button.isChecked())

    def _on_toggled(self, checked: bool) -> None:
        self.toggle_button.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self.content_area.setVisible(checked)
        self.toggled.emit(checked)

    def setContentWidget(self, widget: QWidget) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self.content_layout.addWidget(widget)

    def set_expanded(self, expanded: bool) -> None:
        """Programmatically expand or collapse the section."""

        self.toggle_button.setChecked(bool(expanded))


class PluginChainWidget(QWidget):
    """Widget for managing the plugin chain."""
    
    slot_selected = pyqtSignal(int)
    slot_updated = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(f"{__name__}.PluginChainWidget")
        self.slots: List[PluginChainSlot] = []
        self.selected_slot_index = -1
        self._ui_threads: Dict[PluginChainSlot, threading.Thread] = {}
        self.host_window_id: Optional[int] = None
        self.host_dock_check: Optional[QCheckBox] = None
        self.host_editor_container: Optional["PluginEditorContainer"] = None

        self.init_ui()
        self._install_event_filter()

        # Create one default slot (multi-slot disabled for now)
        self.add_slot()

    def set_host_controls(
        self,
        dock_check: Optional[QCheckBox],
        editor_container: Optional["PluginEditorContainer"],
    ) -> None:
        """Share the host dock toggle and container owned by the main window."""

        self.host_dock_check = dock_check
        self.host_editor_container = editor_container

    def _clear_host_container(self) -> None:
        if self.host_editor_container:
            self.host_editor_container.clear_container()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Chain controls
        controls = QHBoxLayout()
        
        self.add_slot_btn = QPushButton("+ Add Slot")
        self.add_slot_btn.clicked.connect(self.add_slot)
        self.add_slot_btn.setEnabled(False)  # TEMP: Disabled until multi-engine support added
        self.add_slot_btn.setToolTip("Multiple plugins not yet supported - Carla engine limitation")
        controls.addWidget(self.add_slot_btn)
        
        self.remove_slot_btn = QPushButton("- Remove Slot")
        self.remove_slot_btn.clicked.connect(self.remove_selected_slot)
        self.remove_slot_btn.setEnabled(False)
        controls.addWidget(self.remove_slot_btn)
        
        controls.addStretch()
        
        self.bypass_all_btn = QPushButton("Bypass All")
        self.bypass_all_btn.setCheckable(True)
        self.bypass_all_btn.clicked.connect(self.toggle_bypass_all)
        controls.addWidget(self.bypass_all_btn)
        
        layout.addLayout(controls)
        
        # Chain list
        self.chain_list = QListWidget()
        self.chain_list.itemSelectionChanged.connect(self.on_selection_changed)
        layout.addWidget(self.chain_list)
        
        # Slot controls
        slot_controls = QHBoxLayout()
        
        self.load_btn = QPushButton("Load Plugin")
        self.load_btn.clicked.connect(self.load_plugin_for_slot)
        self.load_btn.setEnabled(False)
        slot_controls.addWidget(self.load_btn)
        
        self.unload_btn = QPushButton("Unload")
        self.unload_btn.clicked.connect(self.unload_plugin_from_slot)
        self.unload_btn.setEnabled(False)
        slot_controls.addWidget(self.unload_btn)
        
        self.bypass_btn = QPushButton("Bypass")
        self.bypass_btn.setCheckable(True)
        self.bypass_btn.clicked.connect(self.toggle_bypass_slot)
        self.bypass_btn.setEnabled(False)
        slot_controls.addWidget(self.bypass_btn)
        
        self.ui_btn = QPushButton("Show UI")
        self.ui_btn.clicked.connect(self.toggle_slot_ui)
        self.ui_btn.setEnabled(False)
        slot_controls.addWidget(self.ui_btn)
        
        layout.addLayout(slot_controls)
        
        self.apply_styles()
    
    def apply_styles(self):
        for btn in [self.add_slot_btn, self.remove_slot_btn, self.load_btn, 
                   self.unload_btn, self.bypass_btn, self.ui_btn, self.bypass_all_btn]:
            btn.setStyleSheet("")

        self.chain_list.setStyleSheet(f"""
            QListWidget {{
                background-color: rgba(0, 0, 0, 0.25);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
                padding: 6px;
            }}
            QListWidget::item {{
                padding: 10px;
                border-radius: 8px;
                margin: 4px 0;
            }}
            QListWidget::item:selected {{
                background-color: rgba(89, 167, 255, 0.35);
                border: 1px solid rgba(89, 167, 255, 0.6);
            }}
            QListWidget::item:hover {{
                background-color: rgba(255, 255, 255, 0.08);
            }}
        """)
    
    def _install_event_filter(self) -> None:
        """Register this widget as an event filter with the active QApplication."""
        app = QApplication.instance()
        if app is None:
            return
        try:
            app.installEventFilter(self)
        except Exception:
            pass

    def register_host_window(self, win_id: int) -> None:
        """Remember the main window handle for plugin window discovery."""

        self.host_window_id = int(win_id)
        for slot in self.slots:
            if slot.host:
                slot.host.register_host_window(self.host_window_id)

    def _current_slot(self) -> Optional[PluginChainSlot]:
        if 0 <= self.selected_slot_index < len(self.slots):
            return self.slots[self.selected_slot_index]
        return None

    def _activate_plugin_ui(self, slot: PluginChainSlot, handle: Optional[int]) -> None:
        """Embed or raise the plugin UI based on the dock toggle state."""

        if not slot.host:
            return

        dock_check = self.host_dock_check
        container = self.host_editor_container

        if dock_check and container and dock_check.isChecked():
            parent_id = int(container.winId())
            if handle and slot.host.embed_plugin_window(parent_id):
                container.embed_handle(handle)
                return

            # Docking failed - fall back to floating window and inform the user.
            container.clear_container()
            dock_check.blockSignals(True)
            dock_check.setChecked(False)
            dock_check.blockSignals(False)
            QMessageBox.warning(
                self,
                "Plugin Dock",
                "This plugin's editor could not be docked. It will open as a separate window instead.",
            )

        # Ensure the plugin UI floats and can be focused from the taskbar.
        slot.host.embed_plugin_window(None)
        if container:
            container.clear_container()
        slot.host.ensure_plugin_window_taskbar()
        slot.host.focus_plugin_window()

    def on_host_dock_toggled(self, checked: bool) -> None:
        slot = self._current_slot()
        if not slot or not slot.host or not slot.ui_visible:
            if not checked:
                self._clear_host_container()
            return

        handle = slot.host.get_plugin_window_handle(attempts=20)
        if checked:
            self._activate_plugin_ui(slot, handle)
        else:
            slot.host.embed_plugin_window(None)
            self._clear_host_container()
            slot.host.ensure_plugin_window_taskbar()
            slot.host.focus_plugin_window()

    def _after_ui_shown(self, slot: PluginChainSlot) -> None:
        if slot not in self.slots or not slot.host:
            return
        dock_check = self.host_dock_check
        attempts = 30 if dock_check and dock_check.isChecked() else 15
        handle = slot.host.get_plugin_window_handle(attempts=attempts)
        self._activate_plugin_ui(slot, handle)

    def add_slot(self):
        """Add a new plugin slot to the chain."""
        slot = PluginChainSlot(index=len(self.slots))
        self.slots.append(slot)
        
        item = QListWidgetItem(f"Slot {slot.index + 1}: [Empty]")
        self.chain_list.addItem(item)
        
        # Auto-select the new slot
        self.chain_list.setCurrentRow(slot.index)
        self.slot_updated.emit(slot.index)
    
    def remove_selected_slot(self):
        """Remove the selected slot from the chain."""
        if self.selected_slot_index < 0:
            return

        removed_index = self.selected_slot_index
        slot = self.slots[removed_index]
        if slot.host:
            with slot.lock:
                slot.host.unload()
                slot.host.shutdown()
        slot.supports_midi = False
        self._clear_host_container()

        self.slots.pop(removed_index)
        self.chain_list.takeItem(removed_index)
        self._ui_threads.pop(slot, None)

        # Re-index remaining slots
        for i, remaining in enumerate(self.slots):
            remaining.index = i
            self.update_slot_display(i)

        if self._ui_threads:
            self._ui_threads = {
                s: t for s, t in self._ui_threads.items() if s in self.slots and (not t or t.is_alive())
            }

        # Determine next selection
        next_index = removed_index
        if next_index >= len(self.slots):
            next_index = len(self.slots) - 1

        if next_index >= 0:
            self.chain_list.setCurrentRow(next_index)
        else:
            self.selected_slot_index = -1
            self.update_controls()
            self.slot_selected.emit(-1)

        self.slot_updated.emit(next_index)
    
    def on_selection_changed(self):
        """Handle slot selection change."""
        items = self.chain_list.selectedItems()
        if items:
            self.selected_slot_index = self.chain_list.row(items[0])
        else:
            self.selected_slot_index = -1
        self.update_controls()
        self.slot_selected.emit(self.selected_slot_index)
    
    def update_controls(self):
        """Update control buttons based on selection."""
        has_selection = self.selected_slot_index >= 0
        self.remove_slot_btn.setEnabled(has_selection)
        self.load_btn.setEnabled(has_selection)
        
        if has_selection:
            slot = self.slots[self.selected_slot_index]
            has_plugin = slot.plugin_path is not None
            self.unload_btn.setEnabled(has_plugin)
            self.bypass_btn.setEnabled(has_plugin)
            self.bypass_btn.setChecked(not slot.enabled)
            self.ui_btn.setEnabled(has_plugin)
            self.ui_btn.setText("Hide UI" if slot.ui_visible else "Show UI")
        else:
            self.unload_btn.setEnabled(False)
            self.bypass_btn.setEnabled(False)
            self.ui_btn.setEnabled(False)
    
    def update_slot_display(self, index):
        """Update the display text for a slot."""
        if 0 <= index < len(self.slots):
            slot = self.slots[index]
            item = self.chain_list.item(index)
            if item is None:
                return
            
            if slot.plugin_path:
                name = slot.plugin_path.stem
                status = "Bypassed" if not slot.enabled else "Active"
                text = f"Slot {index + 1}: {name} [{status}]"
            else:
                text = f"Slot {index + 1}: [Empty]"
            
            item.setText(text)
            self.slot_updated.emit(index)
    
    def load_plugin_for_slot(self):
        """Load a plugin into the selected slot."""
        # This will be connected to the main window's plugin selection
        pass
    
    def unload_plugin_from_slot(self):
        """Unload plugin from the selected slot."""
        if self.selected_slot_index < 0:
            return

        slot = self.slots[self.selected_slot_index]
        if slot.host:
            with slot.lock:
                slot.host.unload()
                slot.host.shutdown()
            slot.host = None
        slot.plugin_path = None
        slot.supports_midi = False
        slot.ui_visible = False
        self._clear_host_container()
        self.update_slot_display(self.selected_slot_index)
        self.update_controls()
    
    def toggle_bypass_slot(self):
        """Toggle bypass for the selected slot."""
        if self.selected_slot_index >= 0:
            slot = self.slots[self.selected_slot_index]
            slot.enabled = not slot.enabled
            self.update_slot_display(self.selected_slot_index)
    
    def toggle_bypass_all(self):
        """Toggle bypass for all slots."""
        bypass = self.bypass_all_btn.isChecked()
        for i, slot in enumerate(self.slots):
            slot.enabled = not bypass
            self.update_slot_display(i)
    
    def toggle_slot_ui(self):
        """Toggle UI for the selected slot."""
        if self.selected_slot_index < 0:
            return
        slot = self.slots[self.selected_slot_index]
        if not slot.host:
            QMessageBox.information(self, "No Plugin", "Load a plugin into this slot first.")
            return

        try:
            if slot.ui_visible:
                with slot.lock:
                    try:
                        slot.host.embed_plugin_window(None)
                    except Exception:
                        pass
                    slot.host.hide_ui()
                slot.ui_visible = False
                self._clear_host_container()
                self.update_controls()
            else:
                # Call show_ui() without holding lock - it handles threading internally
                self.logger.info("Requesting UI for slot %s (%s)", slot.index, slot.plugin_path)
                if self.host_window_id is not None:
                    slot.host.register_host_window(self.host_window_id)
                slot.host.show_ui()
                # Set visible flag with a small delay to let UI thread start
                QTimer.singleShot(150, lambda: self._set_ui_visible(slot, True))
                QTimer.singleShot(180, lambda s=slot: self._after_ui_shown(s))
        except Exception as e:
            self.logger.error("UI error for slot %s: %s", slot.index, e, exc_info=True)
            QMessageBox.warning(self, "UI Error", f"Failed to open UI: {e}\n\nSome plugins may not support native UI.")
            slot.ui_visible = False
            self.update_controls()
    
    def _set_ui_visible(self, slot: PluginChainSlot, visible: bool):
        """Set UI visible flag and update controls."""
        slot.ui_visible = visible
        self.update_controls()

    def _show_slot_ui_worker(self, slot: PluginChainSlot):
        if slot not in self.slots:
            return
        host = slot.host
        slot_index = slot.index
        try:
            if host:
                with slot.lock:
                    self.logger.info("Launching host UI for slot %s on worker thread", slot_index)
                    host.show_ui()
                QTimer.singleShot(0, lambda idx=slot_index: self.on_ui_shown(idx, True))
        except Exception as exc:
            self.logger.error("Failed to show UI for slot %s: %s", slot_index, exc, exc_info=True)
            QTimer.singleShot(0, lambda idx=slot_index, msg=str(exc): self.on_ui_error(idx, msg))
        finally:
            self._ui_threads.pop(slot, None)
            QTimer.singleShot(0, self.update_controls)

    def on_ui_shown(self, index: int, shown: bool):
        """Handle UI shown signal."""
        if 0 <= index < len(self.slots):
            self.slots[index].ui_visible = shown
            if index == self.selected_slot_index:
                self.update_controls()
    
    def on_ui_error(self, index: int, error: str):
        """Handle UI error signal."""
        if 0 <= index < len(self.slots):
            slot = self.slots[index]
            self._ui_threads.pop(slot, None)
            slot.ui_visible = False
        QMessageBox.warning(self, "UI Error", f"Failed to show UI for slot {index + 1}:\n{error}")
    
    def get_active_slots(self) -> List[PluginChainSlot]:
        """Get list of active (non-bypassed) slots with hosts."""
        return [s for s in self.slots if s.enabled and s.host]

    def shutdown(self):
        """Ensure any running UI threads are stopped."""
        for thread in list(self._ui_threads.values()):
            if thread and thread.is_alive():
                thread.join(timeout=0.5)
        self._ui_threads.clear()


class AmbianceQtImproved(QMainWindow):
    """Improved Qt desktop app with plugin chaining."""

    # Map QWERTY keyboard keys to semitone offsets from the piano's start note.
    # Layout follows common DAW conventions (Z row = base octave, Q row = +1 octave).
    KEYBOARD_NOTE_MAP: Dict[int, int] = {
        # Lower row (Z-M)
        Qt.Key_Z: 0,
        Qt.Key_S: 1,
        Qt.Key_X: 2,
        Qt.Key_D: 3,
        Qt.Key_C: 4,
        Qt.Key_V: 5,
        Qt.Key_G: 6,
        Qt.Key_B: 7,
        Qt.Key_H: 8,
        Qt.Key_N: 9,
        Qt.Key_J: 10,
        Qt.Key_M: 11,
        Qt.Key_Comma: 12,
        Qt.Key_L: 13,
        Qt.Key_Period: 14,
        Qt.Key_Semicolon: 15,
        Qt.Key_Slash: 16,
        Qt.Key_Apostrophe: 17,
        # Upper row (Q-P) mirrors next octave
        Qt.Key_Q: 12,
        Qt.Key_2: 13,
        Qt.Key_W: 14,
        Qt.Key_3: 15,
        Qt.Key_E: 16,
        Qt.Key_R: 17,
        Qt.Key_5: 18,
        Qt.Key_T: 19,
        Qt.Key_6: 20,
        Qt.Key_Y: 21,
        Qt.Key_7: 22,
        Qt.Key_U: 23,
        Qt.Key_I: 24,
        Qt.Key_9: 25,
        Qt.Key_O: 26,
        Qt.Key_0: 27,
        Qt.Key_P: 28,
        Qt.Key_BracketLeft: 29,
        Qt.Key_Equal: 30,
        Qt.Key_BracketRight: 31,
    }
    
    def _install_event_filter(self):
        if self._qt_app is None:
            self._qt_app = QApplication.instance()
        if self._qt_app is not None:
            try:
                self._qt_app.installEventFilter(self)
            except Exception:
                pass

    def __init__(self):
        super().__init__()
        self.setFocusPolicy(Qt.StrongFocus)
        self.keyboard_active_notes: Dict[int, int] = {}
        self._qt_app = QApplication.instance()
        self._keyboard_suspended = False

        
        # Logging
        self.logger = logging.getLogger(__name__)
        
        # State
        self.plugin_chain = []
        self.param_sliders = {}
        self.updating_from_plugin = False
        self.instrument_velocity = 0.85
        self.instrument_octave = 4
        self.param_refresh_attempts: Dict[int, int] = {}
        self.theme_key = "flat"
        self.dark_mode = THEME_PRESETS[self.theme_key]["dark"]
        self.colors = dict(COLORS)
        self._apply_theme_colors(self.theme_key)
        self.fallback_audio_threads: List[threading.Thread] = []
        self.warned_no_winsound = False

        self.strudel_available = QWebEngineView is not None
        self.strudel_loaded = False
        self._strudel_signals_connected = False
        self.body_stack: Optional[QStackedWidget] = None
        self.strudel_container: Optional[QWidget] = None
        self.strudel_view: Optional["QWebEngineView"] = None
        self.strudel_mode_btn: Optional[QPushButton] = None
        self._strudel_channel: Optional["QWebChannel"] = None
        self._strudel_module_hint: Optional[str] = None
        self._strudel_local_index: Optional[Path] = None
        self._strudel_using_local = False
        self._strudel_static_server: Optional[StrudelStaticServer] = None
        self._strudel_event_queue: Deque[Dict[str, Any]] = deque(maxlen=512)
        self.strudel_bridge = StrudelPatternBridge(self)
        self.default_status_message = "Ready - pick a plugin from the library."

        self.audio_engine: Optional[AudioEngine] = None
        try:
            self.audio_engine = AudioEngine()
            self.logger.info("Audio engine booted (pyo).")
        except Exception as exc:
            self.logger.error("Failed to initialise audio engine: %s", exc, exc_info=True)
            self.audio_engine = None
        
        # Timer for parameter updates
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.poll_parameters)
        
        self.init_ui()

        if self._qt_app is not None:
            self._qt_app.installEventFilter(self)
        
        # Start Qt event processing
        self.process_timer = QTimer()
        self.process_timer.timeout.connect(QApplication.processEvents)
        self.process_timer.start(10)  # Process events every 10ms
    
    def init_ui(self):
        self.setWindowTitle("Ambiance Studio Rack")
        self.setGeometry(120, 80, 1560, 960)
        self.update_theme_palette()

        central = QWidget()
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(14)

        self.toolbar = self.build_toolbar()
        root_layout.addWidget(self.toolbar)

        self.body_stack = QStackedWidget()
        self.body_stack.setObjectName("BodyStack")
        root_layout.addWidget(self.body_stack, 1)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("BodyScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.body_stack.addWidget(self.scroll_area)

        self.body_widget = QWidget()
        self.body_widget.setObjectName("BodyWidget")
        self.scroll_area.setWidget(self.body_widget)

        self.body_layout = QVBoxLayout(self.body_widget)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(20)
        
        self.plugin_block = self.build_plugin_block()
        self.plugin_section = CollapsibleSection("Plugin Rack")
        self.plugin_section.setContentWidget(self.plugin_block)
        self.plugin_section.set_expanded(False)
        self.body_layout.addWidget(self.plugin_section)

        if self.audio_engine is not None:
            self.blocks_panel = BlocksPanel(self.audio_engine)
            self.blocks_panel.apply_theme(self.colors, dark=self.dark_mode)
            created_block = self.blocks_panel.create_block()
            if created_block is not None:
                self.append_log("Blocks engine ready - Block 1 created.")
            self.blocks_section = CollapsibleSection("Blocks & Streams")
            self.blocks_section.setContentWidget(self.blocks_panel)
            self.body_layout.addWidget(self.blocks_section)
        else:
            self.blocks_panel = None
            self.blocks_section = None
            self.append_log("Audio engine unavailable - Blocks panel disabled.")

        self.strudel_container = QWidget()
        self.strudel_container.setObjectName("StrudelContainer")
        strudel_layout = QVBoxLayout(self.strudel_container)
        strudel_layout.setContentsMargins(0, 0, 0, 0)
        strudel_layout.setSpacing(0)

        if self.strudel_available:
            self.strudel_view = QWebEngineView(self.strudel_container)
            self.strudel_view.setObjectName("StrudelView")
            self.strudel_view.setContextMenuPolicy(Qt.NoContextMenu)
            if QWebEngineSettings is not None:
                try:
                    settings = self.strudel_view.settings()
                    settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
                    settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
                except Exception:
                    pass
            strudel_layout.addWidget(self.strudel_view)
        else:
            fallback_label = QLabel(
                "Strudel Mode requires PyQtWebEngine. Install the 'PyQtWebEngine' package "
                "to enable the embedded browser."
            )
            fallback_label.setObjectName("StrudelFallback")
            fallback_label.setWordWrap(True)
            fallback_label.setAlignment(Qt.AlignCenter)
            strudel_layout.addStretch(1)
            strudel_layout.addWidget(fallback_label)
            strudel_layout.addStretch(1)

        self.body_stack.addWidget(self.strudel_container)
        self.body_stack.setCurrentWidget(self.scroll_area)

        self.body_layout.addStretch()

        self.update_host_controls()

        self.statusBar().showMessage(self.default_status_message)
        self.apply_theme(self.theme_key, update_combo=False)

        QTimer.singleShot(150, self.scan_plugins)

    def build_toolbar(self) -> QFrame:
        toolbar = QFrame()
        toolbar.setObjectName("Toolbar")
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(10)

        title = QLabel("Noisetown Ultimate")
        title.setObjectName("ToolbarTitle")
        layout.addWidget(title)

        self.start_audio_btn = QPushButton("Start Audio")
        self.start_audio_btn.clicked.connect(self.on_start_audio_clicked)
        self.start_audio_btn.setEnabled(self.audio_engine is not None)
        layout.addWidget(self.start_audio_btn)

        self.add_block_btn = QPushButton("Add Block")
        self.add_block_btn.clicked.connect(self.on_add_block_clicked)
        self.add_block_btn.setEnabled(self.audio_engine is not None)
        layout.addWidget(self.add_block_btn)

        self.edit_mode_btn = QPushButton("Edit: OFF")
        self.edit_mode_btn.setCheckable(True)
        self.edit_mode_btn.toggled.connect(self.on_edit_mode_toggled)
        layout.addWidget(self.edit_mode_btn)

        self.style_mode_btn = QPushButton("Style Mode: OFF")
        self.style_mode_btn.setCheckable(True)
        self.style_mode_btn.toggled.connect(self.on_style_mode_toggled)
        layout.addWidget(self.style_mode_btn)

        self.strudel_mode_btn = QPushButton("Strudel Mode: OFF")
        self.strudel_mode_btn.setCheckable(True)
        if not self.strudel_available:
            self.strudel_mode_btn.setToolTip(
                "Install the 'PyQtWebEngine' package to enable the embedded Strudel playground."
            )
        self.strudel_mode_btn.toggled.connect(self.on_strudel_mode_toggled)
        layout.addWidget(self.strudel_mode_btn)

        self.theme_combo = QComboBox()
        self.theme_combo.setObjectName("ThemePicker")
        self.theme_combo.blockSignals(True)
        self.theme_combo.addItem("Flat (Default)", "flat")
        self.theme_combo.addItem("Windows 98", "win98")
        self.theme_combo.addItem("Windows XP", "winxp")
        self.theme_combo.currentIndexChanged.connect(self.on_theme_changed)
        default_index = self.theme_combo.findData(self.theme_key)
        if default_index >= 0:
            self.theme_combo.setCurrentIndex(default_index)
        self.theme_combo.blockSignals(False)
        layout.addWidget(self.theme_combo)

        layout.addStretch()

        self.save_session_btn = QPushButton("Save")
        self.save_session_btn.clicked.connect(
            lambda: self.append_log("Session saving is not wired yet in offline mode.")
        )
        layout.addWidget(self.save_session_btn)

        self.save_preset_btn = QPushButton("Save Preset+Audio")
        self.save_preset_btn.clicked.connect(
            lambda: self.append_log("Preset capture is not yet implemented for the desktop app.")
        )
        layout.addWidget(self.save_preset_btn)

        self.load_session_btn = QPushButton("Load")
        self.load_session_btn.clicked.connect(
            lambda: self.append_log("Session loading is coming soon for the desktop app.")
        )
        layout.addWidget(self.load_session_btn)

        self.load_preset_btn = QPushButton("Load Preset")
        self.load_preset_btn.clicked.connect(
            lambda: self.append_log("Preset loading is not yet implemented offline.")
        )
        layout.addWidget(self.load_preset_btn)

        return toolbar

    def ensure_strudel_loaded(self) -> None:
        if not self.strudel_available:
            return
        if self.strudel_loaded:
            return
        if not self.strudel_view:
            return
        if not self._strudel_signals_connected:
            try:
                self.strudel_view.loadStarted.connect(self.on_strudel_load_started)  # type: ignore[attr-defined]
                self.strudel_view.loadProgress.connect(self.on_strudel_load_progress)  # type: ignore[attr-defined]
                self.strudel_view.loadFinished.connect(self.on_strudel_load_finished)  # type: ignore[attr-defined]
            except Exception:
                pass
            else:
                self._strudel_signals_connected = True
        target_url, module_hint, using_local = self._determine_strudel_target()
        self._strudel_module_hint = module_hint
        self._strudel_using_local = using_local
        message = (
            "Strudel Mode active – loading local playground…"
            if using_local
            else "Strudel Mode active – loading web playground…"
        )
        try:
            self.strudel_view.setUrl(target_url)
            self._ensure_strudel_channel()
            self.statusBar().showMessage(message)
        except Exception as exc:
            self.append_log(f"Failed to load Strudel playground: {exc}")
            return
        self.strudel_loaded = True

    def _ensure_strudel_server(self, dist_dir: Path) -> Optional[str]:
        if self._strudel_static_server and self._strudel_static_server.base_url:
            if self._strudel_static_server.root == dist_dir:
                return self._strudel_static_server.base_url
            self._strudel_static_server.stop()
            self._strudel_static_server = None

        server = StrudelStaticServer(dist_dir)
        try:
            server.start()
        except Exception as exc:
            self.logger.warning("Failed to start Strudel asset server: %s", exc)
            return None
        self._strudel_static_server = server
        return server.base_url

    def _teardown_strudel_server(self) -> None:
        if self._strudel_static_server is None:
            return
        try:
            self._strudel_static_server.stop()
        except Exception:
            pass
        finally:
            self._strudel_static_server = None

    def _determine_strudel_target(self) -> Tuple[QUrl, Optional[str], bool]:
        base_dir = Path(__file__).resolve().parent / "resources" / "strudel" / "dist"
        index_path = base_dir / "index.html"
        if index_path.exists():
            self._strudel_local_index = index_path
            server_url = self._ensure_strudel_server(base_dir)
            if server_url:
                # Build full HTTP URL for module hint
                module_hint_path = self._discover_strudel_module(base_dir)
                module_hint = f"{server_url}/{module_hint_path}" if module_hint_path else None
                self.logger.info(f"Strudel server started at {server_url}, module hint: {module_hint}")
                return QUrl(f"{server_url}/index.html"), module_hint, True
            self.logger.warning("Local Strudel bundle present but static server failed; falling back to remote site.")
        else:
            self._teardown_strudel_server()
        self._strudel_local_index = None
        return QUrl(STRUDEL_REMOTE_URL), None, False

    def _discover_strudel_module(self, dist_dir: Path) -> Optional[str]:
        astro_dir = dist_dir / "_astro"
        if not astro_dir.exists():
            return None
        for candidate in sorted(astro_dir.glob("index*.js")):
            # Use forward slashes for URLs (not OS-specific path separators)
            return f"_astro/{candidate.name}"
        return None

    def _ensure_strudel_channel(self) -> None:
        if not self.strudel_view or QWebChannel is None:
            return
        page = self.strudel_view.page()
        if not page:
            return
        if self._strudel_channel is None:
            self._strudel_channel = QWebChannel(page)
            try:
                self._strudel_channel.registerObject("qt_pattern_bridge", self.strudel_bridge)
            except Exception as exc:
                self.logger.debug("Failed to register Strudel bridge: %s", exc)
        try:
            page.setWebChannel(self._strudel_channel)
        except Exception as exc:
            self.logger.debug("Unable to attach web channel: %s", exc)

    def on_strudel_load_started(self) -> None:
        try:
            if self._strudel_using_local:
                self.statusBar().showMessage("Strudel Mode – preparing local playground…")
            else:
                self.statusBar().showMessage("Strudel Mode – contacting playground…")
        except Exception:
            pass

    def on_strudel_load_progress(self, progress: int) -> None:
        try:
            self.statusBar().showMessage(f"Strudel Mode loading… {progress}%")
        except Exception:
            pass

    def on_strudel_load_finished(self, ok: bool) -> None:
        if ok:
            try:
                self.statusBar().showMessage("Strudel Mode active – ready to jam.")
            except Exception:
                pass
            self._ensure_strudel_channel()
            self._inject_strudel_bridge()
            return

        self.strudel_loaded = False
        self.append_log("Strudel playground failed to load. Check your internet connection or firewall settings.")
        try:
            self.statusBar().showMessage("Strudel Mode unavailable – check your internet connection.")
        except Exception:
            pass
        if self.strudel_view:
            bg = self.colors.get('bg', '#111')
            text = self.colors.get('text', '#f0f0f0')
            accent = self.colors.get('accent', '#59a7ff')
            html = f"""
            <html><body style='background:{bg};color:{text};font-family:"Segoe UI",sans-serif;display:flex;align-items:center;justify-content:center;height:100%;text-align:center;padding:32px;'>
                <div>
                    <h2 style='margin-bottom:12px;'>Unable to reach the Strudel playground</h2>
                    <p>Check your internet connection or firewall, then toggle Strudel Mode again.</p>
                    <p style='margin-top:16px;color:{accent};'>https://strudel.tidalcycles.org/</p>
                </div>
            </body></html>
            """
            try:
                self.strudel_view.setHtml(html)  # type: ignore[attr-defined]
            except Exception:
                pass

    def _build_strudel_bridge_script(self) -> str:
        module_hint_js = json.dumps(self._strudel_module_hint)
        script = rf"""
            (function() {{
                if (window.__ambianceStrudelBridgeInstalled) {{
                    return;
                }}
                window.__ambianceStrudelBridgeInstalled = true;
                const moduleHint = {module_hint_js};
                function log(message) {{
                    console.info('[AmbianceBridge]', message);
                }}
                function locateModulePath() {{
                    const candidates = [];
                    document.querySelectorAll('script[type="module"]').forEach((el) => {{
                        if (el.src && el.src.includes('_astro/') && el.src.includes('index')) {{
                            candidates.push(el.src);
                        }}
                    }});
                    document.querySelectorAll('link[rel="modulepreload"]').forEach((el) => {{
                        if (el.href && el.href.includes('_astro/') && el.href.includes('index')) {{
                            candidates.push(el.href);
                        }}
                    }});
                    if (moduleHint) {{
                        if (moduleHint.startsWith('http')) {{
                            return moduleHint;
                        }}
                        try {{
                            return new URL(moduleHint, window.location.href).toString();
                        }} catch (err) {{
                            console.warn('[AmbianceBridge] Failed to resolve module hint', moduleHint, err);
                        }}
                    }}
                    if (candidates.length > 0) {{
                        try {{
                            return new URL(candidates[0], window.location.href).toString();
                        }} catch (err) {{
                            console.warn('[AmbianceBridge] Unable to normalise candidate module path', candidates[0], err);
                            return candidates[0];
                        }}
                    }}
                    return null;
                }}
                function ensureChannel(callback) {{
                    const start = () => {{
                        if (window.qt && window.qt.webChannelTransport) {{
                            const onReady = () => {{
                                new QWebChannel(window.qt.webChannelTransport, function(channel) {{
                                    window.ambianceQtBridge = channel.objects.qt_pattern_bridge;
                                    callback();
                                }});
                            }};
                            if (typeof QWebChannel === 'undefined') {{
                                const script = document.createElement('script');
                                script.src = 'qrc:///qtwebchannel/qwebchannel.js';
                                script.onload = () => onReady();
                                script.onerror = () => console.error('[AmbianceBridge] Unable to load qwebchannel.js');
                                document.head.appendChild(script);
                            }} else {{
                                onReady();
                            }}
                            return;
                        }}
                        setTimeout(start, 100);
                    }};
                    start();
                }}
                function sendToQt(payload) {{
                    try {{
                        if (window.ambianceQtBridge && window.ambianceQtBridge.receivePattern) {{
                            window.ambianceQtBridge.receivePattern(JSON.stringify(payload));
                        }}
                    }} catch (err) {{
                        console.error('[AmbianceBridge] Forward error', err, payload);
                    }}
                }}
                function serialiseHap(hap) {{
                    if (!hap) {{
                        return null;
                    }}
                    const safe = {{
                        value: hap.value ?? null,
                        context: hap.context ?? null,
                        whole: hap.whole ?? null
                    }};
                    try {{
                        if (hap.duration && typeof hap.duration.valueOf === 'function') {{
                            safe.duration = hap.duration.valueOf();
                        }} else if (typeof hap.duration !== 'undefined') {{
                            safe.duration = hap.duration;
                        }}
                    }} catch (err) {{
                        safe.duration = null;
                    }}
                    return safe;
                }}
                function installHooksOnRepl(repl) {{
                    if (!repl || repl.__ambianceHooked) {{
                        return;
                    }}
                    const originalSetPattern = repl.setPattern;
                    if (typeof originalSetPattern === 'function') {{
                        repl.setPattern = async function(pat, autostart) {{
                            let patched = pat;
                            if (patched && typeof patched.onTrigger === 'function' && !patched.__ambianceForwarded) {{
                                try {{
                                    patched = patched.onTrigger((hap, currentTime, cps, targetTime) => {{
                                        sendToQt({{
                                            kind: 'pattern-trigger',
                                            hap: serialiseHap(hap),
                                            currentTime,
                                            cps,
                                            targetTime,
                                            receivedAt: Date.now()
                                        }});
                                    }}, false);
                                    patched.__ambianceForwarded = true;
                                }} catch (err) {{
                                    console.error('[AmbianceBridge] Failed to wrap pattern', err);
                                }}
                            }}
                            return originalSetPattern.call(this, patched, autostart);
                        }};
                    }}
                    if (typeof repl.evaluate === 'function' && !repl.evaluate.__ambianceWrapped) {{
                        const originalEval = repl.evaluate;
                        repl.evaluate = async function(code, autoplay = true) {{
                            return originalEval.call(this, code, autoplay);
                        }};
                        repl.evaluate.__ambianceWrapped = true;
                    }}
                    repl.__ambianceHooked = true;
                    log('Bridge attached to Strudel repl');
                }}
                function scanForRepl() {{
                    const visited = new Set();
                    const attempt = () => {{
                        let found = false;
                        for (const key of Object.getOwnPropertyNames(window)) {{
                            if (visited.has(key)) {{
                                continue;
                            }}
                            visited.add(key);
                            try {{
                                const candidate = window[key];
                                if (candidate && typeof candidate === 'object' && typeof candidate.setPattern === 'function' && typeof candidate.evaluate === 'function') {{
                                    installHooksOnRepl(candidate);
                                    found = true;
                                }}
                            }} catch (err) {{}}
                        }}
                        if (!found) {{
                            setTimeout(attempt, 1000);
                        }}
                    }};
                    attempt();
                }}
                function bootstrapModule() {{
                    const modulePath = locateModulePath();
                    if (!modulePath) {{
                        console.warn('[AmbianceBridge] Module path unresolved, relying on runtime detection');
                        scanForRepl();
                        return;
                    }}
                    import(modulePath).then((mod) => {{
                        if (mod && mod.W && typeof mod.W === 'function' && !mod.W.__ambianceWrapped) {{
                            const originalFactory = mod.W;
                            mod.W = function(options) {{
                                const repl = originalFactory.apply(this, arguments);
                                installHooksOnRepl(repl);
                                return repl;
                            }};
                            mod.W.__ambianceWrapped = true;
                            log('Repl factory patched');
                        }}
                        scanForRepl();
                    }}).catch((err) => {{
                        console.error('[AmbianceBridge] Failed to import Strudel module', err);
                        scanForRepl();
                    }});
                }}
                ensureChannel(() => {{
                    bootstrapModule();
                }});
            }})();
        """
        return dedent(script)

    def _inject_strudel_bridge(self) -> None:
        if not self.strudel_view or QWebChannel is None:
            return
        page = self.strudel_view.page()
        if not page:
            return
        script = self._build_strudel_bridge_script()
        try:
            page.runJavaScript(script)
        except Exception as exc:
            self.logger.warning("Failed to inject Strudel bridge: %s", exc)

    def on_strudel_pattern(self, payload: Dict[str, Any]) -> None:
        self._strudel_event_queue.append(payload)
        if self.audio_engine is not None:
            try:
                self.audio_engine.ensure_running()
            except Exception as exc:
                self.logger.debug("Audio engine ensure_running failed: %s", exc)
        kind = payload.get("kind", "event")
        hap = payload.get("hap")
        try:
            hap_text = json.dumps(hap) if isinstance(hap, dict) else str(hap)
        except Exception:
            hap_text = str(hap)
        self.append_log(f"Strudel {kind}: {hap_text}")

    def on_strudel_mode_toggled(self, checked: bool) -> None:
        if not self.strudel_mode_btn:
            return
        self.strudel_mode_btn.setText("Strudel Mode: ON" if checked else "Strudel Mode: OFF")

        if not self.strudel_available:
            if checked:
                QMessageBox.warning(
                    self,
                    "Strudel Mode",
                    "PyQtWebEngine is not installed. Install 'PyQtWebEngine' to enable the Strudel playground."
                )
                self.strudel_mode_btn.blockSignals(True)
                self.strudel_mode_btn.setChecked(False)
                self.strudel_mode_btn.blockSignals(False)
            self._set_keyboard_suspended(False)
            return

        if not self.body_stack or not self.strudel_container:
            return

        if checked:
            self.ensure_strudel_loaded()
            self.body_stack.setCurrentWidget(self.strudel_container)
            if self.strudel_loaded:
                self.statusBar().showMessage("Strudel Mode active – jam inside the embedded playground.")
        else:
            self.body_stack.setCurrentWidget(self.scroll_area)
            self.statusBar().showMessage(self.default_status_message)

        self._set_keyboard_suspended(self.strudel_mode_btn.isChecked())

    def on_start_audio_clicked(self) -> None:
        if not self.audio_engine:
            QMessageBox.warning(self, "Audio Engine", "Audio engine is unavailable. Install required dependencies (pyo).")
            return
        try:
            self.audio_engine.ensure_running()
            self.append_log("Audio engine running.")
        except Exception as exc:
            QMessageBox.critical(self, "Audio Engine", f"Failed to start audio engine:\n{exc}")

    def on_add_block_clicked(self) -> None:
        if not self.audio_engine or not self.blocks_panel:
            QMessageBox.warning(self, "Blocks", "Audio engine is unavailable, cannot add blocks.")
            return
        self.blocks_panel.create_block()

    def build_plugin_block(self) -> QFrame:
        block = QFrame()
        block.setObjectName("PluginBlock")
        layout = QVBoxLayout(block)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        header = QHBoxLayout()
        header.setSpacing(12)

        rack_title = QLabel("Plugin Rack")
        rack_title.setObjectName("RackTitle")
        header.addWidget(rack_title)

        self.plugin_block_tagline = QLabel("Route native plugins directly alongside your Noisetown sessions.")
        self.plugin_block_tagline.setObjectName("RackTagline")
        header.addWidget(self.plugin_block_tagline, 1)

        self.rack_status_label = QLabel("Library pending")
        self.rack_status_label.setObjectName("RackStatus")
        header.addWidget(self.rack_status_label, 0, Qt.AlignRight)

        layout.addLayout(header)

        plugin_row = QHBoxLayout()
        plugin_row.setSpacing(18)

        self.workspace_panel = self.build_workspace_panel()
        plugin_row.addWidget(self.workspace_panel, 1)

        self.rack_panel = self.build_rack_panel()
        plugin_row.addWidget(self.rack_panel, 1)

        layout.addLayout(plugin_row)

        self.host_panel = self.build_host_panel()
        layout.addWidget(self.host_panel)

        self.instrument_panel = self.build_instrument_panel()
        layout.addWidget(self.instrument_panel)
        self.instrument_panel.setEnabled(False)




        self.log_panel = self.build_rack_log_panel()
        layout.addWidget(self.log_panel)

        return block

    def build_workspace_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("WorkspacePanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel("Plugin Library")
        title.setObjectName("WorkspaceTitle")
        header.addWidget(title)

        self.scan_btn = QPushButton("Refresh")
        self.scan_btn.clicked.connect(self.scan_plugins)
        header.addWidget(self.scan_btn)
        layout.addLayout(header)

        self.workspace_hint = QLabel("Drop VST, VST3, Audio Unit, or mc.svt plugins into this folder.")
        self.workspace_hint.setWordWrap(True)
        self.workspace_hint.setObjectName("WorkspaceHint")
        layout.addWidget(self.workspace_hint)

        path_row = QHBoxLayout()
        path_row.setSpacing(8)

        self.workspace_path_label = QLabel("Not available")
        self.workspace_path_label.setObjectName("WorkspacePath")
        path_row.addWidget(self.workspace_path_label, 1)

        self.copy_path_btn = QPushButton("Copy Path")
        self.copy_path_btn.clicked.connect(self.copy_workspace_path)
        path_row.addWidget(self.copy_path_btn)
        layout.addLayout(path_row)

        self.plugin_list = QListWidget()
        self.plugin_list.setObjectName("PluginList")
        self.plugin_list.itemSelectionChanged.connect(self.on_plugin_focus_changed)
        self.plugin_list.itemDoubleClicked.connect(self.on_plugin_selected)
        layout.addWidget(self.plugin_list, 1)

        self.workspace_notes = QLabel()
        self.workspace_notes.setObjectName("WorkspaceNotes")
        self.workspace_notes.setWordWrap(True)
        layout.addWidget(self.workspace_notes)

        return frame

    def build_rack_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("RackPanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header = QVBoxLayout()
        header.setSpacing(6)

        title = QLabel("Streams & Lanes")
        title.setObjectName("RackStreamsTitle")
        header.addWidget(title)

        self.selected_plugin_label = QLabel("Select a plugin to assign it to a lane.")
        self.selected_plugin_label.setObjectName("SelectedPlugin")
        self.selected_plugin_label.setWordWrap(True)
        header.addWidget(self.selected_plugin_label)

        layout.addLayout(header)

        self.chain_widget = PluginChainWidget()
        self.chain_widget.load_btn.clicked.connect(self.load_plugin_to_chain)
        self.chain_widget.slot_selected.connect(self.on_chain_slot_selected)
        self.chain_widget.slot_updated.connect(self.on_chain_slot_updated)
        layout.addWidget(self.chain_widget)
        QTimer.singleShot(0, self._register_chain_window)

        self.rack_notes_label = QLabel()
        self.rack_notes_label.setObjectName("RackNotes")
        self.rack_notes_label.setWordWrap(True)
        self.rack_notes_label.setText("Tip: Add slots to build A/B processing lanes and stack effects.")
        layout.addWidget(self.rack_notes_label)

        return frame

    def build_host_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("HostPanel")
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)

        titles = QVBoxLayout()
        titles.setSpacing(4)
        host_title = QLabel("Live VST Host")
        host_title.setObjectName("HostTitle")
        titles.addWidget(host_title)
        host_subtitle = QLabel("Powered by the embedded Carla engine")
        host_subtitle.setObjectName("HostSubtitle")
        titles.addWidget(host_subtitle)
        header.addLayout(titles)

        header.addStretch()

        self.host_load_btn = QPushButton("Load Selected")
        self.host_load_btn.clicked.connect(self.load_plugin_to_chain)
        header.addWidget(self.host_load_btn)

        self.host_unload_btn = QPushButton("Unload")
        self.host_unload_btn.clicked.connect(self.unload_selected_slot)
        header.addWidget(self.host_unload_btn)

        self.host_ui_btn = QPushButton("Show Plugin UI")
        self.host_ui_btn.clicked.connect(self.toggle_slot_ui_from_host)
        header.addWidget(self.host_ui_btn)

        self.host_preview_btn = QPushButton("Preview")
        self.host_preview_btn.setEnabled(False)
        self.host_preview_btn.clicked.connect(self.preview_plugin)
        header.addWidget(self.host_preview_btn)
        self.host_preview_btn.hide()

        layout.addLayout(header)

        self.host_status_label = QLabel("Toolkit status pending...")
        self.host_status_label.setObjectName("HostStatus")
        self.host_status_label.setWordWrap(True)
        layout.addWidget(self.host_status_label)

        self.host_warnings_label = QLabel()
        self.host_warnings_label.setObjectName("HostWarnings")
        self.host_warnings_label.setWordWrap(True)
        layout.addWidget(self.host_warnings_label)

        dock_row = QHBoxLayout()
        dock_row.setSpacing(8)
        self.host_dock_check = QCheckBox("Dock plugin UI inside host panel")
        self.host_dock_check.setObjectName("HostDockToggle")
        self.host_dock_check.setChecked(False)
        dock_row.addWidget(self.host_dock_check)
        dock_row.addStretch()
        layout.addLayout(dock_row)

        self.host_editor_container = PluginEditorContainer()
        layout.addWidget(self.host_editor_container, 1)

        if hasattr(self, "chain_widget"):
            self.chain_widget.set_host_controls(self.host_dock_check, self.host_editor_container)
            self.host_dock_check.toggled.connect(self.chain_widget.on_host_dock_toggled)
        else:
            self.host_dock_check.toggled.connect(lambda _checked: None)

        return frame

    def build_instrument_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("InstrumentPanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)

        titles = QVBoxLayout()
        titles.setSpacing(4)
        self.instrument_title_label = QLabel("Digital Instrument")
        self.instrument_title_label.setObjectName("InstrumentTitle")
        titles.addWidget(self.instrument_title_label)
        self.instrument_subtitle_label = QLabel("Load an instrument plugin to unlock performance controls.")
        self.instrument_subtitle_label.setObjectName("InstrumentSubtitle")
        titles.addWidget(self.instrument_subtitle_label)
        header.addLayout(titles)

        header.addStretch()
        octave_box = QHBoxLayout()
        octave_box.setSpacing(6)
        self.instrument_octave_down = QPushButton("Oct -")
        self.instrument_octave_down.clicked.connect(lambda: self.adjust_instrument_octave(-1))
        octave_box.addWidget(self.instrument_octave_down)
        self.instrument_octave_label = QLabel(f"Octave {self.instrument_octave}")
        self.instrument_octave_label.setObjectName("InstrumentOctave")
        octave_box.addWidget(self.instrument_octave_label)
        self.instrument_octave_up = QPushButton("Oct +")
        self.instrument_octave_up.clicked.connect(lambda: self.adjust_instrument_octave(1))
        octave_box.addWidget(self.instrument_octave_up)
        header.addLayout(octave_box)

        layout.addLayout(header)

        self.instrument_status_label = QLabel("Load an instrument plugin to begin.")
        self.instrument_status_label.setObjectName("InstrumentStatus")
        self.instrument_status_label.setWordWrap(True)
        layout.addWidget(self.instrument_status_label)

        control_row = QHBoxLayout()
        control_row.setSpacing(12)
        self.note_names_check = QCheckBox("Show note names")
        self.note_names_check.setChecked(True)
        self.note_names_check.toggled.connect(self.toggle_note_names)
        control_row.addWidget(self.note_names_check)
        control_row.addStretch()
        layout.addLayout(control_row)

        self.piano = PianoKeyboard()
        self.piano.setObjectName("InstrumentKeyboard")
        self.piano.set_callbacks(self.on_note_on, self.on_note_off)
        # MIDI: C4 (middle C) = note 60 = 12 * (4 + 1)
        self.piano.start_note = 12 * (self.instrument_octave + 1)
        layout.addWidget(self.piano)
        self._apply_keyboard_enabled_state()

        footer = QHBoxLayout()
        footer.setSpacing(12)
        velocity_label = QLabel("Velocity")
        velocity_label.setObjectName("VelocityLabel")
        footer.addWidget(velocity_label)
        self.instrument_velocity_slider = QSlider(Qt.Horizontal)
        self.instrument_velocity_slider.setRange(20, 120)
        self.instrument_velocity_slider.setValue(int(self.instrument_velocity * 100))
        self.instrument_velocity_slider.valueChanged.connect(self.on_instrument_velocity_changed)
        footer.addWidget(self.instrument_velocity_slider, 1)
        self.instrument_open_ui_btn = QPushButton("Show UI")
        self.instrument_open_ui_btn.clicked.connect(self.toggle_slot_ui_from_host)
        footer.addWidget(self.instrument_open_ui_btn)
        self.instrument_preview_btn = QPushButton("Preview")
        self.instrument_preview_btn.clicked.connect(self.preview_plugin)
        footer.addWidget(self.instrument_preview_btn)
        self.instrument_preview_btn.hide()
        layout.addLayout(footer)

        self.param_tabs = QTabWidget()
        self.param_tabs.setObjectName("ParameterTabs")
        layout.addWidget(self.param_tabs)

        return frame

    def _register_chain_window(self) -> None:
        """Share the main window handle with the plugin chain widget."""

        if not getattr(self, "chain_widget", None):
            return
        window = self.windowHandle()
        if window is None:
            return
        try:
            self.chain_widget.register_host_window(int(window.winId()))
        except Exception:
            pass

    def build_rack_log_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("RackLogPanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(8)

        title = QLabel("Rack Activity")
        title.setObjectName("RackLogTitle")
        layout.addWidget(title)

        self.rack_output = QPlainTextEdit()
        self.rack_output.setObjectName("RackOutput")
        self.rack_output.setReadOnly(True)
        layout.addWidget(self.rack_output)

        return frame

    def rgba(self, hex_color: str, alpha: float) -> str:
        value = hex_color.lstrip('#')
        if len(value) == 3:
            value = ''.join(ch * 2 for ch in value)
        r = int(value[0:2], 16)
        g = int(value[2:4], 16)
        b = int(value[4:6], 16)
        return f"rgba({r}, {g}, {b}, {alpha})"

    def _apply_theme_colors(self, key: str) -> None:
        preset = THEME_PRESETS.get(key, THEME_PRESETS['flat'])
        self.colors.update(preset["colors"])
        self.dark_mode = preset["dark"]

    def apply_theme(self, key: str, *, update_combo: bool = True, log_change: bool = False) -> None:
        theme_key = key if key in THEME_PRESETS else "flat"
        self.theme_key = theme_key
        self._apply_theme_colors(theme_key)

        if update_combo and hasattr(self, "theme_combo"):
            index = self.theme_combo.findData(theme_key)
            if index >= 0:
                self.theme_combo.blockSignals(True)
                self.theme_combo.setCurrentIndex(index)
                self.theme_combo.blockSignals(False)

        self.update_theme_palette()
        self.apply_global_styles()

        if getattr(self, "blocks_panel", None):
            self.blocks_panel.apply_theme(self.colors, dark=self.dark_mode)

        if log_change and hasattr(self, "rack_output"):
            label = self.theme_combo.currentText() if hasattr(self, "theme_combo") else theme_key
            self.append_log(f"Theme switched to '{label}'.")

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() == QEvent.KeyPress:
            if self._handle_key_press(cast(QKeyEvent, event)):
                return True
        elif event.type() == QEvent.KeyRelease:
            if self._handle_key_release(cast(QKeyEvent, event)):
                return True
        return super().eventFilter(watched, event)

    def _set_keyboard_suspended(self, suspended: bool) -> None:
        if self._keyboard_suspended == suspended:
            return
        self._keyboard_suspended = suspended
        if suspended:
            self._release_all_keyboard_notes()
        self._apply_keyboard_enabled_state()

    def _apply_keyboard_enabled_state(self) -> None:
        piano = getattr(self, "piano", None)
        if not piano:
            return
        enabled = not self._keyboard_suspended
        piano.setEnabled(enabled)
        if enabled:
            piano.setToolTip("")
        else:
            piano.setToolTip("Disable Strudel Mode to play the built-in keyboard.")

    def _release_all_keyboard_notes(self) -> None:
        piano = getattr(self, "piano", None)
        if piano is None:
            return
        pending = set(piano.pressed_keys)
        pending.update(self.keyboard_active_notes.values())
        for note in sorted(pending):
            try:
                self.on_note_off(note)
            except Exception:
                pass
        self.keyboard_active_notes.clear()
        piano.release_all_keys()

    def _handle_key_press(self, event: QKeyEvent) -> bool:
        try:
            if event.isAutoRepeat() or not self.isActiveWindow():
                return False
            if not getattr(self, "piano", None):
                return False
            if self._keyboard_suspended:
                return False
            if not getattr(self, "chain_widget", None):
                return False
            modifiers = event.modifiers()
            disallowed = Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier
            if int(modifiers & disallowed):
                return False
            offset = self.KEYBOARD_NOTE_MAP.get(event.key())
            if offset is None:
                return False
            note = self.piano.start_note + offset
            max_note = self.piano.start_note + self.piano.octaves * 12 - 1
            if not (self.piano.start_note <= note <= max_note):
                return False
            if event.key() in self.keyboard_active_notes:
                return True
            self.keyboard_active_notes[event.key()] = note
            if note not in self.piano.pressed_keys:
                self.piano.pressed_keys.add(note)
                self.piano.update()
            self.on_note_on(note)
            return True
        except Exception as exc:
            if hasattr(self, "logger"):
                self.logger.error("Keyboard press handling failed: %s", exc, exc_info=True)
            return False

    def _handle_key_release(self, event: QKeyEvent) -> bool:
        try:
            if event.isAutoRepeat():
                return False
            if not getattr(self, "piano", None):
                return False
            note = self.keyboard_active_notes.pop(event.key(), None)
            if note is None:
                return False
            if note in self.piano.pressed_keys:
                self.piano.pressed_keys.remove(note)
                self.piano.update()
            self.on_note_off(note)
            return True
        except Exception as exc:
            if hasattr(self, "logger"):
                self.logger.error("Keyboard release handling failed: %s", exc, exc_info=True)
            return False


    def update_theme_palette(self) -> None:
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(self.colors['bg']))
        palette.setColor(QPalette.WindowText, QColor(self.colors['text']))
        base_color = self.colors['panel'] if self.dark_mode else self.colors['card']
        palette.setColor(QPalette.Base, QColor(base_color))
        palette.setColor(QPalette.AlternateBase, QColor(self.colors['card']))
        palette.setColor(QPalette.Text, QColor(self.colors['text']))
        palette.setColor(QPalette.Button, QColor(self.colors['panel']))
        palette.setColor(QPalette.ButtonText, QColor(self.colors['text']))
        palette.setColor(QPalette.Highlight, QColor(self.colors['accent']))
        highlight_text = QColor("#000000") if not self.dark_mode else QColor(self.colors['text'])
        palette.setColor(QPalette.HighlightedText, highlight_text)
        self.setPalette(palette)

    def cleanup_fallback_threads(self):
        self.fallback_audio_threads = [t for t in self.fallback_audio_threads if t.is_alive()]

    def play_fallback_tone(self, note: int, velocity: float = 0.5):
        ws = winsound
        if ws is None:
            if not self.warned_no_winsound and hasattr(self, "rack_output"):
                self.append_log("Fallback audio not available (winsound module missing).")
                self.warned_no_winsound = True
            return

        frequency = int(440 * (2 ** ((note - 69) / 12)))
        frequency = max(37, min(32767, frequency))
        millis = max(40, int(max(0.2, min(1.0, velocity)) * 220))

        def beep() -> None:
            try:
                ws.Beep(frequency, millis)
            except RuntimeError:
                pass

        thread = threading.Thread(target=beep, daemon=True)
        thread.start()
        self.fallback_audio_threads.append(thread)
        self.cleanup_fallback_threads()

    def apply_global_styles(self):
        c = self.colors
        accent_soft = self.rgba(c['accent'], 0.22)
        accent_border = self.rgba(c['accent'], 0.45)
        accent_hover = self.rgba(c['accent'], 0.32)
        accent_selected = self.rgba(c['accent'], 0.4)
        badge_bg = self.rgba(c['accent'], 0.16)
        badge_border = self.rgba(c['accent'], 0.32)
        panel_border = self.rgba(c['border'], 0.9)
        card_border = self.rgba(c['border'], 0.4)
        panel_opaque = self.rgba(c['panel'], 1.0)
        panel_soft = self.rgba(c['panel'], 0.9)
        list_bg = self.rgba(c['card'], 0.65) if self.dark_mode else self.rgba(c['card'], 0.35)
        list_hover = self.rgba(c['accent'], 0.12)
        list_selected = self.rgba(c['accent'], 0.35)
        log_bg = self.rgba(c['card'], 0.55)
        text_disabled = self.rgba(c['text'], 0.45)
        border_disabled = self.rgba(c['border'], 0.25)
        card_disabled = self.rgba(c['card'], 0.25)
        card_half = self.rgba(c['card'], 0.5)
        card_sixty = self.rgba(c['card'], 0.6)

        style_template = Template(
            dedent(
                """
                QMainWindow {
                    background-color: $bg;
                    color: $text;
                    font-family: 'Segoe UI', Arial, sans-serif;
                    font-size: 14px;
                }
                QWidget#CentralWidget,
                QWidget#BodyWidget {
                    background-color: $panel_opaque;
                }
                QScrollArea#BodyScrollArea {
                    background-color: $panel_opaque;
                    border: none;
                }
                QScrollArea#BodyScrollArea QWidget {
                    background-color: $panel_opaque;
                }
                QStackedWidget#BodyStack {
                    background-color: transparent;
                    border: none;
                }
                QWidget#StrudelContainer {
                    background-color: $card;
                    border: 1px solid $panel_border;
                    border-radius: 16px;
                }
                QWebEngineView#StrudelView {
                    background: transparent;
                    border: none;
                    border-radius: 14px;
                }
                QLabel#StrudelFallback {
                    color: $text;
                    padding: 24px;
                }
                QFrame#Toolbar {
                    background-color: $panel;
                    border: 1px solid $panel_border;
                    border-radius: 10px;
                }
                QLabel#ToolbarTitle {
                    font-size: 18px;
                    font-weight: 600;
                    color: $text;
                }
                QComboBox#ThemePicker {
                    background-color: $card;
                    border: 1px solid $panel_border;
                    border-radius: 6px;
                    padding: 6px 10px;
                    color: $text;
                }
                QFrame#PluginBlock {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $panel, stop:1 $card);
                    border-radius: 16px;
                    border: 1px solid $panel_border;
                    box-shadow: 0px 26px 48px rgba(0, 0, 0, 0.30);
                }
                QFrame#CollapsibleSection {
                    background-color: transparent;
                    border: none;
                }
                QToolButton#SectionToggle {
                    border: 1px solid $panel_border;
                    border-radius: 10px;
                    font-weight: 600;
                    padding: 6px 10px;
                    text-align: left;
                    background-color: rgba(240, 240, 240, 0.94);
                    color: #000000;
                }
                QToolButton#SectionToggle:hover {
                    background-color: rgba(255, 255, 255, 0.98);
                    color: #000000;
                }
                QFrame#CollapsibleSectionContent {
                    background-color: $panel_soft;
                    border: 1px solid $panel_border;
                    border-radius: 14px;
                }
                QLabel#RackTitle {
                    font-size: 22px;
                    font-weight: 700;
                    color: $text;
                }
                QLabel#RackTagline {
                    color: $muted;
                }
                QLabel#RackStatus {
                    padding: 6px 12px;
                    border-radius: 999px;
                    background-color: $badge_bg;
                    border: 1px solid $badge_border;
                    color: $text;
                    font-size: 12px;
                }
                QFrame#WorkspacePanel,
                QFrame#RackPanel,
                QFrame#HostPanel,
                QFrame#InstrumentPanel,
                QFrame#RackLogPanel {
                    background-color: $panel_soft;
                    border: 1px solid $card_border;
                    border-radius: 12px;
                }
                QFrame#HostPanel {
                    border: 1px solid $accent_border;
                }
                QFrame#PluginEditorContainer {
                    background-color: $panel_soft;
                    border: 1px dashed $card_border;
                    border-radius: 12px;
                    min-height: 320px;
                }
                QFrame#PluginEditorContainer QLabel#PluginEditorPlaceholder {
                    color: $muted;
                    font-style: italic;
                }
                QListWidget#PluginList {
                    background-color: $list_bg;
                    border: 1px solid $card_border;
                    border-radius: 10px;
                    padding: 6px;
                }
                QListWidget#PluginList::item {
                    padding: 10px;
                    border-radius: 8px;
                    margin: 4px 0;
                    color: $text;
                }
                QListWidget#PluginList::item:selected {
                    background-color: $list_selected;
                    border: 1px solid $accent_border;
                }
                QListWidget#PluginList::item:hover {
                    background-color: $list_hover;
                }
                QPlainTextEdit#RackOutput {
                    background-color: $log_bg;
                    border: 1px solid $card_border;
                    border-radius: 10px;
                    padding: 10px;
                    color: $text;
                }
                QPushButton {
                    background-color: $accent_soft;
                    border: 1px solid $accent_border;
                    border-radius: 8px;
                    padding: 8px 14px;
                    color: $text;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background-color: $accent_hover;
                }
                QPushButton:disabled {
                    color: $text_disabled;
                    border-color: $border_disabled;
                    background-color: $card_disabled;
                }
                QTabWidget#ParameterTabs::pane {
                    border: 1px solid $card_border;
                    background-color: $card_half;
                    border-radius: 10px;
                }
                QTabBar::tab {
                    background-color: $card_sixty;
                    border: 1px solid $card_border;
                    border-radius: 8px;
                    padding: 8px 16px;
                    color: $text;
                    margin-right: 6px;
                }
                QTabBar::tab:selected {
                    background-color: $accent_selected;
                }
                """
            )
        )

        stylesheet = style_template.substitute(
            bg=c['bg'],
            text=c['text'],
            muted=c['muted'],
            panel=c['panel'],
            panel_opaque=panel_opaque,
            panel_soft=panel_soft,
            panel_border=panel_border,
            card=c['card'],
            card_border=card_border,
            card_half=card_half,
            card_sixty=card_sixty,
            card_disabled=card_disabled,
            list_bg=list_bg,
            list_hover=list_hover,
            list_selected=list_selected,
            log_bg=log_bg,
            accent_soft=accent_soft,
            accent_border=accent_border,
            accent_hover=accent_hover,
            accent_selected=accent_selected,
            badge_bg=badge_bg,
            badge_border=badge_border,
            text_disabled=text_disabled,
            border_disabled=border_disabled,
        )

        self.setStyleSheet(stylesheet)

    def on_edit_mode_toggled(self, checked: bool):
        self.edit_mode_btn.setText("Edit: ON" if checked else "Edit: OFF")
        state = "enabled" if checked else "disabled"
        self.append_log(f"Edit mode {state}.")

    def on_style_mode_toggled(self, checked: bool):
        self.style_mode_btn.setText("Style Mode: ON" if checked else "Style Mode: OFF")
        state = "enabled" if checked else "disabled"
        self.append_log(f"Style inspector {state}.")

    def on_theme_changed(self, index: int):
        key = self.theme_combo.itemData(index)
        if not key:
            return
        self.apply_theme(key, update_combo=False, log_change=True)

    def copy_workspace_path(self):
        if not hasattr(self, "last_workspace_path") or not self.last_workspace_path:
            self.append_log("No workspace path available to copy.")
            return
        clipboard = QApplication.clipboard()
        clipboard.setText(self.last_workspace_path)
        self.append_log(f"Workspace path copied: {self.last_workspace_path}")

    def on_plugin_focus_changed(self):
        self.refresh_selected_plugin_label()
        self.update_host_controls()

    def get_selected_slot(self) -> Optional[PluginChainSlot]:
        index = self.chain_widget.selected_slot_index
        if 0 <= index < len(self.chain_widget.slots):
            return self.chain_widget.slots[index]
        return None

    def on_chain_slot_selected(self, index: int):
        self.update_host_controls()
        slot = self.get_selected_slot()
        self.refresh_host_status(slot)

    def on_chain_slot_updated(self, index: int):
        self.update_host_controls()
        if index == self.chain_widget.selected_slot_index:
            slot = self.get_selected_slot()
            self.refresh_host_status(slot)

    def update_host_controls(self):
        slot = self.get_selected_slot()
        has_slot = slot is not None
        has_plugin = bool(slot and slot.plugin_path)
        has_host = bool(slot and slot.host)

        self.host_load_btn.setEnabled(has_slot)
        self.host_unload_btn.setEnabled(has_plugin)
        self.host_ui_btn.setEnabled(has_host)
        self.instrument_open_ui_btn.setEnabled(has_host)

        self.refresh_selected_plugin_label()

    def refresh_selected_plugin_label(self):
        items = self.plugin_list.selectedItems()
        if items:
            item = items[0]
            name = item.text()
            path = item.data(Qt.UserRole) or ""
            suffix = Path(path).suffix.upper()
            if suffix:
                text = f"Selected: {name}  {suffix}"
            else:
                text = f"Selected: {name}"
            self.selected_plugin_label.setText(text)
        else:
            slot = self.get_selected_slot()
            if slot and slot.plugin_path:
                name = slot.plugin_path.stem
                text = f"Slot {slot.index + 1}: {name}"
            else:
                self.selected_plugin_label.setText("Select a plugin to assign it to a lane.")

    def _extract_plugin_capabilities(self, status: Dict[str, Any]) -> Tuple[bool, bool]:
        """Determine plugin MIDI support and instrument flag from a status payload."""
        supports_midi = False
        is_instrument = False

        if not isinstance(status, dict):
            return supports_midi, is_instrument

        def consider(container: Any) -> None:
            nonlocal supports_midi, is_instrument
            if not isinstance(container, dict):
                return
            if container.get("instrument"):
                is_instrument = True
                supports_midi = True
            if container.get("midi"):
                supports_midi = True

        consider(status.get("capabilities"))

        plugin = status.get("plugin")
        if isinstance(plugin, dict):
            consider(plugin.get("capabilities"))
            metadata = plugin.get("metadata")
            if isinstance(metadata, dict):
                categories = metadata.get("categories") or metadata.get("category")
                values: List[str] = []
                if isinstance(categories, str):
                    values = [categories]
                elif isinstance(categories, (list, tuple, set)):
                    values = [str(value) for value in categories]
                for entry in values:
                    lower = entry.lower()
                    if any(keyword in lower for keyword in ("instrument", "synth", "generator")):
                        is_instrument = True
                        supports_midi = True
                        break
            keyboard_info = plugin.get("keyboard")
            if isinstance(keyboard_info, dict):
                supports_midi = True

        return supports_midi, is_instrument

    def refresh_host_status(self, slot: Optional[PluginChainSlot]):
        if slot and slot.host:
            try:
                status = slot.host.status()
            except Exception as exc:
                self.host_status_label.setText(f"Status unavailable: {exc}")
                self.host_warnings_label.setText("")
                return

            plugin = status.get("plugin") or {}
            metadata = plugin.get("metadata") or {}
            plugin_name = metadata.get("name") or (slot.plugin_path.stem if slot.plugin_path else "Unknown plugin")
            engine = status.get("engine") or {}
            driver = engine.get("driver") or "Auto"
            sample_rate = engine.get("sample_rate") or "?"
            buffer_size = engine.get("buffer_size") or "?"

            slot.supports_midi, is_instrument = self._extract_plugin_capabilities(status)

            self.host_status_label.setText(
                f"Loaded {plugin_name} | Driver: {driver} | SR: {sample_rate} | Buffer: {buffer_size}"
            )

            warnings = status.get("warnings") or []
            warnings_text = "\n".join(warnings)
            self.host_warnings_label.setText(warnings_text)

            if slot.supports_midi and is_instrument:
                self.instrument_title_label.setText(plugin_name)
                self.instrument_status_label.setText("Instrument ready. Use the keyboard below to audition.")
                self.instrument_panel.setEnabled(True)
            else:
                self.instrument_title_label.setText("Digital Instrument")
                self.instrument_status_label.setText("Load an instrument plugin to unlock performance controls.")
                self.instrument_panel.setEnabled(False)

            self.rack_status_label.setText(f"Host: {plugin_name}")
        else:
            self.host_status_label.setText("No plugin is currently loaded into the host.")
            self.host_warnings_label.setText("")
            self.instrument_title_label.setText("Digital Instrument")
            self.instrument_status_label.setText("Load an instrument plugin to unlock performance controls.")
            self.instrument_panel.setEnabled(False)
            if slot:
                slot.supports_midi = False
            self.rack_status_label.setText(f"Library: {self.plugin_list.count()} plugins")

    def unload_selected_slot(self):
        slot = self.get_selected_slot()
        if not slot:
            QMessageBox.information(self, "No Slot", "Select a slot from the rack first.")
            return
        self.chain_widget.unload_plugin_from_slot()
        self.param_refresh_attempts.pop(slot.index, None)
        self.append_log(f"Unloaded slot {slot.index + 1}.")
        self.refresh_host_status(self.get_selected_slot())
        self.update_host_controls()

    def toggle_slot_ui_from_host(self):
        slot = self.get_selected_slot()
        if not slot or not slot.host:
            QMessageBox.information(self, "No Plugin", "Load a plugin into the selected slot first.")
            return
        self.chain_widget.toggle_slot_ui()

    def preview_plugin(self):
        slot = self.get_selected_slot()
        if not slot or not slot.host:
            QMessageBox.information(self, "No Plugin", "Load a plugin into the selected slot first.")
            return
        self.append_log("Preview playback is not implemented for the Carla backend yet.")

    def adjust_instrument_octave(self, delta: int):
        self.instrument_octave = max(0, min(8, self.instrument_octave + delta))
        self.update_instrument_octave_label()
        # MIDI: C at octave N = note 12 * (N + 1)
        self.piano.start_note = 12 * (self.instrument_octave + 1)
        self.piano.update()

    def update_instrument_octave_label(self):
        self.instrument_octave_label.setText(f"Octave {self.instrument_octave}")

    def on_instrument_velocity_changed(self, value: int):
        self.instrument_velocity = max(0.2, min(1.2, value / 100.0))

    def append_log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        existing = self.rack_output.toPlainText()
        if existing:
            self.rack_output.setPlainText(entry + "\n" + existing)
        else:
            self.rack_output.setPlainText(entry)
        self.rack_output.verticalScrollBar().setValue(0)

    def scan_plugins(self):
        """Scan for VST plugins."""
        self.plugin_list.clear()
        base_dir = Path(__file__).parent
        workspace_candidates = [
            base_dir / "included_plugins",
            base_dir.parent / "included_plugins",
        ]
        workspace_dir = next((p for p in workspace_candidates if p.exists()), None)
        self.last_workspace_path = str(workspace_dir) if workspace_dir else ""
        self.workspace_path_label.setText(self.last_workspace_path or "Workspace not found")

        # Multiple search paths
        plugin_dirs = [
            base_dir / "included_plugins",
            base_dir.parent / "included_plugins",
            Path("C:/Program Files/VSTPlugins"),
            Path("C:/Program Files/Steinberg/VSTPlugins"),
            Path("C:/Program Files/Common Files/VST3"),
            Path("C:/Program Files (x86)/VSTPlugins"),
            Path("C:/Program Files (x86)/Steinberg/VSTPlugins"),
        ]

        available_dirs = [p for p in plugin_dirs if p.exists()]
        missing_dirs = [p for p in plugin_dirs if not p.exists() and "Program Files" not in str(p)]

        plugins = []
        for plugin_dir in available_dirs:
            for pattern in ("**/*.dll", "**/*.vst3", "**/*.vst"):
                plugins.extend(plugin_dir.glob(pattern))
        
        # Remove duplicates and sort
        seen = {}
        for plugin_path in sorted(set(plugins)):
            key = plugin_path.name.lower()
            if key in seen:
                continue
            seen[key] = plugin_path
            item = QListWidgetItem(plugin_path.stem)
            item.setData(Qt.UserRole, str(plugin_path))
            item.setToolTip(str(plugin_path))
            self.plugin_list.addItem(item)

        notes: List[str] = []
        if not available_dirs:
            notes.append("No plugin directories were found. Drop VST files into the Ambiance 'included_plugins' folder.")
        elif missing_dirs:
            notes.append("Some optional plugin folders were not found and will be skipped.")

        self.workspace_notes.setText("\n".join(notes))

        plugin_count = len(seen)
        dir_count = len(available_dirs)
        self.statusBar().showMessage(f"Found {plugin_count} plugins across {dir_count} folders")
        self.rack_status_label.setText(f"Library: {plugin_count} plugins")
        if plugin_count == 0:
            self.append_log("No plugins discovered. Add VST/VST3 files to your workspace directory.")
        else:
            self.append_log(f"Library refreshed - {plugin_count} plugins ready.")

        self.refresh_selected_plugin_label()
        self.update_host_controls()
    
    def on_plugin_selected(self, item):
        """Handle plugin double-click."""
        # Check if there's a selected slot in chain
        if self.chain_widget.selected_slot_index >= 0:
            self.load_plugin_to_chain()
    
    def load_plugin_to_chain(self):
        """Load selected plugin into selected chain slot."""
        if self.chain_widget.selected_slot_index < 0:
            QMessageBox.information(self, "No Slot", "Please select or add a plugin slot first")
            return
        
        items = self.plugin_list.selectedItems()
        if not items:
            QMessageBox.information(self, "No Plugin", "Please select a plugin to load")
            return
        
        plugin_path = Path(items[0].data(Qt.UserRole))
        slot = self.chain_widget.slots[self.chain_widget.selected_slot_index]
        slot.supports_midi = False
        
        try:
            if slot.host:
                with slot.lock:
                    slot.host.unload()
                    slot.host.shutdown()

            # Create fresh host with unique JACK client name (prevents conflicts)
            slot.host = CarlaVSTHost(client_name=f"AmbianceSlot{slot.index}")
            if self.chain_widget.host_window_id is not None:
                slot.host.register_host_window(self.chain_widget.host_window_id)

            # Configure audio WITHOUT lock (plugin_host.py doesn't use locks)
            # Try DirectSound first for testing - JACK needs server running + routing setup
            slot.host.configure_audio(preferred_drivers=["DirectSound", "ASIO", "WASAPI", "JACK"])

            # Load plugin WITHOUT lock (plugin_host.py doesn't use locks)
            slot.host.load_plugin(plugin_path, show_ui=False)
            slot.plugin_path = plugin_path
            slot.ui_visible = False

            # Get status WITHOUT lock (plugin_host.py doesn't use locks)
            status: Dict[str, Any] = {}
            try:
                status = slot.host.status()
            except Exception:
                status = {}

            # Log which audio driver is being used
            driver_name = status.get("driver", "unknown")
            self.logger.info(f"Slot {slot.index} using audio driver: {driver_name}")
            if driver_name not in ["JACK", "ASIO"]:
                self.logger.warning(f"Using {driver_name} driver - Install JACK or ASIO for better compatibility")
                self.logger.warning(f"See JACK_SETUP.md for installation instructions")

            slot.supports_midi, _ = self._extract_plugin_capabilities(status)

            self.chain_widget.update_slot_display(slot.index)
            self.chain_widget.update_controls()

            self.update_parameters_for_slot(slot)
            self.refresh_host_status(slot)
            self.update_host_controls()
            self.refresh_selected_plugin_label()

            if len(self.chain_widget.get_active_slots()) == 1:
                self.poll_timer.start(100)

            self.statusBar().showMessage(f"Loaded {plugin_path.stem} into slot {slot.index + 1}")
            self.append_log(f"Loaded '{plugin_path.stem}' into slot {slot.index + 1}.")

        except Exception as e:
            slot.supports_midi = False
            QMessageBox.critical(self, "Load Error", f"Failed to load plugin:\n{str(e)}")
            self.logger.error(f"Plugin load error: {e}", exc_info=True)
            self.append_log(f"Failed to load plugin: {e}")
    
    def update_parameters_for_slot(self, slot: PluginChainSlot):
        """Update parameter controls for a slot."""
        if not slot.host:
            return
        
        # Get or create tab for this slot
        tab_name = f"Slot {slot.index + 1}"
        tab_index = -1
        for i in range(self.param_tabs.count()):
            if self.param_tabs.tabText(i) == tab_name:
                tab_index = i
                break
        
        layout: QVBoxLayout
        if tab_index == -1:
            # Create new tab
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            widget = QWidget()
            layout = QVBoxLayout(widget)
            scroll.setWidget(widget)
            tab_index = self.param_tabs.addTab(scroll, tab_name)
        else:
            # Clear existing tab
            scroll_widget = self.param_tabs.widget(tab_index)
            if not isinstance(scroll_widget, QScrollArea):
                return
            widget = scroll_widget.widget()
            if widget is None:
                return
            existing_layout = widget.layout()
            if existing_layout is None or not isinstance(existing_layout, QVBoxLayout):
                existing_layout = QVBoxLayout(widget)
            layout = cast(QVBoxLayout, existing_layout)
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        
        # Add parameters
        status: Dict[str, Any] = {}
        try:
            with slot.lock:
                status = slot.host.status()
        except Exception as exc:
            status = {}
            self.logger.debug("Failed to read slot %s status: %s", slot.index, exc, exc_info=True)

        if not isinstance(status, dict):
            status = {}

        params = status.get("parameters", [])
        self.logger.debug("Slot %s initial parameter count: %s", slot.index, len(params) if isinstance(params, list) else 'n/a')

        if not params:
            descriptor: Dict[str, Any] = {}
            try:
                with slot.lock:
                    descriptor = slot.host.describe_ui(include_parameters=True)
            except Exception as exc:
                self.logger.debug("describe_ui failed for slot %s: %s", slot.index, exc, exc_info=True)
            else:
                if isinstance(descriptor, dict):
                    params = descriptor.get("parameters") or []
                    if not params:
                        plugin_info = descriptor.get("plugin")
                        if isinstance(plugin_info, dict):
                            params = plugin_info.get("parameters") or []
                    if params:
                        status["parameters"] = params
                        self.logger.debug("Slot %s recovered %d parameters via describe_ui()", slot.index, len(params))
                    else:
                        self.logger.debug("Slot %s still reports no parameters after describe_ui()", slot.index)

        attempts = self.param_refresh_attempts.get(slot.index, 0)

        if not params:
            max_attempts = 10  # Increased from 5 to 10 for slow plugins like Aspen
            if attempts == 0:
                message = "Discovering parameters..."
            elif attempts < max_attempts:
                message = f"No parameters yet. Retrying... (attempt {attempts + 1}/{max_attempts})"
            else:
                message = "No parameters reported by this plugin."
            label = QLabel(message)
            layout.addWidget(label)
            layout.addStretch()
            if attempts < max_attempts:
                self.param_refresh_attempts[slot.index] = attempts + 1
                # Progressive delays: start fast, get slower for stubborn plugins
                if attempts < 2:
                    delay = 500  # First 2: 500ms (quick check)
                elif attempts < 5:
                    delay = 1500  # Next 3: 1.5s (give it time)
                else:
                    delay = 3000  # Final 5: 3s (really patient)
                QTimer.singleShot(
                    delay,
                    lambda idx=slot.index: self.retry_parameter_fetch(idx)
                )
            return
        
        self.param_refresh_attempts[slot.index] = 0
        for param in params:
            self.create_parameter_control(layout, slot, param)
        
        layout.addStretch()

    def retry_parameter_fetch(self, slot_index: int):
        if 0 <= slot_index < len(self.chain_widget.slots):
            slot = self.chain_widget.slots[slot_index]
            if slot.host:
                self.update_parameters_for_slot(slot)
                self.refresh_host_status(slot)
    
    def create_parameter_control(self, layout: QVBoxLayout, slot: PluginChainSlot, param: Dict[str, Any]) -> None:
        """Create a parameter control widget."""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        param_layout = QVBoxLayout(frame)
        
        # Label
        name = param.get("display_name") or param.get("name", "Parameter")
        value_label = QLabel(f"{name}: {param['value']:.3f} {param.get('units', '')}")
        param_layout.addWidget(value_label)
        
        # Slider
        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(0)
        slider.setMaximum(1000)
        
        min_val = param.get("min", 0)
        max_val = param.get("max", 1)
        current_val = param.get("value", 0)
        
        normalized = (current_val - min_val) / (max_val - min_val) if max_val != min_val else 0
        slider.setValue(int(normalized * 1000))
        
        def on_value_changed(val: int) -> None:
            host = slot.host
            if host is None:
                return
            norm = val / 1000.0
            actual = min_val + norm * (max_val - min_val)
            try:
                with slot.lock:
                    host.set_parameter(param["id"], actual)
                value_label.setText(f"{name}: {actual:.3f} {param.get('units', '')}")
            except:
                pass
        
        slider.valueChanged.connect(on_value_changed)
        param_layout.addWidget(slider)
        
        layout.addWidget(frame)
    
    def toggle_note_names(self, checked):
        """Toggle note name display."""
        self.piano.show_note_names = checked
        self.piano.update()
    
    def on_note_on(self, note: int):
        """Handle note on event - send to all active plugins in chain."""
        active_slots = [s for s in self.chain_widget.get_active_slots() if s.supports_midi]
        if not active_slots:
            self.play_fallback_tone(note, self.instrument_velocity)
            return

        for slot in active_slots:
            try:
                host = slot.host
                if host is None:
                    continue
                # Don't hold lock during MIDI send to avoid deadlock
                host.note_on(note, velocity=self.instrument_velocity)
            except Exception as e:
                self.logger.error(f"Note on error for slot {slot.index}: {e}")

    def on_note_off(self, note: int):
        """Handle note off event - send to all active plugins in chain."""
        for slot in [s for s in self.chain_widget.get_active_slots() if s.supports_midi]:
            try:
                host = slot.host
                if host is None:
                    continue
                # Don't hold lock during MIDI send to avoid deadlock
                host.note_off(note)
            except Exception as e:
                self.logger.error(f"Note off error for slot {slot.index}: {e}")
    
    def poll_parameters(self):
        """Poll parameter values for all active slots."""
        # TODO: Implement parameter polling for all slots
        pass


    def on_tempo_changed(self, tempo: float):
        """Handle tempo change from Time & Pitch mod."""
        self.logger.info(f"Tempo changed: {tempo:.2f}x")
        # TODO: Apply tempo change to audio stream
        self.append_log(f"Tempo: {tempo:.2f}x")

    def on_pitch_changed(self, pitch: int):
        """Handle pitch change from Time & Pitch mod."""
        self.logger.info(f"Pitch changed: {pitch:+d} semitones")
        # TODO: Apply pitch shift to audio stream
        self.append_log(f"Pitch: {pitch:+d} st")

    def on_reverse_changed(self, reverse: bool):
        """Handle reverse toggle from Time & Pitch mod."""
        self.logger.info(f"Reverse: {reverse}")
        # TODO: Apply reverse to audio stream
        self.append_log(f"Reverse: {'ON' if reverse else 'OFF'}")

    def on_loop_changed(self, loop: bool):
        """Handle loop toggle from Time & Pitch mod."""
        self.logger.info(f"Loop: {loop}")
        # TODO: Apply loop to audio stream
        self.append_log(f"Loop: {'ON' if loop else 'OFF'}")

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        """Clean shutdown."""
        self.poll_timer.stop()
        self.process_timer.stop()

        self._teardown_strudel_server()

        # Shutdown all plugin hosts
        for slot in self.chain_widget.slots:
            if slot.host:
                try:
                    with slot.lock:
                        slot.host.unload()
                        slot.host.shutdown()
                except Exception:
                    pass

        for note in list(self.keyboard_active_notes.values()):
            try:
                self.on_note_off(note)
            except Exception:
                pass
        self.keyboard_active_notes.clear()

        if self.audio_engine is not None:
            try:
                self.audio_engine.shutdown()
            except Exception as exc:
                self.logger.error("Audio engine shutdown failed: %s", exc, exc_info=True)

        self.chain_widget.shutdown()
        for thread in list(self.fallback_audio_threads):
            if thread.is_alive():
                thread.join(timeout=0.2)
        self.fallback_audio_threads.clear()

        if self._qt_app is not None:
            try:
                self._qt_app.removeEventFilter(self)
            except Exception:
                pass

        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Ambiance Improved")
    app.setStyle("Fusion")
    
    window = AmbianceQtImproved()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
