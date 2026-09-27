from pathlib import Path
import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.core.models.preferences import AmbientSuggestionSettings, Preferences
from api.routes import ambient_suggestions as ambient_suggestion_routes
from api.services.ambient_suggestions.evaluator import AmbientSuggestionEvaluator
from api.services.ambient_suggestions.history_context import AmbientSuggestionHistoryContextService
from api.services.ambient_suggestions.models import (
    AmbientContextEnvelope,
    AmbientEvaluationResponse,
    AmbientRecentActivitySpan,
    AmbientRecentSuggestionContext,
    AmbientSuggestionPayload,
)
from api.services.ambient_suggestions.runtime import AmbientSuggestionRuntime
from api.services.ambient_suggestions.store import AmbientSuggestionStore


def test_ambient_suggestion_store_suppresses_recent_rejected_context(tmp_path: Path) -> None:
    store = AmbientSuggestionStore(db_path=tmp_path / "ambient.db")
    payload = AmbientSuggestionPayload(
        should_suggest=True,
        capability="assistant_session",
        suggestion_type="draft_reply",
        confidence=0.9,
        title="Draft a reply",
        summary="Visible email asks for an update.",
        proposed_request="Draft a reply to the visible email asking for an update.",
        instruction="Draft a reply to the visible email.",
        context_text="From: Test\nSubject: Update\nCan you send an update?",
    )

    record = store.create_suggestion(
        app_name="Mail",
        window_title="Inbox",
        content_fingerprint="fingerprint-1",
        source_identifier=None,
        payload=payload,
    )
    assert store.should_suppress(
        content_fingerprint="fingerprint-1",
        suggestion_type="draft_reply",
        capability="assistant_session",
        cooldown_minutes=30,
    )
    assert record.proposed_request == "Draft a reply to the visible email asking for an update."

    updated = store.update_outcome(record.suggestion_id, "rejected")
    assert updated is not None
    assert updated.outcome == "rejected"
    assert store.should_suppress(
        content_fingerprint="fingerprint-1",
        suggestion_type="draft_reply",
        capability="assistant_session",
        cooldown_minutes=30,
    )


def test_ambient_suggestion_store_lists_recent_suggestion_context(tmp_path: Path) -> None:
    store = AmbientSuggestionStore(db_path=tmp_path / "ambient.db")
    payload = AmbientSuggestionPayload(
        should_suggest=True,
        capability="assistant_session",
        suggestion_type="draft_reply",
        confidence=0.9,
        title="Draft a reply",
        summary="Visible email asks for an update.",
        proposed_request="Draft a reply to the visible email asking for an update.",
        instruction="Draft a reply to the visible email.",
        context_text="From: Test\nSubject: Update\nCan you send an update?",
    )
    store.create_suggestion(
        app_name="Mail",
        window_title="Inbox",
        content_fingerprint="fingerprint-1",
        source_identifier=None,
        payload=payload,
    )

    recent = store.list_recent_suggestion_context(
        content_fingerprint="fingerprint-1",
        app_name="Mail",
        window_title="Inbox",
        cooldown_minutes=30,
        lookback_minutes=90,
        limit=10,
    )

    assert len(recent) == 1
    assert recent[0].application == "Mail"
    assert recent[0].suggestion_type == "draft_reply"
    assert recent[0].proposed_request == "Draft a reply to the visible email asking for an update."


def test_ambient_evaluation_response_requires_proposed_request_for_suggestions() -> None:
    with pytest.raises(ValidationError):
        AmbientEvaluationResponse.model_validate(
            {
                "should_suggest": True,
                "capability": "assistant_session",
                "suggestion_type": "draft_reply",
                "confidence": 0.9,
                "primary_activity": "reading_message",
                "visible_context_summary": "A visible message asks for a project update.",
                "evidence": ["From: Alex", "Subject: Project update"],
                "evidence_sources": ["ocr_text"],
                "title": "Draft a reply",
                "summary": "An email is visible.",
                "instruction": "Draft a reply.",
                "grounding": {
                    "application": "Mail",
                    "window_title": "Subject",
                    "visible_excerpt": "From: Alex",
                },
            }
        )


