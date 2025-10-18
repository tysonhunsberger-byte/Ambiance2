"""Audio utility helpers for serialization and diagnostics."""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Iterable

from ..npcompat import np


def write_wav(path: Path | str, buffer: np.ndarray, sample_rate: int) -> None:
    """Write a mono WAV file from a normalized floating point buffer."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    scaled = np.clip(buffer, -1.0, 1.0)
    pcm = (scaled * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def encode_wav_bytes(buffer: np.ndarray, sample_rate: int) -> bytes:
    """Return WAV-formatted bytes for an in-memory buffer."""

    scaled = np.clip(buffer, -1.0, 1.0)
    pcm = (scaled * 32767).astype(np.int16)
    with io.BytesIO() as bio:
        with wave.open(bio, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm.tobytes())
        return bio.getvalue()


def normalize(buffers: Iterable[np.ndarray]) -> Iterable[np.ndarray]:
    """Normalize buffers to prevent clipping when mixing externally."""
    buffers = list(buffers)
    if not buffers:
        return buffers
    max_amp = max(np.max(np.abs(buffer)) for buffer in buffers)
    if max_amp == 0:
        return buffers
    return [buffer / max_amp for buffer in buffers]
