import json

import pytest
from pydantic import ValidationError

from api.services.whisper_live_core.post_processing import (
    meeting_analyzer as analyzer_module,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_executor import (
    MeetingAnalysisExecutor,
    validate_analysis_timestamps,
)
from api.core.models.model_invocation import StructuredModelOutputError
from api.services.whisper_live_core.post_processing.meeting_analysis_models import (
    ANALYSIS_RESPONSE_MODELS,
    AnalysisMode,
    AnalysisModeFailure,
    AnalysisSafetyOmission,
    CustomAnalysisResponse,
    MeetingAnalysisResult,
    SuggestedActionsAnalysisResponse,
    SuggestedActionDraft,
    SummaryAnalysisResponse,
)
from api.services.whisper_live_core.post_processing.meeting_analyzer import (
    MeetingAnalyzer,
)


def test_sentiment_contract_validates_outer_object_with_nested_arrays():
    response_model = ANALYSIS_RESPONSE_MODELS[AnalysisMode.SENTIMENT]
    parsed = response_model.model_validate(
        {
            "analysis": {
                "overall_sentiment": "positive",
                "sentiment_score": 0.6,
                "engagement_level": "high",
                "speaker_sentiments": {
                    "Microphone": {
                        "sentiment": "positive",
                        "engagement": "high",
                        "key_contributions": "Asked implementation questions",
                    }
                },
                "positive_moments": [
                    {
                        "timestamp": 3421.0,
                        "description": "Agreed next step",
                        "context": "Sounds good",
                    }
                ],
                "negative_moments": [],
                "tone_indicators": ["collaborative", "technical"],
            }
        }
    )
    assert parsed.analysis.overall_sentiment == "positive"
    assert parsed.analysis.positive_moments[0]["timestamp"] == 3421.0


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("disposition", "unknown"),
        ("execution_mode", "automatically_execute"),
    ],
)
def test_suggested_action_draft_rejects_invalid_classification(
    field_name: str,
    field_value: str,
) -> None:
    payload = {
        "source_task": "Follow up with Alex.",
        "suggested_agent_task": "Draft the follow-up message.",
        "why_basil_can_help": "This is an unresolved follow-up.",
        "disposition": "todo_candidate",
        "execution_mode": "agent_assisted",
    }
    payload[field_name] = field_value

    with pytest.raises(ValidationError):
        SuggestedActionDraft.model_validate(payload)


def test_structured_analysis_rejects_timestamp_beyond_transcript_duration():
    transcript = {
        "segments": [
            {"start": 0.0, "end": 120.0, "text": "Opening"},
            {"start": 3400.0, "end": 3469.0, "text": "Closing"},
        ]
    }
    result = {
        "positive_moments": [
            {"timestamp": 6810.0, "description": "Fabricated late moment"}
        ]
    }

    with pytest.raises(
        RuntimeError,
        match=r"6810\.0.*outside the transcript range 0\.0-3469\.0",
    ):
        validate_analysis_timestamps(result, transcript)


def test_structured_analysis_accepts_timestamp_in_final_transcript_minute():
    transcript = {
        "segments": [
            {"start": 0.0, "end": 120.0, "text": "Opening"},
            {"start": 3400.0, "end": 3469.0, "text": "Closing"},
        ]
    }
    result = {
        "positive_moments": [
            {"timestamp": 3421.0, "description": "Valid closing moment"}
        ]
    }

    validate_analysis_timestamps(result, transcript)


@pytest.mark.asyncio
async def test_analyzer_persists_partial_success_when_one_mode_fails(monkeypatch):
    analyzer = MeetingAnalyzer("meeting-1")
    save_called = False
    saved_result = None

    async def no_op():
        return None

    async def analyze_mode(mode, *_args, **_kwargs):
        if mode == AnalysisMode.SENTIMENT:
            raise RuntimeError(
                "sentiment failed",
            ) from StructuredModelOutputError(
                "anthropic_output_format ended incompletely: finish_reason=max_tokens",
                category="output_limit",
                retryable=False,
            )
        return "Complete summary"

    async def record_save(result, *_args, **_kwargs):
        nonlocal save_called, saved_result
        save_called = True
        saved_result = result
        analyzer.saved_analysis_filename = "analysis_test.json"

    monkeypatch.setattr(analyzer, "_load_transcript", no_op)
    monkeypatch.setattr(analyzer, "_load_model", no_op)
    monkeypatch.setattr(analyzer, "_load_identity_and_capabilities", no_op)
    monkeypatch.setattr(analyzer, "_analyze_mode", analyze_mode)
    monkeypatch.setattr(analyzer, "_save_analysis", record_save)

    result = await analyzer.analyze(
        [AnalysisMode.SUMMARY.value, AnalysisMode.SENTIMENT.value]
    )

    assert save_called is True
    assert saved_result is result
    assert result.requested_modes == [
        AnalysisMode.SUMMARY.value,
        AnalysisMode.SENTIMENT.value,
    ]
    assert result.modes_analyzed == [AnalysisMode.SUMMARY.value]
    assert len(result.failed_modes) == 1
    assert result.failed_modes[0].mode == AnalysisMode.SENTIMENT.value
    assert result.failed_modes[0].category == "output_limit"
    assert result.summary == "Complete summary"
    assert analyzer.saved_analysis_filename is not None


