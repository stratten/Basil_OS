import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)
pytestmark = pytest.mark.manual

SPEECH_FIXTURE = Path(__file__).parent / "fixtures" / "speech_snippet_16k_mono.wav"


def _openai_key_available() -> bool:
    """Return True when a real OpenAI key is configured for this environment."""
    try:
        from config.api_keys import get_api_key
        return bool(get_api_key("openai"))
    except Exception:
        return False


def create_test_audio_file():
    """Create a dummy audio file for testing."""
    # Create a minimal WAV header (44 bytes) + some dummy audio data
    header = bytes([
        0x52, 0x49, 0x46, 0x46,  # "RIFF"
        0x24, 0x00, 0x00, 0x00,  # Chunk size
        0x57, 0x41, 0x56, 0x45,  # "WAVE"
        0x66, 0x6D, 0x74, 0x20,  # "fmt "
        0x10, 0x00, 0x00, 0x00,  # Subchunk1 size
        0x01, 0x00,              # Audio format (PCM)
        0x01, 0x00,              # Num channels (Mono)
        0x44, 0xAC, 0x00, 0x00,  # Sample rate (44100)
        0x88, 0x58, 0x01, 0x00,  # Byte rate
        0x02, 0x00,              # Block align
        0x10, 0x00,              # Bits per sample
        0x64, 0x61, 0x74, 0x61,  # "data"
        0x00, 0x00, 0x00, 0x00   # Subchunk2 size
    ])
    audio_data = bytes([0] * 1000)  # 1000 bytes of silence
    return io.BytesIO(header + audio_data)

@pytest.mark.skipif(
    not _openai_key_available(),
    reason="No OpenAI API key configured; cannot validate real transcription.",
)
def test_transcribe_endpoint_success():
    """End-to-end: a real ~4s speech clip transcribes to non-empty text.

    Uses an innocuous travel-small-talk snippet carved from a meeting recording
    (no business/sensitive content) so the endpoint is exercised against the
    real transcription pipeline. This guards against silent drift - an empty or
    failed transcription will fail here rather than passing on a no-op stub.
    """
    assert SPEECH_FIXTURE.exists(), f"Missing speech fixture at {SPEECH_FIXTURE}"
    with open(SPEECH_FIXTURE, "rb") as audio_file:
        response = client.post(
            "/transcribe",
            files={"audio": ("speech_snippet_16k_mono.wav", audio_file, "audio/wav")},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True, f"Transcription failed: {data}"
    assert "text" in data
    text = (data["text"] or "").strip().lower()
    assert text, f"Transcription returned empty text: {data}"
    # The clip says: "Yeah, that's cool. Why are you going to South Korea and
    # for how long?" Assert any of several high-confidence words survives so the
    # check catches total drift without being brittle to minor mis-hearings.
    expected_any = ("korea", "going", "long", "cool")
    assert any(word in text for word in expected_any), (
        f"Transcript drifted from expected content: {data['text']!r}"
    )

def test_transcribe_endpoint_no_file():
    """Test transcription request without file."""
    response = client.post("/transcribe")
    assert response.status_code == 422  # Validation error

def test_transcribe_endpoint_invalid_file():
    """Test transcription request with invalid file."""
    response = client.post(
        "/transcribe",
        files={"audio": ("test.txt", io.BytesIO(b"not audio"), "text/plain")}
    )
    
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "Invalid file type" in data["detail"] 