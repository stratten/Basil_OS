"""Agent-task history adapter for the recall toolset."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ..activity_query_tool import _parse_time_parameter
from .recall_core import (
    MAX_DETAIL_FILES,
    MAX_FILES_PER_TASK,
    MAX_PROMPT_CHARS,
    MAX_REASONING_PREVIEW_CHARS,
    MAX_REASONING_RESPONSE_CHARS,
    MAX_REASONING_SEGMENTS,
    MAX_RESULT_CHARS,
    MAX_TRANSCRIPT_ENTRIES,
    MAX_TRANSCRIPT_PREVIEW_CHARS,
    MAX_TRANSCRIPT_TEXT_CHARS,
    TRANSCRIPT_TEXT_CONTEXT_BEFORE,
    truncate,
    truncate_flagged,
)


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _collect_file_labels(cmd_files: List[Dict[str, Any]], ref_paths: List[str]) -> List[str]:
    """Return the full deduped list of file labels; callers apply their own cap."""
    file_labels: List[str] = []
    for entry in cmd_files:
        label = entry.get("path") or entry.get("name")
        if label and label not in file_labels:
            file_labels.append(label)
    for path in ref_paths:
        if path and path not in file_labels:
            file_labels.append(path)
    return file_labels


def _preview_is_truncated(preview: Any) -> bool:
    rendered = "" if preview is None else str(preview)
    return rendered.endswith("...") or rendered.endswith("\u2026")


def _stringify_event_payload(value: Any) -> Optional[str]:
    """Render a timeline event's argument/result payload as a plain string.

    execution_timeline stores tool arguments and results as JSON *strings* in
    the event body, but tolerate a dict/list too (some historical rows) so the
    reader never drops content just because the shape drifted."""
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    try:
        import json as _json

        return _json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _extract_transcript_entries(timeline: Any) -> List[Dict[str, Any]]:
    """Pair tool_input/tool_result events from execution_timeline into ordered
    call entries.

    Each entry is one tool invocation with the full arguments the agent passed
    (``arguments``) and the tool's returned payload (``result``), matched by the
    event ``correlation_id`` the langchain callback stamps on both halves. This
    is the content that scope='detail' and the follow-up context assembler never
    surface -- e.g. the ``reply_body`` an agent composed and handed to
    create_reply_email_draft lives only here, not in any finalizer field."""
    if not isinstance(timeline, list):
        return []

    entries: List[Dict[str, Any]] = []
    by_correlation: Dict[str, Dict[str, Any]] = {}

    for event in timeline:
        if not isinstance(event, dict):
            continue
        kind = event.get("detail_kind")
        correlation_id = event.get("correlation_id")
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}

        if kind == "tool_input":
            entry = {
                "index": len(entries),
                "tool_name": metadata.get("tool_name") or event.get("title"),
                "arguments": _stringify_event_payload(event.get("body")),
                "result": None,
                "timestamp": _iso(event.get("timestamp")),
                "correlation_id": correlation_id,
            }
            entries.append(entry)
            if correlation_id:
                by_correlation[correlation_id] = entry
        elif kind == "tool_result":
            payload = _stringify_event_payload(event.get("body") or event.get("content"))
            paired = by_correlation.get(correlation_id) if correlation_id else None
            if paired is not None and paired.get("result") is None:
                paired["result"] = payload
            else:
                # Orphan result (no matching input in this window): keep it as a
                # standalone entry so a returned payload is never silently lost.
                entries.append({
                    "index": len(entries),
                    "tool_name": metadata.get("tool_name"),
                    "arguments": None,
                    "result": payload,
                    "timestamp": _iso(event.get("timestamp")),
                    "correlation_id": correlation_id,
                })

    return entries


def _preview_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Bound one transcript entry's arguments/result for the list view."""
    arguments, args_truncated = truncate_flagged(entry.get("arguments") or "", MAX_TRANSCRIPT_PREVIEW_CHARS)
    result, result_truncated = truncate_flagged(entry.get("result") or "", MAX_TRANSCRIPT_PREVIEW_CHARS)
    return {
        "index": entry.get("index"),
        "tool_name": entry.get("tool_name"),
        "timestamp": entry.get("timestamp"),
        "arguments": arguments,
        "arguments_truncated": args_truncated,
        "result": result,
        "result_truncated": result_truncated,
    }