def test_ambient_evaluation_response_converts_to_payload_with_grounding() -> None:
    response = AmbientEvaluationResponse.model_validate(
        {
            "should_suggest": True,
            "capability": "assistant_session",
            "suggestion_type": "explain_error",
            "confidence": 0.88,
            "primary_activity": "reviewing_logs",
            "visible_context_summary": "A pytest failure is visible in Cursor.",
            "evidence": ["AssertionError is visible in pytest output"],
            "evidence_sources": ["ocr_text"],
            "title": "Explain this failure",
            "summary": "A concrete error is visible.",
            "proposed_request": "Explain the visible pytest failure and suggest the next debugging step.",
            "instruction": "Explain the visible pytest failure and suggest the next debugging step.",
            "grounding": {
                "application": "Cursor",
                "window_title": "test_file.py",
                "visible_excerpt": "AssertionError",
            },
        }
    )

    payload = response.to_payload()

    assert payload.proposed_request == "Explain the visible pytest failure and suggest the next debugging step."
    assert "App: Cursor" in payload.context_text
    assert "Window: test_file.py" in payload.context_text


def _ambient_response_json(**overrides) -> str:
    data = {
        "should_suggest": True,
        "no_suggestion_reason": None,
        "capability": "assistant_session",
        "suggestion_type": "explain_error",
        "confidence": 0.88,
        "primary_activity": "reviewing_logs",
        "visible_context_summary": "A pytest failure is visible in Cursor.",
        "evidence": ["AssertionError is visible in pytest output"],
        "evidence_sources": ["ocr_text"],
        "title": "Explain this failure",
        "summary": "A concrete error is visible.",
        "details": "Focus on the visible stack trace.",
        "proposed_request": "Explain the visible pytest failure and suggest the next debugging step.",
        "instruction": "Explain the visible pytest failure and suggest the next debugging step.",
        "grounding": {
            "application": "Cursor",
            "window_title": "test_file.py",
            "visible_excerpt": "AssertionError",
        },
        "auto_execute_eligible": False,
    }
    data.update(overrides)
    return json.dumps(data)


@pytest.mark.asyncio
async def test_ambient_evaluator_uses_llama_cpp_response_format_schema() -> None:
    class Llama:
        response_format = None

        def create_chat_completion(self, **kwargs):
            self.response_format = kwargs.get("response_format")
            return {
                "choices": [
                    {
                        "message": {"content": _ambient_response_json()},
                        "finish_reason": "stop",
                    }
                ]
            }

    class Model:
        def __init__(self) -> None:
            self.llm = Llama()

        async def generate_response(self, **kwargs):
            raise AssertionError("structured llama.cpp path should not use plain generate_response")

    model = Model()

    class ModelService:
        async def load_model_by_id(self, model_id, capabilities):
            return model

    evaluator = AmbientSuggestionEvaluator(model_service=ModelService())  # type: ignore[arg-type]
    context = AmbientContextEnvelope(
        capture_id="capture-structured",
        timestamp="2026-05-28T10:00:00",
        app_name="Cursor",
        window_title="test_file.py",
        image_path=None,
        ocr_text="AssertionError: expected compact row",
        structured_context={},
        content_fingerprint="fingerprint-structured",
    )

    suggestion = await evaluator.evaluate(context, model_id="Qwen-qwen3-8b-instruct-q4km")

    assert suggestion.should_suggest is True
    assert model.llm.response_format["type"] == "json_object"
    assert "schema" in model.llm.response_format


@pytest.mark.asyncio
async def test_ambient_evaluator_accepts_exact_json_on_text_fallback() -> None:
    class Model:
        async def generate_response(self, **kwargs):
            return _ambient_response_json()

    class ModelService:
        async def load_model_by_id(self, model_id, capabilities):
            return Model()

    evaluator = AmbientSuggestionEvaluator(model_service=ModelService())  # type: ignore[arg-type]
    context = AmbientContextEnvelope(
        capture_id="capture-exact",
        timestamp="2026-05-28T10:00:00",
        app_name="Cursor",
        window_title="test_file.py",
        image_path=None,
        ocr_text="AssertionError: expected compact row",
        structured_context={},
        content_fingerprint="fingerprint-exact",
    )

    suggestion = await evaluator.evaluate(context, model_id="cloud-model-without-structured-mode")

    assert suggestion.should_suggest is True
    assert suggestion.suggestion_type == "explain_error"


