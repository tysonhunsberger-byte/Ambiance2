"""Core abstract interfaces for audio sources and effects."""

from __future__ import annotations

import abc
from typing import Any

from ..npcompat import np


class AudioSource(abc.ABC):
    """Base class for anything that can generate audio buffers."""

    name: str = "audio_source"

    @abc.abstractmethod
    def generate(self, duration: float, sample_rate: int) -> np.ndarray:
        """Produce an audio buffer for the given duration."""

    def to_dict(self) -> dict[str, Any]:
        """Serializable representation for configuration export."""
        return {"type": self.__class__.__name__}


class AudioEffect(abc.ABC):
    """Base class for post-processing effects."""

    name: str = "audio_effect"

    @abc.abstractmethod
    def apply(self, buffer: np.ndarray, sample_rate: int) -> np.ndarray:
        """Mutate or return a processed copy of the audio buffer."""

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.__class__.__name__}
