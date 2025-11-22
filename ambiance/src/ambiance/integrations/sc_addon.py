"""Optional SuperCollider add-on that exposes automation, FX, and recording hooks."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict

from .supercollider_host import SuperColliderBridge, SuperColliderBridgeError


LOGGER = logging.getLogger("ambiance.sc_addon")


def _escape(string: str) -> str:
    return string.replace("\\", "\\\\").replace('"', r"\"")


class SuperColliderAddon:
    """Manage optional SuperCollider automation/effects outside the main plugin host."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        bridge: SuperColliderBridge | None = None,
        render_root: Path | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.bridge = bridge or (SuperColliderBridge() if enabled else None)
        self.render_root = Path(render_root or Path.cwd() / "outputs").resolve()
        self.render_root.mkdir(parents=True, exist_ok=True)
        self._booted = False
        self._last_error: str | None = None
        self._effects_state: Dict[str, float] = {
            "mix": 0.25,
            "decay": 3.0,
            "cutoff": 4000.0,
        }
        if self.enabled:
            try:
                self.boot()
            except Exception as exc:  # pragma: no cover - safety net
                self._last_error = str(exc)
                LOGGER.error("SuperCollider add-on failed at initialization: %s", exc)
        else:
            LOGGER.info("SuperCollider add-on disabled (set AMB_SC_ADDON=1 to enable).")

    # ------------------------------------------------------------------
    def boot(self) -> bool:
        if not self.enabled or self.bridge is None:
            return False
        if self._booted:
            return True
        LOGGER.info("Booting SuperCollider add-on (sclang/scsynth via supercolliderjs)...")
        try:
            self.bridge.boot()
            self._install_synthdefs()
            self._booted = True
            self._last_error = None
            LOGGER.info("SuperCollider add-on connected to sclang/scsynth.")
        except Exception as exc:  # pragma: no cover - depends on local SC env
            self._booted = False
            self._last_error = str(exc)
            LOGGER.error("SuperCollider add-on boot failure: %s", exc)
            raise
        return self._booted

    def ensure_ready(self) -> bool:
        if not self.enabled:
            return False
        if self._booted:
            return True
        return self.boot()

    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "booted": self._booted,
            "last_error": self._last_error,
            "effects": self._effects_state,
        }

    # ------------------------------------------------------------------
    def send_automation(self, target: str, value: float, *, ramp: float | None = None) -> None:
        if not target:
            raise ValueError("Automation target is required")
        if not self.ensure_ready():
            raise RuntimeError("SuperCollider add-on unavailable")
        ramp = 0.05 if ramp is None else max(0.0, float(ramp))
        literal = _escape(target)
        LOGGER.debug("SC automation target %s -> %s (ramp=%s)", target, value, ramp)
        code = f"""
        {{
            var key = "{literal}";
            var val = {float(value)};
            var ramp = {ramp};
            if(~ambianceAutomation.isNil) {{
                ~ambianceAutomation = Dictionary.new;
            }};
            var bus = ~ambianceAutomation[key];
            if(bus.isNil) {{
                bus = Bus.control(s, 1);
                ~ambianceAutomation[key] = bus;
            }};
            bus.set(val);
        }}
        """
        self.bridge.evaluate(code)  # type: ignore[union-attr]

    def apply_effects(self, mix: float | None = None, decay: float | None = None, cutoff: float | None = None) -> None:
        if not self.ensure_ready():
            raise RuntimeError("SuperCollider add-on unavailable")
        if mix is not None:
            self._effects_state["mix"] = max(0.0, min(1.0, float(mix)))
        if decay is not None:
            self._effects_state["decay"] = max(0.1, float(decay))
        if cutoff is not None:
            self._effects_state["cutoff"] = max(80.0, float(cutoff))
        state = self._effects_state
        LOGGER.debug(
            "SC FX update mix=%s decay=%s cutoff=%s",
            state["mix"],
            state["decay"],
            state["cutoff"],
        )
        code = f"""
        {{
            var params = [\\mix, {state['mix']}, \\decay, {state['decay']}, \\cutoff, {state['cutoff']}];
            if(~ambianceFXNode.isNil) {{
                ~ambianceFXNode = Synth.tail(s, \\ambiance_fx_rack);
            }};
            ~ambianceFXNode.set(*params);
        }}
        """
        self.bridge.evaluate(code)  # type: ignore[union-attr]

    def record_to_file(self, duration: float, *, filename: str | None = None) -> Path:
        if duration <= 0:
            raise ValueError("Duration must be positive")
        if not self.ensure_ready():
            raise RuntimeError("SuperCollider add-on unavailable")
        output = Path(filename) if filename else self.render_root / f"sc_record_{int(time.time())}.wav"
        output.parent.mkdir(parents=True, exist_ok=True)
        escaped_path = _escape(str(output))
        LOGGER.info("Recording SuperCollider output to %s (duration %.2fs)", output, duration)
        code = f"""
        {{
            var path = "{escaped_path}";
            var duration = {float(duration)};
            var frames = (duration * s.sampleRate).asInteger;
            var buffer = Buffer.alloc(s, frames, 2);
            var recorder = Synth.tail(s, \\ambiance_record_bus, [\\buffer, buffer]);
            SystemClock.sched(duration + 0.1, {{
                buffer.write(path, headerFormat: "wav", sampleFormat: "float", leaveOpen: false);
                recorder.free;
                buffer.free;
            }});
        }}
        """
        self.bridge.evaluate(code)  # type: ignore[union-attr]
        LOGGER.info("SC recording scheduled -> %s", output)
        return output

    # ------------------------------------------------------------------
    def _install_synthdefs(self) -> None:
        if self.bridge is None:
            return
        LOGGER.debug("Installing SuperCollider SynthDefs for add-on FX and recorder.")
        code = r"""
        (
        SynthDef("ambiance_fx_rack", { |inBus = 0, outBus = 0, mix = 0.25, decay = 3.0, cutoff = 4000|
            var dry = In.ar(inBus, 2);
            var wet = FreeVerb2.ar(dry[0], dry[1], mix.clip(0, 0.99), decay, 0.5);
            var filtered = RLPF.ar(wet, cutoff.max(80), 0.6);
            Out.ar(outBus, XFade2.ar(dry, filtered, mix * 2 - 1));
        }).add;

        SynthDef("ambiance_record_bus", { |buffer|
            var input = In.ar(0, 2);
            RecordBuf.ar(input, buffer, loop: 0);
        }).add;
        )
        """
        self.bridge.evaluate(code)
        # Ensure FX node exists
        init_code = """
        {
            if(~ambianceFXNode.isNil) {
                ~ambianceFXNode = Synth.tail(s, \\ambiance_fx_rack);
            };
        }
        """
        self.bridge.evaluate(init_code)
        LOGGER.debug("SC add-on SynthDefs installed and FX node initialized.")
