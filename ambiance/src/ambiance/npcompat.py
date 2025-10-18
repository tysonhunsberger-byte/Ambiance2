"""Compat shim that provides either NumPy or a pure Python fallback."""

from __future__ import annotations

try:  # pragma: no cover - exercised indirectly
    import numpy as np  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - triggered in CI without numpy
    from . import simple_numpy as np  # type: ignore

__all__ = ["np"]
