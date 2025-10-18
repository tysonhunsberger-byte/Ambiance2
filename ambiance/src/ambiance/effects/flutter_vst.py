"""Audio effect wrapper that uses the Flutter VST host shim."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.base import AudioEffect
from ..core.registry import registry
from ..integrations.flutter_vst_host import FlutterVSTHost


@dataclass
@registry.register_effect
class FlutterVSTEffect(AudioEffect):
    """Run a Flutter VST plugin inside the Ambiance offline renderer."""

    name: str = "flutter_vst"
    plugin_path: str = ""
    parameters: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.plugin_path:
            raise ValueError("Provide 'plugin_path' when creating FlutterVSTEffect")
        self._host = FlutterVSTHost()
        self._instance = self._host.create_effect(self.plugin_path, parameters=self.parameters)

    def apply(self, buffer, sample_rate: int):
        return self._instance.process(buffer, sample_rate)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "plugin_path": self.plugin_path,
                "parameters": dict(self.parameters),
            }
        )
        return data
