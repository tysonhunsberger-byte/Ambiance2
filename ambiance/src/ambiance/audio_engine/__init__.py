"""Audio engine package providing block/stream playback for the desktop app."""

from __future__ import annotations

from typing import Any, Optional

AUDIO_ENGINE_IMPORT_ERROR: Optional[BaseException] = None

try:
    from .engine import AudioEngine, BlockController, StreamController
except RuntimeError as exc:  # pragma: no cover - optional dependency missing
    AUDIO_ENGINE_IMPORT_ERROR = exc

    class _AudioUnavailable:
        """Placeholder that raises a helpful error when pyo is unavailable."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError(
                "The Ambiance audio engine is disabled because the 'pyo' package "
                "is not installed for this Python interpreter."
            ) from AUDIO_ENGINE_IMPORT_ERROR

    AudioEngine = _AudioUnavailable  # type: ignore[assignment]
    BlockController = _AudioUnavailable  # type: ignore[assignment]
    StreamController = _AudioUnavailable  # type: ignore[assignment]
else:
    AUDIO_ENGINE_IMPORT_ERROR = None

__all__ = ["AudioEngine", "BlockController", "StreamController", "AUDIO_ENGINE_IMPORT_ERROR"]
