from unittest.mock import AsyncMock

import pytest

from api.services.assistant_sessions.assistant_session_router_components.process_audio_pipeline import (
    stream_process_audio,
)


class _FakeModel:
    """Records exactly the messages list it was streamed, so the test can
    assert a leading system-role message was actually included."""

    def __init__(self):
        self.model_name = "fake-model"
        self.received_messages = None

    async def chat_completion_streaming(self, messages):
        self.received_messages = messages
        for token in ["Hello", " world"]:
            yield token


class _FakeContextEnhancer:
    def __init__(self, system_prompt):
        self._system_prompt = system_prompt

    async def enhance_suggestion_context(self, content, instruction, text_selection=None, app_name=None):
        return {
            "context_type": "code_version_control",
            "filtered_content": content,
            "enhanced_prompt": f"ENHANCED: {instruction}",
            "metadata": {},
            "system_prompt": self._system_prompt,
        }


class _FakeModelUsageService:
    def __init__(self, model):
        self._model = model

    async def get_model_for_task(self, capabilities, explicit_model_id=None):
        return self._model


class _FakeService:
    def __init__(self, session_id, model, system_prompt):
        self.sessions = {
            session_id: {
                "text_selection": None,
                "ocr_result": None,
                "app_info": {"app_name": "Messages"},
            }
        }
        self.context_enhancer = _FakeContextEnhancer(system_prompt)
        self.model_usage_service = _FakeModelUsageService(model)
        self.transcription_service = None

    async def transcribe_audio(self, session_id, audio_data, context):
        raise AssertionError("Audio path should not be exercised by this test")


@pytest.mark.asyncio
async def test_streaming_pipeline_sends_system_prompt_as_leading_message(monkeypatch):
    """Regression test for the bug where the escape-hatch system_prompt
    (built by AssistantSessionContextEnhancer._append_instruction_priority)
    was computed but never forwarded to model.chat_completion_streaming in
    the voice-triggered streaming path -- only enhanced_prompt was sent as a
    lone user message. Without the leading system-role message, the model
    never receives permission to discard a misclassified specialized prompt."""
    session_id = "session-1"
    escape_hatch_text = "You are Basil, a general-purpose assistant... ignore mismatched specialized guidance."
    model = _FakeModel()
    service = _FakeService(session_id, model, escape_hatch_text)

    monkeypatch.setattr(
        "api.services.assistant_sessions.assistant_session_router_components.process_audio_pipeline.get_assistant_output_history_service",
        lambda: AsyncMock(persist_assistant_output=AsyncMock(return_value="persisted-1")),
    )

    chunks = []
    async for chunk in stream_process_audio(
        session_id=session_id,
        audio_data=None,
        instruction_text="give me the full text of the reply",
        model_id=None,
        service=service,
        voice_listener_service=None,
    ):
        chunks.append(chunk)

    assert model.received_messages is not None, "model.chat_completion_streaming was never called"
    assert model.received_messages[0] == {"role": "system", "content": escape_hatch_text}
    assert model.received_messages[1] == {"role": "user", "content": "ENHANCED: give me the full text of the reply"}
    assert len(model.received_messages) == 2


@pytest.mark.asyncio
async def test_streaming_pipeline_omits_system_message_when_no_system_prompt(monkeypatch):
    """When the enhancer returns no system_prompt (e.g. a legacy/partial
    result), the pipeline must not send a bogus empty system message -- it
    should fall back to a lone user message, matching prior behavior."""
    session_id = "session-2"
    model = _FakeModel()
    service = _FakeService(session_id, model, system_prompt=None)

    monkeypatch.setattr(
        "api.services.assistant_sessions.assistant_session_router_components.process_audio_pipeline.get_assistant_output_history_service",
        lambda: AsyncMock(persist_assistant_output=AsyncMock(return_value="persisted-2")),
    )

    async for _ in stream_process_audio(
        session_id=session_id,
        audio_data=None,
        instruction_text="hello",
        model_id=None,
        service=service,
        voice_listener_service=None,
    ):
        pass

    assert model.received_messages == [{"role": "user", "content": "ENHANCED: hello"}]
