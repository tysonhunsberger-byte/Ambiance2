from ambiance import AudioEngine, NoiseSource, SineWaveSource, ReverbEffect


def test_engine_renders_expected_length():
    engine = AudioEngine(sample_rate=22050)
    engine.add_source(SineWaveSource(frequency=220))
    engine.add_source(NoiseSource(amplitude=0.01, seed=123))
    engine.add_effect(ReverbEffect(decay=0.2, mix=0.1))

    duration = 1.5
    buffer = engine.render(duration)

    assert len(buffer) == int(duration * engine.sample_rate)
    assert buffer.dtype.name == "float32"
    assert buffer.max() <= 1.0
    assert buffer.min() >= -1.0