@pytest.mark.asyncio
async def test_ambient_evaluator_rejects_trailing_prose_on_text_fallback() -> None:
    class Model:
        async def generate_response(self, **kwargs):
            return _ambient_response_json() + "\n\nActually, this might not be appropriate."

    class ModelService:
        async def load_model_by_id(self, model_id, capabilities):
            return Model()

    evaluator = AmbientSuggestionEvaluator(model_service=ModelService())  # type: ignore[arg-type]
    context = AmbientContextEnvelope(
        capture_id="capture-trailing",
        timestamp="2026-05-28T10:00:00",
        app_name="Cursor",
        window_title="test_file.py",
        image_path=None,
        ocr_text="AssertionError: expected compact row",
        structured_context={},
        content_fingerprint="fingerprint-trailing",
    )

    suggestion = await evaluator.evaluate(context, model_id="cloud-model-without-structured-mode")

    assert suggestion.should_suggest is False


@pytest.mark.asyncio
async def test_ambient_evaluator_rejects_markdown_fenced_json_on_text_fallback() -> None:
    class Model:
        async def generate_response(self, **kwargs):
            return f"```json\n{_ambient_response_json()}\n```"

    class ModelService:
        async def load_model_by_id(self, model_id, capabilities):
            return Model()

    evaluator = AmbientSuggestionEvaluator(model_service=ModelService())  # type: ignore[arg-type]
    context = AmbientContextEnvelope(
        capture_id="capture-fenced",
        timestamp="2026-05-28T10:00:00",
        app_name="Cursor",
        window_title="test_file.py",
        image_path=None,
        ocr_text="AssertionError: expected compact row",
        structured_context={},
        content_fingerprint="fingerprint-fenced",
    )

    suggestion = await evaluator.evaluate(context, model_id="cloud-model-without-structured-mode")

    assert suggestion.should_suggest is False


@pytest.mark.asyncio
async def test_ambient_evaluator_rejects_multiple_json_objects_on_text_fallback() -> None:
    class Model:
        async def generate_response(self, **kwargs):
            return f"{_ambient_response_json()}\n{_ambient_response_json(should_suggest=False)}"

    class ModelService:
        async def load_model_by_id(self, model_id, capabilities):
            return Model()

    evaluator = AmbientSuggestionEvaluator(model_service=ModelService())  # type: ignore[arg-type]
    context = AmbientContextEnvelope(
        capture_id="capture-multiple",
        timestamp="2026-05-28T10:00:00",
        app_name="Cursor",
        window_title="test_file.py",
        image_path=None,
        ocr_text="AssertionError: expected compact row",
        structured_context={},
        content_fingerprint="fingerprint-multiple",
    )

    suggestion = await evaluator.evaluate(context, model_id="cloud-model-without-structured-mode")

    assert suggestion.should_suggest is False


@pytest.mark.asyncio
async def test_ambient_evaluator_accepts_model_approved_suggestion_without_backend_reinterpretation() -> None:
    class Llama:
        def create_chat_completion(self, **kwargs):
            return {
                "choices": [
                    {
                        "message": {
                            "content": _ambient_response_json(
                                suggestion_type="draft_reply",
                                confidence=0.92,
                                primary_activity="using_basil_ui",
                                visible_context_summary="The Ambient Suggestions panel is visible.",
                                evidence=["Ambient Suggestions panel says Draft reply to email"],
                                evidence_sources=["basil_ui"],
                                title="Draft reply to email",
                                summary="The visible excerpt is an email that needs a draft reply.",
                                proposed_request="Draft a reply to this email using only the visible content and preserving the existing tone.",
                                instruction="Draft a reply to this email using only the visible content and preserving the existing tone.",
                                grounding={
                                    "application": "Cursor",
                                    "window_title": "Main todo modal label update",
                                    "visible_excerpt": "Ambient Suggestions Will ask: Draft reply to email",
                                },
                            )
                        },
                        "finish_reason": "stop",
                    }
                ]
            }

    class Model:
        llm = Llama()

    class ModelService:
        async def load_model_by_id(self, model_id, capabilities):
            return Model()

    evaluator = AmbientSuggestionEvaluator(model_service=ModelService())  # type: ignore[arg-type]
    context = AmbientContextEnvelope(
        capture_id="capture-cursor",
        timestamp="2026-05-28T10:00:00",
        app_name="Cursor",
        window_title="Main todo modal label update",
        image_path=None,
        ocr_text="Ambient Suggestions\nWill ask: Draft reply to email\nCode changes and TODO modal label update",
        structured_context={},
        content_fingerprint="fingerprint-cursor",
    )

    suggestion = await evaluator.evaluate(context, model_id="Qwen-qwen3-8b-instruct-q4km")

    assert suggestion.should_suggest is True
    assert suggestion.suggestion_type == "draft_reply"


