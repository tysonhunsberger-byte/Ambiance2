from __future__ import annotations

from pathlib import Path
from typing import Dict

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QPushButton,
    QWidget,
    QSlider,
    QCheckBox,
    QMessageBox,
    QSizePolicy,
    QToolButton,
    QSpacerItem,
)

from ambiance.audio_engine import AudioEngine, BlockController, StreamController
from .stream_mods import StreamModsContainer


class _LegacySignalProxy:
    """Minimal proxy for Qt signals referenced by legacy code."""

    def __init__(self) -> None:
        self._target = None
        self._slots = []

    def set_target(self, signal) -> None:  # type: ignore[no-untyped-def]
        self._target = signal
        if signal is None:
            return
        for slot in self._slots:
            try:
                signal.connect(slot)
            except Exception:
                pass

    def connect(self, slot) -> None:  # type: ignore[no-untyped-def]
        if slot not in self._slots:
            self._slots.append(slot)
        if self._target is not None:
            try:
                self._target.connect(slot)
            except Exception:
                pass


class _LegacySliderProxy:
    """Proxy that mimics a QSlider for compatibility consumers."""

    def __init__(self) -> None:
        self._target = None
        self.sliderMoved = _LegacySignalProxy()
        self.sliderPressed = _LegacySignalProxy()
        self.sliderReleased = _LegacySignalProxy()
        self.valueChanged = _LegacySignalProxy()

    def set_target(self, slider) -> None:  # type: ignore[no-untyped-def]
        self._target = slider
        for name, proxy in (
            ("sliderMoved", self.sliderMoved),
            ("sliderPressed", self.sliderPressed),
            ("sliderReleased", self.sliderReleased),
            ("valueChanged", self.valueChanged),
        ):
            target_signal = getattr(slider, name) if slider is not None else None
            proxy.set_target(target_signal)

    # Basic API surface used by the old desktop code -----------------
    def setValue(self, value: int) -> None:
        if self._target is not None:
            self._target.setValue(value)

    def setRange(self, minimum: int, maximum: int) -> None:
        if self._target is not None:
            self._target.setRange(minimum, maximum)

    def setEnabled(self, enabled: bool) -> None:
        if self._target is not None:
            self._target.setEnabled(enabled)

    def blockSignals(self, block: bool) -> None:
        if self._target is not None:
            self._target.blockSignals(block)

    def value(self) -> int:
        if self._target is not None:
            return int(self._target.value())
        return 0

    def __getattr__(self, item):
        if self._target is None:
            def _noop(*_args, **_kwargs):
                return None

            return _noop
        return getattr(self._target, item)


class _LegacyLabelProxy:
    """Proxy that mimics a QLabel for compatibility consumers."""

    def __init__(self) -> None:
        self._target = None

    def set_target(self, label) -> None:  # type: ignore[no-untyped-def]
        self._target = label

    def setText(self, text: str) -> None:
        if self._target is not None:
            self._target.setText(text)

    def text(self) -> str:
        if self._target is not None:
            return str(self._target.text())
        return ""

    def __getattr__(self, item):
        if self._target is None:
            def _noop(*_args, **_kwargs):
                return None

            return _noop
        return getattr(self._target, item)


