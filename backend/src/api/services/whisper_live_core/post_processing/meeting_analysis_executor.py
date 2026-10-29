"""Model-aware complete-coverage execution for one meeting analysis mode."""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from api.core.models.model_invocation import (
    StructuredModelOutputError,
    call_model_with_schema,
)
from api.core.models.reasoning.streaming_contract import resolve_generation_budget

from .meeting_analysis_concurrency import (
    LOCAL_MODEL_CONCURRENCY,
    AnalysisCallLimiter,
    gather_cancel_on_error,
)
from .meeting_analysis_events import ITEM_STREAM_MODELS, AnalysisItemSink
from .meeting_analysis_item_stream import IncrementalItemsParser
from .meeting_analysis_narrowing import narrow_transcript_for_suggestions
from .meeting_analysis_timing import (
    AnalysisCallLabel,
    AnalysisCallTiming,
    AnalysisTimingRecorder,
    describe_model_id,
)

from .meeting_analysis_coverage import (
    build_analysis_coverage_plan,
    estimate_model_tokens,
    split_transcript_chunk,
    TranscriptChunk,
)
from .meeting_analysis_models import (
    ANALYSIS_RESPONSE_MODELS,
    ActionItemsAnalysisResponse,
    AnalysisContractModel,
    AnalysisMode,
    CustomAnalysisResponse,
    DecisionsAnalysisResponse,
    QuestionsAnalysisResponse,
    AnalysisSafetyOmission,
    SentimentAnalysisResponse,
    SuggestedActionsAnalysisResponse,
    SummaryAnalysisResponse,
    build_action_proposals,
)
from .meeting_analysis_prompts import MeetingAnalysisPromptBuilder
from .meeting_analysis_reduction_prompts import (
    build_chunk_analysis_instruction,
    build_reduction_prompt,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[Dict[str, Any]], Awaitable[None]]
MAX_REFUSAL_LOCALIZATION_CALLS = 32
_FORMATTED_LINE_TIMESTAMP = re.compile(r"^\[(\d{2,}):(\d{2})\]")


def _is_anthropic_refusal(error: StructuredModelOutputError) -> bool:
    return (
        error.category == "safety"
        and (
            error.refusal_category is not None
            or "anthropic_output_format" in str(error)
        )
    )


def _formatted_line_timestamp(line: str) -> float:
    match = _FORMATTED_LINE_TIMESTAMP.match(line)
    if match is None:
        return 0.0
    return float(int(match.group(1)) * 60 + int(match.group(2)))


