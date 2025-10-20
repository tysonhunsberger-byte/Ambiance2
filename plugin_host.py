"""Standalone VST plugin host using Carla with audio output."""

import argparse
import sys
import numpy as np
import requests
import json
from pathlib import Path
from typing import Sequence
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QPushButton,
    QVBoxLayout, QHBoxLayout, QWidget, QLabel, QSlider, QScrollArea,
    QMessageBox, QComboBox, QGroupBox
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtMultimedia import QAudioOutput, QAudioFormat
from PyQt5.QtCore import QByteArray, QIODevice

sys.path.insert(0, str(Path(__file__).parent / "ambiance" / "src"))

from ambiance.integrations.carla_host import CarlaVSTHost, CarlaHostError


class AudioPlayer:
    """Simple audio output handler using PyQt5 multimedia."""
    
    def __init__(self):
        self.audio_output = None
        self.io_device = None
        self.sample_rate = 44100
        self.setup_audio()
    
    def setup_audio(self):
        """Initialize audio output."""
        fmt = QAudioFormat()
        fmt.setSampleRate(self.sample_rate)
        fmt.setChannelCount(2)  # Stereo
        fmt.setSampleSize(16)
        fmt.setCodec("audio/pcm")
        fmt.setByteOrder(QAudioFormat.LittleEndian)
        fmt.setSampleType(QAudioFormat.SignedInt)
        
        self.audio_output = QAudioOutput(fmt)
        self.audio_output.setVolume(0.7)
    
    def play_buffer(self, samples: np.ndarray):
        """Play a numpy buffer (float32, -1 to 1 range)."""
        if self.audio_output is None:
            return
        
        # Stop any existing playback
        if self.io_device:
            self.audio_output.stop()
        
        # Convert float32 to int16
        samples_int = (samples * 32767).astype(np.int16)
        
        # Ensure stereo
        if len(samples_int.shape) == 1:
            samples_int = np.column_stack([samples_int, samples_int])
        
        # Convert to bytes
        byte_array = QByteArray(samples_int.tobytes())
        
        # Create a buffer
        from PyQt5.QtCore import QBuffer
        buffer = QBuffer()
        buffer.setData(byte_array)
        buffer.open(QIODevice.ReadOnly)
        
        # Play
        self.audio_output.start(buffer)
        
        # Keep reference to prevent garbage collection
        self.io_device = buffer
    
    def stop(self):
        """Stop playback."""
        if self.audio_output:
            self.audio_output.stop()


