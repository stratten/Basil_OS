"""Model-budgeted transcript chunk planning for complete meeting analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from api.core.models.reasoning.streaming_contract import resolve_generation_budget
from api.core.models.token_utils import estimate_tokens

_SAFETY_MARGIN_TOKENS = 256
_MIN_TRANSCRIPT_BUDGET_TOKENS = 1024
_UNKNOWN_MODEL_INPUT_BUDGET_TOKENS = 16000


@dataclass(frozen=True)
class TranscriptChunk:
    """One contiguous, complete portion of a formatted transcript."""

    index: int
    total: int
    transcript: str
    first_segment_index: int
    last_segment_index: int
    estimated_tokens: int
    lines: tuple[str, ...] = ()
    source_indexes: tuple[int, ...] = ()


@dataclass(frozen=True)
class AnalysisCoveragePlan:
    """Complete transcript coverage shaped to the selected model's budget."""

    chunks: List[TranscriptChunk]
    model_id: str
    input_budget_tokens: int
    prompt_overhead_tokens: int
    transcript_budget_tokens: int

    @property
    def requires_reduction(self) -> bool:
        return len(self.chunks) > 1


def format_transcript_segments(transcript: Dict[str, Any]) -> List[str]:
    """Render each persisted transcript segment as a separate prompt line."""
    lines: List[str] = []
    for segment in transcript.get("segments", []):
        start = float(segment.get("start", 0.0))
        minutes, seconds = divmod(int(start), 60)
        speaker = segment.get("speaker") or "Unknown"
        text = str(segment.get("text", "")).strip()
        lines.append(f"[{minutes:02d}:{seconds:02d}] {speaker}: {text}")
    return lines


def build_analysis_coverage_plan(
    *,
    model: Any,
    transcript: Dict[str, Any],
    prompt_without_transcript: str,
) -> AnalysisCoveragePlan:
    """Split every transcript segment into contiguous chunks that fit the model."""
    budget = resolve_generation_budget(
        model,
        purpose="general",
        minimum_output_tokens=1024,
    )
    input_budget = (
        budget.input_budget_tokens
        if budget.input_budget_tokens is not None
        else _UNKNOWN_MODEL_INPUT_BUDGET_TOKENS
    )
    overhead = estimate_model_tokens(prompt_without_transcript, model)
    transcript_budget = input_budget - overhead - _SAFETY_MARGIN_TOKENS
    if transcript_budget < _MIN_TRANSCRIPT_BUDGET_TOKENS:
        raise ValueError(
            "The selected analysis model leaves fewer than 1024 tokens for meeting "
            "content after prompt and output reservation. Select a larger-context model."
        )

    source_lines = format_transcript_segments(transcript)
    packed: List[tuple[int, str]] = []
    for segment_index, line in enumerate(source_lines):
        packed.extend(
            (segment_index, piece)
            for piece in _split_line_to_budget(line, transcript_budget, model)
        )

    if not packed:
        packed = [(0, "")]

    draft_chunks: List[List[tuple[int, str]]] = [[]]
    draft_tokens = 0
    for segment_index, line in packed:
        line_tokens = estimate_model_tokens(line, model)
        if draft_chunks[-1] and draft_tokens + line_tokens > transcript_budget:
            draft_chunks.append([])
            draft_tokens = 0
        draft_chunks[-1].append((segment_index, line))
        draft_tokens += line_tokens

    total = len(draft_chunks)
    chunks = [
        TranscriptChunk(
            index=index + 1,
            total=total,
            transcript="\n".join(line for _, line in entries),
            first_segment_index=entries[0][0],
            last_segment_index=entries[-1][0],
            estimated_tokens=estimate_model_tokens(
                "\n".join(line for _, line in entries),
                model,
            ),
            lines=tuple(line for _, line in entries),
            source_indexes=tuple(segment_index for segment_index, _ in entries),
        )
        for index, entries in enumerate(draft_chunks)
    ]
    return AnalysisCoveragePlan(
        chunks=chunks,
        model_id=budget.model_id,
        input_budget_tokens=input_budget,
        prompt_overhead_tokens=overhead,
        transcript_budget_tokens=transcript_budget,
    )


def split_transcript_chunk(
    chunk: TranscriptChunk,
) -> tuple[TranscriptChunk, TranscriptChunk]:
    """Split one refusing chunk without changing any formatted source line."""
    lines = chunk.lines or tuple(chunk.transcript.splitlines())
    source_indexes = chunk.source_indexes or tuple(
        range(chunk.first_segment_index, chunk.first_segment_index + len(lines))
    )
    if len(lines) < 2:
        raise ValueError("Cannot split a transcript chunk with fewer than two lines.")
    midpoint = len(lines) // 2
    left_lines, right_lines = lines[:midpoint], lines[midpoint:]
    left_indexes, right_indexes = source_indexes[:midpoint], source_indexes[midpoint:]

    def build_child(
        child_lines: tuple[str, ...],
        child_indexes: tuple[int, ...],
        child_index: int,
    ) -> TranscriptChunk:
        text = "\n".join(child_lines)
        return TranscriptChunk(
            index=child_index,
            total=2,
            transcript=text,
            first_segment_index=child_indexes[0],
            last_segment_index=child_indexes[-1],
            estimated_tokens=estimate_model_tokens(text),
            lines=child_lines,
            source_indexes=child_indexes,
        )

    return build_child(left_lines, left_indexes, 1), build_child(right_lines, right_indexes, 2)


def _split_line_to_budget(line: str, budget_tokens: int, model: Any) -> List[str]:
    """Split only an oversized segment, preserving every word and its label."""
    if estimate_model_tokens(line, model) <= budget_tokens:
        return [line]

    prefix, separator, body = line.partition(": ")
    if not separator:
        prefix, body = "[00:00] Unknown", line
    words = body.split()
    parts: List[str] = []
    current: List[str] = []
    for word in words:
        candidate = " ".join(current + [word])
        rendered = f"{prefix}: {candidate}"
        if current and estimate_model_tokens(rendered, model) > budget_tokens:
            parts.append(f"{prefix}: {' '.join(current)}")
            current = [word]
        else:
            current.append(word)
    if current:
        parts.append(f"{prefix}: {' '.join(current)}")
    return parts or [f"{prefix}: "]


def estimate_model_tokens(text: str, model: Any = None) -> int:
    """Count with the loaded model tokenizer, falling back only when unavailable."""
    tokenizer = getattr(model, "tokenizer", None)
    encode = getattr(tokenizer, "encode", None)
    if callable(encode):
        try:
            return max(1, len(encode(text)))
        except Exception:
            pass
    return max(1, estimate_tokens(text))
