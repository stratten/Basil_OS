from types import SimpleNamespace

import pytest

from api.routes.websocket_routes import transcription


@pytest.fixture(autouse=True)
def clear_processed_transcription_audio_digests():
    transcription.processed_transcription_audio_digests.clear()
    yield
    transcription.processed_transcription_audio_digests.clear()


class _Clipboard:
    def __init__(self, value: str) -> None:
        self.value = value
        self.copies: list[str] = []

    def paste(self) -> str:
        return self.value

    def copy(self, value: str) -> None:
        self.value = value
        self.copies.append(value)


class _Keyboard:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def press(self, key) -> None:
        self.events.append(f"press:{key}")

    def release(self, key) -> None:
        self.events.append(f"release:{key}")


class _Preferences:
    auto_paste = True
    text_replacements = []

    @classmethod
    def load(cls):
        return SimpleNamespace(
            models=SimpleNamespace(transcription_model="openai-whisper-1"),
            transcription=SimpleNamespace(
                auto_paste=cls.auto_paste,
                auto_close_on_paste=False,
                text_replacements=cls.text_replacements,
            ),
        )


class _TranscriptionService:
    def __init__(self, result):
        self.result = result

    def is_model_loaded(self) -> bool:
        return True

    async def transcribe(self, audio_data: bytes, context_info):
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class _WebSocket:
    def __init__(self, context_info=None) -> None:
        self.scope = {"context_info": context_info or {}}
        self.messages: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.messages.append(message)


@pytest.mark.asyncio
async def test_paste_dispatches_completion_before_clipboard_restoration(
    monkeypatch,
) -> None:
    events: list[str] = []
    clipboard = _Clipboard("original")
    monkeypatch.setattr(transcription, "pyperclip", clipboard)
    monkeypatch.setattr(
        transcription,
        "KeyboardController",
        lambda: _Keyboard(events),
    )

    async def fake_sleep(seconds: float) -> None:
        events.append(f"sleep:{seconds}")

    async def on_dispatched() -> None:
        events.append("completed")

    monkeypatch.setattr(transcription.asyncio, "sleep", fake_sleep)

    await transcription.paste_transcribed_text("transcript", on_dispatched)

    paste_release_index = events.index(f"release:{transcription.Key.cmd}")
    assert paste_release_index < events.index("completed")
    assert events.index("completed") < events.index("sleep:1.5")
    assert clipboard.copies == ["transcript", "original"]


@pytest.mark.asyncio
async def test_paste_preserves_newer_clipboard_content(monkeypatch) -> None:
    clipboard = _Clipboard("original")
    monkeypatch.setattr(transcription, "pyperclip", clipboard)
    monkeypatch.setattr(
        transcription,
        "KeyboardController",
        lambda: _Keyboard([]),
    )

    async def mutate_clipboard_during_grace(seconds: float) -> None:
        clipboard.value = "new user copy"

    monkeypatch.setattr(
        transcription.asyncio,
        "sleep",
        mutate_clipboard_during_grace,
    )

    await transcription.paste_transcribed_text("transcript")

    assert clipboard.value == "new user copy"
    assert clipboard.copies == ["transcript"]


@pytest.mark.asyncio
async def test_paste_failure_still_invokes_completion_once(monkeypatch) -> None:
    callback_count = 0

    class _FailingClipboard:
        def paste(self):
            raise RuntimeError("clipboard unavailable")

    async def on_dispatched() -> None:
        nonlocal callback_count
        callback_count += 1

    monkeypatch.setattr(transcription, "pyperclip", _FailingClipboard())

    await transcription.paste_transcribed_text("transcript", on_dispatched)

    assert callback_count == 1


@pytest.mark.asyncio
async def test_paste_dispatch_failure_restores_replaced_clipboard(monkeypatch) -> None:
    clipboard = _Clipboard("original")

    class _FailingKeyboard:
        def press(self, key) -> None:
            raise RuntimeError("keyboard unavailable")

        def release(self, key) -> None:
            pass

    monkeypatch.setattr(transcription, "pyperclip", clipboard)
    monkeypatch.setattr(transcription, "KeyboardController", _FailingKeyboard)

    await transcription.paste_transcribed_text("transcript")

    assert clipboard.value == "original"
    assert clipboard.copies == ["transcript", "original"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transcribed_text",
    ["", "quotes ' and emoji \N{MICROPHONE}", "long " * 5000],
)
async def test_audio_handler_publishes_exactly_once_without_auto_paste(
    transcribed_text: str,
) -> None:
    _Preferences.auto_paste = False
    sent: list[tuple[str, object]] = []

    async def send_status(event: str, data=None) -> None:
        sent.append((event, data))

    await transcription.handle_audio_transcription(
        _WebSocket(),
        {"bytes": b"audio"},
        _TranscriptionService(transcribed_text),
        send_status,
        transcription.paste_transcribed_text,
        _Preferences,
    )

    assert sent == [
        ("transcription_started", None),
        ("transcription_completed", transcribed_text),
    ]


