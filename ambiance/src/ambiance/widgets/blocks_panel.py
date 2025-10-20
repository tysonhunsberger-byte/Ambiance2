from __future__ import annotations

from pathlib import Path
from typing import Dict

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QPushButton,
    QScrollArea,
    QWidget,
    QSlider,
    QCheckBox,
    QMessageBox,
    QSizePolicy,
)

from ambiance.audio_engine import AudioEngine, BlockController, StreamController
from .stream_mods import StreamModsContainer


class BlocksPanel(QFrame):
    """Panel hosting user audio blocks/streams."""

    def __init__(self, engine: AudioEngine, parent: QWidget | None = None):
        super().__init__(parent)
        self.engine = engine
        self._block_widgets: Dict[BlockController, BlockWidget] = {}
        self.setObjectName("BlocksPanel")

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Blocks & Streams")
        title.setObjectName("BlocksTitle")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        header.addWidget(title)

        header.addStretch()

        add_btn = QPushButton("Add Block")
        add_btn.clicked.connect(self._on_add_block_clicked)
        header.addWidget(add_btn)

        root_layout.addLayout(header)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        root_layout.addWidget(self.scroll_area, 1)

        self.scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(16)
        self.scroll_layout.addStretch()
        self.scroll_area.setWidget(self.scroll_widget)

        engine.block_created.connect(self._on_block_created)
        engine.block_removed.connect(self._on_block_removed)

    # ------------------------------------------------------------------
    def create_block(self) -> BlockController | None:
        try:
            self.engine.ensure_running()
            block = self.engine.add_block()
            block.set_volume(1.0)
            return block
        except Exception as exc:
            QMessageBox.critical(self, "Audio Engine", f"Failed to add block:\n{exc}")
            return None

    def _on_add_block_clicked(self) -> None:
        self.create_block()

    def _on_block_created(self, block: BlockController) -> None:
        widget = BlockWidget(block, panel=self)
        self._block_widgets[block] = widget
        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, widget)

    def _on_block_removed(self, block: BlockController) -> None:
        widget = self._block_widgets.pop(block, None)
        if widget:
            widget.deleteLater()

    def remove_block(self, block: BlockController) -> None:
        self.engine.remove_block(block)


class BlockWidget(QGroupBox):
    """UI wrapper for a BlockController."""

    def __init__(self, controller: BlockController, panel: BlocksPanel):
        super().__init__(f"Block {controller.index}")
        self.controller = controller
        self.panel = panel
        self.stream_widgets: Dict[StreamController, StreamWidget] = {}

        self.setObjectName("BlockWidget")
        self.setStyleSheet("BlockWidget { border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 20, 18, 20)
        layout.setSpacing(18)

        volume_label = QLabel("Volume")
        volume_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(volume_label)

        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(0, 0, 0, 0)
        slider_row.setSpacing(10)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 150)
        self.volume_slider.setValue(int(controller.volume * 100))
        self.volume_slider.setMinimumHeight(24)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        slider_row.addWidget(self.volume_slider, 1)
        self.volume_label = QLabel("100%")
        slider_row.addWidget(self.volume_label)
        layout.addLayout(slider_row)

        button_row = QHBoxLayout()
        button_row.addStretch()
        add_stream_btn = QPushButton("Add Stream")
        add_stream_btn.clicked.connect(self._on_add_stream)
        button_row.addWidget(add_stream_btn)
        remove_btn = QPushButton("Remove Block")
        remove_btn.clicked.connect(self._on_remove_block)
        button_row.addWidget(remove_btn)
        layout.addLayout(button_row)

        self.stream_container = QVBoxLayout()
        self.stream_container.setContentsMargins(0, 0, 0, 0)
        self.stream_container.setSpacing(20)
        layout.addLayout(self.stream_container)

        self.mods = StreamModsContainer()
        layout.addWidget(self.mods)

        self._wire_mod_controls()

        controller.stream_added.connect(self._on_stream_added)
        controller.stream_removed.connect(self._on_stream_removed)
        controller.volume_changed.connect(self._sync_volume)

    # ------------------------------------------------------------------
    def _on_volume_changed(self, value: int) -> None:
        percent = value / 100.0
        if percent <= 0:
            self.volume_label.setText("Muted")
        else:
            self.volume_label.setText(f"{int(percent * 100)}%")
        self.controller.set_volume(percent)

    def _sync_volume(self, value: float) -> None:
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(int(value * 100))
        self.volume_slider.blockSignals(False)
        self.volume_label.setText(f"{int(value * 100)}%")

    def _on_add_stream(self) -> None:
        stream = self.controller.add_stream()
        stream_widget = StreamWidget(stream)
        self.stream_widgets[stream] = stream_widget
        self.stream_container.addWidget(stream_widget)

    def _on_stream_added(self, stream: StreamController) -> None:
        # Already created in _on_add_stream
        pass

    def _on_stream_removed(self, stream: StreamController) -> None:
        widget = self.stream_widgets.pop(stream, None)
        if widget:
            widget.deleteLater()

    def _on_remove_block(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Remove Block",
            "Are you sure you want to remove this block and all streams?",
        )
        if confirm == QMessageBox.Yes:
            self.panel.remove_block(self.controller)