class BlocksPanel(QFrame):
    """Panel hosting user audio blocks/streams."""

    def __init__(self, engine: AudioEngine, parent: QWidget | None = None):
        super().__init__(parent)
        self.engine = engine
        self._block_widgets: Dict[BlockController, BlockWidget] = {}
        self.setObjectName("BlocksPanel")

        self.setStyleSheet(
            """
            #BlocksPanel {
                background-color: #101010;
                color: #f1f1f1;
            }
            #BlocksPanel QLabel {
                color: #f1f1f1;
            }
            #BlocksPanel QPushButton {
                background-color: #232323;
                color: #f1f1f1;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 6px 12px;
            }
            #BlocksPanel QPushButton:hover {
                background-color: #2f2f2f;
            }
            #BlocksPanel QPushButton:pressed {
                background-color: #3b3b3b;
            }
            #BlocksPanel QGroupBox {
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 12px;
                margin-top: 18px;
            }
            #BlocksPanel QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                color: #f1f1f1;
            }
            #BlockWidget {
                background-color: rgba(34, 34, 34, 0.92);
            }
            #BlockWidget QLabel {
                color: #f1f1f1;
            }
            #StreamWidget {
                background-color: rgba(28, 28, 28, 0.95);
            }
            #StreamWidget QLabel {
                color: #f1f1f1;
            }
            #StreamWidget QCheckBox,
            #StreamWidget QComboBox,
            #StreamWidget QDoubleSpinBox {
                color: #f1f1f1;
            }
            #StreamWidget QComboBox,
            #StreamWidget QDoubleSpinBox {
                background-color: #1c1c1c;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 2px 6px;
            }
            #StreamWidget QToolButton {
                background-color: #232323;
                color: #f1f1f1;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 4px 10px;
            }
            #StreamWidget QToolButton:checked {
                background-color: #2d2d2d;
            }
            #StreamWidget QSlider::groove:horizontal {
                height: 6px;
                background: #2e2e2e;
                border-radius: 3px;
            }
            #StreamWidget QSlider::handle:horizontal {
                background: #4f6fe8;
                border: 1px solid #6d8cff;
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            #StreamWidget QSlider::sub-page:horizontal {
                background: #4f6fe8;
                border-radius: 3px;
            }
        """
        )

        # Legacy compatibility handles for the desktop shell which still
        # references panel-level seeker and label attributes.
        self.seekerA = _LegacySliderProxy()
        self.seekerB = _LegacySliderProxy()
        self.progressLabelA = _LegacyLabelProxy()
        self.progressLabelB = _LegacyLabelProxy()

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

        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(16)
        self.list_layout.addStretch()
        root_layout.addWidget(self.list_widget, 1)

        engine.block_created.connect(self._on_block_created)
        engine.block_removed.connect(self._on_block_removed)

    # ------------------------------------------------------------------
    def _ordered_block_widgets(self) -> list["BlockWidget"]:
        return sorted(self._block_widgets.values(), key=lambda widget: widget.controller.index)

    def _first_stream_widget(self) -> "StreamWidget | None":
        for block_widget in self._ordered_block_widgets():
            for stream_widget in block_widget.ordered_stream_widgets:
                return stream_widget
        return None

    def _refresh_legacy_seekers(self) -> None:
        widget = self._first_stream_widget()
        if widget is None:
            self.seekerA.set_target(None)
            self.seekerB.set_target(None)
            self.progressLabelA.set_target(None)
            self.progressLabelB.set_target(None)
            return
        self.seekerA.set_target(widget.progress_a_slider)
        self.seekerB.set_target(widget.progress_b_slider)
        self.progressLabelA.set_target(widget.progress_a_time)
        self.progressLabelB.set_target(widget.progress_b_time)

    def _on_stream_widget_added(self, widget: "StreamWidget") -> None:
        self._refresh_legacy_seekers()

    def _on_stream_widget_removed(self, widget: "StreamWidget") -> None:
        self._refresh_legacy_seekers()

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
        insert_index = max(0, self.list_layout.count() - 1)
        self.list_layout.insertWidget(insert_index, widget)
        self._refresh_legacy_seekers()

    def _on_block_removed(self, block: BlockController) -> None:
        widget = self._block_widgets.pop(block, None)
        if widget:
            widget.deleteLater()
        self._refresh_legacy_seekers()

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

        self.setObjectName("BlockWidget")
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

        controller.stream_added.connect(self._on_stream_added)
        controller.stream_removed.connect(self._on_stream_removed)
        controller.volume_changed.connect(self._sync_volume)

        for stream in controller.streams:
            self._add_stream_widget(stream)

    # ------------------------------------------------------------------
    @property
    def ordered_stream_widgets(self) -> list["StreamWidget"]:
        return [
            self.stream_widgets[stream]
            for stream in sorted(self.stream_widgets.keys(), key=lambda item: item.index)
        ]

    def _add_stream_widget(self, stream: StreamController) -> None:
        widget = StreamWidget(stream)
        self.stream_widgets[stream] = widget
        self.stream_container.addWidget(widget)
        self.panel._on_stream_widget_added(widget)

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
        self._add_stream_widget(stream)

    def _on_stream_added(self, stream: StreamController) -> None:
        if stream not in self.stream_widgets:
            self._add_stream_widget(stream)

    def _on_stream_removed(self, stream: StreamController) -> None:
        widget = self.stream_widgets.pop(stream, None)
        if widget:
            widget.deleteLater()
            self.panel._on_stream_widget_removed(widget)

    def _on_remove_block(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Remove Block",
            "Are you sure you want to remove this block and all streams?",
        )
        if confirm == QMessageBox.Yes:
            self.panel.remove_block(self.controller)

    # ------------------------------------------------------------------
    def _wire_mod_controls(self) -> None:
        """Legacy no-op retained for backwards compatibility.

        Older versions of the desktop shell used to poke the block widgets
        directly to wire the per-stream effect controls. The modern widgets
        handle that work internally (see :class:`StreamWidget`), but we keep
        the attribute so that stale imports don't crash during startup.
        """

        # Nothing to do here – the method simply needs to exist.
        return None


