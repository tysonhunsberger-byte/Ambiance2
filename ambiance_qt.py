"""Ambiance - Pure Qt desktop application matching web UI styling."""

import sys
import argparse
from pathlib import Path
from typing import Optional

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QScrollArea,
    QSlider, QFrame, QSplitter, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer, QSize
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QPalette

sys.path.insert(0, str(Path(__file__).parent / "ambiance" / "src"))

from ambiance.integrations.carla_host import CarlaVSTHost, CarlaHostError


# Color scheme matching web UI
COLORS = {
    'bg': '#121212',
    'panel': '#1e1e1e',
    'card': '#222',
    'text': '#f0f0f0',
    'muted': '#bbb',
    'accent': '#59a7ff',
    'border': '#444',
}


class StyledWidget(QWidget):
    """Base widget with web UI styling."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.apply_style()

    def apply_style(self):
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS['bg']};
                color: {COLORS['text']};
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 14px;
            }}
        """)


class StyledPanel(QFrame):
    """Styled panel matching web UI cards."""

    def __init__(self, title=None, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['panel']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 10px;
            }}
            QLabel {{
                background: transparent;
                border: none;
            }}
        """)

        layout = QVBoxLayout(self)
        if title:
            header = QLabel(title)
            header.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLORS['text']}; margin-bottom: 8px;")
            layout.addWidget(header)

        self.content_layout = QVBoxLayout()
        layout.addLayout(self.content_layout)


class PianoKeyboard(QWidget):
    """Virtual piano keyboard matching web UI style."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(140)
        self.setMaximumHeight(160)

        # Keyboard settings
        self.octaves = 2
        self.start_note = 48  # C3
        self.white_key_width = 42
        self.white_key_height = 140
        self.black_key_width = 24
        self.black_key_height = 98

        # State
        self.pressed_keys = set()
        self.mouse_down_note = None

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

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw white keys
        white_keys = []
        for i in range(self.octaves * 12):
            note = self.start_note + i
            if note % 12 in [0, 2, 4, 5, 7, 9, 11]:
                white_keys.append(note)

        x = 0
        for note in white_keys:
            is_pressed = note in self.pressed_keys
            if is_pressed:
                gradient = QColor('#f97316')
            else:
                gradient = QColor(245, 247, 255)

            painter.fillRect(x, 0, self.white_key_width, self.white_key_height, gradient)
            painter.setPen(QPen(QColor(0, 0, 0, 150), 2))
            painter.drawRect(x, 0, self.white_key_width, self.white_key_height)
            x += self.white_key_width

        # Draw black keys
        x = 0
        for i in range(self.octaves * 12):
            note = self.start_note + i
            if note % 12 in [1, 3, 6, 8, 10]:
                is_pressed = note in self.pressed_keys
                if is_pressed:
                    color = QColor('#f97316')
                else:
                    color = QColor(15, 18, 24)

                offset = self.white_key_width - self.black_key_width // 2
                painter.fillRect(x + offset, 0, self.black_key_width, self.black_key_height, color)
                painter.setPen(QPen(QColor(17, 17, 17), 2))
                painter.drawRect(x + offset, 0, self.black_key_width, self.black_key_height)

            if note % 12 in [0, 2, 4, 5, 7, 9, 11]:
                x += self.white_key_width

    def get_note_at_position(self, x, y):
        # Check black keys first
        white_x = 0
        for i in range(self.octaves * 12):
            note = self.start_note + i
            if note % 12 in [1, 3, 6, 8, 10]:
                offset = white_x + self.white_key_width - self.black_key_width // 2
                if offset <= x < offset + self.black_key_width and y < self.black_key_height:
                    return note
            if note % 12 in [0, 2, 4, 5, 7, 9, 11]:
                white_x += self.white_key_width

        # Check white keys
        white_x = 0
        for i in range(self.octaves * 12):
            note = self.start_note + i
            if note % 12 in [0, 2, 4, 5, 7, 9, 11]:
                if white_x <= x < white_x + self.white_key_width:
                    return note
                white_x += self.white_key_width

        return None

    def mousePressEvent(self, event):
        note = self.get_note_at_position(event.x(), event.y())
        if note is not None:
            self.mouse_down_note = note
            if note not in self.pressed_keys:
                self.pressed_keys.add(note)
                self.update()
                if self.note_on_callback:
                    self.note_on_callback(note)

    def mouseReleaseEvent(self, event):
        if self.mouse_down_note is not None:
            note = self.mouse_down_note
            if note in self.pressed_keys:
                self.pressed_keys.remove(note)
                self.update()
                if self.note_off_callback:
                    self.note_off_callback(note)
            self.mouse_down_note = None

    def mouseMoveEvent(self, event):
        if self.mouse_down_note is not None:
            current_note = self.get_note_at_position(event.x(), event.y())
            if current_note != self.mouse_down_note:
                if self.mouse_down_note in self.pressed_keys:
                    self.pressed_keys.remove(self.mouse_down_note)
                    if self.note_off_callback:
                        self.note_off_callback(self.mouse_down_note)

                if current_note is not None:
                    self.mouse_down_note = current_note
                    if current_note not in self.pressed_keys:
                        self.pressed_keys.add(current_note)
                        if self.note_on_callback:
                            self.note_on_callback(current_note)
                else:
                    self.mouse_down_note = None

                self.update()


