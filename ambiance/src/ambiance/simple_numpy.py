"""Very small, pure-Python subset of NumPy used as a fallback."""

from __future__ import annotations

import builtins
import math
import random as _stdlib_random
from typing import Iterable, Sequence


class _DType:
    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"dtype('{self.name}')"


float32 = _DType("float32")
int16 = _DType("int16")
pi = math.pi


class SimpleArray(list):
    """List-backed array with a NumPy-like surface."""

    def __init__(self, data: Iterable[float] | int = 0, dtype=float32):
        if isinstance(data, int):
            fill = [0] * data if dtype is int16 else [0.0] * data
            super().__init__(fill)
        else:
            if dtype is int16:
                super().__init__(int(round(x)) for x in data)
            else:
                super().__init__(float(x) for x in data)
        self.dtype = dtype

    def __getitem__(self, item):  # type: ignore[override]
        result = super().__getitem__(item)
        if isinstance(item, slice):
            return SimpleArray(result)
        return result

    def __setitem__(self, key, value):  # type: ignore[override]
        if isinstance(key, slice):
            if isinstance(value, SimpleArray):
                value = list(value)
            super().__setitem__(key, value)
        else:
            super().__setitem__(key, float(value))

    def astype(self, dtype=float32):
        if dtype is float32:
            return SimpleArray(list(self), dtype=float32)
        if dtype is int16:
            return SimpleArray([int(round(v)) for v in self], dtype=int16)
        return SimpleArray([dtype(v) for v in self], dtype=dtype)

    def copy(self) -> "SimpleArray":
        return SimpleArray(list(self), dtype=self.dtype)

    @property
    def shape(self) -> tuple[int]:
        return (len(self),)

    def max(self) -> float:
        return max(self) if self else 0.0

    def min(self) -> float:
        return min(self) if self else 0.0

    def __add__(self, other):
        if isinstance(other, SimpleArray):
            return SimpleArray([a + b for a, b in zip(self, other)], dtype=self.dtype)
        return SimpleArray([a + float(other) for a in self], dtype=self.dtype)

    def __iadd__(self, other):
        if isinstance(other, SimpleArray):
            for i, value in enumerate(other):
                if i < len(self):
                    self[i] = float(self[i]) + float(value)
        else:
            delta = float(other)
            for i in range(len(self)):
                self[i] = float(self[i]) + delta
        return self

    def __mul__(self, other):
        return SimpleArray([float(v) * float(other) for v in self], dtype=self.dtype)

    def __rmul__(self, other):
        return self.__mul__(other)

    def __imul__(self, other):
        factor = float(other)
        for i in range(len(self)):
            self[i] = float(self[i]) * factor
        return self

    def __truediv__(self, other):
        divisor = float(other)
        return SimpleArray([float(v) / divisor for v in self], dtype=self.dtype)

    def __itruediv__(self, other):
        divisor = float(other)
        for i in range(len(self)):
            self[i] = float(self[i]) / divisor
        return self


def array(data: Iterable[float]) -> SimpleArray:
    return SimpleArray(data)


def zeros(length: int, dtype=float32) -> SimpleArray:
    return SimpleArray([0.0] * length, dtype=dtype)


def zeros_like(arr: Sequence[float], dtype=float32) -> SimpleArray:
    return SimpleArray([0.0] * len(arr), dtype=dtype)


def linspace(start: float, stop: float, num: int, endpoint: bool = True) -> SimpleArray:
    if num <= 0:
        return SimpleArray([])
    if num == 1:
        return SimpleArray([start])
    if endpoint:
        step = (stop - start) / (num - 1)
        return SimpleArray(start + step * i for i in range(num))
    else:
        step = (stop - start) / num
        return SimpleArray(start + step * i for i in range(num))


def sin(x):
    if isinstance(x, SimpleArray):
        return SimpleArray(math.sin(v) for v in x)
    return math.sin(x)


def exp(x):
    if isinstance(x, SimpleArray):
        return SimpleArray(math.exp(v) for v in x)
    return math.exp(x)


def max(array_like: Sequence[float]) -> float:
    return builtins_max(array_like) if array_like else 0.0


def abs(array_like):
    if isinstance(array_like, SimpleArray):
        return SimpleArray(builtins_abs(v) for v in array_like)
    return builtins_abs(array_like)


def clip(array_like: Sequence[float], min_value: float, max_value: float) -> SimpleArray:
    dtype = getattr(array_like, "dtype", float32)
    return SimpleArray([
        builtins_min(builtins_max(v, min_value), max_value) for v in array_like
    ], dtype=dtype)


def copy(array_like: Sequence[float]) -> SimpleArray:
    return SimpleArray(array_like)


class _Generator:
    def __init__(self, seed: int | None = None) -> None:
        self._rng = _stdlib_random.Random(seed)

    def standard_normal(self, size: int) -> SimpleArray:
        return SimpleArray(self._rng.gauss(0.0, 1.0) for _ in range(size))


class _RandomModule:
    def default_rng(self, seed: int | None = None) -> _Generator:
        return _Generator(seed)


random = _RandomModule()


def asarray(data: Iterable[float]) -> SimpleArray:
    return SimpleArray(data)


def tobytes(arr: SimpleArray) -> bytes:
    import struct

    if arr.dtype is int16:
        return b"".join(struct.pack("<h", int(v)) for v in arr)
    if arr.dtype is float32:
        return b"".join(struct.pack("<f", float(v)) for v in arr)
    return b"".join(struct.pack("<f", float(v)) for v in arr)


SimpleArray.tobytes = tobytes  # type: ignore[attr-defined]


ndarray = SimpleArray


def sqrt(x: float) -> float:
    return math.sqrt(x)


builtins_max = builtins.max
builtins_min = builtins.min
builtins_abs = builtins.abs
