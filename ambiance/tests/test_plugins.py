import zipfile

from ambiance.integrations.plugins import PluginRackManager


def test_status_reports_workspace(tmp_path):
    manager = PluginRackManager(base_dir=tmp_path)

    status = manager.status()

    assert status["workspace"] == str(manager.workspace_path())
    assert status["workspace_exists"] is True
    assert status["plugins"] == []
    assert "Main" in status["streams"]


def test_discover_plugins(tmp_path):
    manager = PluginRackManager(base_dir=tmp_path)
    workspace = manager.workspace_path()

    (workspace / "DreamSynth.vst3").mkdir(parents=True)
    (workspace / "textures.mc.svt").write_text("dummy")

    entries = manager.discover_plugins()
    names = {entry["name"] for entry in entries}

    assert "DreamSynth" in names
    assert "textures" in names


def test_assign_and_toggle(tmp_path):
    manager = PluginRackManager(base_dir=tmp_path)
    workspace = manager.workspace_path()
    plugin = workspace / "bassline.vst3"
    plugin.mkdir()

    result = manager.assign_plugin(plugin, stream="Bass", lane="A")

    assert result["stream"] == "Bass"
    assert result["lane"] == "A"
    status = manager.status()
    lane_entries = status["streams"]["Bass"]["lanes"]["A"]
    assert lane_entries and lane_entries[0]["plugin"]["path"] == str(plugin)

    toggle = manager.toggle_lane("Bass")
    assert toggle["active_lane"] == "B"


def test_remove_plugin(tmp_path):
    manager = PluginRackManager(base_dir=tmp_path)
    workspace = manager.workspace_path()
    plugin = workspace / "pad.svt"
    plugin.write_text("data")

    manager.assign_plugin(plugin, stream="Main", lane="B", slot=3)
    removed = manager.remove_plugin(stream="Main", lane="B", slot=3)

    assert removed["removed"]
    status = manager.status()
    assert status["streams"]["Main"]["lanes"]["B"] == []


def test_modalys_bundle_installation(tmp_path):
    archive = tmp_path / "Modalys Bundle.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Modalys for Max/externals/mlys~.mxe64", b"stub")

    manager = PluginRackManager(base_dir=tmp_path)

    plugin_file = manager.workspace_path() / "Modalys" / "Modalys.mxe64"
    assert plugin_file.exists()

    entries = manager.discover_plugins()
    modalys = next((entry for entry in entries if "Modalys" in entry["name"]), None)

    assert modalys is not None
    assert modalys.get("origin") == "Bundled Modalys package"
    assert modalys.get("display_name") == "Modalys (Max)"

    notes = manager.status()["notes"]
    assert any("Modalys" in note for note in notes)
