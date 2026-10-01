"""Project ACP v1/v2 session-update notifications into the Agent Task timeline.

This module never answers incoming provider requests, never sets Agent Task
or provider-run lifecycle status, and never interprets `_meta`. It is bound
to exactly one agent-issued session ID and publishes bounded, sanitized,
de-duplicated activity through `AgentTaskRoutingService.publish_activity_entry`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path, PureWindowsPath
from typing import Any


MAX_ACTIVITY_TEXT_BYTES = 8_192
MAX_SEEN_ACTIVITY_FINGERPRINTS = 512

_TRUNCATION_SUFFIX = "…[truncated]"
_MAX_PLAN_STEPS = 20
_MAX_LOCATIONS = 20
_MAX_IDENTIFIER_TEXT_BYTES = 256
_MAX_LOCATION_TEXT_BYTES = 512
_MAX_SUMMARY_TEXT_BYTES = 512
_MAX_UNKNOWN_COLLECTION_ITEMS = 20
_EXCLUDED_UNKNOWN_KEYS = ("_meta", "input", "output")


def _sanitize_text(value: Any) -> str:
    """Normalize CRLF/CR to LF and replace NUL/other C0 controls (except tab/newline) with spaces."""
    text = str(value if value is not None else "")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = [
        ch if ch in ("\n", "\t") or ord(ch) >= 0x20 else " "
        for ch in normalized
    ]
    return "".join(cleaned)


def _bounded_text(value: Any, *, maximum_bytes: int = MAX_ACTIVITY_TEXT_BYTES) -> str:
    """Sanitize and truncate text to the specified UTF-8 byte bound."""
    text = _sanitize_text(value)
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= maximum_bytes:
        return text
    suffix_bytes = _TRUNCATION_SUFFIX.encode("utf-8")
    budget = max(maximum_bytes - len(suffix_bytes), 0)
    return encoded[:budget].decode("utf-8", errors="ignore") + _TRUNCATION_SUFFIX


def _is_text_like_content(value: Any) -> bool:
    if isinstance(value, str):
        return True
    if isinstance(value, Mapping):
        return value.get("type") == "text" and isinstance(value.get("text"), str)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return all(_is_text_like_content(item) for item in value)
    return False


def _extract_text_content(content: Any) -> str:
    """Extract sanitized, bounded text from a string, a text content block, or an array of blocks."""
    if content is None:
        return ""
    if isinstance(content, str):
        return _bounded_text(content)
    if isinstance(content, Mapping):
        if content.get("type") == "text" and isinstance(content.get("text"), str):
            return _bounded_text(content["text"])
        return _bounded_text("Provider emitted non-text content.")
    if isinstance(content, Sequence) and not isinstance(content, (bytes, bytearray)):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping) and block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
            else:
                parts.append("Provider emitted non-text content.")
        return _bounded_text("\n".join(parts))
    return _bounded_text("Provider emitted non-text content.")


def _safe_locations(locations: Any) -> list[str]:
    if not isinstance(locations, Sequence) or isinstance(locations, (str, bytes, bytearray)):
        return []
    safe: list[str] = []
    for location in list(locations)[:_MAX_LOCATIONS]:
        if isinstance(location, Mapping):
            path = location.get("path")
            line = location.get("line")
            if isinstance(path, str) and path:
                safe.append(
                    _bounded_text(
                        f"{path}:{line}" if line is not None else path,
                        maximum_bytes=_MAX_LOCATION_TEXT_BYTES,
                    )
                )
        elif isinstance(location, str) and location:
            safe.append(_bounded_text(location, maximum_bytes=_MAX_LOCATION_TEXT_BYTES))
    return safe[:_MAX_LOCATIONS]


def _safe_workspace_locations(locations: Any, workspace_root: str | None) -> list[str]:
    if not isinstance(locations, Sequence) or isinstance(locations, (str, bytes, bytearray)):
        return []
    resolved_root: Path | None = None
    if workspace_root is not None:
        try:
            resolved_root = Path(workspace_root).resolve(strict=True)
        except OSError:
            return []
    safe: list[str] = []
    for location in list(locations)[:_MAX_LOCATIONS]:
        path = location.get("path") if isinstance(location, Mapping) else location
        if not isinstance(path, str) or not path or path.casefold().startswith("file://"):
            continue
        candidate = Path(path)
        windows_path = PureWindowsPath(path)
        if resolved_root is None:
            if candidate.is_absolute() or windows_path.is_absolute() or ".." in candidate.parts:
                continue
            safe.append(_bounded_text(path, maximum_bytes=_MAX_LOCATION_TEXT_BYTES))
            continue
        if not candidate.is_absolute() or windows_path.is_absolute():
            continue
        try:
            relative = candidate.resolve(strict=False).relative_to(resolved_root)
        except (OSError, ValueError):
            continue
        if not relative.parts or ".." in relative.parts:
            continue
        safe.append(_bounded_text(relative.as_posix(), maximum_bytes=_MAX_LOCATION_TEXT_BYTES))
    return safe[:_MAX_LOCATIONS]


def _safe_identifier(value: Any) -> str:
    """Retain a bounded, display-safe source identifier for timeline metadata."""
    return _bounded_text(value, maximum_bytes=_MAX_IDENTIFIER_TEXT_BYTES)


def _identifier_token(value: str) -> str:
    """Return a bounded stable ID fragment without embedding provider-controlled text."""
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]


def _safe_unknown_value(value: Any) -> Any:
    """Create a recursively bounded, JSON-safe representation of an unknown update field."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _bounded_text(value)
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, item in list(value.items())[:_MAX_UNKNOWN_COLLECTION_ITEMS]:
            safe_key = _bounded_text(key, maximum_bytes=_MAX_IDENTIFIER_TEXT_BYTES)
            if safe_key in _EXCLUDED_UNKNOWN_KEYS:
                continue
            if safe_key == "content" and not _is_text_like_content(item):
                continue
            safe[safe_key] = _safe_unknown_value(item)
        return safe
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [
            _safe_unknown_value(item)
            for item in list(value)[:_MAX_UNKNOWN_COLLECTION_ITEMS]
        ]
    return "Provider emitted non-text content."


