from ambiance.utils.audio import encode_wav_bytes
from ambiance.npcompat import np


def test_encode_wav_bytes_contains_riff_header():
    buffer = np.zeros(800, dtype=np.float32)
    data = encode_wav_bytes(buffer, 8000)

    assert data.startswith(b"RIFF")
    assert b"WAVE" in data[:16]
