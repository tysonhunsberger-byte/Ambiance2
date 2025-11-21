"""SuperCollider VST hosting utilities built on top of vstplugin."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable, Sequence

from .supercollider_host import SuperColliderBridge, SuperColliderBridgeError

LOGGER = logging.getLogger(__name__)


def _escape_sc_string(text: str) -> str:
    """Escape a Python string for inclusion inside SuperCollider code."""
    return text.replace("\\", "\\\\").replace('"', r"\"")


class VSTPluginBridge:
    """Drive the vstplugin SuperCollider extensions via supercolliderjs."""

    def __init__(
        self,
        *,
        bridge: SuperColliderBridge | None = None,
        extensions_path: str | Path | None = None,
    ) -> None:
        self.bridge = bridge or SuperColliderBridge()
        repo_root = Path(__file__).resolve().parents[4]
        self.extensions_path = Path(extensions_path) if extensions_path else repo_root / "vstplugin-master" / "sc"
        self._booted = False

    # ------------------------------------------------------------------
    def boot(self, *, include_paths: Iterable[str] | None = None) -> None:
        """Ensure SuperCollider is running with the vstplugin extensions loaded."""
        paths: list[str] = []
        if include_paths:
            paths.extend(str(Path(p)) for p in include_paths)
        if paths:
            self.bridge.boot(include_paths=paths)
        else:
            self.bridge.boot()
        self._booted = True

    def ensure_booted(self) -> None:
        if not self._booted:
            self.boot()

    # ------------------------------------------------------------------
    def load_plugin(
        self,
        plugin_path: str | Path,
        *,
        channels: int = 2,
        open_editor: bool = True,
    ) -> None:
        """Open a VST plugin via VSTPluginController."""
        self.ensure_booted()
        resolved = Path(plugin_path).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"VST plugin not found: {resolved}")
        normalized_path = str(resolved).replace("\\", "/")
        LOGGER.info("Loading VST plugin via SuperCollider: %s", normalized_path)
        escaped = _escape_sc_string(normalized_path)
        bool_literal = "true" if open_editor else "false"
        code = f"""
        Routine.run({{
            try {{
                s.bind({{
                    var synthDefName = \\ambiance_vst_host;
                    if(SynthDescLib.global.at(synthDefName).isNil) {{
                        SynthDef(synthDefName, {{
                            var sig = VSTPlugin.ar(Silent.ar({channels}), {channels}, id: \\ambianceVST);
                            Out.ar(0, sig);
                        }}).add;
                        s.sync;
                    }};
                    if(~ambianceVSTSynth.notNil) {{ ~ambianceVSTSynth.free; }};
                    ~ambianceVSTSynth = Synth(\\ambiance_vst_host);
                    s.sync;
                    if(~ambianceVSTController.notNil) {{ ~ambianceVSTController.free; }};
                    ~ambianceVSTController = VSTPluginController(~ambianceVSTSynth, \\ambianceVST);
                    ~ambianceVSTController.open(path: "{escaped}", editor: {bool_literal});
                }});
                "~AMBIANCE_VST_OK~".postln;
            }} {{
                |error|
                error.reportError;
                ("Ambiance VST load failed for path: {escaped}").postln;
                Error("Ambiance VST load failed. See SuperCollider log for details.").throw;
            }};
        }});
        """
        try:
            self.bridge.evaluate(code)
        except SuperColliderBridgeError as exc:
            hint = (
                "Ensure the SuperCollider 'VSTPlugin' extension is built and installed. "
                "See vstplugin-master/README for build instructions."
            )
            raise SuperColliderBridgeError(f"{exc}\n{hint}") from exc

    def send_midi(self, status: int, data1: int, data2: int) -> None:
        """Send raw MIDI data to the active plugin."""
        self.ensure_booted()
        code = f"""
        {{
            if(~ambianceVSTController.notNil) {{
                ~ambianceVSTController.sendMidi({int(status)}, {int(data1)}, {int(data2)});
            }};
        }}
        """
        self.bridge.evaluate(code)

    def show_editor(self) -> None:
        """Re-open the plugin editor window."""
        self.ensure_booted()
        code = """
        {
            if(~ambianceVSTController.notNil) {
                ~ambianceVSTController.open(editor: true);
            };
        }
        """
        self.bridge.evaluate(code)

    def close_plugin(self) -> None:
        """Close and free the currently loaded plugin instance."""
        self.ensure_booted()
        code = """
        {
            if(~ambianceVSTController.notNil) { ~ambianceVSTController.close; ~ambianceVSTController = nil; };
            if(~ambianceVSTSynth.notNil) { ~ambianceVSTSynth.free; ~ambianceVSTSynth = nil; };
        }
        """
        self.bridge.evaluate(code)

    def set_parameter(self, index: int, value: float) -> None:
        """Set a plugin parameter by index."""
        self.ensure_booted()
        code = f"""
        {{
            if(~ambianceVSTController.notNil) {{
                ~ambianceVSTController.set({index}, {float(value)});
            }};
        }}
        """
        self.bridge.evaluate(code)

    def program_change(self, program: int) -> None:
        """Change the plugin program/bank."""
        self.ensure_booted()
        code = f"""
        {{
            if(~ambianceVSTController.notNil) {{
                ~ambianceVSTController.program_({program});
            }};
        }}
        """
        self.bridge.evaluate(code)

    def list_plugins(self, paths: Sequence[str] | None = None) -> list[dict[str, str]]:
        """Use VSTPlugin.search to enumerate available plugins."""
        self.ensure_booted()
        search_paths = [str(Path(p).expanduser()) for p in (paths or [])]
        path_literal = "[" + ", ".join(f'"{_escape_sc_string(p)}"' for p in search_paths) + "]" if search_paths else "nil"
        code = f"""
        {{
            var searchPaths = {path_literal};
            VSTPlugin.search(dir: searchPaths, verbose: false);
            if(VSTPlugin.plugins.isNil or: {{ VSTPlugin.plugins.isEmpty }}) {{
                "[]"
            }} {{
                var results = VSTPlugin.plugins.collect {{ |desc|
                    (
                        key: desc.key,
                        path: desc.path ?? "",
                        name: desc.name ?? desc.displayName ?? desc.key,
                        format: desc.format ?? "unknown"
                    )
                }};
                results.asJSON;
            }}
        }}
        """
        result = self.bridge.evaluate(code, as_string=True)
        try:
            return json.loads(result) if isinstance(result, str) else []
        except json.JSONDecodeError:
            return []