@pytest.mark.asyncio
async def test_ambient_evaluator_rejects_low_confidence_as_runtime_policy() -> None:
    class Llama:
        def create_chat_completion(self, **kwargs):
            return {
                "choices": [
                    {
                        "message": {"content": _ambient_response_json(confidence=0.5)},
                        "finish_reason": "stop",
                    }
                ]
            }

    class Model:
        llm = Llama()

    class ModelService:
        async def load_model_by_id(self, model_id, capabilities):
            return Model()

    evaluator = AmbientSuggestionEvaluator(model_service=ModelService())  # type: ignore[arg-type]
    context = AmbientContextEnvelope(
        capture_id="capture-low-confidence",
        timestamp="2026-05-28T10:00:00",
        app_name="Cursor",
        window_title="test_file.py",
        image_path=None,
        ocr_text="AssertionError: expected compact row",
        structured_context={},
        content_fingerprint="fingerprint-low-confidence",
    )

    suggestion = await evaluator.evaluate(
        context,
        model_id="Qwen-qwen3-8b-instruct-q4km",
        minimum_confidence=0.8,
    )

    assert suggestion.should_suggest is False


@pytest.mark.asyncio
async def test_ambient_evaluator_allows_grounded_message_drafting() -> None:
    class Llama:
        def create_chat_completion(self, **kwargs):
            return {
                "choices": [
                    {
                        "message": {
                            "content": _ambient_response_json(
                                suggestion_type="draft_reply",
                                confidence=0.91,
                                primary_activity="reading_message",
                                visible_context_summary="Alex asks for an account status update.",
                                evidence=["From: Alex", "To: Me", "Subject: Account status"],
                                evidence_sources=["app_name", "window_title", "ocr_text"],
                                title="Draft a reply",
                                summary="The visible email asks for an account status update.",
                                proposed_request="Draft a reply to Alex about the account status update and mention next steps.",
                                instruction="Draft a reply to Alex about the account status update and mention next steps.",
                                grounding={
                                    "application": "Microsoft Outlook",
                                    "window_title": "Re: Account Status",
                                    "visible_excerpt": "From: Alex\nTo: Me\nSubject: Account Status",
                                },
                            )
                        },
                        "finish_reason": "stop",
                    }
                ]
            }

    class Model:
        llm = Llama()

    class ModelService:
        async def load_model_by_id(self, model_id, capabilities):
            return Model()

    evaluator = AmbientSuggestionEvaluator(model_service=ModelService())  # type: ignore[arg-type]
    context = AmbientContextEnvelope(
        capture_id="capture-outlook",
        timestamp="2026-05-28T10:00:00",
        app_name="Microsoft Outlook",
        window_title="Re: Account Status",
        image_path=None,
        ocr_text="From: Alex\nTo: Me\nSubject: Account Status\nCan you send the latest status?",
        structured_context={},
        content_fingerprint="fingerprint-outlook",
    )

    suggestion = await evaluator.evaluate(context, model_id="Qwen-qwen3-8b-instruct-q4km")

    assert suggestion.should_suggest is True
    assert suggestion.suggestion_type == "draft_reply"