@pytest.mark.asyncio
async def test_analyzer_persists_zero_success_with_failure_diagnostics(
    monkeypatch,
    tmp_path,
):
    analyzer = MeetingAnalyzer("meeting-1", "test-model")
    analyzer.meeting_dir = tmp_path

    async def no_op():
        return None

    async def fail_mode(*_args, **_kwargs):
        raise RuntimeError("malformed structured output")

    monkeypatch.setattr(analyzer, "_load_transcript", no_op)
    monkeypatch.setattr(analyzer, "_load_model", no_op)
    monkeypatch.setattr(analyzer, "_load_identity_and_capabilities", no_op)
    monkeypatch.setattr(analyzer, "_analyze_mode", fail_mode)
    monkeypatch.setattr(
        analyzer_module.MeetingRecorder,
        "load_metadata",
        lambda _meeting_id: None,
    )

    result = await analyzer.analyze([AnalysisMode.SUMMARY.value])

    assert result.modes_analyzed == []
    assert result.requested_modes == [AnalysisMode.SUMMARY.value]
    assert len(result.failed_modes) == 1
    assert result.failed_modes[0].mode == AnalysisMode.SUMMARY.value
    assert result.failed_modes[0].category == "internal"
    assert analyzer.saved_analysis_filename is not None
    saved_payload = json.loads(
        (tmp_path / analyzer.saved_analysis_filename).read_text()
    )
    assert saved_payload["modes_analyzed"] == []
    assert saved_payload["failed_modes"][0]["mode"] == AnalysisMode.SUMMARY.value


def test_legacy_analysis_result_defaults_requested_and_failed_mode_lists():
    legacy_payload = {
        "meeting_id": "meeting-1",
        "analyzed_at": "2026-01-01T00:00:00",
        "model_used": "test-model",
        "modes_analyzed": ["summary"],
        "transcript_duration": 60.0,
        "speaker_count": 1,
        "processing_time": 1.0,
        "summary": "Legacy summary",
    }

    result = MeetingAnalysisResult.model_validate(legacy_payload)

    assert result.requested_modes == []
    assert result.failed_modes == []
    assert result.modes_analyzed == ["summary"]


def test_analysis_result_records_explicit_local_model_id():
    analyzer = MeetingAnalyzer("meeting-1", "Qwen-qwen3-8b-instruct-q4km")
    analyzer.model = object()
    analyzer.transcript = {"segments": []}

    result = analyzer._build_analysis_result(
        modes=[AnalysisMode.SUMMARY.value],
        results={AnalysisMode.SUMMARY.value: "Complete summary"},
        custom_instructions=None,
        processing_time=1.0,
        failed_modes=[],
    )

    assert result.model_used == "Qwen-qwen3-8b-instruct-q4km"


@pytest.mark.parametrize("mode", list(AnalysisMode))
def test_every_analysis_mode_has_object_root_schema(mode):
    schema = ANALYSIS_RESPONSE_MODELS[mode].model_json_schema()
    assert schema["type"] == "object"


@pytest.mark.parametrize(
    "mode",
    [
        AnalysisMode.ACTION_ITEMS,
        AnalysisMode.SUGGESTED_ACTIONS,
        AnalysisMode.DECISIONS,
        AnalysisMode.QUESTIONS,
    ],
)
def test_item_contracts_accept_empty_items(mode):
    response = ANALYSIS_RESPONSE_MODELS[mode].model_validate({"items": []})
    assert response.items == []


@pytest.mark.parametrize(
    ("response_model", "missing_field"),
    [
        (SummaryAnalysisResponse, "markdown"),
        (CustomAnalysisResponse, "content"),
    ],
)
def test_text_contracts_require_their_named_field(response_model, missing_field):
    with pytest.raises(Exception, match=missing_field):
        response_model.model_validate({})


def test_sentiment_contract_requires_analysis_field():
    response_model = ANALYSIS_RESPONSE_MODELS[AnalysisMode.SENTIMENT]
    with pytest.raises(Exception, match="analysis"):
        response_model.model_validate(
            {
                "overall_sentiment": "positive",
                "sentiment_score": 0.6,
                "engagement_level": "high",
            }
        )