class MeetingAnalysisExecutor:
    """Run a mode once or map/reduce it over every transcript chunk."""

    def __init__(
        self,
        meeting_id: str,
        prompt_builder: MeetingAnalysisPromptBuilder,
        *,
        timing_recorder: Optional[AnalysisTimingRecorder] = None,
        call_limiter: Optional[AnalysisCallLimiter] = None,
        item_sink: Optional[AnalysisItemSink] = None,
    ):
        self.meeting_id = meeting_id
        self.prompt_builder = prompt_builder
        self.enforcement_modes: set[str] = set()
        self.safety_omissions: list[AnalysisSafetyOmission] = []
        self._refusal_localization_calls = 0
        self._timing_recorder = timing_recorder
        self._call_limiter = call_limiter or AnalysisCallLimiter(
            LOCAL_MODEL_CONCURRENCY
        )
        self._item_sink = item_sink

    async def _call_schema_with_transient_retry(
        self,
        *,
        model: Any,
        prompt: str,
        response_model: type[AnalysisContractModel],
        max_tokens: int,
        label: Optional[AnalysisCallLabel] = None,
        stream_factory: Optional[
            Callable[[], Awaitable[Callable[[str], Awaitable[None]]]]
        ] = None,
    ) -> Any:
        """Replay one transient structured request without accepting partial output."""
        try:
            return await self._timed_schema_call(
                model=model,
                prompt=prompt,
                response_model=response_model,
                max_tokens=max_tokens,
                label=label,
                attempt=1,
                stream_factory=stream_factory,
            )
        except StructuredModelOutputError as error:
            if not error.retryable:
                raise
            logger.warning(
                "Retrying transient meeting-analysis call: %s",
                error.category,
            )
            return await self._timed_schema_call(
                model=model,
                prompt=prompt,
                response_model=response_model,
                max_tokens=max_tokens,
                label=label,
                attempt=2,
                stream_factory=stream_factory,
            )

    async def _timed_schema_call(
        self,
        *,
        model: Any,
        prompt: str,
        response_model: type[AnalysisContractModel],
        max_tokens: int,
        label: Optional[AnalysisCallLabel],
        attempt: int,
        stream_factory: Optional[
            Callable[[], Awaitable[Callable[[str], Awaitable[None]]]]
        ] = None,
    ) -> Any:
        """Make one limiter-bounded structured call and record how long it took."""
        queued_at = time.monotonic()
        async with self._call_limiter.slot():
            started = time.monotonic()
            started_offset = (
                self._timing_recorder.offset() if self._timing_recorder else 0.0
            )
            try:
                stream_kwargs: Dict[str, Any] = {}
                if stream_factory is not None:
                    stream_kwargs["on_text_delta"] = await stream_factory()
                response = await call_model_with_schema(
                    model,
                    prompt=prompt,
                    response_model=response_model,
                    max_tokens=max_tokens,
                    **stream_kwargs,
                )
            except Exception as error:
                self._record_call(
                    label=label,
                    model=model,
                    prompt=prompt,
                    max_tokens=max_tokens,
                    attempt=attempt,
                    queued_seconds=started - queued_at,
                    started_offset=started_offset,
                    duration_seconds=time.monotonic() - started,
                    response=None,
                    error=error,
                )
                raise
            self._record_call(
                label=label,
                model=model,
                prompt=prompt,
                max_tokens=max_tokens,
                attempt=attempt,
                queued_seconds=started - queued_at,
                started_offset=started_offset,
                duration_seconds=time.monotonic() - started,
                response=response,
                error=None,
            )
            return response

    def _record_call(
        self,
        *,
        label: Optional[AnalysisCallLabel],
        model: Any,
        prompt: str,
        max_tokens: int,
        attempt: int,
        queued_seconds: float,
        started_offset: float,
        duration_seconds: float,
        response: Any,
        error: Optional[Exception],
    ) -> None:
        """Append one call to the run's timing recorder; never raises."""
        if self._timing_recorder is None or label is None:
            return
        try:
            output_tokens: Optional[int] = None
            value = getattr(response, "value", None)
            if value is not None and hasattr(value, "model_dump_json"):
                output_tokens = estimate_model_tokens(value.model_dump_json(), model)
            self._timing_recorder.record_call(
                AnalysisCallTiming(
                    mode=label.mode,
                    kind=label.kind,
                    chunk_index=label.chunk_index,
                    chunk_total=label.chunk_total,
                    attempt=attempt,
                    model_id=describe_model_id(model),
                    max_tokens=max_tokens,
                    estimated_input_tokens=estimate_model_tokens(prompt, model),
                    estimated_output_tokens=output_tokens,
                    provider_usage=getattr(response, "usage", None),
                    queued_seconds=round(queued_seconds, 3),
                    started_offset_seconds=round(started_offset, 3),
                    duration_seconds=round(duration_seconds, 3),
                    finish_reason=getattr(response, "finish_reason", None),
                    enforcement=getattr(response, "enforcement", None),
                    outcome="ok" if error is None else "error",
                    error_category=(
                        None
                        if error is None
                        else str(getattr(error, "category", "internal"))
                    ),
                )
            )
        except Exception:
            logger.warning("Could not record analysis call timing", exc_info=True)

    async def analyze_mode(
        self,
        *,
        mode: AnalysisMode,
        transcript: Dict[str, Any],
        meeting_metadata: Dict[str, Any],
        custom_instructions: Optional[str],
        prior_results: Dict[str, Any],
        model: Any,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Any:
        """Analyze every segment, reconciling typed chunk responses when needed."""
        empty_prompt = self._build_mode_prompt(
            mode,
            "",
            meeting_metadata,
            custom_instructions,
            prior_results,
        )
        analysis_transcript = transcript
        if mode == AnalysisMode.SUGGESTED_ACTIONS:
            analysis_transcript = narrow_transcript_for_suggestions(
                transcript,
                prior_results.get(AnalysisMode.ACTION_ITEMS.value),
                model,
            )
        plan = build_analysis_coverage_plan(
            model=model,
            transcript=analysis_transcript,
            prompt_without_transcript=empty_prompt,
        )
        generation_budget = resolve_generation_budget(
            model,
            purpose="general",
            minimum_output_tokens=1024,
        )
        response_model = ANALYSIS_RESPONSE_MODELS[mode]
        logger.info(
            "Meeting analysis coverage: mode=%s model=%s input_budget=%s "
            "transcript_budget=%s chunks=%s ranges=%s",
            mode.value,
            plan.model_id,
            plan.input_budget_tokens,
            plan.transcript_budget_tokens,
            len(plan.chunks),
            [(chunk.first_segment_index, chunk.last_segment_index) for chunk in plan.chunks],
        )

        completed_chunks = 0

        async def analyze_one_chunk(
            chunk: TranscriptChunk,
        ) -> list[AnalysisContractModel]:
            nonlocal completed_chunks
            chunk_results = await self._analyze_chunk_with_refusal_recovery(
                mode=mode,
                chunk=chunk,
                meeting_metadata=meeting_metadata,
                custom_instructions=custom_instructions,
                prior_results=prior_results,
                model=model,
                response_model=response_model,
                max_tokens=generation_budget.effective_output_tokens,
            )
            for chunk_result in chunk_results:
                validate_analysis_timestamps(chunk_result, transcript)
            completed_chunks += 1
            if progress_callback is not None and plan.requires_reduction:
                await progress_callback(
                    {
                        "stage_progress": completed_chunks / (chunk.total + 1),
                        "message": (
                            f"Analyzing {mode.value.replace('_', ' ')}: "
                            f"chunk {completed_chunks} of {chunk.total}"
                        ),
                    }
                )
            return chunk_results

        chunk_result_groups = await gather_cancel_on_error(
            [analyze_one_chunk(chunk) for chunk in plan.chunks]
        )
        results: list[AnalysisContractModel] = [
            chunk_result
            for chunk_results in chunk_result_groups
            for chunk_result in chunk_results
        ]

        if not results:
            raise StructuredModelOutputError(
                f"{mode.value} could not be recovered because every transcript range was refused.",
                category="safety",
                retryable=False,
            )

        final_response = results[0]
        if plan.requires_reduction or len(results) > 1:
            try:
                final_response = await self._reduce_results(
                    mode=mode,
                    results=results,
                    meeting_metadata=meeting_metadata,
                    custom_instructions=custom_instructions,
                    model=model,
                    response_model=response_model,
                )
            except StructuredModelOutputError as error:
                if not _is_anthropic_refusal(error):
                    raise
                final_response = self._local_recovery_result(mode, results)
                for omission in self.safety_omissions:
                    if omission.mode == mode.value:
                        omission.recovery = "local_recovery_result"
            validate_analysis_timestamps(final_response, transcript)
            if progress_callback is not None:
                await progress_callback(
                    {
                        "stage_progress": 1.0,
                        "message": (
                            f"Reconciling {mode.value.replace('_', ' ')} "
                            "across all chunks"
                        ),
                    }
                )
        return self._finalize_mode_response(mode, final_response)

    async def _analyze_chunk_with_refusal_recovery(
        self,
        *,
        mode: AnalysisMode,
        chunk: TranscriptChunk,
        meeting_metadata: Dict[str, Any],
        custom_instructions: Optional[str],
        prior_results: Dict[str, Any],
        model: Any,
        response_model: type[AnalysisContractModel],
        max_tokens: int,
        is_localization_call: bool = False,
        root_refusal: Optional[StructuredModelOutputError] = None,
    ) -> list[AnalysisContractModel]:
        """Return typed results from every processable contiguous source range."""
        if is_localization_call:
            self._refusal_localization_calls += 1
            if self._refusal_localization_calls > MAX_REFUSAL_LOCALIZATION_CALLS:
                original = root_refusal or StructuredModelOutputError(
                    "Meeting analysis refusal recovery exceeded its localization limit.",
                    category="safety",
                )
                raise StructuredModelOutputError(
                    "Meeting analysis refusal recovery could not safely localize the refusing range.",
                    category="safety",
                    retryable=False,
                    refusal_category=original.refusal_category,
                    refusal_explanation=original.refusal_explanation,
                ) from original
        try:
            response = await self._analyze_chunk(
                mode=mode,
                chunk=chunk,
                meeting_metadata=meeting_metadata,
                custom_instructions=custom_instructions,
                prior_results=prior_results,
                model=model,
                response_model=response_model,
                max_tokens=max_tokens,
            )
            return [response]
        except StructuredModelOutputError as error:
            if not _is_anthropic_refusal(error):
                raise
            original = root_refusal or error
            lines = chunk.lines or tuple(chunk.transcript.splitlines())
            if len(lines) == 1:
                start_timestamp = _formatted_line_timestamp(lines[0])
                self.safety_omissions.append(
                    AnalysisSafetyOmission(
                        mode=mode.value,
                        start_timestamp=start_timestamp,
                        end_timestamp=start_timestamp,
                        segment_count=1,
                        provider="anthropic",
                        refusal_category=error.refusal_category,
                        refusal_explanation=error.refusal_explanation,
                        recovery="omitted_refused_line",
                    )
                )
                return []
            left, right = split_transcript_chunk(chunk)
            recovered: list[AnalysisContractModel] = []
            for child in (left, right):
                recovered.extend(
                    await self._analyze_chunk_with_refusal_recovery(
                        mode=mode,
                        chunk=child,
                        meeting_metadata=meeting_metadata,
                        custom_instructions=custom_instructions,
                        prior_results=prior_results,
                        model=model,
                        response_model=response_model,
                        max_tokens=max_tokens,
                        is_localization_call=True,
                        root_refusal=original,
                    )
                )
            if not recovered:
                raise original
            return recovered

    async def _analyze_chunk(
        self,
        *,
        mode: AnalysisMode,
        chunk: TranscriptChunk,
        meeting_metadata: Dict[str, Any],
        custom_instructions: Optional[str],
        prior_results: Dict[str, Any],
        model: Any,
        response_model: type[AnalysisContractModel],
        max_tokens: int,
    ) -> AnalysisContractModel:
        prompt = self._build_mode_prompt(
            mode,
            chunk.transcript,
            meeting_metadata,
            custom_instructions,
            prior_results,
        ) + build_chunk_analysis_instruction(mode, chunk)
        stream_factory = (
            self._build_stream_factory(mode)
            if self._should_stream_items(mode, chunk)
            else None
        )
        try:
            response = await self._call_schema_with_transient_retry(
                model=model,
                prompt=prompt,
                response_model=response_model,
                max_tokens=max_tokens,
                label=AnalysisCallLabel(
                    mode=mode.value,
                    kind="chunk",
                    chunk_index=chunk.index,
                    chunk_total=chunk.total,
                ),
                stream_factory=stream_factory,
            )
        except Exception:
            if stream_factory is not None and self._item_sink is not None:
                await self._item_sink.reset(mode)
            raise
        self.enforcement_modes.add(response.enforcement)
        return response.value

    def _should_stream_items(self, mode: AnalysisMode, chunk: TranscriptChunk) -> bool:
        """Stream only observed, single-call, item-shaped modes."""
        return (
            self._item_sink is not None
            and self._item_sink.enabled
            and mode in ITEM_STREAM_MODELS
            and chunk.total == 1
        )

    def _build_stream_factory(
        self, mode: AnalysisMode
    ) -> Callable[[], Awaitable[Callable[[str], Awaitable[None]]]]:
        """Return a per-attempt factory so every retry starts with a fresh parser."""
        sink = self._item_sink

        async def factory() -> Callable[[str], Awaitable[None]]:
            assert sink is not None
            await sink.begin_attempt(mode)
            parser = IncrementalItemsParser()

            async def on_text_delta(text: str) -> None:
                for element in parser.feed(text):
                    await sink.emit_element(mode, element)

            return on_text_delta

        return factory

    @staticmethod
    def _local_recovery_result(
        mode: AnalysisMode,
        results: list[AnalysisContractModel],
    ) -> AnalysisContractModel:
        if mode == AnalysisMode.ACTION_ITEMS:
            items = []
            seen = set()
            for result in results:
                for item in ActionItemsAnalysisResponse.model_validate(result).items:
                    key = (item.task, item.context, item.timestamp, item.speaker)
                    if key not in seen:
                        seen.add(key)
                        items.append(item)
            return ActionItemsAnalysisResponse(items=items)
        if mode == AnalysisMode.SUMMARY:
            markdown = "\n\n".join(
                f"## Part {index}\n\n{SummaryAnalysisResponse.model_validate(result).markdown}"
                for index, result in enumerate(results, start=1)
            )
            return SummaryAnalysisResponse(markdown=markdown)
        raise StructuredModelOutputError(
            f"{mode.value} could not be reduced after a provider refusal.",
            category="safety",
            retryable=False,
        )

    async def _reduce_results(
        self,
        *,
        mode: AnalysisMode,
        results: list[AnalysisContractModel],
        meeting_metadata: Dict[str, Any],
        custom_instructions: Optional[str],
        model: Any,
        response_model: type[AnalysisContractModel],
    ) -> AnalysisContractModel:
        """Reduce arbitrary-length typed map output in budgeted levels."""
        current = results
        generation_budget = resolve_generation_budget(
            model,
            purpose="general",
            minimum_output_tokens=1024,
        )
        input_budget = generation_budget.input_budget_tokens or 16000
        static_prompt = build_reduction_prompt(
            mode=mode,
            chunk_results=[],
            meeting_metadata=meeting_metadata,
            custom_instructions=custom_instructions,
        )
        result_budget = (
            input_budget - estimate_model_tokens(static_prompt, model) - 256
        )
        if result_budget < 1024:
            raise ValueError(
                "The selected analysis model cannot fit reduction instructions. "
                "Select a larger-context model."
            )

        while len(current) > 1:
            groups = self._pack_reduction_groups(current, result_budget, model)
            if len(groups) == len(current):
                raise ValueError(
                    "A single chunk analysis result exceeds the selected model's "
                    "reduction budget. Select a larger-context model."
                )
            next_level: list[AnalysisContractModel] = []
            for group in groups:
                reduction_prompt = build_reduction_prompt(
                    mode=mode,
                    chunk_results=group,
                    meeting_metadata=meeting_metadata,
                    custom_instructions=custom_instructions,
                )
                response = await self._call_schema_with_transient_retry(
                    model=model,
                    prompt=reduction_prompt,
                    response_model=response_model,
                    max_tokens=generation_budget.effective_output_tokens,
                    label=AnalysisCallLabel(mode=mode.value, kind="reduction"),
                )
                self.enforcement_modes.add(response.enforcement)
                next_level.append(response.value)
            current = next_level
        return current[0]

    def _finalize_mode_response(
        self,
        mode: AnalysisMode,
        response: AnalysisContractModel,
    ) -> Any:
        if mode == AnalysisMode.ACTION_ITEMS:
            return ActionItemsAnalysisResponse.model_validate(response).items
        if mode == AnalysisMode.SUGGESTED_ACTIONS:
            drafts = SuggestedActionsAnalysisResponse.model_validate(response).items
            return build_action_proposals(drafts, meeting_id=self.meeting_id)
        if mode == AnalysisMode.SUMMARY:
            return SummaryAnalysisResponse.model_validate(response).markdown
        if mode == AnalysisMode.DECISIONS:
            return DecisionsAnalysisResponse.model_validate(response).items
        if mode == AnalysisMode.QUESTIONS:
            return QuestionsAnalysisResponse.model_validate(response).items
        if mode == AnalysisMode.SENTIMENT:
            return SentimentAnalysisResponse.model_validate(response).analysis
        if mode == AnalysisMode.CUSTOM:
            return CustomAnalysisResponse.model_validate(response).content
        raise ValueError(f"Unknown analysis mode: {mode}")

    @staticmethod
    def _pack_reduction_groups(
        results: list[Any],
        budget_tokens: int,
        model: Any = None,
    ) -> list[list[Any]]:
        """Pack serialized map results without ever discarding a result."""
        groups: list[list[Any]] = [[]]
        used_tokens = 0
        for result in results:
            if hasattr(result, "model_dump"):
                serialized = str(result.model_dump(mode="json"))
            else:
                serialized = str(result)
            result_tokens = estimate_model_tokens(serialized, model)
            if groups[-1] and used_tokens + result_tokens > budget_tokens:
                groups.append([])
                used_tokens = 0
            groups[-1].append(result)
            used_tokens += result_tokens
        return groups

    def _build_mode_prompt(
        self,
        mode: AnalysisMode,
        transcript: str,
        meeting_metadata: Dict[str, Any],
        custom_instructions: Optional[str],
        prior_results: Dict[str, Any],
    ) -> str:
        """Build the established prompt shape for one mode and source range."""
        if mode == AnalysisMode.ACTION_ITEMS:
            return self.prompt_builder.build_action_items_prompt(
                transcript, meeting_metadata, custom_instructions
            )
        if mode == AnalysisMode.SUGGESTED_ACTIONS:
            action_items = prior_results.get(AnalysisMode.ACTION_ITEMS.value) or []
            action_items_data = [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in action_items
            ]
            return self.prompt_builder.build_suggested_actions_prompt(
                transcript,
                meeting_metadata,
                action_items_data,
                custom_instructions,
            )
        if mode == AnalysisMode.SUMMARY:
            return self.prompt_builder.build_summary_prompt(
                transcript, meeting_metadata, custom_instructions
            )
        if mode == AnalysisMode.DECISIONS:
            return self.prompt_builder.build_decisions_prompt(
                transcript, meeting_metadata, custom_instructions
            )
        if mode == AnalysisMode.QUESTIONS:
            return self.prompt_builder.build_questions_prompt(
                transcript, meeting_metadata, custom_instructions
            )
        if mode == AnalysisMode.SENTIMENT:
            return self.prompt_builder.build_sentiment_prompt(
                transcript, meeting_metadata, custom_instructions
            )
        if mode == AnalysisMode.CUSTOM:
            if not custom_instructions:
                raise ValueError("Custom mode requires custom_instructions")
            return self.prompt_builder.build_custom_prompt(
                transcript, meeting_metadata, custom_instructions
            )
        raise ValueError(f"Unknown analysis mode: {mode}")


def validate_analysis_timestamps(result: Any, transcript: Dict[str, Any]) -> None:
    """Reject structured findings that cite time outside the source transcript."""
    maximum_timestamp = max(
        (
            max(float(segment.get("start", 0.0)), float(segment.get("end", 0.0)))
            for segment in transcript.get("segments", [])
        ),
        default=0.0,
    )

    def inspect(value: Any, path: str) -> None:
        if hasattr(value, "model_dump"):
            inspect(value.model_dump(mode="python"), path)
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                inspect(item, f"{path}[{index}]")
            return
        if not isinstance(value, dict):
            return

        for key, item in value.items():
            item_path = f"{path}.{key}"
            if key in {"timestamp", "source_timestamp"} and item is not None:
                timestamp = float(item)
                if timestamp < 0.0 or timestamp > maximum_timestamp:
                    raise RuntimeError(
                        f"Analysis timestamp {timestamp} at {item_path} is outside "
                        f"the transcript range 0.0-{maximum_timestamp} seconds."
                    )
            inspect(item, item_path)

    inspect(result, "result")