class PluginHostWindow(QMainWindow):
    def __init__(
        self,
        *,
        preferred_drivers: Sequence[str] | None = None,
        forced_driver: str | None = None,
        auto_plugin: Path | None = None,
        server_url: str | None = None,
    ):
        super().__init__()
        self.preferred_drivers = list(preferred_drivers) if preferred_drivers else [
            "DirectSound",
            "WASAPI",
            "MME",
            "ASIO",
            "Dummy",
        ]
        self.forced_driver = forced_driver
        self.server_url = server_url or "http://127.0.0.1:8000"
        print(f"🌐 External Plugin Host initialized - will sync to {self.server_url}")

        self.host = CarlaVSTHost()
        self.host.configure_audio(
            preferred_drivers=self.preferred_drivers,
            forced_driver=forced_driver,
        )
        self._auto_plugin = Path(auto_plugin) if auto_plugin else None
        if self._auto_plugin:
            print(f"🎵 Auto-loading plugin: {self._auto_plugin}")

        self.audio_player = AudioPlayer()
        self.param_sliders = {}  # Track sliders by parameter ID
        self.updating_from_plugin = False  # Prevent feedback loops
        self.updating_from_server = False  # Prevent sync loops

        # Timer for parameter polling
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.poll_parameters)

        self.init_ui()

        if self._auto_plugin:
            QTimer.singleShot(
                0, lambda: self.load_plugin_path(self._auto_plugin)
            )
        
    def init_ui(self):
        self.setWindowTitle("Ambiance Plugin Host")
        self.setGeometry(100, 100, 600, 700)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # Load section
        load_group = QGroupBox("Plugin Control")
        load_layout = QVBoxLayout(load_group)
        
        self.load_btn = QPushButton("Load VST Plugin")
        self.load_btn.clicked.connect(self.load_plugin)
        load_layout.addWidget(self.load_btn)
        
        self.status_label = QLabel("No plugin loaded")
        self.status_label.setWordWrap(True)
        load_layout.addWidget(self.status_label)
        
        # UI and unload buttons
        btn_row = QHBoxLayout()
        self.ui_btn = QPushButton("Show Plugin UI")
        self.ui_btn.clicked.connect(self.toggle_ui)
        self.ui_btn.setEnabled(False)
        btn_row.addWidget(self.ui_btn)
        
        self.unload_btn = QPushButton("Unload Plugin")
        self.unload_btn.clicked.connect(self.unload_plugin)
        self.unload_btn.setEnabled(False)
        btn_row.addWidget(self.unload_btn)
        load_layout.addLayout(btn_row)
        
        layout.addWidget(load_group)
        
        # Audio test section
        audio_group = QGroupBox("Audio Test")
        audio_layout = QVBoxLayout(audio_group)
        
        test_row = QHBoxLayout()
        
        self.note_combo = QComboBox()
        notes = ['C3', 'C#3', 'D3', 'D#3', 'E3', 'F3', 'F#3', 'G3', 'G#3', 'A3', 'A#3', 'B3',
                 'C4', 'C#4', 'D4', 'D#4', 'E4', 'F4', 'F#4', 'G4', 'G#4', 'A4', 'A#4', 'B4']
        self.note_combo.addItems(notes)
        self.note_combo.setCurrentText('C4')
        test_row.addWidget(QLabel("Note:"))
        test_row.addWidget(self.note_combo)
        
        self.play_note_btn = QPushButton("Play Note")
        self.play_note_btn.clicked.connect(self.play_test_note)
        self.play_note_btn.setEnabled(False)
        test_row.addWidget(self.play_note_btn)
        
        self.render_btn = QPushButton("Render Audio")
        self.render_btn.clicked.connect(self.render_audio)
        self.render_btn.setEnabled(False)
        test_row.addWidget(self.render_btn)
        
        audio_layout.addLayout(test_row)
        layout.addWidget(audio_group)
        
        # Parameters scroll area
        param_group = QGroupBox("Parameters")
        param_layout = QVBoxLayout(param_group)
        
        self.param_scroll = QScrollArea()
        self.param_scroll.setWidgetResizable(True)
        self.param_widget = QWidget()
        self.param_layout = QVBoxLayout(self.param_widget)
        self.param_scroll.setWidget(self.param_widget)
        param_layout.addWidget(self.param_scroll)
        
        layout.addWidget(param_group)
        
        self.update_status()
        
    def load_plugin(self):
        file_dialog = QFileDialog()
        plugin_path, _ = file_dialog.getOpenFileName(
            self,
            "Select VST Plugin",
            str(Path.home()),
            "VST Plugins (*.vst3 *.dll);;All Files (*.*)"
        )
        
        if not plugin_path:
            return
            
        if plugin_path:
            self.load_plugin_path(Path(plugin_path))

    def load_plugin_path(self, plugin_path: Path) -> bool:
        plugin_path = Path(plugin_path).expanduser()
        if not plugin_path.exists():
            QMessageBox.warning(
                self,
                "Load Warning",
                f"Plugin path does not exist:\n{plugin_path}",
            )
            return False

        try:
            self.host.load_plugin(plugin_path, show_ui=False)
            self.update_status()
            self.update_parameters()
            self.ui_btn.setEnabled(True)
            self.unload_btn.setEnabled(True)

            status = self.host.status()
            is_instrument = status.get("capabilities", {}).get("instrument", False)
            self.play_note_btn.setEnabled(is_instrument)
            self.render_btn.setEnabled(True)

            print(f"⏲️  Starting parameter polling timer (100ms interval)")
            self.poll_timer.start(100)

            if status.get("capabilities", {}).get("editor"):
                try:
                    self.host.show_ui()
                    self.ui_btn.setText("Hide Plugin UI")
                except CarlaHostError as e:
                    QMessageBox.warning(self, "UI Warning", f"Plugin UI not available: {e}")

            return True

        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load plugin:\n\n{e}")
            return False
    
    def unload_plugin(self):
        self.poll_timer.stop()
        self.audio_player.stop()
        self.host.unload()
        self.update_status()
        self.clear_parameters()
        self.ui_btn.setEnabled(False)
        self.ui_btn.setText("Show Plugin UI")
        self.unload_btn.setEnabled(False)
        self.play_note_btn.setEnabled(False)
        self.render_btn.setEnabled(False)
    
    def toggle_ui(self):
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
    
    def play_test_note(self):
        """Play a test note through the plugin."""
        note_name = self.note_combo.currentText()
        note_map = {
            'C': 0, 'C#': 1, 'D': 2, 'D#': 3, 'E': 4, 'F': 5,
            'F#': 6, 'G': 7, 'G#': 8, 'A': 9, 'A#': 10, 'B': 11
        }
        
        # Parse note and octave
        if '#' in note_name:
            note = note_name[:2]
            octave = int(note_name[2:])
        else:
            note = note_name[0]
            octave = int(note_name[1:])
        
        midi_note = (octave + 1) * 12 + note_map[note]
        
        try:
            # This requires the Carla backend to support MIDI
            # For now, we'll just show a message
            QMessageBox.information(
                self, 
                "MIDI Note", 
                f"MIDI note {midi_note} ({note_name}) would be played here.\n\n"
                "Full MIDI implementation requires additional Carla integration."
            )
        except Exception as e:
            QMessageBox.warning(self, "Playback Error", str(e))
    
    def render_audio(self):
        """Render audio from the plugin and play it."""
        try:
            # Generate 1 second of audio
            duration = 1.0
            sample_rate = 44100
            
            # For now, show a message since offline rendering needs more work
            QMessageBox.information(
                self,
                "Audio Render",
                "Audio rendering requires additional Carla integration.\n\n"
                "The plugin is loaded and processing audio in real-time through "
                "Carla's engine. Use the native plugin UI to hear and control the sound."
            )
            
        except Exception as e:
            QMessageBox.warning(self, "Render Error", str(e))
    
    def send_parameter_to_server(self, param_id: int, value: float):
        """Send parameter change to the server."""
        try:
            url = f"{self.server_url}/api/vst/parameter"
            payload = {"id": param_id, "value": value}
            print(f"📤 Sending parameter {param_id}={value:.3f} to {url}")
            response = requests.post(url, json=payload, timeout=0.5)
            if response.status_code != 200:
                print(f"❌ Server parameter update failed: {response.status_code}")
            else:
                print(f"✅ Parameter {param_id} synced successfully")
        except Exception as e:
            # Don't block UI on server communication errors
            print(f"❌ Failed to send parameter to server: {e}")

    def poll_parameters(self):
        """Poll parameter values from the plugin to sync with native UI changes."""
        if self.updating_from_plugin:
            return

        try:
            status = self.host.status()
            params = status.get("parameters", [])

            self.updating_from_plugin = True
            changes_detected = 0

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

                    # Update slider position
                    normalized = (value - min_val) / (max_val - min_val) if max_val != min_val else 0
                    slider_pos = int(normalized * 1000)

                    # Only update if significantly different to avoid jitter
                    if abs(slider.value() - slider_pos) > 1:
                        changes_detected += 1
                        slider.blockSignals(True)
                        slider.setValue(slider_pos)
                        slider.blockSignals(False)
                        label.setText(f"{name}: {value:.3f} {units}")

                        # Send updated value to server
                        self.send_parameter_to_server(param_id, value)

            if changes_detected > 0:
                print(f"🔄 Polling detected {changes_detected} parameter changes")

            self.updating_from_plugin = False

        except Exception as e:
            self.updating_from_plugin = False
            print(f"❌ Parameter polling error: {e}")
    
    def update_status(self):
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
                self.status_label.setText("Ready - No plugin loaded")
            
            if status.get("warnings"):
                warnings_text = "\n".join(f"• {w}" for w in status["warnings"])
                self.status_label.setText(
                    self.status_label.text() + f"\n\nWarnings:\n{warnings_text}"
                )
        else:
            self.status_label.setText(
                "Carla backend unavailable:\n" + 
                "\n".join(f"• {w}" for w in status.get("warnings", []))
            )
    
    def clear_parameters(self):
        while self.param_layout.count():
            item = self.param_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.param_sliders.clear()
    
    def update_parameters(self):
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
            
            # Label with name and value
            name = param["display_name"] or param["name"]
            units = param["units"]
            value_label = QLabel(f"{name}: {param['value']:.3f} {units}")
            param_layout.addWidget(value_label)
            
            # Slider
            slider = QSlider(Qt.Horizontal)
            min_val = param["min"]
            max_val = param["max"]
            
            # Scale to int for slider (use 1000 steps)
            slider.setMinimum(0)
            slider.setMaximum(1000)
            normalized = (param["value"] - min_val) / (max_val - min_val) if max_val != min_val else 0
            slider.setValue(int(normalized * 1000))
            
            # Store slider info for polling
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
                    if self.updating_from_plugin or self.updating_from_server:
                        return
                    normalized = slider_val / 1000.0
                    actual = min_v + normalized * (max_v - min_v)
                    try:
                        self.host.set_parameter(param_id, actual)
                        label.setText(f"{name}: {actual:.3f} {units}")

                        # Send parameter change to server
                        self.send_parameter_to_server(param_id, actual)
                    except CarlaHostError as e:
                        print(f"Parameter update failed: {e}")
                return handler
            
            slider.valueChanged.connect(make_handler(param_id, min_val, max_val, value_label, name, units))
            param_layout.addWidget(slider)
            
            self.param_layout.addWidget(param_widget)
        
        self.param_layout.addStretch()
    
    def closeEvent(self, event):
        self.poll_timer.stop()
        self.audio_player.stop()
        self.host.shutdown()
        event.accept()


def main():
    parser = argparse.ArgumentParser(description="Ambiance Carla VST host")
    parser.add_argument(
        "--plugin",
        help="Path to a plugin to load automatically on startup",
    )
    parser.add_argument(
        "--driver",
        action="append",
        help="Preferred audio driver (can be provided multiple times)",
    )
    parser.add_argument(
        "--forced-driver",
        help="Force Carla to use a specific driver (e.g. DirectSound)",
    )
    parser.add_argument(
        "--server",
        default="http://127.0.0.1:8000",
        help="Server URL for parameter sync (default: http://127.0.0.1:8000)",
    )
    args = parser.parse_args()

    preferred = args.driver if args.driver else None
    auto_path = Path(args.plugin).expanduser() if args.plugin else None

    app = QApplication(sys.argv)
    app.setApplicationName("Ambiance Plugin Host")

    window = PluginHostWindow(
        preferred_drivers=preferred,
        forced_driver=args.forced_driver,
        auto_plugin=auto_path,
        server_url=args.server,
    )
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