class StreamWidget(QGroupBox):
    """UI for a single stream."""

    def __init__(self, controller: StreamController):
        super().__init__(f"Stream {controller.index}")
        self.controller = controller
        self._duration_info = {"A": 0.0, "B": 0.0}
        self._seeking_layer: str | None = None
        self.setObjectName("StreamWidget")
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

        self.progress_a_slider = self._make_slider(0, 1, 0)
        self.progress_a_slider.setEnabled(False)
        self.progress_a_slider.sliderPressed.connect(lambda: self._begin_seek("A"))
        self.progress_a_slider.sliderReleased.connect(lambda: self._commit_seek("A"))
        self.progress_a_slider.sliderMoved.connect(lambda value: self._preview_seek("A", value))
        self.progress_a_time = QLabel("0:00 / 0:00")

        self.progress_b_slider = self._make_slider(0, 1, 0)
        self.progress_b_slider.setEnabled(False)
        self.progress_b_slider.sliderPressed.connect(lambda: self._begin_seek("B"))
        self.progress_b_slider.sliderReleased.connect(lambda: self._commit_seek("B"))
        self.progress_b_slider.sliderMoved.connect(lambda value: self._preview_seek("B", value))
        self.progress_b_time = QLabel("0:00 / 0:00")

        # Legacy attribute names expected by parts of the desktop shell.
        self.seekerA = self.progress_a_slider
        self.seekerB = self.progress_b_slider
        self.progressLabelA = self.progress_a_time
        self.progressLabelB = self.progress_b_time

        layout.addLayout(self._progress_row("File A", self.progress_a_slider, self.progress_a_time))
        layout.addLayout(self._progress_row("File B", self.progress_b_slider, self.progress_b_time))
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
        self.mods_spacer = QSpacerItem(0, 6, QSizePolicy.Minimum, QSizePolicy.Fixed)
        layout.addItem(self.mods_spacer)

        self.mods_toggle = QToolButton()
        self.mods_toggle.setText("Effects Rack")
        self.mods_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.mods_toggle.setArrowType(Qt.DownArrow)
        self.mods_toggle.setCheckable(True)
        self.mods_toggle.setChecked(True)
        self.mods_toggle.toggled.connect(self._on_mods_toggled)
        layout.addWidget(self.mods_toggle, 0, Qt.AlignLeft)

        self.mods = StreamModsContainer()
        layout.addWidget(self.mods)
        self._wire_mod_controls()

        controller.file_loaded.connect(self._on_file_loaded)
        controller.state_changed.connect(self._sync_state)
        self._sync_state()

        self.position_timer = QTimer(self)
        self.position_timer.setInterval(200)
        self.position_timer.timeout.connect(self._refresh_positions)
        self.position_timer.start()

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

    def _on_mods_toggled(self, checked: bool) -> None:
        self.mods.setVisible(checked)
        self.mods_toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        if hasattr(self, "mods_spacer"):
            self.mods_spacer.changeSize(0, 6 if checked else 0, QSizePolicy.Minimum, QSizePolicy.Fixed)
            self.layout().invalidate()

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

    def _progress_row(self, label: str, slider: QSlider, time_label: QLabel) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(QLabel(label))
        row.addWidget(slider, 1)
        time_label.setMinimumWidth(110)
        row.addWidget(time_label)
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
        self._update_progress_controls()

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
        self._refresh_positions()

    def _begin_seek(self, layer: str) -> None:
        self._seeking_layer = layer

    def _commit_seek(self, layer: str) -> None:
        if self._seeking_layer != layer:
            return
        slider = self.progress_a_slider if layer == "A" else self.progress_b_slider
        duration = self._duration_info.get(layer, 0.0)
        target = min(duration, max(0.0, slider.value() / 1000.0))
        self._seek_layer(layer, target)
        self._seeking_layer = None

    def _preview_seek(self, layer: str, value: int) -> None:
        duration = self._duration_info.get(layer, 0.0)
        seconds = min(duration, max(0.0, value / 1000.0))
        label = self.progress_a_time if layer == "A" else self.progress_b_time
        label.setText(f"{self._format_time(seconds)} / {self._format_time(duration)}")

    def _seek_layer(self, layer: str, seconds: float) -> None:
        try:
            self.controller.seek(layer, seconds)
        except AttributeError:
            # Older controllers without seek support.
            pass

    def _refresh_positions(self) -> None:
        if self._seeking_layer is not None:
            return
        mapping = (
            ("A", self.progress_a_slider, self.progress_a_time),
            ("B", self.progress_b_slider, self.progress_b_time),
        )
        for layer, slider, label in mapping:
            duration = self._duration_info.get(layer, 0.0)
            if duration <= 0:
                slider.blockSignals(True)
                slider.setEnabled(False)
                slider.setRange(0, 1)
                slider.setValue(0)
                slider.blockSignals(False)
                label.setText("0:00 / 0:00")
                continue

            slider.blockSignals(True)
            slider.setEnabled(True)
            slider.setRange(0, max(1, int(duration * 1000)))
            try:
                position = self.controller.get_position(layer)
            except AttributeError:
                position = 0.0
            position = min(duration, max(0.0, float(position)))
            slider.setValue(int(position * 1000))
            slider.blockSignals(False)
            label.setText(f"{self._format_time(position)} / {self._format_time(duration)}")

    def _update_progress_controls(self) -> None:
        for layer, slider, label in (
            ("A", self.progress_a_slider, self.progress_a_time),
            ("B", self.progress_b_slider, self.progress_b_time),
        ):
            duration = self._duration_info.get(layer, 0.0)
            slider.blockSignals(True)
            slider.setEnabled(duration > 0)
            slider.setRange(0, max(1, int(duration * 1000)))
            slider.setValue(0)
            slider.blockSignals(False)
            label.setText(f"0:00 / {self._format_time(duration)}")

    def _format_time(self, seconds: float) -> str:
        if seconds <= 0:
            return "0:00"
        minutes = int(seconds // 60)
        remaining = int(seconds % 60)
        return f"{minutes}:{remaining:02d}"