def test_ambient_evaluator_fallback_does_not_create_speculative_cards() -> None:
    evaluator = AmbientSuggestionEvaluator(model_service=None)  # type: ignore[arg-type]
    context = AmbientContextEnvelope(
        capture_id="capture-1",
        timestamp="2026-05-28T10:00:00",
        app_name="Mail",
        window_title="Subject: Project update",
        image_path=None,
        ocr_text=(
            "From: Alex\nTo: Me\nSubject: Project update\nCan you send the latest status, "
            "next steps, and whether there are any blockers before tomorrow's planning meeting?"
        ),
        structured_context={},
        content_fingerprint="fingerprint-2",
    )

    suggestion = evaluator._fallback_evaluate(context)

    assert suggestion.should_suggest is False


def test_ambient_evaluator_fallback_rejects_weak_email_noise() -> None:
    evaluator = AmbientSuggestionEvaluator(model_service=None)  # type: ignore[arg-type]
    context = AmbientContextEnvelope(
        capture_id="capture-noise",
        timestamp="2026-05-28T10:00:00",
        app_name="Cursor",
        window_title="mail_parser.py",
        image_path=None,
        ocr_text="This code mentions reply and inbox but does not show a visible email.",
        structured_context={},
        content_fingerprint="fingerprint-noise",
    )

    suggestion = evaluator._fallback_evaluate(context)

    assert suggestion.should_suggest is False


def test_ambient_evaluator_adds_app_window_grounding_to_suggestion_context() -> None:
    evaluator = AmbientSuggestionEvaluator(model_service=None)  # type: ignore[arg-type]
    context = AmbientContextEnvelope(
        capture_id="capture-code",
        timestamp="2026-05-28T10:00:00",
        app_name="Cursor",
        window_title="test_ambient_suggestions.py",
        image_path=None,
        ocr_text="FAILED test_widget.py::test_card_layout AssertionError: expected compact row",
        structured_context={"frontmost_application": "Cursor"},
        content_fingerprint="fingerprint-code",
    )
    request = evaluator._build_evaluation_request(context)

    assert request.application == "Cursor"
    assert request.window_title == "test_ambient_suggestions.py"
    assert request.ocr_excerpt == "FAILED test_widget.py::test_card_layout AssertionError: expected compact row"
    assert request.structured_context["frontmost_application"] == "Cursor"
    assert request.content_fingerprint == "fingerprint-code"


def test_ambient_evaluator_adds_history_to_evaluation_request() -> None:
    evaluator = AmbientSuggestionEvaluator(model_service=None)  # type: ignore[arg-type]
    context = AmbientContextEnvelope(
        capture_id="capture-email",
        timestamp="2026-05-28T11:00:00",
        app_name="Microsoft Outlook",
        window_title="Project update",
        image_path=None,
        ocr_text="Hi team, here is the status update on the IDE work...",
        structured_context={},
        content_fingerprint="fingerprint-email",
    )
    recent_suggestion = AmbientRecentSuggestionContext(
        created_at=datetime(2026, 5, 28, 10, 30),
        outcome="rejected",
        application="Cursor",
        window_title="feature.py",
        content_fingerprint="fingerprint-code",
        capability="assistant_session",
        suggestion_type="summarize_visible_code",
        title="Summarize code",
        summary="Summarize the visible implementation.",
        proposed_request="Summarize the visible implementation changes.",
    )
    recent_span = AmbientRecentActivitySpan(
        started_at=datetime(2026, 5, 28, 10, 0),
        ended_at=datetime(2026, 5, 28, 10, 45),
        app_name="Cursor",
        window_title="feature.py",
        capture_count=2,
        activity_ids=["activity-1", "activity-2"],
        text_excerpts=["Implemented the status update feature."],
    )

    request = evaluator._build_evaluation_request(
        context,
        recent_suggestions=[recent_suggestion],
        recent_activity_spans=[recent_span],
    )

    assert request.recent_suggestion_types == ["summarize_visible_code"]
    assert request.previously_rejected is True
    assert request.recent_suggestions[0].proposed_request == "Summarize the visible implementation changes."
    assert request.recent_activity_spans[0].app_name == "Cursor"
    assert request.recent_activity_spans[0].text_excerpts == ["Implemented the status update feature."]


