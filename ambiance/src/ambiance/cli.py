"""Command-line interface for rendering procedural ambience tracks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import (
    AudioEngine,
    DelayEffect,
    LowPassFilterEffect,
    NoiseSource,
    ResonantInstrumentSource,
    ReverbEffect,
    SineWaveSource,
    VocalFormantSource,
)
from .core.registry import registry
from .utils.audio import write_wav


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Path to the output WAV file")
    parser.add_argument("--duration", type=float, default=5.0, help="Duration in seconds")
    parser.add_argument("--sample-rate", type=int, default=44100, help="Sample rate")
    parser.add_argument("--config", type=Path, help="JSON config describing sources/effects")
    return parser


def _create_from_config(kind: str, config: dict) -> object:
    payload = dict(config)
    name = payload.pop("name", payload.pop("type", None))
    if not name:
        raise ValueError(f"Missing identifier for {kind}")
    if kind == "source":
        return registry.create_source(name, **payload)
    if kind == "effect":
        return registry.create_effect(name, **payload)
    raise ValueError(f"Unsupported kind '{kind}'")


def run_from_config(engine: AudioEngine, config_path: Path) -> None:
    data = json.loads(config_path.read_text())
    for source_conf in data.get("sources", []):
        engine.add_source(_create_from_config("source", source_conf))
    for effect_conf in data.get("effects", []):
        engine.add_effect(_create_from_config("effect", effect_conf))


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    engine = AudioEngine(sample_rate=args.sample_rate)

    if args.config:
        run_from_config(engine, args.config)
    else:
        engine.add_source(SineWaveSource(frequency=432, amplitude=0.2))
        engine.add_source(NoiseSource(amplitude=0.05))
        engine.add_source(ResonantInstrumentSource())
        engine.add_source(VocalFormantSource(vowel="o", amplitude=0.15))
        engine.add_effect(ReverbEffect())
        engine.add_effect(DelayEffect(time=0.35, feedback=0.25))
        engine.add_effect(LowPassFilterEffect(cutoff=5500))

    buffer = engine.render(duration=args.duration)
    write_wav(args.output, buffer, engine.sample_rate)
    print(f"Rendered ambience to {args.output} ({len(buffer)} samples)")


if __name__ == "__main__":
    main()
