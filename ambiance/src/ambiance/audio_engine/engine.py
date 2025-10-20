"""Realtime audio engine built on pyo providing block/stream playback."""

from __future__ import annotations

import math
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

        # Time/pitch parameters
        self._tempo = 1.0
        self._pitch = 0
        self._reverse_a = False
        self._reverse_b = False

        # Effect parameters
        self._muffle_enabled = False
        self._muffle_amount = 1.0
        self._tone_enabled = False
        self._tone_wave = "sine"
        self._tone_base = 200.0
        self._tone_beat = 10.0
        self._tone_level = 0.0
        self._noise_enabled = False
        self._noise_type = "white"
        self._noise_level = 0.0
        self._noise_tilt = 0.0
        self._tone_tables: Dict[str, pyo.PyoObject] = {}
        self._eq_low = 0.0
        self._eq_mid = 0.0
        self._eq_high = 0.0
        self._fx_mix = 0.0
        self._fx_delay = 0.25
        self._fx_feedback = 0.3
        self._fx_dist = 0.0
        self._space_preset = "none"
        self._space_mix = 0.0
        self._space_decay = 1.2
        self._space_pre = 0.0

        # Effect nodes
        self._effect_nodes: List[pyo.PyoObject] = []
        self._generator_nodes: List[pyo.PyoObject] = []
        self._pitch_node: Optional[pyo.PyoObject] = None
        self._muffle_node: Optional[pyo.PyoObject] = None
        self._eq_low_node: Optional[pyo.PyoObject] = None
        self._eq_mid_node: Optional[pyo.PyoObject] = None
        self._eq_high_node: Optional[pyo.PyoObject] = None
        self._disto_node: Optional[pyo.PyoObject] = None
        self._delay_node: Optional[pyo.PyoObject] = None
        self._fx_mix_sig: Optional[pyo.Sig] = None
        self._fx_interp: Optional[pyo.PyoObject] = None
        self._space_predelay: Optional[pyo.PyoObject] = None
        self._reverb_node: Optional[pyo.PyoObject] = None
        self.silence = pyo.Sig(0.0)

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

    def seek(self, layer: str, seconds: float) -> None:
        player, info = self._player_and_info(layer)
        if not player or not info or info.duration <= 0:
            return
        seconds = max(0.0, min(float(seconds), info.duration))
        norm = 0.0 if info.duration <= 0 else seconds / info.duration
        try:
            player.setPos(norm)
        except AttributeError:
            try:
                player.pos = norm
            except Exception:
                return
        self.state_changed.emit()

    def get_position(self, layer: str) -> float:
        player, info = self._player_and_info(layer)
        if not player or not info or info.duration <= 0:
            return 0.0
        position: float = 0.0
        for accessor in ("getPos", "getpos", "getPointer"):
            if hasattr(player, accessor):
                try:
                    raw = getattr(player, accessor)()
                    position = self._normalise_position_value(raw, info)
                    break
                except Exception:
                    continue
        else:
            for attr in ("pos", "pointer", "index"):
                if hasattr(player, attr):
                    try:
                        raw = getattr(player, attr)
                        position = self._normalise_position_value(raw, info)
                        break
                    except Exception:
                        continue
        return max(0.0, min(info.duration, position))

    def _player_and_info(
        self, layer: str
    ) -> Tuple[Optional[pyo.SfPlayer], Optional[AudioFileInfo]]:
        layer = layer.upper()
        if layer == "A":
            return self.player_a, self.file_info_a
        return self.player_b, self.file_info_b

    def _normalise_position_value(self, raw: object, info: AudioFileInfo) -> float:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(value):
            return 0.0
        duration = info.duration
        if duration <= 0:
            return 0.0
        if 0.0 <= value <= 1.0:
            return value * duration
        if 0.0 <= value <= duration * 1.1:
            return value
        total_frames = duration * info.sample_rate
        if total_frames > 0 and 0.0 <= value <= total_frames * 1.1:
            return (value / total_frames) * duration
        return 0.0

    def _rebuild_output(self) -> None:
        self._cleanup_effects()

        source_a = self.player_a if self.player_a is not None else self.silence
        source_b = self.player_b if self.player_b is not None else self.silence

        cross = pyo.Interp(source_a, source_b, interp=self.crossfade)
        self._register_node(cross)

        pitch = pyo.Harmonizer(cross, transpo=self._pitch)
        self._pitch_node = pitch
        self._register_node(pitch)

        muffle_freq = self._muffle_cutoff()
        muffle = pyo.Biquad(pitch, freq=muffle_freq, q=0.707, type=0)
        self._muffle_node = muffle
        self._register_node(muffle)

        eq_low = pyo.EQ(muffle, freq=120, boost=self._eq_low, q=0.7, type=1)
        self._eq_low_node = eq_low
        self._register_node(eq_low)
        eq_mid = pyo.EQ(eq_low, freq=1000, boost=self._eq_mid, q=1.0, type=0)
        self._eq_mid_node = eq_mid
        self._register_node(eq_mid)
        eq_high = pyo.EQ(eq_mid, freq=8000, boost=self._eq_high, q=0.7, type=2)
        self._eq_high_node = eq_high
        self._register_node(eq_high)

        disto = pyo.Disto(eq_high, drive=self._fx_dist, slope=0.8, mul=1.0)
        self._disto_node = disto
        self._register_node(disto)

        delay = pyo.Delay(disto, delay=self._fx_delay, feedback=self._fx_feedback, maxdelay=2.0)
        self._delay_node = delay
        self._register_node(delay)

        self._fx_mix_sig = pyo.Sig(self._fx_mix)
        self._register_node(self._fx_mix_sig)
        fx_interp = pyo.Interp(eq_high, delay, interp=self._fx_mix_sig)
        self._fx_interp = fx_interp
        self._register_node(fx_interp)

        predelay = pyo.Delay(fx_interp, delay=self._space_pre, maxdelay=1.0)
        self._space_predelay = predelay
        self._register_node(predelay)

        size, damp = self._space_params()
        reverb_mix = self._space_mix if self._space_preset != "none" else 0.0
        reverb = pyo.Freeverb(predelay, size=size, damp=damp, bal=reverb_mix)
        self._reverb_node = reverb
        self._register_node(reverb)

        signal: pyo.PyoObject = reverb

        generators = self._build_generators()
        if generators is not None:
            signal = signal + generators

        final = pyo.Pan(signal * self.volume, outs=2, pan=self.pan)
        self.output = final
        self._register_node(final)
        self.block._rebuild_output()

    # ------------------------------------------------------------------
    def delete(self) -> None:
        if self.player_a:
            self.player_a.stop()
        if self.player_b:
            self.player_b.stop()
        self.player_a = None
        self.player_b = None
        self._cleanup_effects()
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

    # Time & pitch -----------------------------------------------------
    def set_tempo(self, tempo: float) -> None:
        tempo = max(0.25, min(4.0, float(tempo)))
        self._tempo = tempo
        self._update_player_speed("A")
        self._update_player_speed("B")
        self.state_changed.emit()

    def set_pitch(self, semitones: int) -> None:
        self._pitch = int(max(-24, min(24, semitones)))
        if self._pitch_node is not None:
            self._set_attr(self._pitch_node, "transpo", self._pitch)
        self.state_changed.emit()

    def set_reverse(self, layer: str, enabled: bool) -> None:
        if layer.upper() == "A":
            self._reverse_a = bool(enabled)
            self._update_player_speed("A")
        else:
            self._reverse_b = bool(enabled)
            self._update_player_speed("B")
        self.state_changed.emit()

    def _update_player_speed(self, layer: str) -> None:
        player, _ = self._player_and_info(layer)
        if not player:
            return
        reverse = self._reverse_a if layer == "A" else self._reverse_b
        speed = self._tempo * (-1.0 if reverse else 1.0)
        try:
            player.setSpeed(speed)
        except AttributeError:
            try:
                player.speed = speed
            except Exception:
                pass

    # Muffle -----------------------------------------------------------
    def set_muffle_enabled(self, enabled: bool) -> None:
        self._muffle_enabled = bool(enabled)
        if self._muffle_node is not None:
            self._set_attr(self._muffle_node, "freq", self._muffle_cutoff())
        self.state_changed.emit()

    def set_muffle_amount(self, amount: float) -> None:
        self._muffle_amount = max(0.0, min(1.0, float(amount)))
        if self._muffle_node is not None and self._muffle_enabled:
            self._set_attr(self._muffle_node, "freq", self._muffle_cutoff())
        self.state_changed.emit()

    # Tone -------------------------------------------------------------
    def set_tone_enabled(self, enabled: bool) -> None:
        enabled_flag = bool(enabled)
        self._tone_enabled = enabled_flag
        if enabled_flag and self._tone_level <= 0.0:
            self._tone_level = 0.35
        self._rebuild_output()
        self.state_changed.emit()

    def set_tone_wave(self, wave: str) -> None:
        self._tone_wave = str(wave) or "sine"
        self._rebuild_output()
        self.state_changed.emit()

    def set_tone_base(self, base: float) -> None:
        self._tone_base = max(20.0, min(2000.0, float(base)))
        self._rebuild_output()
        self.state_changed.emit()

    def set_tone_beat(self, beat: float) -> None:
        self._tone_beat = max(0.0, min(45.0, float(beat)))
        self._rebuild_output()
        self.state_changed.emit()

    def set_tone_level(self, level: float) -> None:
        self._tone_level = max(0.0, min(1.0, float(level)))
        self._rebuild_output()
        self.state_changed.emit()

    # Noise ------------------------------------------------------------
    def set_noise_enabled(self, enabled: bool) -> None:
        enabled_flag = bool(enabled)
        self._noise_enabled = enabled_flag
        if enabled_flag and self._noise_level <= 0.0:
            self._noise_level = 0.3
        self._rebuild_output()
        self.state_changed.emit()

    def set_noise_type(self, noise_type: str) -> None:
        self._noise_type = str(noise_type) or "white"
        self._rebuild_output()
        self.state_changed.emit()

    def set_noise_level(self, level: float) -> None:
        self._noise_level = max(0.0, min(1.0, float(level)))
        self._rebuild_output()
        self.state_changed.emit()

    def set_noise_tilt(self, tilt: float) -> None:
        self._noise_tilt = max(-1.0, min(1.0, float(tilt)))
        self._rebuild_output()
        self.state_changed.emit()

    # EQ ----------------------------------------------------------------
    def set_eq_low(self, gain: float) -> None:
        self._eq_low = max(-12.0, min(12.0, float(gain)))
        if self._eq_low_node is not None:
            self._set_attr(self._eq_low_node, "boost", self._eq_low)
        self.state_changed.emit()

    def set_eq_mid(self, gain: float) -> None:
        self._eq_mid = max(-12.0, min(12.0, float(gain)))
        if self._eq_mid_node is not None:
            self._set_attr(self._eq_mid_node, "boost", self._eq_mid)
        self.state_changed.emit()

    def set_eq_high(self, gain: float) -> None:
        self._eq_high = max(-12.0, min(12.0, float(gain)))
        if self._eq_high_node is not None:
            self._set_attr(self._eq_high_node, "boost", self._eq_high)
        self.state_changed.emit()

    # FX chain ---------------------------------------------------------
    def set_fx_mix(self, amount: float) -> None:
        self._fx_mix = max(0.0, min(1.0, float(amount)))
        if self._fx_mix_sig is not None:
            self._fx_mix_sig.setValue(self._fx_mix)
        self.state_changed.emit()

    def set_fx_delay(self, seconds: float) -> None:
        self._fx_delay = max(0.0, min(1.0, float(seconds)))
        if self._delay_node is not None:
            self._set_attr(self._delay_node, "delay", self._fx_delay, method_names=("setDelay",))
        self.state_changed.emit()

    def set_fx_feedback(self, amount: float) -> None:
        self._fx_feedback = max(0.0, min(0.95, float(amount)))
        if self._delay_node is not None:
            self._set_attr(self._delay_node, "feedback", self._fx_feedback, method_names=("setFeedback",))
        self.state_changed.emit()

    def set_fx_distortion(self, amount: float) -> None:
        self._fx_dist = max(0.0, min(1.0, float(amount)))
        if self._disto_node is not None:
            self._set_attr(self._disto_node, "drive", self._fx_dist, method_names=("setDrive",))
        self.state_changed.emit()

    # Spaces -----------------------------------------------------------
    def set_space_preset(self, preset: str) -> None:
        self._space_preset = str(preset) or "none"
        self._update_space_nodes()
        self.state_changed.emit()

    def set_space_mix(self, mix: float) -> None:
        self._space_mix = max(0.0, min(1.0, float(mix)))
        self._update_space_nodes()
        self.state_changed.emit()

    def set_space_decay(self, decay: float) -> None:
        self._space_decay = max(0.2, min(6.0, float(decay)))
        self._update_space_nodes()
        self.state_changed.emit()

    def set_space_predelay(self, predelay: float) -> None:
        self._space_pre = max(0.0, min(0.25, float(predelay)))
        if self._space_predelay is not None:
            self._set_attr(self._space_predelay, "delay", self._space_pre, method_names=("setDelay",))
        self.state_changed.emit()

    # Helpers ----------------------------------------------------------
    def _cleanup_effects(self) -> None:
        for node in self._effect_nodes:
            try:
                node.stop()
            except Exception:
                pass
        self._effect_nodes.clear()
        for node in self._generator_nodes:
            try:
                node.stop()
            except Exception:
                pass
        self._generator_nodes.clear()
        self._pitch_node = None
        self._muffle_node = None
        self._eq_low_node = None
        self._eq_mid_node = None
        self._eq_high_node = None
        self._disto_node = None
        self._delay_node = None
        self._fx_mix_sig = None
        self._fx_interp = None
        self._space_predelay = None
        self._reverb_node = None

    def _register_node(self, node: pyo.PyoObject) -> None:
        self._effect_nodes.append(node)

    def _register_generator(self, node: Optional[pyo.PyoObject]) -> None:
        if node is not None and node not in self._generator_nodes:
            self._generator_nodes.append(node)

    def _muffle_cutoff(self) -> float:
        if not self._muffle_enabled:
            return 20000.0
        amount = self._muffle_amount
        return 200.0 + (20000.0 - 200.0) * (amount ** 2)

    def _tone_wave_table(self, wave: str) -> pyo.PyoObject:
        key = wave.lower()
        table = self._tone_tables.get(key)
        if table is not None:
            return table
        table_map = {
            "sine": getattr(pyo, "SineTable", None),
            "square": getattr(pyo, "SquareTable", None),
            "triangle": getattr(pyo, "TriTable", None),
            "sawtooth": getattr(pyo, "SawTable", None),
        }
        table_cls = table_map.get(key) or getattr(pyo, "SineTable", None)
        table = None
        if table_cls is not None:
            try:
                table = table_cls()
            except Exception:
                table = None
        if table is None:
            fallback_cls = getattr(pyo, "SineTable", None)
            if fallback_cls is not None:
                try:
                    table = fallback_cls()
                except Exception:
                    table = None
        if table is None:
            size = 512
            table = pyo.DataTable(size=size)
            waveform = [math.sin((2.0 * math.pi * i) / size) for i in range(size)]
            table.replace(waveform)
        self._tone_tables[key] = table
        return table

    def _space_params(self) -> Tuple[float, float]:
        preset_defaults = {
            "none": (0.2, 0.5),
            "hall": (0.9, 0.6),
            "studio": (0.6, 0.3),
            "cabin": (0.4, 0.5),
        }
        base_size, base_damp = preset_defaults.get(self._space_preset, (0.6, 0.4))
        size = max(0.1, min(1.0, base_size * (self._space_decay / 1.2)))
        damp = max(0.0, min(1.0, base_damp + (self._space_mix - 0.5) * 0.3))
        return size, damp

    def _build_generators(self) -> Optional[pyo.PyoObject]:
        generators: List[pyo.PyoObject] = []

        if self._tone_enabled and self._tone_level > 0:
            freqs = [
                max(20.0, self._tone_base - self._tone_beat / 2.0),
                max(20.0, self._tone_base + self._tone_beat / 2.0),
            ]
            table = self._tone_wave_table(self._tone_wave)
            try:
                tone = pyo.Osc(table=table, freq=freqs, mul=self._tone_level)
            except Exception:
                tone = pyo.Sine(freq=freqs, mul=self._tone_level)
            self._register_generator(tone)
            tone_mix = pyo.Mix(tone, voices=2)
            generators.append(tone_mix)
            self._register_generator(tone_mix)

        if self._noise_enabled and self._noise_level > 0:
            noise_source: Optional[pyo.PyoObject] = None
            if self._noise_type == "pink":
                noise_source = pyo.PinkNoise(mul=self._noise_level)
            elif self._noise_type == "brown":
                noise_source = pyo.BrownNoise(mul=self._noise_level)
            else:
                noise_source = pyo.Noise(mul=self._noise_level)
            self._register_generator(noise_source)

            if self._noise_tilt != 0:
                if self._noise_tilt < 0:
                    cutoff = 500.0 + 19500.0 * (1.0 + self._noise_tilt)
                    noise_source = pyo.Biquad(noise_source, freq=cutoff, q=0.707, type=0)
                else:
                    cutoff = 20.0 + 8000.0 * self._noise_tilt
                    noise_source = pyo.Biquad(noise_source, freq=max(20.0, cutoff), q=0.707, type=1)
                self._register_generator(noise_source)

            noise_mix = pyo.Mix(noise_source, voices=2)
            generators.append(noise_mix)
            self._register_generator(noise_mix)

        if not generators:
            return None

        if len(generators) == 1:
            self._register_generator(generators[0])
            return generators[0]
        mix = generators[0]
        for gen in generators[1:]:
            mix = mix + gen
        self._register_generator(mix)
        return mix

    def _set_attr(
        self,
        obj: pyo.PyoObject,
        attr: str,
        value: float,
        *,
        method_names: Optional[Tuple[str, ...]] = None,
    ) -> None:
        if method_names:
            for name in method_names:
                if hasattr(obj, name):
                    try:
                        getattr(obj, name)(value)
                        return
                    except Exception:
                        continue
        if hasattr(obj, attr):
            try:
                setattr(obj, attr, value)
                return
            except Exception:
                pass
        method = f"set{attr.capitalize()}"
        if hasattr(obj, method):
            try:
                getattr(obj, method)(value)
            except Exception:
                pass

    def _update_space_nodes(self) -> None:
        size, damp = self._space_params()
        if self._reverb_node is not None:
            self._set_attr(self._reverb_node, "size", size, method_names=("setSize",))
            self._set_attr(self._reverb_node, "damp", damp, method_names=("setDamp",))
            bal = self._space_mix if self._space_preset != "none" else 0.0
            self._set_attr(self._reverb_node, "bal", bal, method_names=("setBal",))

    # State ------------------------------------------------------------
    def get_mod_state(self) -> Dict[str, Dict[str, object]]:
        return {
            "time_pitch": {
                "tempo": self._tempo,
                "pitch": self._pitch,
                "reverse_a": self._reverse_a,
                "reverse_b": self._reverse_b,
                "loop": self.loop,
            },
            "muffle": {
                "enabled": self._muffle_enabled,
                "amount": self._muffle_amount,
            },
            "tone": {
                "enabled": self._tone_enabled,
                "wave": self._tone_wave,
                "base": self._tone_base,
                "beat": self._tone_beat,
                "level": self._tone_level,
            },
            "noise": {
                "enabled": self._noise_enabled,
                "type": self._noise_type,
                "level": self._noise_level,
                "tilt": self._noise_tilt,
            },
            "eq": {
                "low": self._eq_low,
                "mid": self._eq_mid,
                "high": self._eq_high,
            },
            "fx": {
                "mix": self._fx_mix,
                "delay": self._fx_delay,
                "feedback": self._fx_feedback,
                "dist": self._fx_dist,
            },
            "space": {
                "preset": self._space_preset,
                "mix": self._space_mix,
                "decay": self._space_decay,
                "pre": self._space_pre,
            },
        }