class StreamWidget(QGroupBox):
    """UI for a single stream."""

    def __init__(self, controller: StreamController):
        super().__init__(f"Stream {controller.index}")
        self.controller = controller
        self._duration_info = {"A": 0.0, "B": 0.0}
        self.setObjectName("StreamWidget")
        self.setStyleSheet("StreamWidget { border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; }")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)
        file_row = QHBoxLayout()
        file_row.setSpacing(12)

        self.file_a_btn = QPushButton("Load A")
        self.file_a_btn.clicked.connect(lambda: self._pick_file("A"))
        self.file_a_label = QLabel("None")
        self.file_a_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.file_b_btn = QPushButton("Load B")
        self.file_b_btn.clicked.connect(lambda: self._pick_file("B"))
        self.file_b_label = QLabel("None")
        self.file_b_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        file_row.addWidget(self.file_a_btn)
        file_row.addWidget(self.file_a_label, 1)
        file_row.addSpacing(10)
        file_row.addWidget(self.file_b_btn)
        file_row.addWidget(self.file_b_label, 1)

        layout.addLayout(file_row)
        layout.addSpacing(10)

        transport_row = QHBoxLayout()
        play_btn = QPushButton("Play")
        play_btn.clicked.connect(controller.play)
        stop_btn = QPushButton("Stop")
        stop_btn.clicked.connect(controller.stop)
        self.loop_check = QCheckBox("Loop")
        self.loop_check.setChecked(controller.loop)
        self.loop_check.toggled.connect(controller.set_loop)

        transport_row.addWidget(play_btn)
        transport_row.addWidget(stop_btn)
        transport_row.addWidget(self.loop_check)
        transport_row.addStretch()

        self.mute_btn = QPushButton("Mute")
        self.mute_btn.setCheckable(True)
        self.mute_btn.toggled.connect(controller.set_muted)
        transport_row.addWidget(self.mute_btn)

        layout.addLayout(transport_row)
        layout.addSpacing(12)

        # Sliders
        self.cross_slider = self._make_slider(0, 100, int(controller.crossfade_value * 100))
        self.cross_slider.valueChanged.connect(self._cross_changed)

        self.volume_slider = self._make_slider(0, 150, int(controller.volume_value * 100))
        self.volume_slider.valueChanged.connect(self._volume_changed)

        self.pan_slider = self._make_slider(-100, 100, int(controller.pan_value * 100))
        self.pan_slider.valueChanged.connect(self._pan_changed)

        layout.addLayout(self._slider_row("Crossfade A <-> B", self.cross_slider))
        layout.addSpacing(8)
        layout.addLayout(self._slider_row("Volume", self.volume_slider))
        layout.addSpacing(8)
        layout.addLayout(self._slider_row("Pan", self.pan_slider))
        layout.addSpacing(6)

        controller.file_loaded.connect(self._on_file_loaded)
        controller.state_changed.connect(self._sync_state)
        self._sync_state()

    def _wire_mod_controls(self) -> None:
        mods = self.mods
        mods.time_pitch.tempo_changed.connect(self.controller.set_tempo)
        mods.time_pitch.pitch_changed.connect(self.controller.set_pitch)
        mods.time_pitch.reverse_a_changed.connect(lambda val: self.controller.set_reverse("A", val))
        mods.time_pitch.reverse_b_changed.connect(lambda val: self.controller.set_reverse("B", val))
        mods.time_pitch.loop_changed.connect(self.controller.set_loop)

        mods.muffle.enabled_changed.connect(self.controller.set_muffle_enabled)
        mods.muffle.amount_changed.connect(self.controller.set_muffle_amount)

        mods.tone.enabled_changed.connect(self.controller.set_tone_enabled)
        mods.tone.wave_changed.connect(self.controller.set_tone_wave)
        mods.tone.base_changed.connect(self.controller.set_tone_base)
        mods.tone.beat_changed.connect(self.controller.set_tone_beat)
        mods.tone.level_changed.connect(self.controller.set_tone_level)

        mods.noise.enabled_changed.connect(self.controller.set_noise_enabled)
        mods.noise.type_changed.connect(self.controller.set_noise_type)
        mods.noise.level_changed.connect(self.controller.set_noise_level)
        mods.noise.tilt_changed.connect(self.controller.set_noise_tilt)

        mods.eq.low_changed.connect(self.controller.set_eq_low)
        mods.eq.mid_changed.connect(self.controller.set_eq_mid)
        mods.eq.high_changed.connect(self.controller.set_eq_high)

        mods.fx.mix_changed.connect(self.controller.set_fx_mix)
        mods.fx.delay_changed.connect(self.controller.set_fx_delay)
        mods.fx.feedback_changed.connect(self.controller.set_fx_feedback)
        mods.fx.dist_changed.connect(self.controller.set_fx_distortion)

        mods.space.preset_changed.connect(self.controller.set_space_preset)
        mods.space.mix_changed.connect(self.controller.set_space_mix)
        mods.space.decay_changed.connect(self.controller.set_space_decay)
        mods.space.predelay_changed.connect(self.controller.set_space_predelay)

    def _make_slider(self, minimum: int, maximum: int, value: int) -> QSlider:
        slider = QSlider(Qt.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        return slider

    def _slider_row(self, label: str, slider: QSlider) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(QLabel(label))
        row.addWidget(slider, 1)
        return row

    def _update_file_labels(self) -> None:
        desc = self.controller.describe()
        mapping = (("file_a", "A", self.file_a_label), ("file_b", "B", self.file_b_label))
        for key, layer, label in mapping:
            path = desc.get(key)
            duration = self._duration_info.get(layer, 0.0)
            if path:
                name = Path(path).name
                if duration:
                    label.setText(f"{name} ({duration:.2f}s)")
                else:
                    label.setText(name)
            else:
                self._duration_info[layer] = 0.0
                label.setText("None")

    # ------------------------------------------------------------------
    def _pick_file(self, layer: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, f"Select audio file for {layer}", "", "Audio Files (*.wav *.mp3 *.flac)")
        if not path:
            return
        try:
            self.controller.load_file(layer, Path(path))
        except Exception as exc:
            QMessageBox.critical(self, "Load Audio", f"Failed to load file:\n{exc}")

    def _on_file_loaded(self, layer: str, metadata: Dict[str, object]) -> None:
        duration = float(metadata.get("duration", 0.0) or 0.0)
        if layer in self._duration_info:
            self._duration_info[layer] = duration
        self._update_file_labels()

    def _cross_changed(self, value: int) -> None:
        self.controller.set_crossfade(value / 100.0)

    def _volume_changed(self, value: int) -> None:
        self.controller.set_volume(value / 100.0)

    def _pan_changed(self, value: int) -> None:
        self.controller.set_pan(value / 100.0)

    def _sync_state(self) -> None:
        self.cross_slider.blockSignals(True)
        self.cross_slider.setValue(int(self.controller.crossfade_value * 100))
        self.cross_slider.blockSignals(False)

        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(int(self.controller.volume_value * 100))
        self.volume_slider.blockSignals(False)

        self.pan_slider.blockSignals(True)
        self.pan_slider.setValue(int(self.controller.pan_value * 100))
        self.pan_slider.blockSignals(False)

        self.loop_check.blockSignals(True)
        self.loop_check.setChecked(self.controller.loop)
        self.loop_check.blockSignals(False)

        self.mute_btn.blockSignals(True)
        self.mute_btn.setChecked(self.controller.muted)
        self.mute_btn.blockSignals(False)
        self._update_file_labels()
        self.mods.set_state(self.controller.get_mod_state())