_STEP_LINE_RE = re.compile(r"^STEP_(?:START|COMPLETE):.*$", re.MULTILINE)
_BASE64_BLOB_RE = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")
# Best-effort secret redaction for a raw string log (full_content is a string,
# not a dict, so the structural key-redaction the context assembler uses does
# not apply). Matches "<sensitive-key><:|=><quoted-or-bare value>".
_SECRET_RE = re.compile(
    r"(?i)(\"?(?:api[_-]?key|secret|password|authorization|bearer|"
    r"refresh_token|access_token|token|cookie)\"?\s*[:=]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s,}]+)"
)


def _denoise_transcript_text(text: str) -> str:
    """Drop STEP telemetry lines and collapse long base64 blobs (thinking-block
    signatures) that are pure noise in the raw agent log."""
    without_steps = _STEP_LINE_RE.sub("", text)
    collapsed = _BASE64_BLOB_RE.sub(
        lambda m: f"[omitted {len(m.group(0))}-char blob]", without_steps
    )
    return collapsed


def _redact_secrets(text: str) -> str:
    return _SECRET_RE.sub(lambda m: f"{m.group(1)}[redacted]", text)


def _summarize_task(task: Any) -> Dict[str, Any]:
    # Reuse the canonical result/file extractor that the history detail
    # endpoint uses (api/routes/agent_tasks/history_routes.py). Real finalized
    # tasks store their result message and files inside the finalizer envelope
    # (result_data["finalizer_result"|"final_envelope"]["result_payload"]),
    # NOT at result_data["files"] / accumulated_artifacts["files"]; a hand-
    # rolled reader silently returns no files for exactly the "which file did I
    # pick earlier" case this tool exists to answer. Lazy-imported because the
    # routes package __init__ pulls in FastAPI routers (heavy + cycle risk at
    # tool-construction time); utils.py itself only depends on ast/json/typing.
    from api.routes.agent_tasks.utils import extract_result_data

    result_msg, cmd_files, ref_paths, _err_msg, _timeline = extract_result_data(task)
    file_labels = _collect_file_labels(cmd_files, ref_paths)[:MAX_FILES_PER_TASK]
    result_text, result_truncated = truncate_flagged(result_msg or "", MAX_RESULT_CHARS)

    return {
        "id": getattr(task, "id", None),
        "chain_sequence_number": getattr(task, "chain_sequence_number", None),
        "timestamp": _iso(getattr(task, "timestamp", None)),
        "title": getattr(task, "title", None),
        "prompt": truncate(getattr(task, "original_prompt", ""), MAX_PROMPT_CHARS),
        "status": getattr(task, "status", None),
        "result": result_text,
        "result_truncated": result_truncated,
        "files": file_labels,
    }


