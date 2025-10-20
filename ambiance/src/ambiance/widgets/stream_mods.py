"""Stream mods - Audio effect modules with collapsible UI."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

DEFAULT_THEME = {
    "bg": "#10141d",
    "panel": "#19202b",
    "card": "#202835",
    "text": "#f4f6fb",
    "muted": "#aeb7c9",
    "accent": "#4da3ff",
    "border": "#2f3b4c",
}


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    r = int(value[0:2], 16)
    g = int(value[2:4], 16)
    b = int(value[4:6], 16)
    return r, g, b


def _blend(color_a: str, color_b: str, ratio: float) -> str:
    ratio = max(0.0, min(1.0, ratio))
    ar, ag, ab = _hex_to_rgb(color_a)
    br, bg, bb = _hex_to_rgb(color_b)
    r = int(ar * ratio + br * (1.0 - ratio))
    g = int(ag * ratio + bg * (1.0 - ratio))
    b = int(ab * ratio + bb * (1.0 - ratio))
    return f"#{r:02x}{g:02x}{b:02x}"


def _mix_with_white(color: str, amount: float) -> str:
    return _blend("#ffffff", color, 1.0 - max(0.0, min(1.0, amount)))


class CollapsibleMod(QWidget):
    """Collapsible module with a themed toggle header."""

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("CollapsibleMod")

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(6)

        self.toggle_button = QToolButton()
        self.toggle_button.setObjectName("ModToggle")
        self.toggle_button.setText(title)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.RightArrow)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(False)
        self.toggle_button.toggled.connect(self._on_toggled)
        self.layout.addWidget(self.toggle_button)

        self.body = QFrame()
        self.body.setObjectName("ModBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(18, 16, 18, 18)
        self.body_layout.setSpacing(10)
        self.body.setVisible(False)
        self.layout.addWidget(self.body)

    # ------------------------------------------------------------------
    def _on_toggled(self, checked: bool) -> None:
        self.body.setVisible(checked)
        self.toggle_button.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self.toggled.emit(checked)

    def set_expanded(self, expanded: bool) -> None:
        self.toggle_button.blockSignals(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.blockSignals(False)
        self._on_toggled(expanded)

    def add_widget(self, widget: QWidget) -> None:
        self.body_layout.addWidget(widget)

    def add_layout(self, layout: QHBoxLayout | QVBoxLayout) -> None:
        self.body_layout.addLayout(layout)


class TimePitchMod(CollapsibleMod):
    """Time & Pitch modification module."""

    tempo_changed = pyqtSignal(float)
    pitch_changed = pyqtSignal(int)
    reverse_a_changed = pyqtSignal(bool)
    reverse_b_changed = pyqtSignal(bool)
    loop_changed = pyqtSignal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Time & Pitch", parent)

        self.tempo = 1.0
        self.pitch = 0
        self.reverse_a = False
        self.reverse_b = False
        self.loop = False

        self._build_ui()
        self.set_expanded(True)

    def _build_ui(self) -> None:
        tempo_row = QHBoxLayout()
        tempo_label = QLabel("Tempo")
        tempo_label.setMinimumWidth(60)
        tempo_row.addWidget(tempo_label)

        self.tempo_slider = QSlider(Qt.Horizontal)
        self.tempo_slider.setRange(25, 400)  # Represents 0.25x - 4.0x
        self.tempo_slider.setValue(100)
        self.tempo_slider.valueChanged.connect(self._on_tempo_changed)
        tempo_row.addWidget(self.tempo_slider, 1)

        self.tempo_value = QLabel("1.00x")
        self.tempo_value.setMinimumWidth(60)
        tempo_row.addWidget(self.tempo_value)
        self.add_layout(tempo_row)

        pitch_row = QHBoxLayout()
        pitch_label = QLabel("Pitch")
        pitch_label.setMinimumWidth(60)
        pitch_row.addWidget(pitch_label)

        self.pitch_slider = QSlider(Qt.Horizontal)
        self.pitch_slider.setRange(-24, 24)
        self.pitch_slider.setValue(0)
        self.pitch_slider.valueChanged.connect(self._on_pitch_changed)
        pitch_row.addWidget(self.pitch_slider, 1)

        self.pitch_value = QLabel("0 st")
        self.pitch_value.setMinimumWidth(60)
        pitch_row.addWidget(self.pitch_value)
        self.add_layout(pitch_row)

        toggle_row = QHBoxLayout()
        self.reverse_a_check = QCheckBox("Reverse A")
        self.reverse_a_check.stateChanged.connect(
            lambda state: self.reverse_a_changed.emit(state == Qt.Checked)
        )
        toggle_row.addWidget(self.reverse_a_check)

        self.reverse_b_check = QCheckBox("Reverse B")
        self.reverse_b_check.stateChanged.connect(
            lambda state: self.reverse_b_changed.emit(state == Qt.Checked)
        )
        toggle_row.addWidget(self.reverse_b_check)

        self.loop_check = QCheckBox("Loop")
        self.loop_check.stateChanged.connect(
            lambda state: self.loop_changed.emit(state == Qt.Checked)
        )
        toggle_row.addWidget(self.loop_check)
        toggle_row.addStretch()
        self.add_layout(toggle_row)

    def _on_tempo_changed(self, value: int) -> None:
        self.tempo = value / 100.0
        self.tempo_value.setText(f"{self.tempo:.2f}x")
        self.tempo_changed.emit(self.tempo)

    def _on_pitch_changed(self, value: int) -> None:
        self.pitch = value
        self.pitch_value.setText(f"{value:+d} st")
        self.pitch_changed.emit(value)

    def get_state(self) -> Dict[str, object]:
        return {
            "tempo": self.tempo,
            "pitch": self.pitch,
            "reverse_a": self.reverse_a_check.isChecked(),
            "reverse_b": self.reverse_b_check.isChecked(),
            "loop": self.loop_check.isChecked(),
        }

    def set_state(self, state: Dict[str, object]) -> None:
        if not state:
            return
        if "tempo" in state:
            value = max(0.25, min(4.0, float(state["tempo"])))
            self.tempo = value
            self.tempo_slider.blockSignals(True)
            self.tempo_slider.setValue(int(value * 100))
            self.tempo_slider.blockSignals(False)
            self.tempo_value.setText(f"{value:.2f}x")
        if "pitch" in state:
            pitch = int(state["pitch"])
            self.pitch = pitch
            self.pitch_slider.blockSignals(True)
            self.pitch_slider.setValue(pitch)
            self.pitch_slider.blockSignals(False)
            self.pitch_value.setText(f"{pitch:+d} st")
        if "reverse_a" in state:
            self.reverse_a_check.blockSignals(True)
            self.reverse_a_check.setChecked(bool(state["reverse_a"]))
            self.reverse_a_check.blockSignals(False)
        if "reverse_b" in state:
            self.reverse_b_check.blockSignals(True)
            self.reverse_b_check.setChecked(bool(state["reverse_b"]))
            self.reverse_b_check.blockSignals(False)
        if "loop" in state:
            self.loop_check.blockSignals(True)
            self.loop_check.setChecked(bool(state["loop"]))
            self.loop_check.blockSignals(False)


class MuffleMod(CollapsibleMod):
    """Low-pass filter control."""

    enabled_changed = pyqtSignal(bool)
    amount_changed = pyqtSignal(float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Muffle", parent)
        self._build_ui()

    def _build_ui(self) -> None:
        row = QHBoxLayout()
        self.toggle_btn = QPushButton("Muffle: OFF")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.toggled.connect(self._on_toggled)
        row.addWidget(self.toggle_btn)

        row.addWidget(QLabel("Amount"))
        self.amount_slider = QSlider(Qt.Horizontal)
        self.amount_slider.setRange(0, 100)
        self.amount_slider.setValue(100)
        self.amount_slider.valueChanged.connect(self._on_amount_changed)
        row.addWidget(self.amount_slider, 1)

        self.freq_label = QLabel("Cutoff: 20,000 Hz")
        row.addWidget(self.freq_label)
        self.add_layout(row)

    def _on_toggled(self, checked: bool) -> None:
        self.toggle_btn.setText(f"Muffle: {'ON' if checked else 'OFF'}")
        if checked:
            self.set_expanded(True)
        self.enabled_changed.emit(checked)

    def _on_amount_changed(self, value: int) -> None:
        amount = value / 100.0
        freq = 200 + (20000 - 200) * amount * amount
        self.freq_label.setText(f"Cutoff: {int(freq):,} Hz")
        self.amount_changed.emit(amount)

    def set_state(self, state: Dict[str, object]) -> None:
        if not state:
            return
        if "enabled" in state:
            enabled = bool(state["enabled"])
            self.toggle_btn.blockSignals(True)
            self.toggle_btn.setChecked(enabled)
            self.toggle_btn.blockSignals(False)
            self.toggle_btn.setText(f"Muffle: {'ON' if enabled else 'OFF'}")
        if "amount" in state:
            value = max(0.0, min(1.0, float(state["amount"])) )
            self.amount_slider.blockSignals(True)
            self.amount_slider.setValue(int(value * 100))
            self.amount_slider.blockSignals(False)
            freq = 200 + (20000 - 200) * value * value
            self.freq_label.setText(f"Cutoff: {int(freq):,} Hz")


class ToneMod(CollapsibleMod):
    """Binaural tone generator controls."""

    enabled_changed = pyqtSignal(bool)
    wave_changed = pyqtSignal(str)
    base_changed = pyqtSignal(float)
    beat_changed = pyqtSignal(float)
    level_changed = pyqtSignal(float)

    PRESET_MAP: Dict[str, float] = {
        "custom": None,
        "schumann": 7.83,
        "delta": 2.0,
        "theta": 6.0,
        "alpha": 10.0,
        "beta": 20.0,
        "gamma": 40.0,
    }

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Tone", parent)
        self._build_ui()

    def _build_ui(self) -> None:
        top_row = QHBoxLayout()
        self.toggle_btn = QPushButton("Tone: OFF")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.toggled.connect(self._on_toggle)
        top_row.addWidget(self.toggle_btn)

        top_row.addWidget(QLabel("Wave"))
        self.wave_combo = QComboBox()
        self.wave_combo.addItems(["sine", "square", "triangle", "sawtooth"])
        self.wave_combo.currentTextChanged.connect(self.wave_changed.emit)
        top_row.addWidget(self.wave_combo)

        top_row.addWidget(QLabel("Preset"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(self.PRESET_MAP.keys()))
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        top_row.addWidget(self.preset_combo)
        self.add_layout(top_row)

        bottom_row = QHBoxLayout()
        bottom_row.addWidget(QLabel("Base"))
        self.base_spin = QDoubleSpinBox()
        self.base_spin.setRange(20.0, 2000.0)
        self.base_spin.setDecimals(1)
        self.base_spin.setValue(200.0)
        self.base_spin.valueChanged.connect(self._on_base_changed)
        bottom_row.addWidget(self.base_spin)

        bottom_row.addWidget(QLabel("Beat"))
        self.beat_spin = QDoubleSpinBox()
        self.beat_spin.setRange(0.0, 45.0)
        self.beat_spin.setDecimals(2)
        self.beat_spin.setValue(10.0)
        self.beat_spin.valueChanged.connect(self._on_beat_changed)
        bottom_row.addWidget(self.beat_spin)

        bottom_row.addWidget(QLabel("Level"))
        self.level_slider = QSlider(Qt.Horizontal)
        self.level_slider.setRange(0, 100)
        self.level_slider.setValue(35)
        self.level_slider.valueChanged.connect(self._on_level_changed)
        bottom_row.addWidget(self.level_slider, 1)

        self.summary_label = QLabel("L 195.0 Hz / R 205.0 Hz")
        bottom_row.addWidget(self.summary_label)
        self.add_layout(bottom_row)
        self._update_summary()

    def _on_toggle(self, checked: bool) -> None:
        self._update_toggle_text(checked)
        if checked:
            self.set_expanded(True)
        self.enabled_changed.emit(checked)

    def _on_preset_changed(self, preset: str) -> None:
        value = self.PRESET_MAP.get(preset)
        if value is not None:
            self.beat_spin.blockSignals(True)
            self.beat_spin.setValue(value)
            self.beat_spin.blockSignals(False)
            self._on_beat_changed(value)
        self.wave_changed.emit(self.wave_combo.currentText())

    def _on_base_changed(self, value: float) -> None:
        self._update_summary()
        self.base_changed.emit(float(value))

    def _on_beat_changed(self, value: float) -> None:
        self._update_summary()
        self.beat_changed.emit(float(value))

    def _on_level_changed(self, value: int) -> None:
        self.level_changed.emit(value / 100.0)

    def _update_toggle_text(self, checked: bool) -> None:
        self.toggle_btn.setText(f"Tone: {'ON' if checked else 'OFF'}")

    def _update_summary(self) -> None:
        base = self.base_spin.value()
        beat = self.beat_spin.value()
        left = base - beat / 2.0
        right = base + beat / 2.0
        self.summary_label.setText(f"L {left:.1f} Hz / R {right:.1f} Hz")

    def set_state(self, state: Dict[str, object]) -> None:
        if not state:
            return
        if "enabled" in state:
            self.toggle_btn.blockSignals(True)
            self.toggle_btn.setChecked(bool(state["enabled"]))
            self.toggle_btn.blockSignals(False)
            self._update_toggle_text(bool(state["enabled"]))
        if "wave" in state:
            wave = str(state["wave"])
            index = self.wave_combo.findText(wave)
            if index >= 0:
                self.wave_combo.blockSignals(True)
                self.wave_combo.setCurrentIndex(index)
                self.wave_combo.blockSignals(False)
        if "base" in state:
            value = float(state["base"])
            self.base_spin.blockSignals(True)
            self.base_spin.setValue(value)
            self.base_spin.blockSignals(False)
            self._update_summary()
        if "beat" in state:
            value = float(state["beat"])
            self.beat_spin.blockSignals(True)
            self.beat_spin.setValue(value)
            self.beat_spin.blockSignals(False)
            self._update_summary()
        if "level" in state:
            value = max(0.0, min(1.0, float(state["level"])) )
            self.level_slider.blockSignals(True)
            self.level_slider.setValue(int(value * 100))
            self.level_slider.blockSignals(False)


class NoiseMod(CollapsibleMod):
    """Noise generator controls."""

    enabled_changed = pyqtSignal(bool)
    type_changed = pyqtSignal(str)
    level_changed = pyqtSignal(float)
    tilt_changed = pyqtSignal(float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Noise", parent)
        self._build_ui()

    def _build_ui(self) -> None:
        row = QHBoxLayout()
        self.toggle_btn = QPushButton("Noise: OFF")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.toggled.connect(self._on_toggle)
        row.addWidget(self.toggle_btn)

        row.addWidget(QLabel("Type"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["white", "pink", "brown"])
        self.type_combo.currentTextChanged.connect(self.type_changed.emit)
        row.addWidget(self.type_combo)

        row.addWidget(QLabel("Level"))
        self.level_slider = QSlider(Qt.Horizontal)
        self.level_slider.setRange(0, 100)
        self.level_slider.setValue(30)
        self.level_slider.valueChanged.connect(
            lambda value: self.level_changed.emit(value / 100.0)
        )
        row.addWidget(self.level_slider, 1)

        row.addWidget(QLabel("Tilt"))
        self.tilt_slider = QSlider(Qt.Horizontal)
        self.tilt_slider.setRange(-100, 100)
        self.tilt_slider.setValue(0)
        self.tilt_slider.valueChanged.connect(
            lambda value: self.tilt_changed.emit(value / 100.0)
        )
        row.addWidget(self.tilt_slider, 1)
        self.add_layout(row)

    def _on_toggle(self, checked: bool) -> None:
        self._update_toggle_text(checked)
        if checked:
            self.set_expanded(True)
        self.enabled_changed.emit(checked)

    def _update_toggle_text(self, checked: bool) -> None:
        self.toggle_btn.setText(f"Noise: {'ON' if checked else 'OFF'}")

    def set_state(self, state: Dict[str, object]) -> None:
        if not state:
            return
        if "enabled" in state:
            self.toggle_btn.blockSignals(True)
            self.toggle_btn.setChecked(bool(state["enabled"]))
            self.toggle_btn.blockSignals(False)
            self._update_toggle_text(bool(state["enabled"]))
        if "type" in state:
            index = self.type_combo.findText(str(state["type"]))
            if index >= 0:
                self.type_combo.blockSignals(True)
                self.type_combo.setCurrentIndex(index)
                self.type_combo.blockSignals(False)
        if "level" in state:
            value = max(0.0, min(1.0, float(state["level"])) )
            self.level_slider.blockSignals(True)
            self.level_slider.setValue(int(value * 100))
            self.level_slider.blockSignals(False)
        if "tilt" in state:
            value = max(-1.0, min(1.0, float(state["tilt"])) )
            self.tilt_slider.blockSignals(True)
            self.tilt_slider.setValue(int(value * 100))
            self.tilt_slider.blockSignals(False)


class EQMod(CollapsibleMod):
    """Three band equaliser."""

    low_changed = pyqtSignal(float)
    mid_changed = pyqtSignal(float)
    high_changed = pyqtSignal(float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("EQ", parent)
        self._build_ui()

    def _build_ui(self) -> None:
        row = QHBoxLayout()
        self.low_slider, self.low_value = self._add_band(row, "Low", self.low_changed.emit)
        self.mid_slider, self.mid_value = self._add_band(row, "Mid", self.mid_changed.emit)
        self.high_slider, self.high_value = self._add_band(row, "High", self.high_changed.emit)
        self.add_layout(row)

    def _add_band(self, layout: QHBoxLayout, label: str, callback) -> tuple[QSlider, QLabel]:
        layout.addWidget(QLabel(label))
        slider = QSlider(Qt.Horizontal)
        slider.setRange(-120, 120)  # -12dB to +12dB in 0.1 increments
        slider.setValue(0)
        slider.valueChanged.connect(lambda value: self._on_band_changed(value, callback))
        layout.addWidget(slider, 1)
        value_label = QLabel("0.0 dB")
        layout.addWidget(value_label)
        return slider, value_label

    def _on_band_changed(self, value: int, callback) -> None:
        db = value / 10.0
        callback(db)
        sender = self.sender()
        if sender is self.low_slider:
            self.low_value.setText(f"{db:+.1f} dB")
        elif sender is self.mid_slider:
            self.mid_value.setText(f"{db:+.1f} dB")
        elif sender is self.high_slider:
            self.high_value.setText(f"{db:+.1f} dB")

    def set_state(self, state: Dict[str, object]) -> None:
        if not state:
            return
        if "low" in state:
            value = float(state["low"]) * 10
            self.low_slider.blockSignals(True)
            self.low_slider.setValue(int(value))
            self.low_slider.blockSignals(False)
            self.low_value.setText(f"{float(state['low']):+.1f} dB")
        if "mid" in state:
            value = float(state["mid"]) * 10
            self.mid_slider.blockSignals(True)
            self.mid_slider.setValue(int(value))
            self.mid_slider.blockSignals(False)
            self.mid_value.setText(f"{float(state['mid']):+.1f} dB")
        if "high" in state:
            value = float(state["high"]) * 10
            self.high_slider.blockSignals(True)
            self.high_slider.setValue(int(value))
            self.high_slider.blockSignals(False)
            self.high_value.setText(f"{float(state['high']):+.1f} dB")


class FXMod(CollapsibleMod):
    """Delay / distortion FX chain."""

    mix_changed = pyqtSignal(float)
    delay_changed = pyqtSignal(float)
    feedback_changed = pyqtSignal(float)
    dist_changed = pyqtSignal(float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("FX Chain", parent)
        self._build_ui()

    def _build_ui(self) -> None:
        row = QHBoxLayout()
        self.mix_slider, self.mix_value = self._add_slider(row, "FX Mix", 0, 100, self._on_mix_changed)
        self.delay_slider, self.delay_value = self._add_slider(row, "Delay", 0, 100, self._on_delay_changed)
        self.feedback_slider, self.feedback_value = self._add_slider(row, "Feedback", 0, 95, self._on_feedback_changed)
        self.dist_slider, self.dist_value = self._add_slider(row, "Dist", 0, 100, self._on_dist_changed)
        self.add_layout(row)

    def _add_slider(self, layout: QHBoxLayout, label: str, minimum: int, maximum: int, callback):
        layout.addWidget(QLabel(label))
        slider = QSlider(Qt.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(minimum)
        slider.valueChanged.connect(callback)
        layout.addWidget(slider, 1)
        value_label = QLabel("0")
        layout.addWidget(value_label)
        return slider, value_label

    def _on_mix_changed(self, value: int) -> None:
        self.mix_value.setText(f"{value}%")
        self.mix_changed.emit(value / 100.0)

    def _on_delay_changed(self, value: int) -> None:
        seconds = value / 100.0
        self.delay_value.setText(f"{seconds:.2f}s")
        self.delay_changed.emit(seconds)

    def _on_feedback_changed(self, value: int) -> None:
        self.feedback_value.setText(f"{value}%")
        self.feedback_changed.emit(value / 100.0)

    def _on_dist_changed(self, value: int) -> None:
        self.dist_value.setText(f"{value}%")
        self.dist_changed.emit(value / 100.0)

    def set_state(self, state: Dict[str, object]) -> None:
        if not state:
            return
        if "mix" in state:
            value = max(0.0, min(1.0, float(state["mix"])) )
            self.mix_slider.blockSignals(True)
            self.mix_slider.setValue(int(value * 100))
            self.mix_slider.blockSignals(False)
            self.mix_value.setText(f"{int(value * 100)}%")
        if "delay" in state:
            value = max(0.0, min(1.0, float(state["delay"])) )
            self.delay_slider.blockSignals(True)
            self.delay_slider.setValue(int(value * 100))
            self.delay_slider.blockSignals(False)
            self.delay_value.setText(f"{value:.2f}s")
        if "feedback" in state:
            value = max(0.0, min(0.95, float(state["feedback"])) )
            self.feedback_slider.blockSignals(True)
            self.feedback_slider.setValue(int(value * 100))
            self.feedback_slider.blockSignals(False)
            self.feedback_value.setText(f"{int(value * 100)}%")
        if "dist" in state:
            value = max(0.0, min(1.0, float(state["dist"])) )
            self.dist_slider.blockSignals(True)
            self.dist_slider.setValue(int(value * 100))
            self.dist_slider.blockSignals(False)
            self.dist_value.setText(f"{int(value * 100)}%")


class SpaceMod(CollapsibleMod):
    """Reverb / space controls."""

    preset_changed = pyqtSignal(str)
    mix_changed = pyqtSignal(float)
    decay_changed = pyqtSignal(float)
    predelay_changed = pyqtSignal(float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Spaces", parent)
        self._build_ui()

    def _build_ui(self) -> None:
        row = QHBoxLayout()
        row.addWidget(QLabel("Preset"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["none", "hall", "studio", "cabin"])
        self.preset_combo.currentTextChanged.connect(self.preset_changed.emit)
        row.addWidget(self.preset_combo)

        row.addWidget(QLabel("Mix"))
        self.mix_slider = QSlider(Qt.Horizontal)
        self.mix_slider.setRange(0, 100)
        self.mix_slider.setValue(0)
        self.mix_slider.valueChanged.connect(
            lambda value: self.mix_changed.emit(value / 100.0)
        )
        row.addWidget(self.mix_slider, 1)
        self.mix_value = QLabel("0%")
        row.addWidget(self.mix_value)

        row.addWidget(QLabel("Decay"))
        self.decay_slider = QSlider(Qt.Horizontal)
        self.decay_slider.setRange(20, 600)  # 0.20s - 6.00s
        self.decay_slider.setValue(120)
        self.decay_slider.valueChanged.connect(self._on_decay_changed)
        row.addWidget(self.decay_slider, 1)
        self.decay_value = QLabel("1.20s")
        row.addWidget(self.decay_value)

        row.addWidget(QLabel("Pre"))
        self.pre_slider = QSlider(Qt.Horizontal)
        self.pre_slider.setRange(0, 250)  # 0 - 0.25s
        self.pre_slider.setValue(0)
        self.pre_slider.valueChanged.connect(self._on_pre_changed)
        row.addWidget(self.pre_slider, 1)
        self.pre_value = QLabel("0.00s")
        row.addWidget(self.pre_value)
        self.add_layout(row)

    def _on_decay_changed(self, value: int) -> None:
        seconds = value / 100.0
        self.decay_value.setText(f"{seconds:.2f}s")
        self.decay_changed.emit(seconds)

    def _on_pre_changed(self, value: int) -> None:
        seconds = value / 1000.0
        self.pre_value.setText(f"{seconds:.2f}s")
        self.predelay_changed.emit(seconds)

    def set_state(self, state: Dict[str, object]) -> None:
        if not state:
            return
        if "preset" in state:
            preset = str(state["preset"]) or "none"
            index = self.preset_combo.findText(preset)
            if index >= 0:
                self.preset_combo.blockSignals(True)
                self.preset_combo.setCurrentIndex(index)
                self.preset_combo.blockSignals(False)
        if "mix" in state:
            value = max(0.0, min(1.0, float(state["mix"])) )
            self.mix_slider.blockSignals(True)
            self.mix_slider.setValue(int(value * 100))
            self.mix_slider.blockSignals(False)
            self.mix_value.setText(f"{int(value * 100)}%")
        if "decay" in state:
            value = max(0.2, min(6.0, float(state["decay"])) )
            slider_value = int(value * 100)
            self.decay_slider.blockSignals(True)
            self.decay_slider.setValue(slider_value)
            self.decay_slider.blockSignals(False)
            self.decay_value.setText(f"{value:.2f}s")
        if "pre" in state:
            value = max(0.0, min(0.25, float(state["pre"])) )
            slider_value = int(value * 1000)
            self.pre_slider.blockSignals(True)
            self.pre_slider.setValue(slider_value)
            self.pre_slider.blockSignals(False)
            self.pre_value.setText(f"{value:.2f}s")


@dataclass
class StreamModState:
    """Represents state bundle for all stream mods."""

    time_pitch: Dict[str, object]
    muffle: Dict[str, object]
    tone: Dict[str, object]
    noise: Dict[str, object]
    eq: Dict[str, object]
    fx: Dict[str, object]
    space: Dict[str, object]


class StreamModsContainer(QWidget):
    """Container for all stream mods."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("StreamModsContainer")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(12)

        self.time_pitch = TimePitchMod()
        self.muffle = MuffleMod()
        self.tone = ToneMod()
        self.noise = NoiseMod()
        self.eq = EQMod()
        self.fx = FXMod()
        self.space = SpaceMod()

        self._mods = [
            self.time_pitch,
            self.muffle,
            self.tone,
            self.noise,
            self.eq,
            self.fx,
            self.space,
        ]

        for mod in self._mods:
            self.layout.addWidget(mod)

        self.layout.addStretch()

        self._theme_colors = dict(DEFAULT_THEME)
        self._dark_mode = True
        self.apply_theme(self._theme_colors, dark=self._dark_mode)

    def apply_theme(self, colors: Dict[str, str], *, dark: bool = True) -> None:
        self._theme_colors = dict(colors)
        self._dark_mode = dark

        panel = colors.get("panel", DEFAULT_THEME["panel"])
        card = colors.get("card", DEFAULT_THEME["card"])
        text = colors.get("text", DEFAULT_THEME["text"])
        accent = colors.get("accent", DEFAULT_THEME["accent"])
        border = colors.get("border", DEFAULT_THEME["border"])
        header_bg = _blend(card, panel, 0.6)
        header_hover = _blend(accent, header_bg, 0.22)
        header_checked = _blend(header_hover, accent, 0.33)
        header_text = text if dark else "#101010"
        body_bg = _blend(card, panel, 0.45)
        body_border = _blend(border, body_bg, 0.65)
        button_bg = _blend(body_bg, accent, 0.18)
        button_hover = _blend(body_bg, accent, 0.32)
        button_checked = _blend(accent, body_bg, 0.55)
        button_checked_text = text if dark else "#000000"
        combo_bg = _mix_with_white(body_bg, 0.22 if dark else 0.18)
        combo_border = _blend(border, accent, 0.3)
        combo_text = "#101010" if dark else "#000000"
        slider_track = _blend(panel, card, 0.38)
        slider_handle = _blend(accent, "#ffffff", 0.45)
        slider_fill = accent
        style = f"""
            QWidget#StreamModsContainer {{
                background-color: transparent;
            }}
            QWidget#StreamModsContainer QToolButton#ModToggle {{
                background-color: {header_bg};
                border: 1px solid {_blend(border, header_bg, 0.65)};
                border-radius: 10px;
                padding: 6px 12px;
                font-weight: 600;
                color: {header_text};
                text-align: left;
            }}
            QWidget#StreamModsContainer QToolButton#ModToggle:hover {{
                background-color: {header_hover};
            }}
            QWidget#StreamModsContainer QToolButton#ModToggle:checked {{
                background-color: {header_checked};
                color: {header_text};
            }}
            QWidget#StreamModsContainer QFrame#ModBody {{
                background-color: {body_bg};
                border: 1px solid {body_border};
                border-radius: 12px;
            }}
            QWidget#StreamModsContainer QFrame#ModBody QLabel,
            QWidget#StreamModsContainer QFrame#ModBody QCheckBox {{
                color: {text};
            }}
            QWidget#StreamModsContainer QFrame#ModBody QPushButton {{
                background-color: {button_bg};
                color: {text};
                border: 1px solid {_blend(border, button_bg, 0.6)};
                border-radius: 8px;
                padding: 4px 10px;
            }}
            QWidget#StreamModsContainer QFrame#ModBody QPushButton:hover {{
                background-color: {button_hover};
            }}
            QWidget#StreamModsContainer QFrame#ModBody QPushButton:checked {{
                background-color: {button_checked};
                color: {button_checked_text};
                border-color: {_blend(accent, button_bg, 0.4)};
            }}
            QWidget#StreamModsContainer QFrame#ModBody QComboBox,
            QWidget#StreamModsContainer QFrame#ModBody QDoubleSpinBox {{
                background-color: {combo_bg};
                color: {combo_text};
                border: 1px solid {combo_border};
                border-radius: 8px;
                padding: 4px 10px;
            }}
            QWidget#StreamModsContainer QFrame#ModBody QComboBox QAbstractItemView {{
                background-color: {_mix_with_white(combo_bg, 0.18 if dark else 0.25)};
                color: {combo_text};
            }}
            QWidget#StreamModsContainer QFrame#ModBody QSlider::groove:horizontal {{
                height: 8px;
                background: {slider_track};
                border-radius: 4px;
            }}
            QWidget#StreamModsContainer QFrame#ModBody QSlider::handle:horizontal {{
                background: {slider_handle};
                border: 1px solid {_blend(accent, '#000000', 0.55)};
                width: 18px;
                margin: -6px 0;
                border-radius: 9px;
            }}
            QWidget#StreamModsContainer QFrame#ModBody QSlider::sub-page:horizontal {{
                background: {slider_fill};
                border-radius: 3px;
            }}
        """

        self.setStyleSheet(style)

    def get_state(self) -> StreamModState:
        return StreamModState(
            time_pitch=self.time_pitch.get_state(),
            muffle={
                "enabled": self.muffle.toggle_btn.isChecked(),
                "amount": self.muffle.amount_slider.value() / 100.0,
            },
            tone={
                "enabled": self.tone.toggle_btn.isChecked(),
                "wave": self.tone.wave_combo.currentText(),
                "base": self.tone.base_spin.value(),
                "beat": self.tone.beat_spin.value(),
                "level": self.tone.level_slider.value() / 100.0,
            },
            noise={
                "enabled": self.noise.toggle_btn.isChecked(),
                "type": self.noise.type_combo.currentText(),
                "level": self.noise.level_slider.value() / 100.0,
                "tilt": self.noise.tilt_slider.value() / 100.0,
            },
            eq={
                "low": self.eq.low_slider.value() / 10.0,
                "mid": self.eq.mid_slider.value() / 10.0,
                "high": self.eq.high_slider.value() / 10.0,
            },
            fx={
                "mix": self.fx.mix_slider.value() / 100.0,
                "delay": self.fx.delay_slider.value() / 100.0,
                "feedback": self.fx.feedback_slider.value() / 100.0,
                "dist": self.fx.dist_slider.value() / 100.0,
            },
            space={
                "preset": self.space.preset_combo.currentText(),
                "mix": self.space.mix_slider.value() / 100.0,
                "decay": self.space.decay_slider.value() / 100.0,
                "pre": self.space.pre_slider.value() / 1000.0,
            },
        )

    def set_state(self, state: Optional[Dict[str, Dict[str, object]]]) -> None:
        if not state:
            return
        if "time_pitch" in state:
            self.time_pitch.set_state(dict(state["time_pitch"]))
        if "muffle" in state:
            self.muffle.set_state(dict(state["muffle"]))
            if bool(state["muffle"].get("enabled")):
                self.muffle.set_expanded(True)
        if "tone" in state:
            self.tone.set_state(dict(state["tone"]))
            if bool(state["tone"].get("enabled")) and float(state["tone"].get("level", 0.0)) > 0.0:
                self.tone.set_expanded(True)
        if "noise" in state:
            self.noise.set_state(dict(state["noise"]))
            if bool(state["noise"].get("enabled")) and float(state["noise"].get("level", 0.0)) > 0.0:
                self.noise.set_expanded(True)
        if "eq" in state:
            eq_state = dict(state["eq"])
            self.eq.set_state(eq_state)
            if any(abs(float(eq_state.get(key, 0.0))) > 1e-3 for key in ("low", "mid", "high")):
                self.eq.set_expanded(True)
        if "fx" in state:
            self.fx.set_state(dict(state["fx"]))
            fx_state = dict(state["fx"])
            if any(float(fx_state.get(key, 0.0)) > 0.0 for key in ("mix", "delay", "feedback", "dist")):
                self.fx.set_expanded(True)
        if "space" in state:
            self.space.set_state(dict(state["space"]))
            space_state = dict(state["space"])
            if (space_state.get("preset") not in (None, "none")) or float(space_state.get("mix", 0.0)) > 0.0:
                self.space.set_expanded(True)