@pytest.mark.asyncio
async def test_audio_handler_orders_paste_dispatch_before_completion_and_restore() -> None:
    _Preferences.auto_paste = True
    events: list[str] = []
    sent: list[tuple[str, object]] = []

    async def send_status(event: str, data=None) -> None:
        sent.append((event, data))
        if event == "transcription_completed":
            events.append("completed")

    async def fake_paste(text: str, on_dispatched) -> None:
        events.append("paste-dispatched")
        await on_dispatched()
        events.append("clipboard-restored")

    await transcription.handle_audio_transcription(
        _WebSocket(),
        {"bytes": b"audio"},
        _TranscriptionService("result"),
        send_status,
        fake_paste,
        _Preferences,
    )

    assert events == [
        "paste-dispatched",
        "completed",
        "clipboard-restored",
    ]
    assert sent.count(("transcription_completed", "result")) == 1


@pytest.mark.asyncio
async def test_audio_handler_pastes_normalized_text_and_broadcasts_raw_text() -> None:
    _Preferences.auto_paste = True
    _Preferences.text_replacements = [
        SimpleNamespace(source="slash", replacement="/"),
    ]
    sent: list[tuple[str, object]] = []
    pasted_text: list[str] = []

    async def send_status(event: str, data=None) -> None:
        sent.append((event, data))

    async def fake_paste(text: str, on_dispatched) -> None:
        pasted_text.append(text)
        await on_dispatched()

    try:
        await transcription.handle_audio_transcription(
            _WebSocket(),
            {"bytes": b"replacement-audio"},
            _TranscriptionService("go slash home"),
            send_status,
            fake_paste,
            _Preferences,
        )
    finally:
        _Preferences.text_replacements = []

    assert pasted_text == ["go / home"]
    assert ("transcription_completed", "go slash home") in sent


@pytest.mark.asyncio
async def test_audio_handler_ignores_duplicate_audio_from_separate_clients_before_auto_paste() -> None:
    _Preferences.auto_paste = True
    transcription.processed_transcription_audio_digests.clear()
    sent: list[tuple[str, object]] = []
    paste_calls = 0

    async def send_status(event: str, data=None) -> None:
        sent.append((event, data))

    async def fake_paste(text: str, on_dispatched) -> None:
        nonlocal paste_calls
        paste_calls += 1
        await on_dispatched()

    for websocket in (_WebSocket(), _WebSocket()):
        await transcription.handle_audio_transcription(
            websocket,
            {"bytes": b"audio"},
            _TranscriptionService("result"),
            send_status,
            fake_paste,
            _Preferences,
        )

    assert paste_calls == 1
    assert sent == [
        ("transcription_started", None),
        ("transcription_completed", "result"),
    ]


@pytest.mark.asyncio
async def test_flow_context_uses_dedicated_event_and_skips_auto_paste() -> None:
    _Preferences.auto_paste = True
    websocket = _WebSocket()
    sent: list[tuple[str, object]] = []
    paste_calls = 0
    result = {"flowContext": "agentTask", "text": "result"}

    async def send_status(event: str, data=None) -> None:
        sent.append((event, data))

    async def fake_paste(text: str, on_dispatched) -> None:
        nonlocal paste_calls
        paste_calls += 1

    await transcription.handle_audio_transcription(
        websocket,
        {"bytes": b"audio"},
        _TranscriptionService(result),
        send_status,
        fake_paste,
        _Preferences,
    )

    assert sent == [("transcription_started", None)]
    assert websocket.messages == [
        {"event": "flow_context_transcription_completed", "data": result}
    ]
    assert paste_calls == 0


@pytest.mark.asyncio
async def test_transcription_failure_publishes_failed_event() -> None:
    sent: list[tuple[str, object]] = []

    async def send_status(event: str, data=None) -> None:
        sent.append((event, data))

    await transcription.handle_audio_transcription(
        _WebSocket(),
        {"bytes": b"audio"},
        _TranscriptionService(RuntimeError("transcription failed")),
        send_status,
        transcription.paste_transcribed_text,
        _Preferences,
    )

    assert sent == [
        ("transcription_started", None),
        ("transcription_failed", "transcription failed"),
    ]


@pytest.mark.asyncio
async def test_database_warning_fallback_completes_once() -> None:
    class _TranscribedDatabaseError(RuntimeError):
        transcribed_text = "recovered result"

    class _DatabaseWarningService(_TranscriptionService):
        async def transcribe(self, audio_data: bytes, context_info):
            try:
                raise _TranscribedDatabaseError("saved transcript")
            except _TranscribedDatabaseError:
                raise RuntimeError("no such table: transcriptions")

    _Preferences.auto_paste = False
    sent: list[tuple[str, object]] = []

    async def send_status(event: str, data=None) -> None:
        sent.append((event, data))

    await transcription.handle_audio_transcription(
        _WebSocket(),
        {"bytes": b"audio"},
        _DatabaseWarningService(None),
        send_status,
        transcription.paste_transcribed_text,
        _Preferences,
    )

    assert sent == [
        ("transcription_started", None),
        ("transcription_completed", "recovered result"),
    ]
