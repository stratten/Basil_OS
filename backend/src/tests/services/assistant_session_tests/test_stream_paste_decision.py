import json
from unittest.mock import AsyncMock

import pytest

from api.services.assistant_sessions.assistant_session_router_components.paste_directive import (
    PASTE_DECISION_INSTRUCTION,
)
from api.services.assistant_sessions.assistant_session_router_components.process_audio_pipeline import (
    stream_process_audio,
)
from api.services.assistant_sessions.assistant_session_router_components.refinement_pipeline import (
    stream_refinement,
)

PIPELINE = "api.services.assistant_sessions.assistant_session_router_components.process_audio_pipeline"
REFINEMENT = "api.services.assistant_sessions.assistant_session_router_components.refinement_pipeline"
TAGGED_TOKENS = ["Hi Sam,", " thanks.\n<basil_", "paste>insert</basil_paste>"]


class _FakeModel:
    def __init__(self, tokens):
        self.model_name = "fake-model"
        self.received_messages = None
        self._tokens = tokens

    async def chat_completion_streaming(self, messages):
        self.received_messages = messages
        for token in self._tokens:
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
    def __init__(self, session_id, model, system_prompt="SYSTEM"):
        self.sessions = {session_id: {"text_selection": None, "ocr_result": None, "app_info": {"app_name": "Mail"}}}
        self.context_enhancer = _FakeContextEnhancer(system_prompt)
        self.model_usage_service = _FakeModelUsageService(model)
        self.transcription_service = None

    async def _build_refinement_prompt(self, session):
        return "REFINE PROMPT"


def _patch_history(monkeypatch, module):
    history = AsyncMock()
    history.persist_assistant_output = AsyncMock(return_value="persisted-1")
    history.update_refinement = AsyncMock(return_value=None)
    monkeypatch.setattr(f"{module}.get_assistant_output_history_service", lambda: history)
    return history


async def _collect_process_audio(service, session_id):
    chunks = []
    async for line in stream_process_audio(
        session_id=session_id,
        audio_data=None,
        instruction_text="help me reply to this",
        model_id=None,
        service=service,
        voice_listener_service=None,
    ):
        chunks.append(json.loads(line))
    return chunks


@pytest.mark.asyncio
async def test_auto_mode_adds_instruction_strips_tag_and_reports_insert(monkeypatch):
    monkeypatch.setattr(f"{PIPELINE}.resolve_paste_mode", lambda: "auto")
    history = _patch_history(monkeypatch, PIPELINE)
    model = _FakeModel(TAGGED_TOKENS)
    service = _FakeService("s-auto", model)

    chunks = await _collect_process_audio(service, "s-auto")

    assert model.received_messages[0]["role"] == "system"
    assert model.received_messages[0]["content"].endswith(PASTE_DECISION_INSTRUCTION)
    assert not any("error" in chunk for chunk in chunks)
    assert not any("basil_paste" in json.dumps(chunk) for chunk in chunks)
    final = chunks[-1]
    assert final["complete"] is True
    assert final["assistant_output"] == "Hi Sam, thanks."
    assert final["paste_decision"] == "insert"
    assert service.sessions["s-auto"]["suggestion"] == "Hi Sam, thanks."
    assert history.persist_assistant_output.await_args.kwargs["output_text"] == "Hi Sam, thanks."


@pytest.mark.asyncio
async def test_auto_mode_without_system_prompt_appends_instruction_to_user_message(monkeypatch):
    monkeypatch.setattr(f"{PIPELINE}.resolve_paste_mode", lambda: "auto")
    _patch_history(monkeypatch, PIPELINE)
    model = _FakeModel(["Explanation."])
    service = _FakeService("s-nosys", model, system_prompt=None)

    chunks = await _collect_process_audio(service, "s-nosys")

    assert len(model.received_messages) == 1
    assert model.received_messages[0]["content"] == f"ENHANCED: help me reply to this\n\n{PASTE_DECISION_INSTRUCTION}"
    assert chunks[-1]["paste_decision"] is None
    assert chunks[-1]["assistant_output"] == "Explanation."


@pytest.mark.asyncio
async def test_always_mode_sends_no_instruction_but_still_strips_stray_tags(monkeypatch):
    monkeypatch.setattr(f"{PIPELINE}.resolve_paste_mode", lambda: "always")
    _patch_history(monkeypatch, PIPELINE)
    model = _FakeModel(TAGGED_TOKENS)
    service = _FakeService("s-always", model)

    chunks = await _collect_process_audio(service, "s-always")

    assert model.received_messages[0] == {"role": "system", "content": "SYSTEM"}
    assert chunks[-1]["assistant_output"] == "Hi Sam, thanks."
    assert chunks[-1]["paste_decision"] is None


@pytest.mark.asyncio
async def test_untagged_reply_is_streamed_unchanged(monkeypatch):
    monkeypatch.setattr(f"{PIPELINE}.resolve_paste_mode", lambda: "auto")
    _patch_history(monkeypatch, PIPELINE)
    model = _FakeModel(["Line one\n", "Line two\n"])
    service = _FakeService("s-plain", model)

    chunks = await _collect_process_audio(service, "s-plain")

    tokens = [chunk["assistant_output_token"] for chunk in chunks if "assistant_output_token" in chunk]
    assert "".join(tokens) == "Line one\nLine two\n"
    assert chunks[-1]["assistant_output"] == "Line one\nLine two\n"
    assert chunks[-1]["paste_decision"] is None


@pytest.mark.asyncio
async def test_refinement_auto_mode_appends_instruction_and_reports_show(monkeypatch):
    monkeypatch.setattr(f"{REFINEMENT}.resolve_paste_mode", lambda: "auto")
    _patch_history(monkeypatch, REFINEMENT)
    model = _FakeModel(["It means X.", "\n<basil_paste>show</basil_paste>"])
    service = _FakeService("s-refine", model)
    service.sessions["s-refine"].update({"transcription": "explain this", "suggestion": "Old output"})

    chunks = []
    async for line in stream_refinement(
        session_id="s-refine",
        audio_data=None,
        instruction_text="shorter please",
        model_id=None,
        service=service,
        voice_listener_service=None,
    ):
        chunks.append(json.loads(line))

    assert model.received_messages == [{"role": "user", "content": f"REFINE PROMPT\n\n{PASTE_DECISION_INSTRUCTION}"}]
    assert not any("error" in chunk for chunk in chunks)
    assert not any("basil_paste" in json.dumps(chunk) for chunk in chunks)
    final = chunks[-1]
    assert final["assistant_output"] == "It means X."
    assert final["paste_decision"] == "show"
    assert final["iteration_count"] == 1
    assert service.sessions["s-refine"]["current_suggestion"] == "It means X."


@pytest.mark.asyncio
async def test_refinement_never_mode_sends_prompt_unchanged(monkeypatch):
    monkeypatch.setattr(f"{REFINEMENT}.resolve_paste_mode", lambda: "never")
    _patch_history(monkeypatch, REFINEMENT)
    model = _FakeModel(["Refined."])
    service = _FakeService("s-never", model)

    chunks = []
    async for line in stream_refinement(
        session_id="s-never",
        audio_data=None,
        instruction_text="again",
        model_id=None,
        service=service,
        voice_listener_service=None,
    ):
        chunks.append(json.loads(line))

    assert model.received_messages == [{"role": "user", "content": "REFINE PROMPT"}]
    assert chunks[-1]["paste_decision"] is None
    assert chunks[-1]["assistant_output"] == "Refined."
