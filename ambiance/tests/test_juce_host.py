"""Tests for the JUCE VST3 host bridge."""

from __future__ import annotations

from pathlib import Path

from ambiance.integrations.juce_vst3_host import JuceVST3Host


def test_status_reports_unavailable_when_binary_missing(tmp_path: Path) -> None:
    host = JuceVST3Host(base_dir=tmp_path)
    status = host.status()
    assert not status.available
    assert status.executable is None
    assert not status.running


def test_launch_with_missing_plugin_sets_error(tmp_path: Path) -> None:
    host = JuceVST3Host(base_dir=tmp_path)
    target = tmp_path / "MissingPlugin.vst3"
    status = host.launch(target)
    assert not status.running
    assert status.plugin_path is None
    assert status.last_error and "does not exist" in status.last_error


def test_terminate_safe_when_not_running(tmp_path: Path) -> None:
    host = JuceVST3Host(base_dir=tmp_path)
    status = host.terminate()
    assert not status.running
    assert status.plugin_path is None


def test_discovers_visual_studio_release_binary(tmp_path: Path) -> None:
    exe = (
        tmp_path
        / "cpp"
        / "juce_host"
        / "build"
        / "JucePluginHost"
        / "Release"
        / "JucePluginHost.exe"
    )
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")
    exe.chmod(0o755)

    host = JuceVST3Host(base_dir=tmp_path)
    status = host.status()
    assert status.available
    assert status.executable == str(exe)


def test_discovers_nested_artefacts_binary(tmp_path: Path) -> None:
    exe = (
        tmp_path
        / "cpp"
        / "juce_host"
        / "build"
        / "JucePluginHost_artefacts"
        / "Release"
        / "Standalone"
        / "Ambiance JUCE Plugin Host.exe"
    )
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")
    exe.chmod(0o755)

    host = JuceVST3Host(base_dir=tmp_path)
    status = host.status()
    assert status.available
    assert status.executable == str(exe)