class AgentTaskRecallSource:
    """Recall over the agent_tasks table (current chain + history search)."""

    name = "agent_tasks"

    async def chain(self, root_task_id: str, limit: int) -> List[Dict[str, Any]]:
        from api.dependencies import get_sqlite_knowledge_service

        service = get_sqlite_knowledge_service()
        tasks = await service.get_agent_task_chain(root_task_id)
        summaries = [_summarize_task(task) for task in tasks]
        if limit and len(summaries) > limit:
            summaries = summaries[-limit:]  # keep the most recent turns
        return summaries

    async def search(
        self,
        query: Optional[str],
        start_time: Optional[str],
        end_time: Optional[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        from api.dependencies import get_sqlite_knowledge_service

        service = get_sqlite_knowledge_service()
        start_dt = _parse_time_parameter(start_time, default=None) if start_time else None
        end_dt = _parse_time_parameter(end_time, default=None) if end_time else None
        rows = await service.agent_task_service.search_agent_task_summaries(
            query=query or None,
            start_date=start_dt,
            end_date=end_dt,
            limit=limit,
        )
        results: List[Dict[str, Any]] = []
        for row in rows:
            preview = row.get("result_preview", "")
            results.append({
                "id": row.get("id"),
                "timestamp": _iso(row.get("timestamp")),
                "title": row.get("title"),
                "prompt": truncate(row.get("original_prompt", ""), MAX_PROMPT_CHARS),
                "status": row.get("status"),
                "result": truncate(preview, MAX_RESULT_CHARS),
                "result_truncated": _preview_is_truncated(preview),
                "file_count": row.get("file_count", 0),
                "follow_up_count": row.get("follow_up_count", 0),
            })
        return results

    async def detail(self, task_id: str) -> Optional[Dict[str, Any]]:
        from api.dependencies import get_sqlite_knowledge_service
        from api.routes.agent_tasks.utils import extract_result_data

        service = get_sqlite_knowledge_service()
        task = await service.get_agent_task(task_id)
        if task is None:
            return None

        result_msg, cmd_files, ref_paths, err_msg, _timeline = extract_result_data(task)
        all_labels = _collect_file_labels(cmd_files, ref_paths)
        file_labels = all_labels[:MAX_DETAIL_FILES]

        # detail is the lossless escape hatch: prompt and result are returned in
        # full so this path can never silently sever a conclusion the way the
        # bounded list views can. Files remain bounded but are signaled, so a
        # dropped file is never invisible.
        return {
            "id": getattr(task, "id", None),
            "chain_sequence_number": getattr(task, "chain_sequence_number", None),
            "timestamp": _iso(getattr(task, "timestamp", None)),
            "title": getattr(task, "title", None),
            "prompt": getattr(task, "original_prompt", "") or "",
            "status": getattr(task, "status", None),
            "result": result_msg or "",
            "error": err_msg,
            "files": file_labels,
            "total_file_count": len(all_labels),
            "files_truncated": len(all_labels) > MAX_DETAIL_FILES,
            "root_task_id": getattr(task, "root_task_id", None),
            "previous_task_id": getattr(task, "previous_task_id", None),
            "screen_text_status": "pending" if getattr(task, "screen_text", None) is None else "ready",
            "screen_text": getattr(task, "screen_text", None) or "",
        }

    async def transcript(
        self,
        task_id: str,
        limit: int,
        offset: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """Return a bounded, ordered window of a task's tool-call transcript.

        Reads the durable execution_timeline column (no new persistence) and
        pairs tool_input/tool_result events into call entries. Entries are
        returned oldest-first from ``offset``; each entry's arguments/result are
        previewed (flagged when truncated). This is Tier 1: a cheap overview
        only. execution_timeline itself truncates long arguments/results at
        storage time, so there is no lossless view within this method -- use
        scope='transcript_text' for the exact composed content."""
        from api.dependencies import get_sqlite_knowledge_service

        service = get_sqlite_knowledge_service()
        task = await service.get_agent_task(task_id)
        if task is None:
            return None

        all_entries = _extract_transcript_entries(getattr(task, "execution_timeline", None))
        total = len(all_entries)
        start = max(0, offset)
        window = all_entries[start:start + max(1, min(limit, MAX_TRANSCRIPT_ENTRIES))]
        return {
            "id": getattr(task, "id", None),
            "title": getattr(task, "title", None),
            "status": getattr(task, "status", None),
            "total_entries": total,
            "offset": start,
            "returned": len(window),
            "has_more": start + len(window) < total,
            "entries": [_preview_entry(entry) for entry in window],
            "note": (
                "arguments/result are previews and may be truncated at source; "
                "for exact composed content use scope='transcript_text' with "
                "contains=<a distinctive phrase or the tool name>."
            ),
        }

    async def transcript_text(
        self,
        task_id: str,
        contains: Optional[str],
        offset: int,
    ) -> Optional[Dict[str, Any]]:
        """Return a bounded, denoised, redacted window of a task's full agent log.

        Sourced from result_data['full_content'] (fallback agent_output /
        enhanced_output) -- the only place the complete composed content is
        durably stored. When ``contains`` is given, the window is centered on the
        first match at/after ``offset``; otherwise it starts at ``offset``. This
        is the lossless content path; the timeline-backed scope='transcript' only
        previews."""
        from api.dependencies import get_sqlite_knowledge_service

        service = get_sqlite_knowledge_service()
        task = await service.get_agent_task(task_id)
        if task is None:
            return None

        result_data = getattr(task, "result_data", None)
        raw = ""
        if isinstance(result_data, dict):
            raw = (
                result_data.get("full_content")
                or result_data.get("agent_output")
                or result_data.get("enhanced_output")
                or ""
            )
        base = {
            "id": getattr(task, "id", None),
            "title": getattr(task, "title", None),
            "status": getattr(task, "status", None),
        }
        if not raw:
            return {
                **base,
                "available": False,
                "text": "",
                "total_length": 0,
                "note": "No transcript text was stored for this task.",
            }

        clean = _redact_secrets(_denoise_transcript_text(str(raw)))
        total = len(clean)
        start = max(0, min(offset, total))
        match_count: Optional[int] = None
        if contains:
            haystack = clean.lower()
            needle = contains.lower()
            match_count = haystack.count(needle)
            pos = haystack.find(needle, start)
            if pos == -1:
                pos = haystack.find(needle)
            if pos == -1:
                return {
                    **base,
                    "available": True,
                    "total_length": total,
                    "match_count": 0,
                    "contains": contains,
                    "text": "",
                    "note": f"{contains!r} was not found in the transcript.",
                }
            start = max(0, pos - TRANSCRIPT_TEXT_CONTEXT_BEFORE)

        end = min(total, start + MAX_TRANSCRIPT_TEXT_CHARS)
        window = clean[start:end]
        return {
            **base,
            "available": True,
            "total_length": total,
            "offset": start,
            "returned": len(window),
            "has_more": end < total,
            "match_count": match_count,
            "contains": contains,
            "text": window,
        }

    async def reasoning(
        self,
        task_id: str,
        limit: int,
        offset: int = 0,
        contains: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Return an explicitly requested, bounded reasoning trace for one task."""
        from api.dependencies import get_sqlite_knowledge_service
        from api.services.agent_processing.lifecycle.finalization.task_state_persistence import (
            normalize_thinking_history,
        )

        service = get_sqlite_knowledge_service()
        task = await service.get_agent_task(task_id)
        if task is None:
            return None

        result_data = getattr(task, "result_data", None)
        raw_history = result_data.get("thinking_history") if isinstance(result_data, dict) else None
        history = normalize_thinking_history(raw_history)
        if contains:
            needle = contains.lower()
            history = [segment for segment in history if needle in segment["text"].lower()]

        total = len(history)
        start = max(0, offset)
        requested = history[start:start + max(1, min(limit, MAX_REASONING_SEGMENTS))]
        segments: List[Dict[str, Any]] = []
        remaining_chars = MAX_REASONING_RESPONSE_CHARS
        for segment in requested:
            if remaining_chars <= 0:
                break
            preview_limit = min(MAX_REASONING_PREVIEW_CHARS, remaining_chars)
            text, text_truncated = truncate_flagged(
                _redact_secrets(segment["text"]),
                preview_limit,
            )
            segments.append({
                "iteration": segment["iteration"],
                "text": text,
                "text_truncated": text_truncated,
                "is_complete": segment["is_complete"],
            })
            remaining_chars -= len(text)

        return {
            "id": getattr(task, "id", None),
            "title": getattr(task, "title", None),
            "status": getattr(task, "status", None),
            "total_segments": total,
            "offset": start,
            "returned": len(segments),
            "has_more": start + len(segments) < total,
            "contains": contains,
            "segments": segments,
        }

    async def screen_context(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Return the screen text captured for one task, with a readiness flag.

        screen_text is NULL until the background OCR writer runs, so a NULL
        value maps to status='pending'; any string (including '') means the
        capture finished ('' = ready but no readable text).
        """
        from api.dependencies import get_sqlite_knowledge_service

        service = get_sqlite_knowledge_service()
        task = await service.get_agent_task(task_id)
        if task is None:
            return None

        raw = getattr(task, "screen_text", None)
        status = "pending" if raw is None else "ready"
        return {
            "id": getattr(task, "id", None),
            "app_name": getattr(task, "app_name", None),
            "window_title": getattr(task, "window_title", None),
            "screen_text_status": status,
            "screen_text": raw or "",
        }
