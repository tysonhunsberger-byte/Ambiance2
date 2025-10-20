"""Stream mods - Audio effect modules with collapsible UI."""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
    QCheckBox, QComboBox, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal
from typing import Optional, Callable


class CollapsibleMod(QWidget):
    """Collapsible module with header and body."""

    toggled = pyqtSignal(bool)  # Emits when opened/closed

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.is_open = False

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # Header (clickable)
        self.header = QFrame()
        self.header.setObjectName("ModHeader")
        header_layout = QHBoxLayout(self.header)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("ModTitle")
        header_layout.addWidget(self.title_label)

        header_layout.addStretch()

        self.caret = QLabel("▼")
        self.caret.setObjectName("ModCaret")
        header_layout.addWidget(self.caret)

        self.header.mousePressEvent = lambda e: self.toggle()
        self.header.setCursor(Qt.PointingHandCursor)

        self.layout.addWidget(self.header)

        # Body (collapsible)
        self.body = QFrame()
        self.body.setObjectName("ModBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body.hide()

        self.layout.addWidget(self.body)

        self.apply_styles()

    def toggle(self):
        """Toggle open/closed state."""
        self.is_open = not self.is_open
        self.body.setVisible(self.is_open)
        self.caret.setText("▲" if self.is_open else "▼")
        self.toggled.emit(self.is_open)

    def add_widget(self, widget: QWidget):
        """Add widget to the body."""
        self.body_layout.addWidget(widget)

    def add_layout(self, layout):
        """Add layout to the body."""
        self.body_layout.addLayout(layout)

    def apply_styles(self):
        """Apply dark theme styles."""
        self.setStyleSheet("""
            QFrame#ModHeader {
                background-color: #2a2a2a;
                border: 1px solid #555;
                border-radius: 6px 6px 0 0;
                padding: 6px 10px;
            }
            QFrame#ModHeader:hover {
                background-color: #333;
            }
            QLabel#ModTitle {
                font-weight: 700;
                color: #f0f0f0;
            }
            QLabel#ModCaret {
                font-weight: 800;
                color: #f0f0f0;
            }
            QFrame#ModBody {
                background-color: #1a1a1a;
                border: 1px solid #555;
                border-top: none;
                border-radius: 0 0 6px 6px;
                padding: 8px;
            }
        """)


class TimePitchMod(CollapsibleMod):
    """Time & Pitch modification module."""

    tempo_changed = pyqtSignal(float)  # 0.25 - 4.0
    pitch_changed = pyqtSignal(int)    # -24 to +24 semitones
    reverse_changed = pyqtSignal(bool)
    loop_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__("Time & Pitch", parent)

        self.tempo = 1.0
        self.pitch = 0
        self.reverse = False
        self.loop = False

        self.init_controls()

    def init_controls(self):
        """Create tempo, pitch, reverse, loop controls."""

        # Tempo control
        tempo_row = QHBoxLayout()
        tempo_label = QLabel("Tempo")
        tempo_label.setMinimumWidth(60)
        tempo_row.addWidget(tempo_label)

        self.tempo_slider = QSlider(Qt.Horizontal)
        self.tempo_slider.setMinimum(25)  # 0.25x
        self.tempo_slider.setMaximum(400)  # 4.0x
        self.tempo_slider.setValue(100)  # 1.0x
        self.tempo_slider.setTickPosition(QSlider.TicksBelow)
        self.tempo_slider.setTickInterval(25)
        self.tempo_slider.valueChanged.connect(self.on_tempo_changed)
        tempo_row.addWidget(self.tempo_slider)

        self.tempo_value = QLabel("1.00x")
        self.tempo_value.setMinimumWidth(50)
        self.tempo_value.setStyleSheet("color: #bbb; font-size: 12px;")
        tempo_row.addWidget(self.tempo_value)

        self.add_layout(tempo_row)

        # Pitch control
        pitch_row = QHBoxLayout()
        pitch_label = QLabel("Pitch")
        pitch_label.setMinimumWidth(60)
        pitch_row.addWidget(pitch_label)

        self.pitch_slider = QSlider(Qt.Horizontal)
        self.pitch_slider.setMinimum(-24)  # -2 octaves
        self.pitch_slider.setMaximum(24)   # +2 octaves
        self.pitch_slider.setValue(0)
        self.pitch_slider.setTickPosition(QSlider.TicksBelow)
        self.pitch_slider.setTickInterval(12)
        self.pitch_slider.valueChanged.connect(self.on_pitch_changed)
        pitch_row.addWidget(self.pitch_slider)

        self.pitch_value = QLabel("0 st")
        self.pitch_value.setMinimumWidth(50)
        self.pitch_value.setStyleSheet("color: #bbb; font-size: 12px;")
        pitch_row.addWidget(self.pitch_value)

        self.add_layout(pitch_row)

        # Reverse and Loop toggles
        toggle_row = QHBoxLayout()

        self.reverse_check = QCheckBox("Reverse")
        self.reverse_check.stateChanged.connect(self.on_reverse_changed)
        toggle_row.addWidget(self.reverse_check)

        toggle_row.addSpacing(20)

        self.loop_check = QCheckBox("Loop")
        self.loop_check.stateChanged.connect(self.on_loop_changed)
        toggle_row.addWidget(self.loop_check)

        toggle_row.addStretch()

        self.add_layout(toggle_row)

        # Reset button
        reset_row = QHBoxLayout()
        reset_row.addStretch()
        reset_btn = QPushButton("Reset to Default")
        reset_btn.clicked.connect(self.reset)
        reset_btn.setStyleSheet("""
            QPushButton {
                padding: 4px 10px;
                background-color: #2a2a2a;
                border: 1px solid #666;
                border-radius: 4px;
                color: #fff;
            }
            QPushButton:hover {
                background-color: #333;
            }
        """)
        reset_row.addWidget(reset_btn)
        self.add_layout(reset_row)

    def on_tempo_changed(self, value: int):
        """Handle tempo slider change."""
        self.tempo = value / 100.0
        self.tempo_value.setText(f"{self.tempo:.2f}x")
        self.tempo_changed.emit(self.tempo)

    def on_pitch_changed(self, value: int):
        """Handle pitch slider change."""
        self.pitch = value
        self.pitch_value.setText(f"{value:+d} st")
        self.pitch_changed.emit(self.pitch)

    def on_reverse_changed(self, state: int):
        """Handle reverse checkbox change."""
        self.reverse = state == Qt.Checked
        self.reverse_changed.emit(self.reverse)

    def on_loop_changed(self, state: int):
        """Handle loop checkbox change."""
        self.loop = state == Qt.Checked
        self.loop_changed.emit(self.loop)

    def reset(self):
        """Reset all values to default."""
        self.tempo_slider.setValue(100)
        self.pitch_slider.setValue(0)
        self.reverse_check.setChecked(False)
        self.loop_check.setChecked(False)

    def get_state(self):
        """Get current state as dict."""
        return {
            'tempo': self.tempo,
            'pitch': self.pitch,
            'reverse': self.reverse,
            'loop': self.loop
        }

    def set_state(self, state: dict):
        """Restore state from dict."""
        if 'tempo' in state:
            self.tempo_slider.setValue(int(state['tempo'] * 100))
        if 'pitch' in state:
            self.pitch_slider.setValue(state['pitch'])
        if 'reverse' in state:
            self.reverse_check.setChecked(state['reverse'])
        if 'loop' in state:
            self.loop_check.setChecked(state['loop'])


class StreamModsContainer(QWidget):
    """Container for all stream mods."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(14)

        # Time & Pitch mod
        self.time_pitch = TimePitchMod()
        self.layout.addWidget(self.time_pitch)

        # Placeholder for future mods
        self.layout.addStretch()

        self.setStyleSheet("""
            QWidget {
                background-color: transparent;
            }
        """)

    def get_state(self):
        """Get state of all mods."""
        return {
            'time_pitch': self.time_pitch.get_state()
        }

    def set_state(self, state: dict):
        """Restore state of all mods."""
        if 'time_pitch' in state:
            self.time_pitch.set_state(state['time_pitch'])
