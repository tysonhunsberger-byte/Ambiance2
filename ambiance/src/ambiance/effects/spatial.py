"""Spatial and tonal effects for the Ambiance engine."""

from __future__ import annotations

from dataclasses import dataclass

from ..npcompat import np

from ..core.base import AudioEffect
from ..core.registry import registry


@dataclass
@registry.register_effect
class ReverbEffect(AudioEffect):
    """Simple Schroeder-style reverb using feedback delay networks."""

    name: str = "reverb"
    decay: float = 0.5
    mix: float = 0.3

    def apply(self, buffer: np.ndarray, sample_rate: int) -> np.ndarray:
        delays = [0.0297, 0.0371, 0.0411]
        wet = np.zeros_like(buffer, dtype=np.float32)
        for delay in delays:
            samples = int(delay * sample_rate)
            delayed = np.zeros_like(buffer, dtype=np.float32)
            if samples < len(buffer):
                delayed[samples:] = buffer[:-samples]
            wet += delayed
        wet *= self.decay / len(delays)
        return ((1 - self.mix) * buffer + self.mix * wet).astype(np.float32)

    def to_dict(self) -> dict[str, float]:
        data = super().to_dict()
        data.update({"decay": self.decay, "mix": self.mix})
        return data


@dataclass
@registry.register_effect
class DelayEffect(AudioEffect):
    """Stereo-like ping pong delay."""

    name: str = "delay"
    time: float = 0.25
    feedback: float = 0.3

    def apply(self, buffer: np.ndarray, sample_rate: int) -> np.ndarray:
        samples = int(self.time * sample_rate)
        output = np.copy(buffer).astype(np.float32)
        if samples >= len(buffer):
            return output
        delayed = np.zeros_like(buffer, dtype=np.float32)
        delayed[samples:] = buffer[:-samples]
        output += self.feedback * delayed
        return output

    def to_dict(self) -> dict[str, float]:
        data = super().to_dict()
        data.update({"time": self.time, "feedback": self.feedback})
        return data


@dataclass
@registry.register_effect
class LowPassFilterEffect(AudioEffect):
    """One-pole low pass filter to smooth the signal."""

    name: str = "lowpass"
    cutoff: float = 2000.0

    def apply(self, buffer: np.ndarray, sample_rate: int) -> np.ndarray:
        rc = 1 / (2 * np.pi * self.cutoff)
        dt = 1 / sample_rate
        alpha = dt / (rc + dt)
        out = np.zeros_like(buffer, dtype=np.float32)
        out[0] = alpha * buffer[0]
        for i in range(1, len(buffer)):
            out[i] = out[i - 1] + alpha * (buffer[i] - out[i - 1])
        return out

    def to_dict(self) -> dict[str, float]:
        data = super().to_dict()
        data.update({"cutoff": self.cutoff})
        return data
