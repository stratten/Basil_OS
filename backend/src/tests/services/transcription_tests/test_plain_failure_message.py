"""The Dill widget shows the transcription failure text it is sent, so recognized model errors must read as plain advice."""

import pytest

from api.services.transcription.plain_failure_message import (
    DID_NOT_FINISH_LOADING_MESSAGE,
    NOT_REGISTERED_MESSAGE,
    plain_transcription_failure_message,
)


@pytest.mark.parametrize(
    "error",
    [
        ValueError("Whisper transcription model is not registered: 'base'"),
        RuntimeError("Transcription model is not registered: Parakeet Old"),
        ValueError("WHISPER TRANSCRIPTION MODEL IS NOT REGISTERED: ''"),
    ],
)
def test_not_registered_errors_say_what_to_do(error: Exception) -> None:
    message = plain_transcription_failure_message(error)

    assert message == NOT_REGISTERED_MESSAGE
    assert "Settings" in message
    assert "registered" not in message
    assert "'" not in message


def test_a_model_that_did_not_finish_loading_says_to_try_again() -> None:
    message = plain_transcription_failure_message(RuntimeError("Parakeet model Parakeet-int8 did not finish loading"))

    assert message == DID_NOT_FINISH_LOADING_MESSAGE
    assert "Parakeet" not in message


@pytest.mark.parametrize(
    "text",
    [
        "Incorrect API key provided.",
        "transcription failed",
        "",
        "The audio was empty.",
    ],
)
def test_any_other_error_keeps_its_own_text(text: str) -> None:
    assert plain_transcription_failure_message(RuntimeError(text)) == text
