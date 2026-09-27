"""Shared, backward-compatible agent activity timeline contract."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Dict, Literal, Mapping, MutableMapping, TypedDict
from uuid import uuid4


AgentTimelineState = Literal[
    "started",
    "in_progress",
    "completed",
    "failed",
    "cancelled",
    "waiting_user_input",
    "blocked",
]
ArtifactLifecycle = Literal["discovered", "ready", "verified", "failed", "unavailable"]
ArtifactPreviewCapability = Literal["supported", "unsupported", "unknown"]
ArtifactVerificationStatus = Literal["not_applicable", "pending", "verified", "failed", "unknown"]


class AgentTimelineArtifactPreview(TypedDict, total=False):
    capability: ArtifactPreviewCapability
    kind: str


class AgentTimelineArtifactVerification(TypedDict, total=False):
    status: ArtifactVerificationStatus
    summary: str


class AgentTimelineArtifactPathTransition(TypedDict, total=False):
    operation: str
    source_path: str
    target_path: str
    timestamp: str


class AgentTimelineArtifactLineage(TypedDict, total=False):
    origin_path: str
    current_path: str
    state: Literal["current", "moved", "deleted"]
    transitions: list[AgentTimelineArtifactPathTransition]


class AgentTimelineArtifact(TypedDict, total=False):
    artifact_id: str
    display_name: str
    local_path: str
    artifact_kind: Literal["file", "directory", "unknown"]
    operation: str
    lifecycle: ArtifactLifecycle
    source_timeline_entry_id: str
    source_step_id: str
    preview: AgentTimelineArtifactPreview
    verification: AgentTimelineArtifactVerification
    lineage: AgentTimelineArtifactLineage


class AgentTimelineEntry(TypedDict, total=False):
    """Canonical durable activity entry; unknown legacy fields are retained."""

    id: str
    timestamp: str
    type: str
    content: str
    detail_kind: str
    summary: str
    body: str
    metadata: Dict[str, Any]
    phase: str
    state: AgentTimelineState
    source: str
    title: str
    correlation_id: str
    step_id: str
    streaming: bool


def timeline_timestamp() -> str:
    """Return an explicit UTC timestamp suitable for persisted activity entries."""
    return datetime.now(timezone.utc).isoformat()


def safe_timeline_id(prefix: str, value: Any = None) -> str:
    """Build a readable, collision-resistant legacy-compatible entry identifier."""
    raw = value or uuid4().hex
    safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(raw)).strip("_")
    return f"{prefix}_{safe}_{uuid4().hex[:8]}"


def sanitize_timeline_title(value: Any, *, fallback: str = "Working") -> str:
    """Produce a short, single-line title safe for user-visible progress."""
    text = str(value or "").replace("\x00", "").replace("\r", " ").replace("\n", " ")
    text = " ".join(text.split()).strip()
    if not text:
        return fallback
    return text[:160].rstrip()


def _json_safe(value: Any) -> Any:
    """Convert arbitrary callback values without rejecting legacy payload fields."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def normalize_timeline_artifact_metadata(value: Any) -> Dict[str, Any] | None:
    """Return a JSON-safe copy of mapping-valued artifact metadata."""
    if not isinstance(value, Mapping):
        return None
    normalized = _json_safe(value)
    return dict(normalized) if isinstance(normalized, Mapping) else None


def attach_progress_metadata(
    metadata: MutableMapping[str, Any],
    *,
    phase: str | None = None,
    state: str | None = None,
    step: str | None = None,
) -> MutableMapping[str, Any]:
    """Mirror the canonical phase/state/title into the metadata the UI reads.

    The React activity trail (``selectActivityTrail``) and collapsed-chrome
    status snapshot key off ``metadata.progress_*``; the durable contract has
    historically only carried ``phase``/``state`` as top-level fields, so those
    fields never reached the frontend mapper. This helper is the single place
    that populates the ``progress_*`` mirror for both the live WebSocket entry
    and the persisted entry.

    Raw tool-detail entries opt out via ``metadata['raw_detail'] = True`` so
    that verbose tray payloads stay out of the readable progress trail. Any
    ``progress_current`` / ``progress_total`` the caller already supplied is
    left untouched, and explicit caller values are never overwritten.
    """
    if metadata.get("raw_detail"):
        return metadata
    if step:
        metadata.setdefault("progress_step", step)
    if phase:
        metadata.setdefault("progress_phase", phase)
    if state:
        metadata.setdefault("progress_status", str(state))
    return metadata


def normalize_timeline_entry(
    entry: Mapping[str, Any] | None = None,
    *,
    phase: str | None = None,
    state: AgentTimelineState | str | None = None,
    source: str | None = None,
    title: str | None = None,
    correlation_id: str | None = None,
) -> AgentTimelineEntry:
    """Return a complete, JSON-safe entry while preserving all legacy fields.

    Existing timeline dictionaries are permissive input: unfamiliar keys remain
    available to historical consumers instead of being silently discarded.
    """
    normalized: MutableMapping[str, Any] = {
        str(key): _json_safe(value)
        for key, value in (entry or {}).items()
    }
    metadata = normalized.get("metadata")
    normalized["metadata"] = dict(metadata) if isinstance(metadata, Mapping) else {}
    normalized_artifact = normalize_timeline_artifact_metadata(normalized["metadata"].get("artifact"))
    if normalized_artifact is not None:
        normalized["metadata"]["artifact"] = normalized_artifact

    normalized.setdefault("id", f"timeline_{uuid4().hex}")
    normalized.setdefault("timestamp", timeline_timestamp())
    normalized.setdefault("type", "step")
    normalized.setdefault("streaming", False)

    visible_title = sanitize_timeline_title(
        title or normalized.get("title") or normalized.get("summary") or normalized.get("content"),
    )
    normalized["title"] = visible_title
    normalized.setdefault("summary", visible_title)
    normalized.setdefault("content", visible_title)
    normalized.setdefault("body", normalized["content"])
    normalized.setdefault("detail_kind", "step_note")

    if phase or normalized.get("phase"):
        normalized["phase"] = sanitize_timeline_title(phase or normalized["phase"])
    if state or normalized.get("state"):
        normalized["state"] = str(state or normalized["state"])
    if source or normalized.get("source"):
        normalized["source"] = sanitize_timeline_title(source or normalized["source"])
    if correlation_id or normalized.get("correlation_id"):
        normalized["correlation_id"] = str(correlation_id or normalized["correlation_id"])

    attach_progress_metadata(
        normalized["metadata"],
        phase=normalized.get("phase"),
        state=normalized.get("state"),
        step=visible_title,
    )

    return dict(normalized)  # type: ignore[return-value]


def build_timeline_event(
    entry: Mapping[str, Any] | None = None,
    **contract_fields: Any,
) -> Dict[str, Any]:
    """Build the canonical event payload plus the legacy top-level fields."""
    timeline_entry = normalize_timeline_entry(entry, **contract_fields)
    event = dict(timeline_entry)
    event["timeline_entry"] = timeline_entry
    return event
