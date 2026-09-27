"""Presentation-safe Agent Task artifact and summary projections."""

from hashlib import sha256
from os.path import basename, isabs, normpath
from typing import Any, Dict, List, Mapping, Optional, Sequence

from api.services.agent_processing.lifecycle.runtime.agent_timeline_contract import sanitize_timeline_title  # type: ignore[import-untyped]
from api.services.agent_processing.lifecycle.runtime.artifact_activity_publication import (
    select_serialized_direct_text_artifact,
)

from .finalizer_result import get_finalizer_envelope

_ARTIFACT_KINDS = {"file", "directory", "unknown"}


def _non_empty_string(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _bounded_plain_text(value: Any) -> Optional[str]:
    text = _non_empty_string(value)
    if text is None:
        return None
    normalized = sanitize_timeline_title(text, fallback="")
    return normalized or None


def _absolute_local_path(value: Any) -> Optional[str]:
    path = _non_empty_string(value)
    return normpath(path) if path and isabs(path) else None


def _stable_artifact_identifier(
    source: Mapping[str, Any],
    *,
    display_name: str,
    path: Optional[str],
    operation: Optional[str],
    source_path: Optional[str],
) -> str:
    supplied_identifier = _non_empty_string(source.get("artifact_id"))
    if supplied_identifier is not None:
        return supplied_identifier
    if path is not None:
        return f"file-{sha256(path.encode('utf-8')).hexdigest()[:24]}"
    selected_identity = "\x1f".join((display_name, source_path or "", operation or ""))
    return f"file-{sha256(selected_identity.encode('utf-8')).hexdigest()[:24]}"


def _artifact_kind(value: Any) -> str:
    kind = _non_empty_string(value)
    if kind is None:
        return "unknown"
    normalized = kind.lower()
    return normalized if normalized in _ARTIFACT_KINDS else "unknown"


def _artifact_identity(artifact: Mapping[str, Any]) -> Optional[str]:
    local_path = _absolute_local_path(artifact.get("local_path"))
    if local_path is not None:
        return f"path:{local_path}"
    artifact_id = _non_empty_string(artifact.get("artifact_id"))
    return f"id:{artifact_id}" if artifact_id is not None else None


def _persisted_direct_text_timeline_artifact(entry: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(entry, Mapping):
        return None
    entry_id = _non_empty_string(entry.get("id"))
    metadata = entry.get("metadata")
    if (
        entry.get("type") != "artifact"
        or not isinstance(metadata, Mapping)
        or metadata.get("event_type") != "agent_task_artifact"
        or metadata.get("raw_detail") is not True
        or entry_id is None
    ):
        return None
    raw_artifact = metadata.get("artifact")
    selected = select_serialized_direct_text_artifact(
        {"agent_task_artifact": raw_artifact}
    )
    if selected is None:
        return None
    artifact_id = selected["artifact_id"]
    source_timeline_entry_id = _non_empty_string(
        raw_artifact.get("source_timeline_entry_id")
        if isinstance(raw_artifact, Mapping)
        else None
    )
    source_step_id = _non_empty_string(
        raw_artifact.get("source_step_id")
        if isinstance(raw_artifact, Mapping)
        else None
    )
    if (
        entry_id != f"artifact_{artifact_id}"
        or source_timeline_entry_id != entry_id
        or source_step_id is None
    ):
        return None
    persisted_artifact = {
        **selected,
        "source_timeline_entry_id": source_timeline_entry_id,
        "source_step_id": source_step_id,
    }
    review = _valid_artifact_review(
        raw_artifact.get("review") if isinstance(raw_artifact, Mapping) else None
    )
    if review is not None:
        persisted_artifact["review"] = review
    return persisted_artifact


_REVIEW_KINDS = {"markdown", "html", "text", "code", "json", "yaml", "xml", "pdf", "unsupported"}
_REVIEW_STATUSES = {"available", "unchanged", "unavailable"}


def _valid_artifact_review(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    revision = value.get("revision")
    revision_count = value.get("revision_count")
    kind = value.get("kind")
    snapshot_status = value.get("snapshot_status")
    unavailable_reason = value.get("unavailable_reason")
    if revision is not None and (not isinstance(revision, int) or revision < 1):
        return None
    if not isinstance(revision_count, int) or revision_count < 0:
        return None
    if kind is not None and kind not in _REVIEW_KINDS:
        return None
    if snapshot_status not in _REVIEW_STATUSES:
        return None
    if unavailable_reason is not None and (
        not isinstance(unavailable_reason, str) or len(unavailable_reason) > 160
    ):
        return None
    result: Dict[str, Any] = {
        "revision": revision,
        "revision_count": revision_count,
        "snapshot_status": snapshot_status,
    }
    if kind is not None:
        result["kind"] = kind
    if unavailable_reason is not None:
        result["unavailable_reason"] = unavailable_reason
    return result


def _merge_timeline_evidence(
    existing: Mapping[str, Any],
    timeline_artifact: Mapping[str, Any],
) -> Dict[str, Any]:
    merged = dict(existing)
    verification = timeline_artifact.get("verification")
    verification_status = verification.get("status") if isinstance(verification, Mapping) else None
    if verification_status in {"verified", "failed"}:
        merged["lifecycle"] = timeline_artifact["lifecycle"]
        merged["verification"] = dict(verification)
    for key in ("source_timeline_entry_id", "source_step_id"):
        if merged.get(key) is None and timeline_artifact.get(key) is not None:
            merged[key] = timeline_artifact[key]
    review = _valid_artifact_review(timeline_artifact.get("review"))
    if review is not None:
        merged["review"] = review
    return merged


def build_file_artifact_presentation(source: Mapping[str, Any]) -> Dict[str, Any]:
    """Build one selected artifact object without exposing arbitrary source fields."""
    raw_path = _non_empty_string(source.get("path") or source.get("full_path") or source.get("fullPath"))
    local_path = _absolute_local_path(raw_path)
    display_name = _non_empty_string(source.get("name")) or (basename(raw_path) if raw_path else "Unnamed artifact")
    operation = _non_empty_string(source.get("operation"))
    source_path = _non_empty_string(source.get("source_path") or source.get("sourcePath"))
    artifact = {
        "artifact_id": _stable_artifact_identifier(
            source,
            display_name=display_name,
            path=local_path,
            operation=operation,
            source_path=source_path,
        ),
        "display_name": display_name,
        "artifact_kind": _artifact_kind(source.get("kind")),
        "lifecycle": "ready" if local_path else "unavailable",
        "preview": {"capability": "unknown" if local_path else "unsupported"},
        "verification": {"status": "unknown"},
    }
    review = _valid_artifact_review(source.get("review"))
    if review is not None:
        artifact["review"] = review
    if local_path is not None:
        artifact["local_path"] = local_path
    if operation is not None:
        artifact["operation"] = operation
    source_timeline_entry_id = _non_empty_string(source.get("source_timeline_entry_id"))
    if source_timeline_entry_id is not None:
        artifact["source_timeline_entry_id"] = source_timeline_entry_id
    source_step_id = _non_empty_string(source.get("source_step_id"))
    if source_step_id is not None:
        artifact["source_step_id"] = source_step_id
    return artifact


def normalize_file_entry(source: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize legacy file keys and attach a selected presentation-safe artifact."""
    entry = {
        "name": source.get("name", ""),
        "path": source.get("path") or source.get("full_path") or source.get("fullPath") or "",
        "operation": source.get("operation", ""),
    }
    if source.get("source_path") or source.get("sourcePath"):
        entry["source_path"] = source.get("source_path") or source.get("sourcePath")
    if source.get("kind"):
        entry["kind"] = source["kind"]
    entry["artifact"] = build_file_artifact_presentation(source)
    return entry


def _finalizer_workflow_counts(result_data: Optional[Mapping[str, Any]]) -> Dict[str, int]:
    if not isinstance(result_data, Mapping):
        return {}
    finalizer = get_finalizer_envelope(result_data)
    payload = finalizer.get("result_payload") if isinstance(finalizer, Mapping) else None
    steps = payload.get("steps") if isinstance(payload, Mapping) else None
    if not isinstance(steps, Mapping):
        return {}
    completed = steps.get("completed")
    total = steps.get("total")
    if type(completed) is not int or completed < 0:
        return {}
    if type(total) is not int or total < 0:
        return {}
    return {"completed_steps": completed, "total_steps": total}


def _latest_presentation_activity(execution_timeline: Optional[Sequence[Mapping[str, Any]]]) -> Optional[str]:
    if not isinstance(execution_timeline, Sequence) or isinstance(execution_timeline, (str, bytes)):
        return None
    for entry in reversed(execution_timeline):
        if not isinstance(entry, Mapping):
            continue
        metadata = entry.get("metadata")
        if isinstance(metadata, Mapping) and metadata.get("raw_detail"):
            continue
        for key in ("title", "summary", "content"):
            activity = _bounded_plain_text(entry.get(key))
            if activity is not None:
                return activity
    return None


def _summary_verification_status(artifacts: Sequence[Mapping[str, Any]]) -> str:
    statuses = {
        artifact.get("verification", {}).get("status")
        for artifact in artifacts
        if isinstance(artifact.get("verification"), Mapping)
    }
    if not statuses:
        return "unknown"
    if "pending" in statuses:
        return "pending"
    if statuses <= {"verified", "failed", "not_applicable"}:
        return "resolved"
    return "unknown"


def _delegated_provider_report_cards(value: Optional[Sequence[Mapping[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return {"items": []}
    cards: List[Dict[str, Any]] = []
    seen_run_ids: set[str] = set()
    for candidate in value:
        if not isinstance(candidate, Mapping):
            continue
        run_id = _non_empty_string(candidate.get("delegated_agent_run_id"))
        run_status = _non_empty_string(candidate.get("run_status"))
        capture_state = _non_empty_string(candidate.get("capture_state"))
        verification_state = _non_empty_string(candidate.get("verification_state"))
        revision = candidate.get("run_revision")
        evidence_count = candidate.get("evidence_count")
        latest_summary = _bounded_plain_text(candidate.get("latest_summary"))
        if (
            run_id is None
            or run_status not in {"admitted", "running", "idle", "waiting_user_input", "waiting_permission", "supervision_due", "cancelling", "interrupted", "settled", "failed", "cancelled"}
            or capture_state not in {"available", "unavailable"}
            or verification_state not in {"not_applicable", "pending", "verified", "verification_mismatch", "unavailable"}
            or type(revision) is not int
            or revision < 0
            or type(evidence_count) is not int
            or evidence_count < 0
            or run_id in seen_run_ids
        ):
            continue
        if latest_summary is not None and len(latest_summary) > 160:
            continue
        seen_run_ids.add(run_id)
        card = {
            "delegated_agent_run_id": run_id,
            "run_status": run_status,
            "run_revision": revision,
            "capture_state": capture_state,
            "evidence_count": evidence_count,
            "verification_state": verification_state,
        }
        if latest_summary is not None:
            card["latest_summary"] = latest_summary
        cards.append(card)
    return {"items": cards}


def build_agent_task_presentation_summary(
    *,
    agent_task_id: str,
    lifecycle: str,
    result_data: Optional[Mapping[str, Any]],
    execution_timeline: Optional[Sequence[Mapping[str, Any]]],
    files: Sequence[Mapping[str, Any]],
    delegated_provider_report_cards: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build the bounded durable summary exposed by the Agent Task detail route."""
    artifacts: List[Dict[str, Any]] = []
    indexes_by_identity: Dict[str, int] = {}

    for file_entry in files:
        artifact = file_entry.get("artifact") if isinstance(file_entry, Mapping) else None
        if not isinstance(artifact, Mapping):
            continue
        identity = _artifact_identity(artifact)
        if identity is None or identity in indexes_by_identity:
            continue
        indexes_by_identity[identity] = len(artifacts)
        artifacts.append(dict(artifact))

    if isinstance(execution_timeline, Sequence) and not isinstance(
        execution_timeline,
        (str, bytes),
    ):
        for entry in execution_timeline:
            artifact = _persisted_direct_text_timeline_artifact(entry)
            if artifact is None:
                continue
            identity = _artifact_identity(artifact)
            if identity is None:
                continue
            existing_index = indexes_by_identity.get(identity)
            if existing_index is None:
                indexes_by_identity[identity] = len(artifacts)
                artifacts.append(artifact)
            else:
                artifacts[existing_index] = _merge_timeline_evidence(
                    artifacts[existing_index],
                    artifact,
                )

    summary = {
        "agent_task_id": agent_task_id,
        "lifecycle": lifecycle,
        "workflow": _finalizer_workflow_counts(result_data),
        "artifacts": artifacts[:6],
        "artifact_count": len(artifacts),
        "verification_status": _summary_verification_status(artifacts),
        "requires_user_attention": lifecycle in {"awaiting_user_input", "waiting_user_input", "needs_clarification"},
        "delegated_provider_report_cards": _delegated_provider_report_cards(delegated_provider_report_cards),
    }
    latest_activity = _latest_presentation_activity(execution_timeline)
    if latest_activity is not None:
        summary["latest_activity"] = latest_activity
    return summary