class AmbianceQt(QMainWindow):
    """Pure Qt desktop app matching web UI."""

    def __init__(self, preferred_drivers=None, forced_driver=None, auto_plugin=None):
        super().__init__()

        # Initialize Carla
        self.host = CarlaVSTHost()
        self.host.configure_audio(
            preferred_drivers=preferred_drivers or ["DirectSound", "WASAPI", "MME", "ASIO", "Dummy"],
            forced_driver=forced_driver,
        )

        # State
        self.param_sliders = {}
        self.updating_from_plugin = False
        self._auto_plugin = Path(auto_plugin) if auto_plugin else None

        # Timer for parameter polling
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.poll_parameters)

        self.init_ui()

        # Auto-load plugin
        if self._auto_plugin:
            QTimer.singleShot(100, lambda: self.load_plugin_path(self._auto_plugin))

    def init_ui(self):
        self.setWindowTitle("Ambiance - VST Host")
        self.setGeometry(100, 100, 1200, 800)

        # Set dark theme
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(COLORS['bg']))
        palette.setColor(QPalette.WindowText, QColor(COLORS['text']))
        palette.setColor(QPalette.Base, QColor(COLORS['panel']))
        palette.setColor(QPalette.AlternateBase, QColor(COLORS['card']))
        palette.setColor(QPalette.Text, QColor(COLORS['text']))
        palette.setColor(QPalette.Button, QColor(COLORS['panel']))
        palette.setColor(QPalette.ButtonText, QColor(COLORS['text']))
        palette.setColor(QPalette.Highlight, QColor(COLORS['accent']))
        palette.setColor(QPalette.HighlightedText, QColor(COLORS['text']))
        self.setPalette(palette)

        # Main widget
        central = StyledWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Splitter for resize
        splitter = QSplitter(Qt.Horizontal)

        # LEFT: Plugin Library
        left_panel = StyledPanel("Plugin Library")
        self.plugin_list = QListWidget()
        self.plugin_list.setStyleSheet(f"""
            QListWidget {{
                background-color: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 8px;
                border-radius: 6px;
                margin: 2px 0;
            }}
            QListWidget::item:selected {{
                background-color: rgba(89, 167, 255, 0.3);
                border: 1px solid rgba(89, 167, 255, 0.6);
            }}
            QListWidget::item:hover {{
                background-color: rgba(255, 255, 255, 0.06);
            }}
        """)
        self.plugin_list.itemDoubleClicked.connect(self.on_plugin_selected)
        left_panel.content_layout.addWidget(self.plugin_list)

        scan_btn = QPushButton("Scan for Plugins")
        scan_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(89, 167, 255, 0.2);
                border: 1px solid rgba(89, 167, 255, 0.4);
                border-radius: 6px;
                padding: 8px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: rgba(89, 167, 255, 0.3);
            }}
        """)
        scan_btn.clicked.connect(self.scan_plugins)
        left_panel.content_layout.addWidget(scan_btn)

        splitter.addWidget(left_panel)

        # RIGHT: Plugin controls
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setSpacing(14)

        # Host panel
        host_panel = StyledPanel("Loaded Plugin")
        self.status_label = QLabel("No plugin loaded")
        self.status_label.setWordWrap(True)
        host_panel.content_layout.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        self.ui_btn = QPushButton("Show Plugin UI")
        self.ui_btn.setEnabled(False)
        self.ui_btn.clicked.connect(self.toggle_ui)
        btn_row.addWidget(self.ui_btn)

        self.unload_btn = QPushButton("Unload Plugin")
        self.unload_btn.setEnabled(False)
        self.unload_btn.clicked.connect(self.unload_plugin)
        btn_row.addWidget(self.unload_btn)
        host_panel.content_layout.addLayout(btn_row)

        for btn in [self.ui_btn, self.unload_btn]:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['panel']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 6px;
                    padding: 6px 10px;
                }}
                QPushButton:hover {{
                    background-color: #333;
                }}
                QPushButton:disabled {{
                    opacity: 0.5;
                }}
            """)

        right_layout.addWidget(host_panel)

        # Keyboard panel
        keyboard_panel = StyledPanel("MIDI Keyboard")
        self.piano = PianoKeyboard()
        self.piano.set_callbacks(self.on_note_on, self.on_note_off)
        keyboard_panel.content_layout.addWidget(self.piano)
        right_layout.addWidget(keyboard_panel)

        # Parameters panel
        param_panel = StyledPanel("Parameters")
        self.param_scroll = QScrollArea()
        self.param_scroll.setWidgetResizable(True)
        self.param_scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: transparent;
            }}
        """)

        self.param_widget = QWidget()
        self.param_layout = QVBoxLayout(self.param_widget)
        self.param_scroll.setWidget(self.param_widget)
        param_panel.content_layout.addWidget(self.param_scroll)
        right_layout.addWidget(param_panel)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter)

        # Scan on startup
        QTimer.singleShot(100, self.scan_plugins)

    def scan_plugins(self):
        """Scan for plugins."""
        self.plugin_list.clear()
        base_dir = Path(__file__).parent
        plugin_dirs = [
            base_dir / "included_plugins",
            base_dir.parent / "included_plugins",
        ]

        plugins = []
        for plugin_dir in plugin_dirs:
            if plugin_dir.exists():
                for pattern in ("**/*.dll", "**/*.vst3"):
                    plugins.extend(plugin_dir.glob(pattern))

        for plugin_path in sorted(set(plugins)):
            item = QListWidgetItem(plugin_path.stem)
            item.setData(Qt.UserRole, str(plugin_path))
            self.plugin_list.addItem(item)

    def on_plugin_selected(self, item):
        """Load selected plugin."""
        plugin_path = Path(item.data(Qt.UserRole))
        self.load_plugin_path(plugin_path)

    def load_plugin_path(self, plugin_path: Path) -> bool:
        """Load plugin."""
        try:
            self.host.load_plugin(plugin_path, show_ui=False)
            self.update_status()
            self.update_parameters()
            self.ui_btn.setEnabled(True)
            self.unload_btn.setEnabled(True)
            self.poll_timer.start(100)
            return True
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load plugin:\n\n{e}")
            return False

    def unload_plugin(self):
        """Unload plugin."""
        self.poll_timer.stop()
        self.host.unload()
        self.update_status()
        self.clear_parameters()
        self.ui_btn.setEnabled(False)
        self.unload_btn.setEnabled(False)

    def toggle_ui(self):
        """Toggle native UI."""
        try:
            status = self.host.status()
            if status.get("ui_visible"):
                self.host.hide_ui()
                self.ui_btn.setText("Show Plugin UI")
            else:
                self.host.show_ui()
                self.ui_btn.setText("Hide Plugin UI")
        except CarlaHostError as e:
            QMessageBox.warning(self, "UI Error", str(e))

    def on_note_on(self, note: int):
        """Note on."""
        try:
            self.host.note_on(note, velocity=0.8)
        except Exception as e:
            print(f"Note on error: {e}")

    def on_note_off(self, note: int):
        """Note off."""
        try:
            self.host.note_off(note)
        except Exception as e:
            print(f"Note off error: {e}")

    def update_status(self):
        """Update status label."""
        status = self.host.status()
        if status.get("plugin"):
            plugin = status["plugin"]
            name = plugin["metadata"]["name"]
            vendor = plugin["metadata"]["vendor"]
            self.status_label.setText(f"<b>{name}</b><br/>Vendor: {vendor}")
        else:
            self.status_label.setText("No plugin loaded")

    def clear_parameters(self):
        """Clear parameter sliders."""
        while self.param_layout.count():
            item = self.param_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.param_sliders.clear()

    def update_parameters(self):
        """Update parameter sliders."""
        self.clear_parameters()
        status = self.host.status()
        params = status.get("parameters", [])

        if not params:
            self.param_layout.addWidget(QLabel("No parameters"))
            return

        for param in params:
            param_frame = QFrame()
            param_frame.setStyleSheet(f"""
                QFrame {{
                    background-color: rgba(255, 255, 255, 0.04);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 8px;
                    padding: 10px;
                }}
            """)
            param_layout = QVBoxLayout(param_frame)

            name = param["display_name"] or param["name"]
            value_label = QLabel(f"{name}: {param['value']:.3f} {param['units']}")
            param_layout.addWidget(value_label)

            slider = QSlider(Qt.Horizontal)
            slider.setMinimum(0)
            slider.setMaximum(1000)
            min_val, max_val = param["min"], param["max"]
            normalized = (param["value"] - min_val) / (max_val - min_val) if max_val != min_val else 0
            slider.setValue(int(normalized * 1000))

            slider.setStyleSheet(f"""
                QSlider::groove:horizontal {{
                    background: rgba(255, 255, 255, 0.1);
                    height: 6px;
                    border-radius: 3px;
                }}
                QSlider::handle:horizontal {{
                    background: {COLORS['accent']};
                    width: 16px;
                    height: 16px;
                    margin: -5px 0;
                    border-radius: 8px;
                }}
            """)

            param_id = param["id"]
            self.param_sliders[param_id] = {
                "slider": slider,
                "label": value_label,
                "min": min_val,
                "max": max_val,
                "name": name,
                "units": param["units"]
            }

            def make_handler(pid, minv, maxv, lbl, nm, u):
                def handler(val):
                    if self.updating_from_plugin:
                        return
                    norm = val / 1000.0
                    actual = minv + norm * (maxv - minv)
                    try:
                        self.host.set_parameter(pid, actual)
                        lbl.setText(f"{nm}: {actual:.3f} {u}")
                    except:
                        pass
                return handler

            slider.valueChanged.connect(make_handler(param_id, min_val, max_val, value_label, name, param["units"]))
            param_layout.addWidget(slider)
            self.param_layout.addWidget(param_frame)

        self.param_layout.addStretch()

    def poll_parameters(self):
        """Poll parameter values."""
        if self.updating_from_plugin:
            return
        try:
            status = self.host.status()
            self.updating_from_plugin = True
            for param in status.get("parameters", []):
                if param["id"] in self.param_sliders:
                    info = self.param_sliders[param["id"]]
                    norm = (param["value"] - info["min"]) / (info["max"] - info["min"]) if info["max"] != info["min"] else 0
                    pos = int(norm * 1000)
                    if abs(info["slider"].value() - pos) > 1:
                        info["slider"].blockSignals(True)
                        info["slider"].setValue(pos)
                        info["slider"].blockSignals(False)
                        info["label"].setText(f"{info['name']}: {param['value']:.3f} {info['units']}")
            self.updating_from_plugin = False
        except:
            self.updating_from_plugin = False

    def closeEvent(self, event):
        """Handle close."""
        self.poll_timer.stop()
        self.host.shutdown()
        event.accept()


def main():
    parser = argparse.ArgumentParser(description="Ambiance - Pure Qt VST Host")
    parser.add_argument("--plugin", help="Plugin to load on startup")
    parser.add_argument("--driver", action="append", help="Preferred audio driver")
    parser.add_argument("--forced-driver", help="Force specific driver")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("Ambiance")

    window = AmbianceQt(
        preferred_drivers=args.driver,
        forced_driver=args.forced_driver,
        auto_plugin=args.plugin,
    )
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