def _activity_fingerprint(session_id: str, update: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {"sessionId": session_id, "update": update},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8", errors="replace")).hexdigest()


def _entry(
    *,
    entry_id: str,
    entry_type: str,
    content: str,
    summary: str,
    body: str,
    detail_kind: str,
    metadata: Mapping[str, Any],
    streaming: bool,
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "type": entry_type,
        "content": content,
        "summary": summary,
        "body": body,
        "detail_kind": detail_kind,
        "metadata": dict(metadata),
        "streaming": streaming,
    }


def _publish_malformed_update(
    provider_run_id: str, session_id: str | None, fingerprint: str, reason: str
) -> dict[str, Any]:
    text = _bounded_text(reason)
    metadata = {
        "provider_activity_kind": "malformed_update",
        "provider_run_id": provider_run_id,
        "provider_session_id": session_id,
        "raw_detail": True,
    }
    return _entry(
        entry_id=f"provider-activity-malformed-{provider_run_id}-{fingerprint[:12]}",
        entry_type="step",
        content=text,
        summary="Provider activity update",
        body=text,
        detail_kind="step_note",
        metadata=metadata,
        streaming=False,
    )


class ProviderActivityProjector:
    """Project one bound ACP v1/v2 session's `session/update` notifications into the Agent Task timeline."""

    def __init__(
        self,
        *,
        routing_service: Any,
        agent_task_id: str,
        root_task_id: str | None,
        previous_task_id: str | None,
        provider_run_id: str,
        workspace_root: str | None = None,
        logger: logging.Logger | None = None,
        safe_activity_observer: Callable[[Mapping[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self._routing_service = routing_service
        self._agent_task_id = agent_task_id
        self._root_task_id = root_task_id
        self._previous_task_id = previous_task_id
        self._provider_run_id = provider_run_id
        self._workspace_root = workspace_root
        self._logger = logger or logging.getLogger(__name__)
        self._safe_activity_observer = safe_activity_observer
        self._session_id: str | None = None
        self._seen_fingerprints: deque[str] = deque(maxlen=MAX_SEEN_ACTIVITY_FINGERPRINTS)
        self._seen_fingerprint_set: set[str] = set()

    def bind_session(self, session_id: str) -> None:
        """Bind this projector to the agent-issued session ID exactly once."""
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        if self._session_id is not None and self._session_id != session_id:
            raise ValueError("ProviderActivityProjector is already bound to a different session")
        self._session_id = session_id

    async def handle_session_update(self, params: Mapping[str, Any]) -> None:
        """Handle one ACP `session/update` notification. Never raises."""
        try:
            await self._dispatch(params)
        except Exception as exc:  # noqa: BLE001 - activity transport must never break the provider process.
            self._logger.debug(
                "Provider activity dispatch raised for task %s: %s",
                self._agent_task_id,
                exc.__class__.__name__,
            )

    async def _dispatch(self, params: Mapping[str, Any]) -> None:
        if self._session_id is None:
            return
        if not isinstance(params, Mapping):
            return
        if params.get("sessionId") != self._session_id:
            return
        update = params.get("update")
        if not isinstance(update, Mapping):
            return

        fingerprint = _activity_fingerprint(self._session_id, update)
        if fingerprint in self._seen_fingerprint_set:
            return
        if len(self._seen_fingerprints) == self._seen_fingerprints.maxlen:
            evicted = self._seen_fingerprints[0]
            self._seen_fingerprint_set.discard(evicted)
        self._seen_fingerprints.append(fingerprint)
        self._seen_fingerprint_set.add(fingerprint)

        kind = update.get("sessionUpdate")
        if kind is None:
            kind = update.get("kind")

        entry: dict[str, Any] | None
        if kind in ("agent_message", "agent_message_chunk"):
            entry = self._build_message_entry(update, str(kind), fingerprint, is_thought=False)
        elif kind in ("agent_thought", "agent_thought_chunk"):
            entry = self._build_message_entry(update, str(kind), fingerprint, is_thought=True)
        elif kind in ("tool_call", "tool_call_update"):
            entry = self._build_tool_call_entry(update, str(kind), fingerprint)
        elif kind == "tool_call_content_chunk":
            entry = self._build_tool_content_chunk_entry(update, fingerprint)
        elif kind == "terminal_update":
            entry = self._build_terminal_entry(update, fingerprint, is_chunk=False)
        elif kind == "terminal_output_chunk":
            entry = self._build_terminal_entry(update, fingerprint, is_chunk=True)
        elif kind == "state_update":
            entry = self._build_state_entry(update, fingerprint)
        elif kind == "plan":
            entry = self._build_plan_entry(update, fingerprint)
        else:
            entry = self._build_unknown_entry(update, fingerprint)

        if entry is not None:
            await self._publish(entry)

    def _build_message_entry(
        self, update: Mapping[str, Any], kind: str, fingerprint: str, *, is_thought: bool
    ) -> dict[str, Any]:
        message_id = update.get("messageId")
        has_message_id = isinstance(message_id, str) and bool(message_id)
        message_token = _identifier_token(message_id) if has_message_id else fingerprint[:12]
        is_chunk = kind.endswith("_chunk")
        text = _extract_text_content(update.get("content"))
        label = "thought" if is_thought else "message"
        if is_chunk and has_message_id:
            entry_id = f"provider-{label}-chunk-{self._provider_run_id}-{message_token}-{fingerprint[:12]}"
        elif has_message_id:
            entry_id = f"provider-{label}-{self._provider_run_id}-{message_token}"
        else:
            entry_id = f"provider-{label}-{self._provider_run_id}-{fingerprint[:12]}"
        metadata: dict[str, Any] = {
            "provider_activity_kind": kind,
            "provider_run_id": self._provider_run_id,
            "provider_session_id": self._session_id,
        }
        if has_message_id:
            metadata["message_id"] = _safe_identifier(message_id)
        if is_thought:
            metadata["raw_detail"] = True
        return _entry(
            entry_id=entry_id,
            entry_type="thinking" if is_thought else "step",
            content=text,
            summary="Provider reasoning" if is_thought else "Provider message",
            body=text,
            detail_kind="thinking" if is_thought else "step_note",
            metadata=metadata,
            streaming=is_chunk,
        )

    def _build_tool_call_entry(
        self,
        update: Mapping[str, Any],
        activity_kind: str,
        fingerprint: str,
    ) -> dict[str, Any]:
        tool_call_id = update.get("toolCallId")
        if not isinstance(tool_call_id, str) or not tool_call_id.strip():
            return _publish_malformed_update(
                self._provider_run_id, self._session_id, fingerprint, "tool_call_update missing toolCallId"
            )
        tool_call_token = _identifier_token(tool_call_id)
        status = _safe_identifier(update.get("status")) if isinstance(update.get("status"), str) else None
        tool_kind = _safe_identifier(update.get("kind")) if isinstance(update.get("kind"), str) else None
        title = update.get("title")
        if status in ("pending", "in_progress"):
            entry_type, detail_kind = "tool_start", "tool_input"
        elif status in ("completed", "failed", "cancelled"):
            entry_type, detail_kind = "tool_complete", "tool_result"
        else:
            entry_type, detail_kind = "step", "step_note"
        summary = (
            _bounded_text(title, maximum_bytes=_MAX_SUMMARY_TEXT_BYTES)
            if isinstance(title, str) and title.strip()
            else f"Provider {tool_kind or 'other'} tool"
        )
        text_summary = _extract_text_content(update.get("content"))
        locations = _safe_locations(update.get("locations"))
        body_parts = [summary]
        if text_summary:
            body_parts.append(text_summary)
        if locations:
            body_parts.append("Locations: " + ", ".join(locations))
        body = _bounded_text("\n".join(body_parts))
        metadata = {
            "provider_activity_kind": activity_kind,
            "provider_run_id": self._provider_run_id,
            "provider_session_id": self._session_id,
            "tool_call_id": _safe_identifier(tool_call_id),
            "tool_kind": tool_kind,
            "tool_status": status,
            "location_count": len(locations),
            "provider_locations": _safe_workspace_locations(update.get("locations"), self._workspace_root),
        }
        return _entry(
            entry_id=f"provider-tool-{self._provider_run_id}-{tool_call_token}",
            entry_type=entry_type,
            content=summary,
            summary=summary,
            body=body,
            detail_kind=detail_kind,
            metadata=metadata,
            streaming=False,
        )

    def _build_tool_content_chunk_entry(self, update: Mapping[str, Any], fingerprint: str) -> dict[str, Any]:
        tool_call_id = update.get("toolCallId")
        if not isinstance(tool_call_id, str) or not tool_call_id.strip():
            return _publish_malformed_update(
                self._provider_run_id,
                self._session_id,
                fingerprint,
                "tool_call_content_chunk missing toolCallId",
            )
        tool_call_token = _identifier_token(tool_call_id)
        text = _extract_text_content(update.get("content"))
        metadata = {
            "provider_activity_kind": "tool_call_content_chunk",
            "provider_run_id": self._provider_run_id,
            "provider_session_id": self._session_id,
            "tool_call_id": _safe_identifier(tool_call_id),
            "raw_detail": True,
        }
        return _entry(
            entry_id=f"provider-tool-chunk-{self._provider_run_id}-{tool_call_token}-{fingerprint[:12]}",
            entry_type="tool_complete",
            content=text,
            summary="Provider tool output",
            body=text,
            detail_kind="tool_result",
            metadata=metadata,
            streaming=True,
        )

    def _build_terminal_entry(
        self, update: Mapping[str, Any], fingerprint: str, *, is_chunk: bool
    ) -> dict[str, Any]:
        terminal_id = update.get("terminalId")
        if not isinstance(terminal_id, str) or not terminal_id.strip():
            return _publish_malformed_update(
                self._provider_run_id, self._session_id, fingerprint, "terminal update missing terminalId"
            )
        terminal_token = _identifier_token(terminal_id)
        raw_content = update.get("output") if is_chunk else update.get("content")
        text = _extract_text_content(raw_content)
        metadata = {
            "provider_activity_kind": "terminal_output_chunk" if is_chunk else "terminal_update",
            "provider_run_id": self._provider_run_id,
            "provider_session_id": self._session_id,
            "terminal_id": _safe_identifier(terminal_id),
            "raw_detail": True,
        }
        if is_chunk:
            entry_id = f"provider-terminal-output-{self._provider_run_id}-{terminal_token}-{fingerprint[:12]}"
        else:
            entry_id = f"provider-terminal-{self._provider_run_id}-{terminal_token}"
        return _entry(
            entry_id=entry_id,
            entry_type="step",
            content=text,
            summary="Provider terminal output",
            body=text,
            detail_kind="step_note",
            metadata=metadata,
            streaming=is_chunk,
        )

    def _build_state_entry(self, update: Mapping[str, Any], fingerprint: str) -> dict[str, Any]:
        state = update.get("state")
        stop_reason = update.get("stopReason")
        if state == "running":
            message = "Provider is working."
        elif state == "idle" and stop_reason == "end_turn":
            message = "Provider completed this turn."
        elif state == "idle" and stop_reason == "cancelled":
            message = "Provider canceled this turn."
        elif state == "requires_action":
            message = "Provider is waiting for an action."
        else:
            message = f"Provider reported state: {_safe_identifier(state)}."
        metadata = {
            "provider_activity_kind": "state_update",
            "provider_run_id": self._provider_run_id,
            "provider_session_id": self._session_id,
            "provider_state": _safe_identifier(state) if isinstance(state, str) else None,
            "provider_stop_reason": _safe_identifier(stop_reason) if isinstance(stop_reason, str) else None,
        }
        return _entry(
            entry_id=f"provider-state-{self._provider_run_id}-{fingerprint[:12]}",
            entry_type="step",
            content=message,
            summary=message,
            body=message,
            detail_kind="step_note",
            metadata=metadata,
            streaming=False,
        )

    def _build_plan_entry(self, update: Mapping[str, Any], fingerprint: str) -> dict[str, Any]:
        raw_entries = update.get("entries")
        steps: list[str] = []
        if isinstance(raw_entries, Sequence) and not isinstance(raw_entries, (str, bytes, bytearray)):
            for item in list(raw_entries)[:_MAX_PLAN_STEPS]:
                if isinstance(item, Mapping):
                    description = item.get("content") or item.get("description") or item.get("title")
                    steps.append(_bounded_text(description, maximum_bytes=_MAX_SUMMARY_TEXT_BYTES))
                elif isinstance(item, str):
                    steps.append(_bounded_text(item, maximum_bytes=_MAX_SUMMARY_TEXT_BYTES))
        body = _bounded_text("\n".join(f"- {step}" for step in steps[:_MAX_PLAN_STEPS]))
        metadata = {
            "provider_activity_kind": "plan",
            "provider_run_id": self._provider_run_id,
            "provider_session_id": self._session_id,
            "plan_step_count": len(steps),
        }
        return _entry(
            entry_id=f"provider-plan-{self._provider_run_id}-{fingerprint[:12]}",
            entry_type="step",
            content=body,
            summary="Provider plan updated",
            body=body,
            detail_kind="step_note",
            metadata=metadata,
            streaming=False,
        )

    def _build_unknown_entry(self, update: Mapping[str, Any], fingerprint: str) -> dict[str, Any]:
        safe_update: dict[str, Any] = {}
        for key, value in update.items():
            if key in _EXCLUDED_UNKNOWN_KEYS:
                continue
            if key == "content" and not _is_text_like_content(value):
                continue
            safe_update[_bounded_text(key, maximum_bytes=_MAX_IDENTIFIER_TEXT_BYTES)] = _safe_unknown_value(value)
        rendered = _bounded_text(
            json.dumps(safe_update, ensure_ascii=False, sort_keys=True, default=str)
        )
        metadata = {
            "provider_activity_kind": str(update.get("sessionUpdate") or update.get("kind") or "unknown"),
            "provider_run_id": self._provider_run_id,
            "provider_session_id": self._session_id,
            "raw_detail": True,
        }
        return _entry(
            entry_id=f"provider-activity-{self._provider_run_id}-{fingerprint[:12]}",
            entry_type="step",
            content=rendered,
            summary="Provider activity update",
            body=rendered,
            detail_kind="step_note",
            metadata=metadata,
            streaming=False,
        )

    async def _publish(self, entry: Mapping[str, Any]) -> None:
        if self._safe_activity_observer is not None:
            try:
                await self._safe_activity_observer(dict(entry))
            except Exception as exc:  # noqa: BLE001 - evidence capture must never block activity projection.
                self._logger.debug(
                    "Provider activity observer raised for task %s: %s",
                    self._agent_task_id,
                    exc.__class__.__name__,
                )
        try:
            published = await self._routing_service.publish_activity_entry(
                agent_task_id=self._agent_task_id,
                root_task_id=self._root_task_id,
                previous_task_id=self._previous_task_id,
                entry=entry,
            )
        except Exception as exc:  # noqa: BLE001 - activity transport must never break the provider process.
            self._logger.debug(
                "Provider activity publish raised for task %s: %s",
                self._agent_task_id,
                exc.__class__.__name__,
            )
            return
        if not published:
            self._logger.debug(
                "Provider activity publish returned False for task %s (entry id=%s)",
                self._agent_task_id,
                entry.get("id"),
            )


__all__ = ["ProviderActivityProjector", "MAX_ACTIVITY_TEXT_BYTES", "MAX_SEEN_ACTIVITY_FINGERPRINTS"]
