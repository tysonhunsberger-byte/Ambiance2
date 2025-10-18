from ambiance.server import render_payload


def test_render_payload_produces_audio_data_url():
    payload = {
        "duration": 0.1,
        "sample_rate": 8000,
        "sources": [
            {"name": "sine", "frequency": 220, "amplitude": 0.1},
        ],
        "effects": [
            {"name": "lowpass", "cutoff": 1000},
        ],
    }

    response = render_payload(payload)

    assert response["ok"] is True
    assert response["audio"].startswith("data:audio/wav;base64,")
    assert response["samples"] == int(payload["duration"] * payload["sample_rate"])
