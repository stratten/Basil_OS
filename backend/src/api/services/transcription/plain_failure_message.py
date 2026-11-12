"""Plain-language wording for a transcription failure that is shown to the person in the Dill widget.

The transcription services raise errors written for the log, such as ``Whisper transcription model is not registered: 'base'``.
The widget shows whatever the websocket sends, so the route converts the errors it recognizes here and leaves every other message as it was.
"""

from __future__ import annotations

NOT_REGISTERED_MESSAGE = (
    "The transcription model chosen in Settings is not available on this Mac. "
    "Open Settings, then Transcription, and choose another model."
)
DID_NOT_FINISH_LOADING_MESSAGE = (
    "The transcription model did not finish loading. "
    "Try again in a moment, or open Settings, then Transcription, and choose another model."
)


def plain_transcription_failure_message(error: BaseException) -> str:
    """The message the Dill widget shows for a failed transcription or model start-up.

    Recognized model-selection failures get a sentence that says what to do. Any other error keeps its own text, because many of
    them, such as a cloud provider rejecting an API key, are already written for the person.
    """
    text = str(error)
    lowered = text.lower()
    if "model is not registered" in lowered:
        return NOT_REGISTERED_MESSAGE
    if "did not finish loading" in lowered:
        return DID_NOT_FINISH_LOADING_MESSAGE
    return text
