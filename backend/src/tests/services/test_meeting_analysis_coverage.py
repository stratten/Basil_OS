"""Tests that model-aware meeting analysis covers complete transcripts."""

import pytest

from api.core.models.model_invocation import (
    StructuredModelOutputError,
    StructuredModelResponse,
)
from api.services.whisper_live_core.post_processing import (
    meeting_analysis_executor as executor_module,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_coverage import (
    build_analysis_coverage_plan,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_executor import (
    MeetingAnalysisExecutor,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_models import (
    ActionItemsAnalysisResponse,
    AnalysisMode,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_prompts import (
    MeetingAnalysisPromptBuilder,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_reduction_prompts import (
    build_reduction_prompt,
)


class _Model:
    def __init__(self, context_window=6000, max_output_tokens=None):
        self.model_name = "unknown-test-model"
        self.max_context_length = context_window
        if max_output_tokens is not None:
            self.max_output_tokens = max_output_tokens
        self.prompts = []
        self.call_kwargs = []

    async def generate_response(self, prompt, **kwargs):
        self.prompts.append(prompt)
        self.call_kwargs.append(kwargs)
        if "reconciling a complete meeting analysis" in prompt:
            return '{"items":[{"task":"final action","context":"final evidence","timestamp":99,"speaker":"A"}]}'
        if "final-action" in prompt:
            return '{"items":[{"task":"final action","context":"final evidence","timestamp":99,"speaker":"A"}]}'
        return '{"items":[]}'


class _NativeTokenizerModel(_Model):
    class _Tokenizer:
        @staticmethod
        def encode(text):
            return list(range(max(1, len(text) // 2)))

    def __init__(self, context_window=6000):
        super().__init__(context_window)
        self.tokenizer = self._Tokenizer()


def _metadata():
    return {
        "name": "Planning",
        "participants": ["A"],
        "duration": 100.0,
        "speaker_count": 1,
    }


def _transcript(segment_count=3, words_per_segment=20):
    return {
        "segments": [
            {
                "start": index * 10,
                "end": index * 10 + 9,
                "speaker": "A",
                "text": f"segment-{index} " + " ".join(["word"] * words_per_segment),
            }
            for index in range(segment_count)
        ]
    }


def test_suggested_actions_prompt_requires_outcome_level_todo_candidates():
    prompt = MeetingAnalysisPromptBuilder().build_suggested_actions_prompt(
        "",
        _metadata(),
    )

    assert "Return one candidate only for a concrete, unresolved outcome" in prompt
    assert "Do not return a candidate for work completed, closed, billed" in prompt
    assert "Group checklist-level tasks into one candidate" in prompt
    assert "source_action_item_indexes" in prompt
    assert "disposition" in prompt
    assert "execution_mode" in prompt
    assert "Research viable encryption key management and rotation options" in prompt
    assert 'execution_mode "agent_assisted"' in prompt
    assert "Missing inputs should be listed in missing_information" in prompt


def test_suggested_actions_reduction_prompt_requires_grouping_and_filters_non_candidates():
    prompt = build_reduction_prompt(
        mode=AnalysisMode.SUGGESTED_ACTIONS,
        chunk_results=[],
        meeting_metadata=_metadata(),
        custom_instructions=None,
    )

    assert "outcome-level candidate" in prompt
    assert 'todo_candidate' in prompt
    assert "execution_mode" in prompt
    assert "source_action_item_indexes" in prompt
    assert "research, drafting, planning" in prompt
    assert "missing_information rather than forcing todo_only" in prompt


def test_large_context_uses_one_chunk_and_preserves_all_segments():
    transcript = _transcript(segment_count=3, words_per_segment=100)
    plan = build_analysis_coverage_plan(
        model=_Model(context_window=1_000_000),
        transcript=transcript,
        prompt_without_transcript="static prompt",
    )

    assert len(plan.chunks) == 1
    assert all(f"segment-{index}" in plan.chunks[0].transcript for index in range(3))


def test_coverage_plan_reserves_the_selected_models_output_limit():
    plan = build_analysis_coverage_plan(
        model=_Model(context_window=20_000, max_output_tokens=8_192),
        transcript=_transcript(),
        prompt_without_transcript="static prompt",
    )

    assert plan.input_budget_tokens == 11_808


def test_small_context_chunks_at_segment_boundaries_without_dropping_text():
    transcript = _transcript(segment_count=10, words_per_segment=250)
    plan = build_analysis_coverage_plan(
        model=_Model(context_window=6000),
        transcript=transcript,
        prompt_without_transcript="static prompt",
    )

    assert len(plan.chunks) > 1
    combined = "\n".join(chunk.transcript for chunk in plan.chunks)
    assert all(f"segment-{index}" in combined for index in range(10))
    assert all(chunk.estimated_tokens <= plan.transcript_budget_tokens for chunk in plan.chunks)


def test_chunk_planning_uses_loaded_models_native_tokenizer():
    model = _NativeTokenizerModel(context_window=6000)
    transcript = _transcript(segment_count=10, words_per_segment=250)
    plan = build_analysis_coverage_plan(
        model=model,
        transcript=transcript,
        prompt_without_transcript="static prompt",
    )

    assert len(plan.chunks) > 1
    assert all(
        len(model.tokenizer.encode(chunk.transcript)) <= plan.transcript_budget_tokens
        for chunk in plan.chunks
    )


def test_reduction_grouping_uses_loaded_models_native_tokenizer():
    model = _NativeTokenizerModel(context_window=6000)

    groups = MeetingAnalysisExecutor._pack_reduction_groups(
        ["abcdefghijkl", "mnopqrstuvwx"],
        budget_tokens=10,
        model=model,
    )

    assert groups == [["abcdefghijkl"], ["mnopqrstuvwx"]]


def test_oversize_segment_is_continued_without_losing_words():
    transcript = _transcript(segment_count=1, words_per_segment=4000)
    plan = build_analysis_coverage_plan(
        model=_Model(context_window=6000),
        transcript=transcript,
        prompt_without_transcript="static prompt",
    )

    assert len(plan.chunks) > 1
    combined = " ".join(chunk.transcript for chunk in plan.chunks)
    assert combined.count("word") == 4000
    assert all("[00:00] A:" in chunk.transcript for chunk in plan.chunks)


def test_too_small_context_is_rejected_instead_of_truncated():
    with pytest.raises(ValueError, match="larger-context model"):
        build_analysis_coverage_plan(
            model=_Model(context_window=1200),
            transcript=_transcript(),
            prompt_without_transcript="x" * 1000,
        )


@pytest.mark.asyncio
async def test_multi_chunk_action_analysis_reduces_all_chunk_results():
    model = _Model(context_window=6000)
    executor = MeetingAnalysisExecutor("meeting-1", MeetingAnalysisPromptBuilder())
    transcript = _transcript(segment_count=10, words_per_segment=250)

    result = await executor.analyze_mode(
        mode=AnalysisMode.ACTION_ITEMS,
        transcript=transcript,
        meeting_metadata=_metadata(),
        custom_instructions=None,
        prior_results={},
        model=model,
    )

    assert result[0].task == "final action"
    assert any("chunk 1 of" in prompt for prompt in model.prompts)
    assert any("chunk 2 of" in prompt for prompt in model.prompts)
    assert any("reconciling a complete meeting analysis" in prompt for prompt in model.prompts)
    assert all(kwargs["max_tokens"] == 4096 for kwargs in model.call_kwargs)
    assert executor.enforcement_modes == {"strict_json_fallback"}
    assert sum("chunk 1 of" in prompt for prompt in model.prompts) == 1
    assert sum("chunk 2 of" in prompt for prompt in model.prompts) == 1
    assert (
        sum(
            "reconciling a complete meeting analysis" in prompt
            for prompt in model.prompts
        )
        == 1
    )


@pytest.mark.asyncio
async def test_chunk_and_reduction_calls_use_the_selected_models_output_limit(
    monkeypatch,
):
    model = _Model(context_window=20_000, max_output_tokens=8_192)
    transcript = _transcript(segment_count=4, words_per_segment=3_000)
    calls = []

    async def fake_structured_call(
        _model,
        *,
        prompt,
        response_model,
        max_tokens,
    ):
        calls.append((prompt, response_model, max_tokens))
        payload = {
            "items": [
                {
                    "task": "complete action",
                    "context": "complete evidence",
                    "timestamp": 39,
                    "speaker": "A",
                }
            ]
        }
        return StructuredModelResponse(
            value=response_model.model_validate(payload),
            enforcement="strict_json_fallback",
        )

    monkeypatch.setattr(
        executor_module,
        "call_model_with_schema",
        fake_structured_call,
    )
    executor = MeetingAnalysisExecutor(
        "meeting-1",
        MeetingAnalysisPromptBuilder(),
    )

    result = await executor.analyze_mode(
        mode=AnalysisMode.ACTION_ITEMS,
        transcript=transcript,
        meeting_metadata=_metadata(),
        custom_instructions=None,
        prior_results={},
        model=model,
    )

    assert result[0].task == "complete action"
    assert len(calls) == 3
    assert all(max_tokens == 8_192 for _, _, max_tokens in calls)


@pytest.mark.asyncio
async def test_transient_structured_failure_retries_once(monkeypatch):
    model = _Model(context_window=1_000_000)
    calls = []

    async def fake_structured_call(
        _model,
        *,
        prompt,
        response_model,
        max_tokens,
    ):
        calls.append(max_tokens)
        if len(calls) == 1:
            raise StructuredModelOutputError(
                "temporary",
                category="transient",
                retryable=True,
            )
        return StructuredModelResponse(
            value=response_model.model_validate({"items": []}),
            enforcement="strict_json_fallback",
        )

    monkeypatch.setattr(
        executor_module,
        "call_model_with_schema",
        fake_structured_call,
    )
    executor = MeetingAnalysisExecutor(
        "meeting-1",
        MeetingAnalysisPromptBuilder(),
    )

    result = await executor.analyze_mode(
        mode=AnalysisMode.ACTION_ITEMS,
        transcript=_transcript(),
        meeting_metadata=_metadata(),
        custom_instructions=None,
        prior_results={},
        model=model,
    )

    assert result == []
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_output_limit_failure_does_not_retry(monkeypatch):
    model = _Model(context_window=1_000_000)
    calls = []

    async def fake_structured_call(
        _model,
        *,
        prompt,
        response_model,
        max_tokens,
    ):
        calls.append(max_tokens)
        raise StructuredModelOutputError(
            "anthropic_output_format ended incompletely: finish_reason=max_tokens",
            category="output_limit",
            retryable=False,
        )

    monkeypatch.setattr(
        executor_module,
        "call_model_with_schema",
        fake_structured_call,
    )
    executor = MeetingAnalysisExecutor(
        "meeting-1",
        MeetingAnalysisPromptBuilder(),
    )

    with pytest.raises(StructuredModelOutputError, match="finish_reason=max_tokens"):
        await executor.analyze_mode(
            mode=AnalysisMode.ACTION_ITEMS,
            transcript=_transcript(),
            meeting_metadata=_metadata(),
            custom_instructions=None,
            prior_results={},
            model=model,
        )

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_two_chunks_and_reduction_use_the_same_response_contract(
    monkeypatch,
):
    model = _Model(context_window=6000)
    transcript = _transcript(segment_count=4, words_per_segment=250)
    plan = build_analysis_coverage_plan(
        model=model,
        transcript=transcript,
        prompt_without_transcript=MeetingAnalysisPromptBuilder().build_action_items_prompt(
            "",
            _metadata(),
            None,
        ),
    )
    assert len(plan.chunks) == 2
    calls = []

    async def fake_structured_call(
        _model,
        *,
        prompt,
        response_model,
        max_tokens,
    ):
        calls.append((prompt, response_model, max_tokens))
        payload = {
            "items": [
                {
                    "task": "final action",
                    "context": "final evidence",
                    "timestamp": 39,
                    "speaker": "A",
                }
            ]
        } if "reconciling a complete meeting analysis" in prompt else {"items": []}
        return StructuredModelResponse(
            value=response_model.model_validate(payload),
            enforcement="strict_json_fallback",
        )

    monkeypatch.setattr(
        executor_module,
        "call_model_with_schema",
        fake_structured_call,
    )
    executor = MeetingAnalysisExecutor(
        "meeting-1",
        MeetingAnalysisPromptBuilder(),
    )
    result = await executor.analyze_mode(
        mode=AnalysisMode.ACTION_ITEMS,
        transcript=transcript,
        meeting_metadata=_metadata(),
        custom_instructions=None,
        prior_results={},
        model=model,
    )

    assert result[0].task == "final action"
    assert len(calls) == 3
    assert all(call[1] is ActionItemsAnalysisResponse for call in calls)
    assert executor.enforcement_modes == {"strict_json_fallback"}


@pytest.mark.asyncio
async def test_later_chunk_findings_survive_reconciliation_and_enforcement_accumulates(
    monkeypatch,
):
    model = _Model(context_window=6000)
    transcript = _transcript(segment_count=4, words_per_segment=250)
    calls = []

    async def fake_structured_call(
        _model,
        *,
        prompt,
        response_model,
        max_tokens,
    ):
        calls.append((prompt, response_model, max_tokens))
        if "reconciling a complete meeting analysis" in prompt:
            assert "early finding" in prompt
            assert "later finding" in prompt
            payload = {
                "items": [
                    {
                        "task": "early finding",
                        "context": "segment-0 evidence",
                        "timestamp": 0,
                        "speaker": "A",
                    },
                    {
                        "task": "later finding",
                        "context": "segment-3 evidence",
                        "timestamp": 39,
                        "speaker": "A",
                    },
                ]
            }
            enforcement = "strict_json_fallback"
        elif "segment-3" in prompt:
            payload = {
                "items": [
                    {
                        "task": "later finding",
                        "context": "segment-3 evidence",
                        "timestamp": 39,
                        "speaker": "A",
                    }
                ]
            }
            enforcement = "gemini_response_schema"
        else:
            payload = {
                "items": [
                    {
                        "task": "early finding",
                        "context": "segment-0 evidence",
                        "timestamp": 0,
                        "speaker": "A",
                    }
                ]
            }
            enforcement = "llama_cpp_json_schema"
        return StructuredModelResponse(
            value=response_model.model_validate(payload),
            enforcement=enforcement,
        )

    monkeypatch.setattr(
        executor_module,
        "call_model_with_schema",
        fake_structured_call,
    )
    executor = MeetingAnalysisExecutor(
        "meeting-1",
        MeetingAnalysisPromptBuilder(),
    )
    result = await executor.analyze_mode(
        mode=AnalysisMode.ACTION_ITEMS,
        transcript=transcript,
        meeting_metadata=_metadata(),
        custom_instructions=None,
        prior_results={},
        model=model,
    )

    assert [item.task for item in result] == ["early finding", "later finding"]
    assert len(calls) == 3
    assert all(call[1] is ActionItemsAnalysisResponse for call in calls)
    assert executor.enforcement_modes == {
        "gemini_response_schema",
        "llama_cpp_json_schema",
        "strict_json_fallback",
    }


@pytest.mark.asyncio
async def test_single_chunk_run_does_not_reconcile(monkeypatch):
    calls = []

    async def fake_structured_call(
        _model,
        *,
        prompt,
        response_model,
        max_tokens,
    ):
        calls.append((prompt, response_model, max_tokens))
        return StructuredModelResponse(
            value=response_model.model_validate({"items": []}),
            enforcement="strict_json_fallback",
        )

    monkeypatch.setattr(
        executor_module,
        "call_model_with_schema",
        fake_structured_call,
    )
    executor = MeetingAnalysisExecutor(
        "meeting-1",
        MeetingAnalysisPromptBuilder(),
    )
    result = await executor.analyze_mode(
        mode=AnalysisMode.ACTION_ITEMS,
        transcript=_transcript(),
        meeting_metadata=_metadata(),
        custom_instructions=None,
        prior_results={},
        model=_Model(context_window=1_000_000),
    )

    assert result == []
    assert len(calls) == 1
    assert "reconciling a complete meeting analysis" not in calls[0][0]


@pytest.mark.asyncio
async def test_typed_chunk_rejects_out_of_range_timestamp_before_finalization(
    monkeypatch,
):
    async def fake_structured_call(
        _model,
        *,
        prompt,
        response_model,
        max_tokens,
    ):
        return StructuredModelResponse(
            value=response_model.model_validate(
                {
                    "items": [
                        {
                            "task": "fabricated future task",
                            "context": "not in transcript",
                            "timestamp": 999,
                            "speaker": "A",
                        }
                    ]
                }
            ),
            enforcement="strict_json_fallback",
        )

    monkeypatch.setattr(
        executor_module,
        "call_model_with_schema",
        fake_structured_call,
    )
    executor = MeetingAnalysisExecutor(
        "meeting-1",
        MeetingAnalysisPromptBuilder(),
    )

    with pytest.raises(RuntimeError, match=r"999\.0.*outside the transcript range"):
        await executor.analyze_mode(
            mode=AnalysisMode.ACTION_ITEMS,
            transcript=_transcript(),
            meeting_metadata=_metadata(),
            custom_instructions=None,
            prior_results={},
            model=_Model(context_window=1_000_000),
        )


@pytest.mark.asyncio
async def test_refusal_recovery_preserves_safe_action_items_and_records_leaf_omission(
    monkeypatch,
):
    refusal = StructuredModelOutputError(
        "anthropic_output_format ended incompletely: finish_reason=refusal",
        category="safety",
        refusal_category="general_harms",
        refusal_explanation="The provider declined this range.",
    )

    async def fake_structured_call(
        _model,
        *,
        prompt,
        response_model,
        max_tokens,
    ):
        if "segment-0" in prompt and "segment-1" in prompt and "segment-2" in prompt:
            raise refusal
        if "segment-2" in prompt:
            raise refusal
        return StructuredModelResponse(
            value=response_model.model_validate(
                {
                    "items": [
                        {
                            "task": "Keep the safe action item",
                            "context": "segment-0 evidence",
                            "timestamp": 0,
                            "speaker": "A",
                        }
                    ]
                }
            ),
            enforcement="anthropic_output_format",
        )

    monkeypatch.setattr(executor_module, "call_model_with_schema", fake_structured_call)
    executor = MeetingAnalysisExecutor("meeting-1", MeetingAnalysisPromptBuilder())

    result = await executor.analyze_mode(
        mode=AnalysisMode.ACTION_ITEMS,
        transcript=_transcript(),
        meeting_metadata=_metadata(),
        custom_instructions=None,
        prior_results={},
        model=_Model(context_window=1_000_000),
    )

    assert [item.task for item in result] == ["Keep the safe action item"]
    assert len(executor.safety_omissions) == 1
    omission = executor.safety_omissions[0]
    assert omission.start_timestamp == 20
    assert omission.refusal_category == "general_harms"
    assert omission.recovery == "omitted_refused_line"


@pytest.mark.asyncio
async def test_refusal_recovery_uses_local_summary_when_reduction_refuses(monkeypatch):
    refusal = StructuredModelOutputError(
        "anthropic_output_format ended incompletely: finish_reason=refusal",
        category="safety",
        refusal_category="general_harms",
    )

    async def fake_structured_call(
        _model,
        *,
        prompt,
        response_model,
        max_tokens,
    ):
        if "reconciling a complete meeting analysis" in prompt:
            raise refusal
        if "segment-0" in prompt and "segment-1" in prompt:
            raise refusal
        if "segment-0" in prompt:
            payload = {"markdown": "First safe summary."}
        else:
            payload = {"markdown": "Second safe summary."}
        return StructuredModelResponse(
            value=response_model.model_validate(payload),
            enforcement="anthropic_output_format",
        )

    monkeypatch.setattr(executor_module, "call_model_with_schema", fake_structured_call)
    executor = MeetingAnalysisExecutor("meeting-1", MeetingAnalysisPromptBuilder())

    result = await executor.analyze_mode(
        mode=AnalysisMode.SUMMARY,
        transcript=_transcript(segment_count=2),
        meeting_metadata=_metadata(),
        custom_instructions=None,
        prior_results={},
        model=_Model(context_window=1_000_000),
    )

    assert result == "## Part 1\n\nFirst safe summary.\n\n## Part 2\n\nSecond safe summary."
    assert executor.safety_omissions == []


@pytest.mark.asyncio
async def test_refusal_recovery_stops_at_localization_limit(monkeypatch):
    refusal = StructuredModelOutputError(
        "anthropic_output_format ended incompletely: finish_reason=refusal",
        category="safety",
        refusal_category="general_harms",
    )

    async def fake_structured_call(*_args, **_kwargs):
        raise refusal

    monkeypatch.setattr(executor_module, "call_model_with_schema", fake_structured_call)
    monkeypatch.setattr(executor_module, "MAX_REFUSAL_LOCALIZATION_CALLS", 2)
    executor = MeetingAnalysisExecutor("meeting-1", MeetingAnalysisPromptBuilder())

    with pytest.raises(StructuredModelOutputError, match="could not safely localize"):
        await executor.analyze_mode(
            mode=AnalysisMode.ACTION_ITEMS,
            transcript=_transcript(segment_count=4),
            meeting_metadata=_metadata(),
            custom_instructions=None,
            prior_results={},
            model=_Model(context_window=1_000_000),
        )
