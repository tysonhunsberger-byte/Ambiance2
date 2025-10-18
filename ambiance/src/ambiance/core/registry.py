"""Central registry for discovering audio sources and effects."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Dict, Iterable, Type

from .base import AudioEffect, AudioSource


class _Registry:
    """Simple pluggable registry for sources and effects."""

    def __init__(self) -> None:
        self._sources: Dict[str, Type[AudioSource]] = {}
        self._effects: Dict[str, Type[AudioEffect]] = {}
        self._listeners: Dict[str, list[Callable[[], None]]] = defaultdict(list)

    def register_source(self, cls: Type[AudioSource]) -> Type[AudioSource]:
        self._sources[cls.name] = cls
        self._notify("source")
        return cls

    def register_effect(self, cls: Type[AudioEffect]) -> Type[AudioEffect]:
        self._effects[cls.name] = cls
        self._notify("effect")
        return cls

    def sources(self) -> Iterable[str]:
        return sorted(self._sources.keys())

    def effects(self) -> Iterable[str]:
        return sorted(self._effects.keys())

    def create_source(self, name: str, **kwargs) -> AudioSource:
        if name not in self._sources:
            raise KeyError(f"Unknown source '{name}'")
        return self._sources[name](**kwargs)  # type: ignore[arg-type]

    def create_effect(self, name: str, **kwargs) -> AudioEffect:
        if name not in self._effects:
            raise KeyError(f"Unknown effect '{name}'")
        return self._effects[name](**kwargs)  # type: ignore[arg-type]

    def listen(self, kind: str, callback: Callable[[], None]) -> None:
        self._listeners[kind].append(callback)

    def _notify(self, kind: str) -> None:
        for callback in self._listeners[kind]:
            callback()


registry = _Registry()
