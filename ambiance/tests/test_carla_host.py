import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ambiance.integrations import carla_host


class _DummyBackend:
    def __init__(self, base_dir=None, **_: object) -> None:
        self.available = True
        self.warnings: list[str] = []
        self._plugin: dict[str, str] | None = None
        self.closed = False
        self.load_calls: list[str] = []
        self.show_requests: list[bool] = []
        self.configure_calls: list[dict[str, object]] = []
        self.ui_visible = False
        self.supports_ui = True

    def can_handle_path(self, path: Path) -> bool:
        return path.suffix.lower() == ".vst3"

    def status(self) -> dict:
        return {
            "available": True,
            "plugin": self._plugin,
            "parameters": [],
            "capabilities": {"editor": self.supports_ui, "instrument": False},
            "ui_visible": self.ui_visible,
            "engine": {
                "running": False,
                "driver": "Dummy",
                "forced_driver": None,
                "preferred_drivers": ["Dummy"],
                "sample_rate": 48000,
                "buffer_size": 256,
            },
        }

    def load_plugin(self, plugin_path: Path, parameters=None, *, show_ui: bool = False) -> dict:
        self.load_calls.append(str(plugin_path))
        self.show_requests.append(show_ui)
        self._plugin = {"path": str(plugin_path)}
        self.ui_visible = bool(show_ui and self.supports_ui)
        return self._plugin

    def unload(self) -> None:
        self._plugin = None
        self.ui_visible = False

    def set_parameter(self, identifier, value):
        return {"id": identifier, "value": value}

    def describe_ui(self, plugin_path=None):
        return {
            "plugin": self._plugin,
            "path": str(plugin_path) if plugin_path else None,
            "capabilities": {"editor": self.supports_ui},
        }

    def show_ui(self) -> dict:
        if not self._plugin:
            raise carla_host.CarlaHostError("No plugin hosted")
        if not self.supports_ui:
            raise carla_host.CarlaHostError("Plugin does not expose a custom UI")
        self.ui_visible = True
        return self.status()

    def hide_ui(self) -> dict:
        if not self._plugin:
            raise carla_host.CarlaHostError("No plugin hosted")
        self.ui_visible = False
        return self.status()

    def close(self) -> None:
        self.closed = True
        self.unload()

    def configure_audio(
        self,
        *,
        forced_driver=None,
        preferred_drivers=None,
        sample_rate=None,
        buffer_size=None,
    ) -> None:
        self.configure_calls.append(
            {
                "forced_driver": forced_driver,
                "preferred_drivers": preferred_drivers,
                "sample_rate": sample_rate,
                "buffer_size": buffer_size,
            }
        )


class _FailingBackend(_DummyBackend):
    def load_plugin(self, plugin_path: Path, parameters=None, *, show_ui: bool = False) -> dict:
        raise carla_host.CarlaHostError("backend rejected plugin")


def test_carla_vst_host_loads_via_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(carla_host, "CarlaBackend", _DummyBackend)

    plugin_path = tmp_path / "Test.vst3"
    plugin_path.write_text("stub")

    host = carla_host.CarlaVSTHost(base_dir=tmp_path)
    plugin = host.load_plugin(plugin_path)

    assert plugin["path"] == str(plugin_path)
    assert host._backend.load_calls == [str(plugin_path)]  # type: ignore[attr-defined]
    assert host._backend.show_requests == [True]  # type: ignore[attr-defined]
    status = host.status()
    assert status["plugin"]["path"] == str(plugin_path)
    assert status["engine"]["preferred_drivers"] == ["Dummy"]


def test_carla_vst_host_shutdown(monkeypatch, tmp_path):
    monkeypatch.setattr(carla_host, "CarlaBackend", _DummyBackend)

    plugin_path = tmp_path / "Another.vst3"
    plugin_path.write_text("stub")

    host = carla_host.CarlaVSTHost(base_dir=tmp_path)
    host.load_plugin(plugin_path)
    host.shutdown()

    assert host._backend.closed is True  # type: ignore[attr-defined]
    assert host._backend.status()["plugin"] is None  # type: ignore[attr-defined]


def test_carla_vst_host_ui_toggle(monkeypatch, tmp_path):
    monkeypatch.setattr(carla_host, "CarlaBackend", _DummyBackend)

    plugin_path = tmp_path / "UiPlugin.vst3"
    plugin_path.write_text("stub")

    host = carla_host.CarlaVSTHost(base_dir=tmp_path)
    host.load_plugin(plugin_path)

    status = host.show_ui()
    assert status["ui_visible"] is True

    status = host.hide_ui()
    assert status["ui_visible"] is False


def test_carla_vst_host_propagates_backend_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(carla_host, "CarlaBackend", _FailingBackend)

    plugin_path = tmp_path / "Broken.vst3"
    plugin_path.write_text("stub")

    host = carla_host.CarlaVSTHost(base_dir=tmp_path)

    with pytest.raises(carla_host.CarlaHostError) as exc:
        host.load_plugin(plugin_path)

    assert "backend rejected plugin" in str(exc.value)


def test_carla_vst_host_configure_audio_delegates(monkeypatch, tmp_path):
    monkeypatch.setattr(carla_host, "CarlaBackend", _DummyBackend)

    host = carla_host.CarlaVSTHost(base_dir=tmp_path)
    host.configure_audio(
        forced_driver="ASIO",
        preferred_drivers=["ASIO", "Dummy"],
        sample_rate=96000,
        buffer_size=512,
    )

    assert host._backend.configure_calls == [  # type: ignore[attr-defined]
        {
            "forced_driver": "ASIO",
            "preferred_drivers": ["ASIO", "Dummy"],
            "sample_rate": 96000,
            "buffer_size": 512,
        }
    ]


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows-only binary inspection")
def test_carla_backend_binary_type_prefers_bridge_when_needed(monkeypatch):
    backend = carla_host.CarlaBackend.__new__(carla_host.CarlaBackend)
    backend.module = SimpleNamespace(BINARY_NATIVE=0, BINARY_WIN32=1, BINARY_WIN64=2)
    backend.root = None
    backend.library_path = None
    backend._find_pe_image = lambda path: path  # type: ignore[assignment]
    backend._detect_pe_architecture = lambda image: 32  # type: ignore[assignment]

    win32_type = backend._binary_type_for(Path("Plugin.vst3"), 0)
    assert win32_type == 1

    backend._detect_pe_architecture = lambda image: 64  # type: ignore[assignment]
    win64_type = backend._binary_type_for(Path("Plugin.vst3"), 0)
    assert win64_type == 2
