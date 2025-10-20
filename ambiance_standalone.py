"""Standalone VST plugin host with built-in keyboard and plugin browser."""

import argparse
import sys
from pathlib import Path
from typing import Sequence

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QVBoxLayout, QHBoxLayout,
    QWidget, QLabel, QSlider, QScrollArea, QMessageBox, QGroupBox,
    QListWidget, QListWidgetItem, QSplitter, QFrame
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QColor, QPen

sys.path.insert(0, str(Path(__file__).parent / "ambiance" / "src"))

from ambiance.integrations.carla_host import CarlaVSTHost, CarlaHostError


class PianoKeyboard(QWidget):
    """Virtual piano keyboard widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(100)
        self.setMaximumHeight(150)

        # Piano settings
        self.octaves = 2  # Show 2 octaves
        self.start_note = 48  # C3
        self.white_key_width = 40
        self.white_key_height = 100
        self.black_key_width = 24
        self.black_key_height = 60

        # Track pressed keys
        self.pressed_keys = set()
        self.mouse_down_note = None

        # Callback for note events
        self.note_on_callback = None
        self.note_off_callback = None

        self.setMouseTracking(True)

    def set_callbacks(self, note_on, note_off):
        """Set callbacks for note events."""
        self.note_on_callback = note_on
        self.note_off_callback = note_off

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw white keys
        white_keys = []
        for i in range(self.octaves * 12):
            note = self.start_note + i
            if note % 12 in [0, 2, 4, 5, 7, 9, 11]:  # White keys
                white_keys.append(note)

        x = 0
        for note in white_keys:
            is_pressed = note in self.pressed_keys
            color = QColor(200, 200, 200) if is_pressed else QColor(255, 255, 255)
            painter.fillRect(x, 0, self.white_key_width, self.white_key_height, color)
            painter.setPen(QPen(Qt.black, 2))
            painter.drawRect(x, 0, self.white_key_width, self.white_key_height)
            x += self.white_key_width

        # Draw black keys
        x = 0
        for i in range(self.octaves * 12):
            note = self.start_note + i
            if note % 12 in [1, 3, 6, 8, 10]:  # Black keys
                is_pressed = note in self.pressed_keys
                color = QColor(80, 80, 80) if is_pressed else QColor(0, 0, 0)
                # Position black keys between white keys
                offset = self.white_key_width - self.black_key_width // 2
                painter.fillRect(x + offset, 0, self.black_key_width, self.black_key_height, color)
                painter.setPen(QPen(Qt.black, 2))
                painter.drawRect(x + offset, 0, self.black_key_width, self.black_key_height)

            # Move x for white keys only
            if note % 12 in [0, 2, 4, 5, 7, 9, 11]:
                x += self.white_key_width

    def get_note_at_position(self, x, y):
        """Get MIDI note number at mouse position."""
        # Check black keys first (they're on top)
        white_x = 0
        for i in range(self.octaves * 12):
            note = self.start_note + i
            if note % 12 in [1, 3, 6, 8, 10]:  # Black key
                offset = white_x + self.white_key_width - self.black_key_width // 2
                if offset <= x < offset + self.black_key_width and y < self.black_key_height:
                    return note

            if note % 12 in [0, 2, 4, 5, 7, 9, 11]:
                white_x += self.white_key_width

        # Check white keys
        white_x = 0
        for i in range(self.octaves * 12):
            note = self.start_note + i
            if note % 12 in [0, 2, 4, 5, 7, 9, 11]:  # White key
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
                # Release previous note
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


class AmbianceApp(QMainWindow):
    def __init__(
        self,
        *,
        preferred_drivers: Sequence[str] | None = None,
        forced_driver: str | None = None,
        auto_plugin: Path | None = None,
    ):
        super().__init__()

        self.preferred_drivers = list(preferred_drivers) if preferred_drivers else [
            "DirectSound", "WASAPI", "MME", "ASIO", "Dummy"
        ]
        self.forced_driver = forced_driver

        # Initialize Carla host
        self.host = CarlaVSTHost()
        self.host.configure_audio(
            preferred_drivers=self.preferred_drivers,
            forced_driver=forced_driver,
        )

        self.param_sliders = {}
        self.updating_from_plugin = False
        self._auto_plugin = Path(auto_plugin) if auto_plugin else None

        # Timer for parameter polling
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.poll_parameters)

        self.init_ui()

        # Auto-load plugin if specified
        if self._auto_plugin:
            QTimer.singleShot(0, lambda: self.load_plugin_path(self._auto_plugin))

    def init_ui(self):
        self.setWindowTitle("Ambiance - VST Host")
        self.setGeometry(100, 100, 1000, 800)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # Create splitter for resizable sections
        splitter = QSplitter(Qt.Horizontal)

        # LEFT PANEL: Plugin browser
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        browser_group = QGroupBox("Plugin Library")
        browser_layout = QVBoxLayout(browser_group)

        self.plugin_list = QListWidget()
        self.plugin_list.itemDoubleClicked.connect(self.on_plugin_selected)
        browser_layout.addWidget(self.plugin_list)

        scan_btn = QPushButton("Scan for Plugins")
        scan_btn.clicked.connect(self.scan_plugins)
        browser_layout.addWidget(scan_btn)

        left_layout.addWidget(browser_group)

        # RIGHT PANEL: Plugin controls
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        # Status section
        status_group = QGroupBox("Loaded Plugin")
        status_layout = QVBoxLayout(status_group)

        self.status_label = QLabel("No plugin loaded")
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label)

        # Control buttons
        btn_row = QHBoxLayout()
        self.ui_btn = QPushButton("Show Plugin UI")
        self.ui_btn.clicked.connect(self.toggle_ui)
        self.ui_btn.setEnabled(False)
        btn_row.addWidget(self.ui_btn)

        self.unload_btn = QPushButton("Unload Plugin")
        self.unload_btn.clicked.connect(self.unload_plugin)
        self.unload_btn.setEnabled(False)
        btn_row.addWidget(self.unload_btn)
        status_layout.addLayout(btn_row)

        right_layout.addWidget(status_group)

        # Piano keyboard
        keyboard_group = QGroupBox("MIDI Keyboard")
        keyboard_layout = QVBoxLayout(keyboard_group)

        self.piano = PianoKeyboard()
        self.piano.set_callbacks(self.on_note_on, self.on_note_off)
        keyboard_layout.addWidget(self.piano)

        right_layout.addWidget(keyboard_group)

        # Parameters
        param_group = QGroupBox("Parameters")
        param_layout = QVBoxLayout(param_group)

        self.param_scroll = QScrollArea()
        self.param_scroll.setWidgetResizable(True)
        self.param_widget = QWidget()
        self.param_layout = QVBoxLayout(self.param_widget)
        self.param_scroll.setWidget(self.param_widget)
        param_layout.addWidget(self.param_scroll)

        right_layout.addWidget(param_group)

        # Add panels to splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)  # Left panel
        splitter.setStretchFactor(1, 2)  # Right panel takes more space

        main_layout.addWidget(splitter)

        # Initial plugin scan
        QTimer.singleShot(100, self.scan_plugins)

    def scan_plugins(self):
        """Scan for available VST plugins."""
        self.plugin_list.clear()
        self.status_label.setText("Scanning for plugins...")
        QApplication.processEvents()

        try:
            # Get plugin directories from Carla
            # For now, scan included_plugins
            base_dir = Path(__file__).parent
            plugin_dirs = [
                base_dir / "included_plugins",
                base_dir.parent / "included_plugins",
            ]

            plugins = []
            for plugin_dir in plugin_dirs:
                if plugin_dir.exists():
                    # Find .dll and .vst3 files
                    for pattern in ("**/*.dll", "**/*.vst3"):
                        for plugin_file in plugin_dir.glob(pattern):
                            plugins.append(plugin_file)

            # Add to list
            for plugin_path in sorted(set(plugins)):
                item = QListWidgetItem(plugin_path.stem)
                item.setData(Qt.UserRole, str(plugin_path))
                self.plugin_list.addItem(item)

            self.status_label.setText(f"Found {len(plugins)} plugin(s)")
        except Exception as e:
            QMessageBox.warning(self, "Scan Error", f"Failed to scan plugins:\n{e}")
            self.status_label.setText("Scan failed")

    def on_plugin_selected(self, item):
        """Load selected plugin."""
        plugin_path = Path(item.data(Qt.UserRole))
        self.load_plugin_path(plugin_path)

    def load_plugin_path(self, plugin_path: Path) -> bool:
        """Load a plugin from path."""
        if not plugin_path.exists():
            QMessageBox.warning(self, "Load Error", f"Plugin not found:\n{plugin_path}")
            return False

        try:
            self.host.load_plugin(plugin_path, show_ui=False)
            self.update_status()
            self.update_parameters()
            self.ui_btn.setEnabled(True)
            self.unload_btn.setEnabled(True)

            # Start parameter polling
            self.poll_timer.start(100)

            return True
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load plugin:\n\n{e}")
            return False

    def unload_plugin(self):
        """Unload current plugin."""
        self.poll_timer.stop()
        self.host.unload()
        self.update_status()
        self.clear_parameters()
        self.ui_btn.setEnabled(False)
        self.ui_btn.setText("Show Plugin UI")
        self.unload_btn.setEnabled(False)

    def toggle_ui(self):
        """Toggle plugin native UI."""
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
        """Handle note on from keyboard."""
        try:
            self.host.note_on(note, velocity=0.8)
        except CarlaHostError as e:
            print(f"Note on error: {e}")

    def on_note_off(self, note: int):
        """Handle note off from keyboard."""
        try:
            self.host.note_off(note)
        except CarlaHostError as e:
            print(f"Note off error: {e}")

    def update_status(self):
        """Update status label."""
        status = self.host.status()
        if status["available"]:
            if status.get("plugin"):
                plugin = status["plugin"]
                name = plugin["metadata"]["name"]
                vendor = plugin["metadata"]["vendor"]
                format_type = plugin["metadata"].get("format", "Unknown")
                self.status_label.setText(
                    f"Loaded: {name}\n"
                    f"Vendor: {vendor}\n"
                    f"Format: {format_type}"
                )
            else:
                self.status_label.setText("No plugin loaded")
        else:
            warnings = "\n".join(f"• {w}" for w in status.get("warnings", []))
            self.status_label.setText(f"Carla unavailable:\n{warnings}")

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
            label = QLabel("No parameters available")
            self.param_layout.addWidget(label)
            return

        for param in params:
            param_widget = QWidget()
            param_layout = QVBoxLayout(param_widget)
            param_layout.setContentsMargins(0, 5, 0, 5)

            # Label
            name = param["display_name"] or param["name"]
            units = param["units"]
            value_label = QLabel(f"{name}: {param['value']:.3f} {units}")
            param_layout.addWidget(value_label)

            # Slider
            slider = QSlider(Qt.Horizontal)
            min_val = param["min"]
            max_val = param["max"]

            slider.setMinimum(0)
            slider.setMaximum(1000)
            normalized = (param["value"] - min_val) / (max_val - min_val) if max_val != min_val else 0
            slider.setValue(int(normalized * 1000))

            # Store slider info
            param_id = param["id"]
            self.param_sliders[param_id] = {
                "slider": slider,
                "label": value_label,
                "min": min_val,
                "max": max_val,
                "name": name,
                "units": units
            }

            # Connect slider
            def make_handler(param_id, min_v, max_v, label, name, units):
                def handler(slider_val):
                    if self.updating_from_plugin:
                        return
                    normalized = slider_val / 1000.0
                    actual = min_v + normalized * (max_v - min_v)
                    try:
                        self.host.set_parameter(param_id, actual)
                        label.setText(f"{name}: {actual:.3f} {units}")
                    except CarlaHostError as e:
                        print(f"Parameter update failed: {e}")
                return handler

            slider.valueChanged.connect(make_handler(param_id, min_val, max_val, value_label, name, units))
            param_layout.addWidget(slider)

            self.param_layout.addWidget(param_widget)

        self.param_layout.addStretch()

    def poll_parameters(self):
        """Poll parameter values from plugin."""
        if self.updating_from_plugin:
            return

        try:
            status = self.host.status()
            params = status.get("parameters", [])

            self.updating_from_plugin = True

            for param in params:
                param_id = param["id"]
                value = param["value"]

                if param_id in self.param_sliders:
                    slider_info = self.param_sliders[param_id]
                    slider = slider_info["slider"]
                    label = slider_info["label"]
                    min_val = slider_info["min"]
                    max_val = slider_info["max"]
                    name = slider_info["name"]
                    units = slider_info["units"]

                    # Update slider
                    normalized = (value - min_val) / (max_val - min_val) if max_val != min_val else 0
                    slider_pos = int(normalized * 1000)

                    if abs(slider.value() - slider_pos) > 1:
                        slider.blockSignals(True)
                        slider.setValue(slider_pos)
                        slider.blockSignals(False)
                        label.setText(f"{name}: {value:.3f} {units}")

            self.updating_from_plugin = False
        except Exception:
            self.updating_from_plugin = False

    def closeEvent(self, event):
        """Handle window close."""
        self.poll_timer.stop()
        self.host.shutdown()
        event.accept()


def main():
    parser = argparse.ArgumentParser(description="Ambiance standalone VST host")
    parser.add_argument("--plugin", help="Path to plugin to load on startup")
    parser.add_argument("--driver", action="append", help="Preferred audio driver")
    parser.add_argument("--forced-driver", help="Force specific driver")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("Ambiance")

    window = AmbianceApp(
        preferred_drivers=args.driver if args.driver else None,
        forced_driver=args.forced_driver,
        auto_plugin=Path(args.plugin) if args.plugin else None,
    )
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
