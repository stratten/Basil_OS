from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.basil_board.home_routes import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def make_wav_bytes(length: int = 64) -> bytes:
    return b"RIFF" + b"\x00" * (length - 4)


@pytest.mark.parametrize(
    ("path", "source", "notes", "capture_method", "default_filename"),
    [
        (
            "/api/v1/basil-board/home/transcribe",
            "basil_board_home",
            "BasilBoard Home voice capture",
            "basil_board_home_voice",
            "home_turn.wav",
        ),
        (
            "/api/v1/basil-board/conversation/transcribe",
            "basil_board_conversation",
            "BasilBoard Conversation voice capture",
            "basil_board_conversation_voice",
            "conversation_turn.wav",
        ),
    ],
)
def test_valid_audio_forwards_distinct_context(
    client,
    path,
    source,
    notes,
    capture_method,
    default_filename,
):
    transcription_service = AsyncMock()
    transcription_service.transcribe = AsyncMock(return_value="Hello there")

    with patch(
        "api.dependencies.resolve_transcription_service",
        return_value=transcription_service,
    ):
        response = client.post(
            path,
            files={"audio_file": ("turn.wav", BytesIO(make_wav_bytes()), "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json() == {"success": True, "transcription": "Hello there", "error_code": None}
    context_info = transcription_service.transcribe.await_args.kwargs["context_info"]
    assert context_info["source"] == source
    assert context_info["notes"] == notes
    assert context_info["capture_method"] == capture_method
    assert context_info["original_filename"] == "turn.wav"


@pytest.mark.parametrize("path", [
    "/api/v1/basil-board/home/transcribe",
    "/api/v1/basil-board/conversation/transcribe",
])
def test_invalid_content_type(client, path):
    response = client.post(
        path,
        files={"audio_file": ("turn.txt", BytesIO(b"hello"), "text/plain")},
    )
    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "transcription": "",
        "error_code": "invalid_content_type",
    }


@pytest.mark.parametrize("path", [
    "/api/v1/basil-board/home/transcribe",
    "/api/v1/basil-board/conversation/transcribe",
])
def test_audio_too_small(client, path):
    response = client.post(
        path,
        files={"audio_file": ("turn.wav", BytesIO(b"tiny"), "audio/wav")},
    )
    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "transcription": "",
        "error_code": "audio_too_small",
    }


@pytest.mark.parametrize("path", [
    "/api/v1/basil-board/home/transcribe",
    "/api/v1/basil-board/conversation/transcribe",
])
def test_transcription_exception(client, path):
    transcription_service = AsyncMock()
    transcription_service.transcribe = AsyncMock(side_effect=RuntimeError("boom"))

    with patch(
        "api.dependencies.resolve_transcription_service",
        return_value=transcription_service,
    ):
        response = client.post(
            path,
            files={"audio_file": ("turn.wav", BytesIO(make_wav_bytes()), "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "transcription": "",
        "error_code": "transcription_failed",
    }


@pytest.mark.parametrize("path", [
    "/api/v1/basil-board/home/transcribe",
    "/api/v1/basil-board/conversation/transcribe",
])
def test_no_speech(client, path):
    transcription_service = AsyncMock()
    transcription_service.transcribe = AsyncMock(return_value="   ")

    with patch(
        "api.dependencies.resolve_transcription_service",
        return_value=transcription_service,
    ):
        response = client.post(
            path,
            files={"audio_file": ("turn.wav", BytesIO(make_wav_bytes()), "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "transcription": "",
        "error_code": "no_speech",
    }
