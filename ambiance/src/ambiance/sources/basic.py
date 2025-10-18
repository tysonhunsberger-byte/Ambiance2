"""Built-in procedural audio sources."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..npcompat import np

from ..core.base import AudioSource
from ..core.registry import registry


@dataclass
@registry.register_source
class SineWaveSource(AudioSource):
    """Generate a sine wave of a given frequency."""

    name: str = "sine"
    frequency: float = 440.0
    amplitude: float = 0.3
    phase: float = 0.0

    def generate(self, duration: float, sample_rate: int) -> np.ndarray:
        total_samples = int(duration * sample_rate)
        t = np.linspace(0, duration, total_samples, endpoint=False)
        waveform = self.amplitude * np.sin(2 * math.pi * self.frequency * t + self.phase)
        return waveform.astype(np.float32)

    def to_dict(self) -> dict[str, float]:
        data = super().to_dict()
        data.update({
            "frequency": self.frequency,
            "amplitude": self.amplitude,
            "phase": self.phase,
        })
        return data


@dataclass
@registry.register_source
class NoiseSource(AudioSource):
    """White noise generator."""

    name: str = "noise"
    amplitude: float = 0.1
    seed: int | None = None

    def generate(self, duration: float, sample_rate: int) -> np.ndarray:
        rng = np.random.default_rng(self.seed)
        total_samples = int(duration * sample_rate)
        waveform = self.amplitude * rng.standard_normal(total_samples)
        return waveform.astype(np.float32)

    def to_dict(self) -> dict[str, float | int | None]:
        data = super().to_dict()
        data.update({
            "amplitude": self.amplitude,
            "seed": self.seed,
        })
        return data