@pytest.mark.asyncio
async def test_ambient_history_context_groups_recent_activity_spans(tmp_path: Path) -> None:
    class Activity:
        def __init__(self, activity_id, timestamp, app_name, window_title, extracted_text):
            self.id = activity_id
            self.timestamp = timestamp
            self.app_name = app_name
            self.window_title = window_title
            self.extracted_text = extracted_text
            self.metadata = {}

    class KnowledgeService:
        async def search_activities(self, **kwargs):
            base = datetime.now() - timedelta(minutes=20)
            return [
                Activity("activity-3", base + timedelta(minutes=10), "Outlook", "Status email", "Drafting an update email"),
                Activity("activity-2", base + timedelta(minutes=5), "Cursor", "feature.py", "Added history context tests"),
                Activity("activity-1", base, "Cursor", "feature.py", "Implemented history context service"),
            ]

    service = AmbientSuggestionHistoryContextService(
        store=AmbientSuggestionStore(db_path=tmp_path / "ambient.db"),
        knowledge_service=KnowledgeService(),
    )
    context = AmbientContextEnvelope(
        capture_id="capture-email",
        timestamp=datetime.now(),
        app_name="Outlook",
        window_title="Status email",
        image_path=None,
        ocr_text="Preparing a status email",
        structured_context={},
        content_fingerprint="fingerprint-email",
    )

    spans = await service.build_recent_activity_spans(context=context)

    assert len(spans) == 2
    assert spans[0].app_name == "Cursor"
    assert spans[0].capture_count == 2
    assert spans[0].text_excerpts == ["Implemented history context service", "Added history context tests"]
    assert spans[1].app_name == "Outlook"


@pytest.mark.asyncio
async def test_ambient_evaluator_logs_raw_output_artifact_on_parse_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class Storage:
        base_path = tmp_path

        def __init__(self, development_mode: bool = True) -> None:
            pass

    class Model:
        async def generate_response(self, **kwargs):
            return "not-json but enough output to persist"

    class ModelService:
        async def load_model_by_id(self, model_id, capabilities):
            return Model()

    monkeypatch.setattr("api.services.ambient_suggestions.evaluator.StorageService", Storage)
    evaluator = AmbientSuggestionEvaluator(model_service=ModelService())  # type: ignore[arg-type]
    context = AmbientContextEnvelope(
        capture_id="capture-debug",
        timestamp="2026-05-28T10:00:00",
        app_name="Cursor",
        window_title="debug.py",
        image_path=None,
        ocr_text="Visible code context without email headers.",
        structured_context={},
        content_fingerprint="fingerprint-debug",
    )

    suggestion = await evaluator.evaluate(context, model_id="Qwen-qwen3-8b-instruct-q4km")
    artifacts = list((tmp_path / "data" / "debug" / "ambient_evaluator").glob("*.json"))

    assert suggestion.should_suggest is False
    assert len(artifacts) == 1
    assert "not-json" in artifacts[0].read_text()


def test_ambient_settings_syncs_seconds_and_minutes() -> None:
    seconds_settings = AmbientSuggestionSettings(frequency_seconds=5)
    assert seconds_settings.frequency_seconds == 5
    assert seconds_settings.frequency_minutes == pytest.approx(5 / 60)

    minutes_settings = AmbientSuggestionSettings(frequency_minutes=0.25)
    assert minutes_settings.frequency_seconds == 15


@pytest.mark.asyncio
async def test_ambient_runtime_apply_enabled_settings_does_not_start_loop(tmp_path: Path) -> None:
    runtime = AmbientSuggestionRuntime(
        model_service=None,  # type: ignore[arg-type]
        store=AmbientSuggestionStore(db_path=tmp_path / "ambient.db"),
    )

    await runtime.apply_settings(AmbientSuggestionSettings(enabled=True, frequency_seconds=5))

    assert runtime.settings.enabled is True
    assert runtime.is_running() is False