def test_suggested_action_draft_rejects_backend_owned_id():
    with pytest.raises(Exception):
        SuggestedActionDraft.model_validate(
            {
                "id": "model-owned-id",
                "source_task": "Follow up",
                "suggested_agent_task": "Draft the follow-up",
                "why_basil_can_help": "You can use Basil to draft it.",
                "disposition": "todo_candidate",
            }
        )


def test_suggested_actions_receive_stable_ids_only_during_finalization():
    response = SuggestedActionsAnalysisResponse.model_validate(
        {
            "items": [
                {
                    "source_action_item_index": 0,
                    "source_task": "Follow up",
                    "suggested_agent_task": "Draft the follow-up",
                    "why_basil_can_help": "You can use Basil to draft it.",
                    "disposition": "todo_candidate",
                }
            ]
        }
    )
    serialized_draft = response.model_dump(mode="json")
    assert "id" not in serialized_draft["items"][0]

    executor = MeetingAnalysisExecutor("meeting-1", object())
    first = executor._finalize_mode_response(
        AnalysisMode.SUGGESTED_ACTIONS,
        response,
    )
    second = executor._finalize_mode_response(
        AnalysisMode.SUGGESTED_ACTIONS,
        response,
    )

    assert first[0].id
    assert first[0].id == second[0].id


def test_legacy_analysis_result_defaults_enforcement_metadata():
    analyzer = MeetingAnalyzer("meeting-1", "Qwen-qwen3-8b-instruct-q4km")
    analyzer.model = object()
    analyzer.transcript = {"segments": []}
    result = analyzer._build_analysis_result(
        modes=[AnalysisMode.SUMMARY.value],
        results={AnalysisMode.SUMMARY.value: "Complete summary"},
        custom_instructions=None,
        processing_time=1.0,
        failed_modes=[],
    )
    assert result.structured_output_enforcement == {}


def test_analysis_result_preserves_external_shape_with_additive_enforcement():
    analyzer = MeetingAnalyzer("meeting-1", "Qwen-qwen3-8b-instruct-q4km")
    analyzer.model = object()
    analyzer.transcript = {"segments": []}
    analyzer._structured_output_enforcement = {
        AnalysisMode.SUMMARY.value: ["llama_cpp_json_schema"]
    }
    result = analyzer._build_analysis_result(
        modes=[AnalysisMode.SUMMARY.value],
        results={AnalysisMode.SUMMARY.value: "Complete summary"},
        custom_instructions=None,
        processing_time=1.0,
        failed_modes=[],
    )
    serialized = result.to_dict()
    assert serialized["summary"] == "Complete summary"
    assert serialized["model_used"] == "Qwen-qwen3-8b-instruct-q4km"
    assert serialized["structured_output_enforcement"] == {
        "summary": ["llama_cpp_json_schema"]
    }
    assert "action_items" in serialized
    assert "sentiment_analysis" in serialized


def test_analysis_result_serializes_refusal_diagnostics_and_safety_omissions():
    result = MeetingAnalysisResult(
        meeting_id="meeting-1",
        analyzed_at="2026-08-21T14:00:00",
        model_used="claude-test",
        failed_modes=[
            AnalysisModeFailure(
                mode="summary",
                category="safety",
                message="provider refusal",
                retryable=False,
                refusal_category="general_harms",
                refusal_explanation="The provider declined this range.",
            )
        ],
        safety_omissions=[
            AnalysisSafetyOmission(
                mode="action_items",
                start_timestamp=20,
                end_timestamp=20,
                segment_count=1,
                provider="anthropic",
                refusal_category="general_harms",
                refusal_explanation="The provider declined this range.",
                recovery="omitted_refused_line",
            )
        ],
        transcript_duration=60,
        speaker_count=1,
        processing_time=1,
    )

    serialized = result.to_dict()

    assert serialized["failed_modes"][0]["refusal_category"] == "general_harms"
    assert serialized["safety_omissions"][0]["start_timestamp"] == 20
    restored = MeetingAnalysisResult.model_validate(serialized)
    assert restored.safety_omissions[0].recovery == "omitted_refused_line"


def test_legacy_analysis_result_defaults_refusal_fields_and_safety_omissions():
    result = MeetingAnalysisResult.model_validate(
        {
            "meeting_id": "meeting-1",
            "analyzed_at": "2026-08-21T14:00:00",
            "model_used": "claude-test",
            "failed_modes": [
                {
                    "mode": "summary",
                    "category": "safety",
                    "message": "provider refusal",
                    "retryable": False,
                }
            ],
            "transcript_duration": 60,
            "speaker_count": 1,
            "processing_time": 1,
        }
    )

    assert result.failed_modes[0].refusal_category is None
    assert result.failed_modes[0].refusal_explanation is None
    assert result.safety_omissions == []
