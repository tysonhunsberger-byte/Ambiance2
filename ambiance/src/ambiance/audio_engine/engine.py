"""Realtime audio engine built on pyo providing block/stream playback."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import soundfile as sf  # type: ignore
from PyQt5.QtCore import QObject, pyqtSignal

try:
    import pyo  # type: ignore
except ImportError as exc:  # pragma: no cover - runtime dependency
    raise RuntimeError(
        "The pyo package is required for the Ambiance audio engine. "
        "Install it with 'python -m pip install pyo'."
    ) from exc


@dataclass
class AudioFileInfo:
    path: Path
    duration: float
    sample_rate: int
    channels: int


def _load_audio_info(path: Path) -> AudioFileInfo:
    """Read audio metadata without loading the entire file."""
    with sf.SoundFile(str(path)) as snd:
        duration = len(snd) / float(snd.samplerate)
        channels = snd.channels
        sr = snd.samplerate
    return AudioFileInfo(path=path, duration=duration, sample_rate=sr, channels=channels)


class AudioEngine(QObject):
    """Top-level audio engine orchestrating pyo server and block routing."""

    block_created = pyqtSignal(object)
    block_removed = pyqtSignal(object)

    def __init__(
        self,
        *,
        auto_start: bool = True,
        sample_rate: int = 48000,
        buffer_size: int = 512,
        preferred_driver: str = "portaudio",
    ):
        super().__init__()
        self._server_lock = threading.RLock()
        self._server = self._boot_server(sample_rate, buffer_size, preferred_driver)
        if auto_start:
            self._server.start()
        self.blocks: List[BlockController] = []
        self.master_gain = pyo.Sig(1.0)
        self.master_output: Optional[pyo.PyoObject] = None

    @property
    def server(self) -> pyo.Server:
        return self._server

    def _boot_server(self, sample_rate: int, buffer_size: int, preferred_driver: str) -> pyo.Server:
        """Create and boot a pyo Server, preferring PortAudio on Windows."""
        drivers = [preferred_driver]
        if preferred_driver != "jack":
            drivers.append("jack")
        drivers.append("coreaudio")
        drivers.append("portaudio")

        last_error = None
        for driver in drivers:
            try:
                server = pyo.Server(
                    sr=sample_rate,
                    buffersize=buffer_size,
                    duplex=0,
                    nchnls=2,
                    audio=driver,
                )
                server.boot()
                return server
            except Exception as exc:  # pragma: no cover - depends on host system
                last_error = exc
        raise RuntimeError(f"Failed to initialise pyo audio server. Last error: {last_error}")

    def ensure_running(self) -> None:
        with self._server_lock:
            if not self._server.getIsStarted():
                self._server.start()

    def shutdown(self) -> None:
        with self._server_lock:
            try:
                for block in list(self.blocks):
                    block.deleteLater()
                self.blocks.clear()
                if self._server.getIsStarted():
                    self._server.stop()
            finally:
                self._server.shutdown()

    def set_master_volume(self, value: float) -> None:
        value = max(0.0, min(1.5, value))
        self.master_gain.setValue(value)

    def add_block(self) -> "BlockController":
        block = BlockController(engine=self, index=len(self.blocks) + 1)
        self.blocks.append(block)
        self.block_created.emit(block)
        self._refresh_master_mix()
        return block

    def remove_block(self, block: "BlockController") -> None:
        if block in self.blocks:
            self.blocks.remove(block)
            block.delete()
            self.block_removed.emit(block)
            self._refresh_master_mix()

    def _refresh_master_mix(self) -> None:
        outputs = [block.output for block in self.blocks if block.output is not None]
        if self.master_output is not None:
            try:
                self.master_output.stop()
            except Exception:
                pass
            self.master_output = None
        if outputs:
            mix = pyo.Mix(outputs, voices=2)
            self.master_output = (mix * self.master_gain).out()


class BlockController(QObject):
    """Represents a block (collection of streams routed to master)."""

    stream_added = pyqtSignal(object)
    stream_removed = pyqtSignal(object)
    volume_changed = pyqtSignal(float)

    def __init__(self, *, engine: AudioEngine, index: int):
        super().__init__()
        self.engine = engine
        self.index = index
        self.volume = 1.0
        self.gain = pyo.Sig(1.0)
        self.streams: List[StreamController] = []
        self.output: Optional[pyo.PyoObject] = None

    def set_volume(self, value: float) -> None:
        value = max(0.0, min(1.5, value))
        self.volume = value
        self.gain.setValue(value)
        self.volume_changed.emit(value)

    def add_stream(self) -> "StreamController":
        stream = StreamController(block=self, index=len(self.streams) + 1)
        self.streams.append(stream)
        self.stream_added.emit(stream)
        self._rebuild_output()
        return stream

    def remove_stream(self, stream: "StreamController") -> None:
        if stream in self.streams:
            self.streams.remove(stream)
            stream.delete()
            self.stream_removed.emit(stream)
            self._rebuild_output()

    def _rebuild_output(self) -> None:
        outputs = [stream.output for stream in self.streams if stream.output is not None]
        if self.output is not None:
            try:
                self.output.stop()
            except Exception:
                pass
            self.output = None
        if outputs:
            mix = pyo.Mix(outputs, voices=2)
            self.output = (mix * self.gain)
        else:
            self.output = None
        self.engine._refresh_master_mix()

    def delete(self) -> None:
        for stream in list(self.streams):
            stream.delete()
        self.streams.clear()
        if self.output is not None:
            try:
                self.output.stop()
            except Exception:
                pass
            self.output = None
        self.gain.stop()


class StreamController(QObject):
    """One stream within a block with A/B layers and mix controls."""

    file_loaded = pyqtSignal(str, dict)
    state_changed = pyqtSignal()

    def __init__(self, *, block: BlockController, index: int):
        super().__init__()
        self.block = block
        self.index = index
        self.loop = True
        self.muted = False

        self.crossfade = pyo.Sig(0.5)  # 0 => A, 1 => B
        self.volume = pyo.Sig(1.0)
        self.pan = pyo.Sig(0.5)  # 0..1

        self._crossfade_value = 0.5
        self._volume_value = 1.0
        self._pan_value = 0.0

        self.file_info_a: Optional[AudioFileInfo] = None
        self.file_info_b: Optional[AudioFileInfo] = None

        self.player_a: Optional[pyo.SfPlayer] = None
        self.player_b: Optional[pyo.SfPlayer] = None

        self.output: Optional[pyo.PyoObject] = None
        self._rebuild_output()

    # ------------------------------------------------------------------
    # Layer management
    def _create_player(self, path: Path) -> pyo.SfPlayer:
        player = pyo.SfPlayer(str(path), loop=int(self.loop), mul=1.0)
        player.stop()
        try:
            player.setLoop(int(self.loop))
        except AttributeError:
            # Older pyo versions expose loop as attribute
            player.loop = int(self.loop)
        return player

    def load_file(self, layer: str, path: Path) -> None:
        info = _load_audio_info(path)
        player = self._create_player(path)
        if layer == "A":
            if self.player_a is not None:
                self.player_a.stop()
            self.player_a = player
            self.file_info_a = info
        else:
            if self.player_b is not None:
                self.player_b.stop()
            self.player_b = player
            self.file_info_b = info
        self._rebuild_output()
        metadata = {
            "duration": info.duration,
            "sample_rate": info.sample_rate,
            "channels": info.channels,
            "layer": layer,
            "path": str(info.path),
        }
        self.file_loaded.emit(layer, metadata)
        self.state_changed.emit()

    def unload(self) -> None:
        if self.player_a:
            self.player_a.stop()
            self.player_a = None
            self.file_info_a = None
        if self.player_b:
            self.player_b.stop()
            self.player_b = None
            self.file_info_b = None
        self._rebuild_output()
        self.state_changed.emit()

    # ------------------------------------------------------------------
    # Playback controls
    def play(self) -> None:
        if self.player_a:
            self.player_a.play()
        if self.player_b:
            self.player_b.play()

    def stop(self) -> None:
        if self.player_a:
            self.player_a.stop()
        if self.player_b:
            self.player_b.stop()

    def set_loop(self, enabled: bool) -> None:
        self.loop = bool(enabled)
        if self.player_a:
            try:
                self.player_a.setLoop(int(self.loop))
            except AttributeError:
                self.player_a.loop = int(self.loop)
        if self.player_b:
            try:
                self.player_b.setLoop(int(self.loop))
            except AttributeError:
                self.player_b.loop = int(self.loop)
        self.state_changed.emit()

    def set_crossfade(self, value: float) -> None:
        value = max(0.0, min(1.0, value))
        self._crossfade_value = value
        self.crossfade.setValue(value)
        self.state_changed.emit()

    def set_volume(self, value: float) -> None:
        value = max(0.0, min(1.5, value))
        self._volume_value = value
        self.volume.setValue(value if not self.muted else 0.0)
        self.state_changed.emit()

    def set_pan(self, value: float) -> None:
        # UI uses -1..1; convert to 0..1 for pyo.
        norm = max(-1.0, min(1.0, value))
        self._pan_value = norm
        self.pan.setValue((norm + 1.0) / 2.0)
        self.state_changed.emit()

    def set_muted(self, muted: bool) -> None:
        self.muted = bool(muted)
        self.volume.setValue(0.0 if self.muted else self._volume_value)
        self.state_changed.emit()

    def _rebuild_output(self) -> None:
        signals: List[pyo.PyoObject] = []
        if self.player_a is not None:
            signals.append(self.player_a * (1.0 - self.crossfade))
        if self.player_b is not None:
            signals.append(self.player_b * self.crossfade)

        if self.output is not None:
            try:
                self.output.stop()
            except Exception:
                pass
            self.output = None

        if signals:
            mix = signals[0]
            for sig in signals[1:]:
                mix = mix + sig
            mixed = mix * self.volume
            self.output = pyo.Pan(mixed, outs=2, pan=self.pan)
        else:
            self.output = None
        self.block._rebuild_output()

    # ------------------------------------------------------------------
    def delete(self) -> None:
        if self.player_a:
            self.player_a.stop()
        if self.player_b:
            self.player_b.stop()
        self.player_a = None
        self.player_b = None
        if self.output is not None:
            try:
                self.output.stop()
            except Exception:
                pass
            self.output = None

    # Convenience -------------------------------------------------------
    def describe(self) -> Dict[str, Optional[str]]:
        return {
            "file_a": str(self.file_info_a.path) if self.file_info_a else None,
            "file_b": str(self.file_info_b.path) if self.file_info_b else None,
        }

    # Exposed properties for UI sync ----------------------------------
    @property
    def crossfade_value(self) -> float:
        return self._crossfade_value

    @property
    def volume_value(self) -> float:
        return self._volume_value if not self.muted else 0.0

    @property
    def pan_value(self) -> float:
        return self._pan_value