@pytest.mark.asyncio
async def test_ambient_start_route_requires_settings_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    class Runtime:
        async def apply_settings(self, settings: AmbientSuggestionSettings) -> None:
            raise AssertionError("Disabled settings should not be applied before start")

        async def start(self) -> None:
            raise AssertionError("Disabled Ambient Suggestions should not start")

    preferences = Preferences()
    preferences.ambient_suggestions = AmbientSuggestionSettings(enabled=False)
    monkeypatch.setattr(ambient_suggestion_routes, "load_preferences", lambda: preferences)
    monkeypatch.setattr(ambient_suggestion_routes, "get_ambient_suggestion_runtime", lambda: Runtime())

    with pytest.raises(HTTPException) as exc_info:
        await ambient_suggestion_routes.start_ambient_suggestions()

    assert exc_info.value.status_code == 409
    assert preferences.ambient_suggestions.enabled is False


@pytest.mark.asyncio
async def test_ambient_stop_route_does_not_disable_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    class Runtime:
        stopped = False

        async def stop(self) -> None:
            self.stopped = True

    runtime = Runtime()
    preferences = Preferences()
    preferences.ambient_suggestions = AmbientSuggestionSettings(enabled=True)
    monkeypatch.setattr(ambient_suggestion_routes, "load_preferences", lambda: preferences)
    monkeypatch.setattr(ambient_suggestion_routes, "get_ambient_suggestion_runtime", lambda: runtime)

    response = await ambient_suggestion_routes.stop_ambient_suggestions()

    assert response.success is True
    assert runtime.stopped is True
    assert preferences.ambient_suggestions.enabled is True


@pytest.mark.asyncio
async def test_ambient_runtime_evaluates_selected_api_model_without_cloud_toggle(tmp_path: Path) -> None:
    class CaptureService:
        async def capture_current_context(self) -> AmbientContextEnvelope:
            return AmbientContextEnvelope(
                capture_id="capture-2",
                timestamp="2026-05-28T10:00:00",
                app_name="Mail",
                window_title="Subject: Project update",
                image_path=None,
                ocr_text="From: Alex\nSubject: Project update\nCan you send a status update?",
                structured_context={},
                content_fingerprint="fingerprint-3",
            )

    class Evaluator:
        called = False
        recent_activity_spans = None

        async def evaluate(
            self,
            context: AmbientContextEnvelope,
            *,
            model_id: str,
            minimum_confidence: float = 0.8,
            allowed_capabilities=None,
            recent_suggestions=None,
            recent_activity_spans=None,
        ) -> AmbientSuggestionPayload:
            self.called = True
            self.recent_activity_spans = recent_activity_spans
            return AmbientSuggestionPayload(should_suggest=True, confidence=0.9)

    class HistoryContextService:
        async def build_history_context(self, *, context: AmbientContextEnvelope, cooldown_minutes: float):
            return [], [
                AmbientRecentActivitySpan(
                    started_at=datetime(2026, 5, 28, 10, 0),
                    ended_at=datetime(2026, 5, 28, 10, 30),
                    app_name="Cursor",
                    window_title="feature.py",
                    capture_count=1,
                    activity_ids=["activity-1"],
                    text_excerpts=["Recent IDE work"],
                )
            ]

    evaluator = Evaluator()
    runtime = AmbientSuggestionRuntime(
        model_service=None,  # type: ignore[arg-type]
        capture_service=CaptureService(),  # type: ignore[arg-type]
        evaluator=evaluator,  # type: ignore[arg-type]
        store=AmbientSuggestionStore(db_path=tmp_path / "ambient.db"),
        history_context_service=HistoryContextService(),  # type: ignore[arg-type]
    )
    runtime.settings = AmbientSuggestionSettings(
        evaluation_model="unknown-provider/unknown-model",
        allow_cloud_evaluation=False,
        frequency_seconds=3,
    )

    suggestion = await runtime.run_once()

    status = runtime.get_status()
    assert suggestion is None
    assert evaluator.called is True
    assert evaluator.recent_activity_spans[0].text_excerpts == ["Recent IDE work"]
    assert runtime.is_evaluating is False
    assert runtime.last_evaluation_completed_at is not None
    assert status["frequency_seconds"] == 3
    assert status["last_evaluation_completed_at"] is not None
