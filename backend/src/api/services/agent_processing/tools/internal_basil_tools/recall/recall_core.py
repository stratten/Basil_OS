"""Shared contract + helpers for Basil history recall tools."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

MAX_SUMMARY_CHARS = 500
MAX_FILES_PER_TASK = 8
MAX_PROMPT_CHARS = 800
MAX_RESULT_CHARS = 2000
# scope='detail' is the lossless escape hatch: prompt/result are returned in
# full (no char cap) so the "give me the real thing" path can never reintroduce
# the silent-truncation bug. Files stay bounded but are signaled (files_truncated
# + total_file_count) so nothing is dropped silently.
MAX_DETAIL_FILES = 40
# scope='transcript' (Tier 1) list view: the ordered tool_input/tool_result
# entries of a single run, read straight from the durable execution_timeline
# column. execution_timeline itself truncates tool arguments/results at storage
# time (observed ~400-900 chars for a real run), so this list can only ever be a
# preview -- there is no lossless escape hatch within the timeline. The lossless
# content path is scope='transcript_text' (Tier 2), which reads
# result_data['full_content'] instead.
MAX_TRANSCRIPT_ENTRIES = 40
# Tier 1 previews are intentionally short: the timeline is a truncated display
# artifact, so a preview can never be trusted as complete. The lossless content
# path is scope='transcript_text' over result_data['full_content'].
MAX_TRANSCRIPT_PREVIEW_CHARS = 300
# Tier 2 (scope='transcript_text') window over the full agent log.
MAX_TRANSCRIPT_TEXT_CHARS = 6000
TRANSCRIPT_TEXT_CONTEXT_BEFORE = 200
# scope='reasoning' returns the persisted, emitted reasoning segments for one
# task. It is intentionally a separate bounded surface from transcripts: it is
# not injected into prompts and must be explicitly requested by the agent.
MAX_REASONING_SEGMENTS = 20
MAX_REASONING_PREVIEW_CHARS = 600
MAX_REASONING_RESPONSE_CHARS = 6000


def truncate(text: Any, limit: int = MAX_SUMMARY_CHARS) -> str:
    """Bound any value to a short display string (recall output must stay small)."""
    rendered = "" if text is None else str(text)
    if len(rendered) <= limit:
        return rendered
    return rendered[: max(0, limit - 1)] + "\u2026"


def truncate_flagged(text: Any, limit: int) -> tuple[str, bool]:
    """Like truncate but also reports whether truncation occurred."""
    rendered = "" if text is None else str(text)
    if len(rendered) <= limit:
        return rendered, False
    return rendered[: max(0, limit - 1)] + "\u2026", True


@runtime_checkable
class RecallSource(Protocol):
    """One queryable slice of Basil history. Adapters implement this."""

    name: str

    async def chain(self, root_task_id: str, limit: int) -> List[Dict[str, Any]]:
        ...

    async def search(
        self,
        query: Optional[str],
        start_time: Optional[str],
        end_time: Optional[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        ...


_REGISTRY: Dict[str, "RecallSource"] = {}


def register_recall_source(source: "RecallSource") -> None:
    _REGISTRY[source.name] = source


def get_recall_source(name: str) -> Optional["RecallSource"]:
    return _REGISTRY.get(name)


def recall_source_names() -> List[str]:
    return sorted(_REGISTRY.keys())
