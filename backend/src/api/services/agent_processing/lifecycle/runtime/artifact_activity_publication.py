"""Persist and publish verified local filesystem artifact activity."""

from __future__ import annotations

import json
import logging
import os
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from .agent_timeline_contract import (
    normalize_timeline_entry,
    sanitize_timeline_title,
    timeline_timestamp,
)
from .conversation_progress_projection import broadcast_workflow_notification
from .timeline_persistence import persist_artifact_timeline_entry
from api.services.agent_processing.shared.material_operation_receipts import (
    MaterialOperationContractError,
    MaterialOperationReceipt,
    extract_material_operation_envelope,
)

logger = logging.getLogger(__name__)

_ARTIFACT_ID_PREFIX = "file-"
_ARTIFACT_ID_LENGTH = 29
_ARTIFACT_ID_HEX_LENGTH = 24
_MAX_VERIFICATION_SUMMARY_LENGTH = 2_000
_FILE_OPERATIONS = frozenset({"create", "modify", "copy", "move", "rename", "delete"})
_PATH_TRANSITION_LIMIT = 32


def _non_empty_text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _valid_artifact_id(value: Any) -> Optional[str]:
    artifact_id = _non_empty_text(value)
    artifact_id_suffix = (
        artifact_id[len(_ARTIFACT_ID_PREFIX):]
        if artifact_id is not None and artifact_id.startswith(_ARTIFACT_ID_PREFIX)
        else ""
    )
    if (
        artifact_id is None
        or len(artifact_id) != _ARTIFACT_ID_LENGTH
        or len(artifact_id_suffix) != _ARTIFACT_ID_HEX_LENGTH
        or any(character not in "0123456789abcdef" for character in artifact_id_suffix)
    ):
        return None
    return artifact_id


def _normalized_absolute_path(value: Any) -> Optional[str]:
    path = _non_empty_text(value)
    if path is None or not path.startswith("/"):
        return None
    return os.path.normpath(path)


def _artifact_id_for_path(path: str) -> str:
    return f"{_ARTIFACT_ID_PREFIX}{sha256(path.encode('utf-8')).hexdigest()[:_ARTIFACT_ID_HEX_LENGTH]}"


def _valid_sha256(value: Any) -> Optional[str]:
    digest = _non_empty_text(value)
    if (
        digest is None
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        return None
    return digest


def _capture_revision_for_artifact(
    artifact: Mapping[str, Any],
    expected_sha256: Optional[str],
) -> Any:
    """Best-effort durable-snapshot capture for one verified current file."""
    from api.services.agent_processing.lifecycle.runtime.artifact_revision_capture import (
        ArtifactRevisionCaptureResult,
        capture_artifact_revision,
    )

    if artifact.get("lifecycle") != "verified" or not expected_sha256:
        return None
    try:
        return capture_artifact_revision(
            local_path=artifact["local_path"],
            expected_sha256=expected_sha256,
            latest_known_sha256=None,
            task_snapshot_bytes_used=0,
        )
    except Exception:  # noqa: BLE001 - capture must never fail publication.
        return ArtifactRevisionCaptureResult(
            status="unavailable",
            unavailable_reason="Snapshot unavailable: capture failed.",
        )


def _decode_tool_output(output: Any) -> Mapping[str, Any] | None:
    candidate = output
    if isinstance(candidate, str):
        try:
            candidate = json.loads(candidate)
        except (TypeError, ValueError):
            return None
    return candidate if isinstance(candidate, Mapping) else None


def _selected_artifact_from_receipt(
    receipt: MaterialOperationReceipt,
) -> Dict[str, Any] | None:
    """Copy bounded, verified local-file receipt data into an artifact candidate."""
    if (
        receipt.entity.entity_type != "file"
        or receipt.entity.source_system != "filesystem"
        or receipt.entity.source_scope != {"host_scope": "local"}
        or receipt.execution_state != "succeeded"
        or receipt.verification_status != "verified"
    ):
        return None
    operation = receipt.requested_effect.get("operation")
    target_path = _normalized_absolute_path(receipt.entity.external_id)
    if operation not in _FILE_OPERATIONS or target_path is None:
        return None
    source_path = _normalized_absolute_path(receipt.requested_effect.get("source_path"))
    if operation in {"move", "rename", "copy"} and source_path is None:
        return None

    evidence_artifact = receipt.evidence.get("file_artifact")
    if not isinstance(evidence_artifact, Mapping):
        return None
    if (
        _normalized_absolute_path(evidence_artifact.get("full_path")) != target_path
        or evidence_artifact.get("operation") != operation
        or evidence_artifact.get("kind") != "file"
    ):
        return None
    digest = _valid_sha256(evidence_artifact.get("sha256"))
    if operation != "delete" and digest is None:
        return None
    summary = (
        f"Verified file deletion at {target_path}."
        if operation == "delete"
        else f"Verified file at {target_path}; SHA-256 {digest}."
    )
    return {
        "target_path": target_path,
        "source_path": source_path,
        "operation": operation,
        "lifecycle": "verified",
        "expected_sha256": digest,
        "verification": {"status": "verified", "summary": summary},
    }


def _legacy_direct_text_artifact(payload: Mapping[str, Any]) -> Dict[str, Any] | None:
    """Preserve pre-envelope direct-write compatibility for durable replay."""
    artifact = payload.get("agent_task_artifact")
    if not isinstance(artifact, Mapping):
        return None
    artifact_id = _valid_artifact_id(artifact.get("artifact_id"))
    display_name = _non_empty_text(artifact.get("display_name"))
    local_path = _normalized_absolute_path(artifact.get("local_path"))
    operation = artifact.get("operation")
    lifecycle = artifact.get("lifecycle")
    verification = artifact.get("verification")
    if (
        artifact_id is None
        or display_name is None
        or local_path is None
        or artifact.get("artifact_kind") != "file"
        or operation not in {"create", "modify"}
        or lifecycle not in {"verified", "failed"}
        or not isinstance(verification, Mapping)
        or verification.get("status") != lifecycle
    ):
        return None
    summary = _non_empty_text(verification.get("summary"))
    if summary is None or len(summary) > _MAX_VERIFICATION_SUMMARY_LENGTH:
        return None
    expected_sha256 = _valid_sha256(summary.rsplit("SHA-256 ", 1)[-1].rstrip("."))
    return {
        "target_path": local_path,
        "source_path": None,
        "operation": operation,
        "lifecycle": lifecycle,
        "expected_sha256": expected_sha256,
        "legacy_artifact_id": artifact_id,
        "verification": {"status": lifecycle, "summary": summary},
    }


def select_serialized_direct_text_artifact(output: Any) -> Dict[str, Any] | None:
    """Read the legacy public artifact shape used by existing projections.

    New publication is receipt-driven, but stored task timelines and the
    presentation projection still need to recognize direct-write artifacts
    emitted before material-operation envelopes existed.
    """
    payload = _decode_tool_output(output)
    artifact = payload.get("agent_task_artifact") if payload is not None else None
    if not isinstance(artifact, Mapping):
        return None
    artifact_id = _valid_artifact_id(artifact.get("artifact_id"))
    display_name = _non_empty_text(artifact.get("display_name"))
    local_path = _normalized_absolute_path(artifact.get("local_path"))
    operation = artifact.get("operation")
    lifecycle = artifact.get("lifecycle")
    verification = artifact.get("verification")
    if (
        artifact_id is None
        or display_name is None
        or local_path is None
        or artifact.get("artifact_kind") != "file"
        or operation not in {"create", "modify"}
        or lifecycle not in {"verified", "failed"}
        or not isinstance(verification, Mapping)
        or verification.get("status") != lifecycle
    ):
        return None
    summary = _non_empty_text(verification.get("summary"))
    if summary is None or len(summary) > _MAX_VERIFICATION_SUMMARY_LENGTH:
        return None
    return {
        "artifact_id": artifact_id,
        "display_name": display_name,
        "local_path": local_path,
        "artifact_kind": "file",
        "operation": operation,
        "lifecycle": lifecycle,
        "preview": {"capability": "unknown"},
        "verification": {"status": lifecycle, "summary": summary},
    }


def select_serialized_file_artifacts(output: Any) -> list[Dict[str, Any]]:
    """Select all well-formed verified local-file artifacts from tool output."""
    payload = _decode_tool_output(output)
    if payload is None:
        return []
    try:
        envelope = extract_material_operation_envelope(payload)
    except MaterialOperationContractError:
        return []
    if envelope is not None:
        return [
            candidate
            for receipt in envelope.receipts
            if (candidate := _selected_artifact_from_receipt(receipt)) is not None
        ]
    legacy = _legacy_direct_text_artifact(payload)
    return [legacy] if legacy is not None else []


def _artifact_from_timeline_entry(value: Any) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    metadata = value.get("metadata")
    artifact = metadata.get("artifact") if isinstance(metadata, Mapping) else None
    return artifact if isinstance(artifact, Mapping) else None


def _paths_for_existing_artifact(artifact: Mapping[str, Any]) -> Iterable[str]:
    lineage = artifact.get("lineage")
    if isinstance(lineage, Mapping):
        for key in ("origin_path", "current_path"):
            if (path := _normalized_absolute_path(lineage.get(key))) is not None:
                yield path
    if (path := _normalized_absolute_path(artifact.get("local_path"))) is not None:
        yield path


def _artifact_index_by_path(timeline: Iterable[Any] | None) -> dict[str, Dict[str, Any]]:
    index: dict[str, Dict[str, Any]] = {}
    for entry in timeline or ():
        artifact = _artifact_from_timeline_entry(entry)
        if artifact is None:
            continue
        artifact_id = _valid_artifact_id(artifact.get("artifact_id"))
        if artifact_id is None:
            continue
        normalized_artifact = dict(artifact)
        for path in _paths_for_existing_artifact(normalized_artifact):
            index[path] = normalized_artifact
    return index


def _existing_lineage(artifact: Mapping[str, Any] | None) -> Dict[str, Any]:
    lineage = artifact.get("lineage") if isinstance(artifact, Mapping) else None
    return dict(lineage) if isinstance(lineage, Mapping) else {}


def _build_artifact(
    candidate: Mapping[str, Any],
    artifacts_by_path: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    target_path = str(candidate["target_path"])
    source_path = candidate.get("source_path")
    operation = str(candidate["operation"])
    lookup_path = (
        source_path
        if operation in {"move", "rename", "delete"}
        else target_path
    )
    existing = artifacts_by_path.get(lookup_path) if isinstance(lookup_path, str) else None
    previous_lineage = _existing_lineage(existing)
    origin_path = _normalized_absolute_path(previous_lineage.get("origin_path"))
    if origin_path is None:
        origin_path = (
            source_path
            if operation in {"move", "rename", "delete"} and isinstance(source_path, str)
            else target_path
        )
    artifact_id = (
        _valid_artifact_id(existing.get("artifact_id"))
        if existing is not None
        else _valid_artifact_id(candidate.get("legacy_artifact_id"))
    ) or _artifact_id_for_path(origin_path)
    previous_transitions = previous_lineage.get("transitions")
    transitions = list(previous_transitions) if isinstance(previous_transitions, list) else []
    transition: Dict[str, Any] = {
        "operation": operation,
        "timestamp": timeline_timestamp(),
    }
    if isinstance(source_path, str):
        transition["source_path"] = source_path
    if operation != "delete":
        transition["target_path"] = target_path
    transitions.append(transition)
    state = "deleted" if operation == "delete" else "moved" if operation in {"move", "rename"} else "current"
    lineage: Dict[str, Any] = {
        "origin_path": origin_path,
        "state": state,
        "transitions": transitions[-_PATH_TRANSITION_LIMIT:],
    }
    if state != "deleted":
        lineage["current_path"] = target_path
    return {
        "artifact_id": artifact_id,
        "display_name": Path(target_path).name,
        "local_path": target_path,
        "artifact_kind": "file",
        "operation": operation,
        "lifecycle": candidate["lifecycle"],
        "preview": {"capability": "unknown"},
        "verification": dict(candidate["verification"]),
        "lineage": lineage,
    }


def build_artifact_timeline_entry(
    artifact: Mapping[str, Any],
    *,
    source_step_id: str,
) -> Dict[str, Any]:
    """Build the one durable activity entry for an already selected artifact."""
    artifact_id = str(artifact["artifact_id"])
    entry_id = f"artifact_{artifact_id}"
    lifecycle = str(artifact["lifecycle"])
    display_name = sanitize_timeline_title(artifact["display_name"], fallback="local file")
    summary = str(artifact["verification"]["summary"])
    persisted_artifact = {
        **dict(artifact),
        "source_timeline_entry_id": entry_id,
        "source_step_id": source_step_id,
    }
    return normalize_timeline_entry(
        {
            "id": entry_id,
            "step_id": source_step_id,
            "type": "artifact",
            "timestamp": timeline_timestamp(),
            "content": f"{lifecycle.title()} local file: {display_name}",
            "detail_kind": "artifact",
            "summary": f"{lifecycle.title()} local file: {display_name}",
            "body": summary,
            "metadata": {
                "event_type": "agent_task_artifact",
                "raw_detail": True,
                "artifact": persisted_artifact,
            },
            "streaming": False,
        },
        phase="execution",
        state="completed",
        source="filesystem_receipt",
        correlation_id=source_step_id,
    )


async def publish_agent_task_artifact(
    *,
    websocket_manager: Any,
    agent_task_id: Optional[str],
    root_task_id: Optional[str],
    previous_task_id: Optional[str],
    output: Any,
    source_step_id: str,
) -> bool:
    """Persist selected filesystem artifacts before correlated event publication."""
    candidates = select_serialized_file_artifacts(output)
    if not candidates or not agent_task_id or not source_step_id:
        return False
    from api.dependencies import get_sqlite_knowledge_service

    try:
        record = await get_sqlite_knowledge_service().get_agent_task(agent_task_id)
    except Exception as exc:  # noqa: BLE001 - publication must never break the callback.
        logger.warning(
            "Artifact timeline prefetch failed task=%s error_type=%s",
            agent_task_id,
            type(exc).__name__,
        )
        return False
    artifacts_by_path = _artifact_index_by_path(record.execution_timeline if record else [])
    did_persist = False
    for candidate in candidates:
        artifact = _build_artifact(candidate, artifacts_by_path)
        entry = build_artifact_timeline_entry(artifact, source_step_id=source_step_id)
        revision_capture = _capture_revision_for_artifact(
            artifact,
            candidate.get("expected_sha256"),
        )
        try:
            persisted_entry = await persist_artifact_timeline_entry(
                agent_task_id,
                entry,
                artifact_id=artifact["artifact_id"],
                revision_capture=revision_capture,
                local_path=artifact["local_path"] if revision_capture is not None else None,
                display_name=artifact["display_name"] if revision_capture is not None else None,
            )
        except Exception as exc:  # noqa: BLE001 - publication must never break the callback.
            logger.warning(
                "Artifact timeline persistence failed task=%s artifact=%s error_type=%s",
                agent_task_id,
                artifact["artifact_id"],
                type(exc).__name__,
            )
            continue
        if persisted_entry is None:
            continue
        did_persist = True
        for path in _paths_for_existing_artifact(artifact):
            artifacts_by_path[path] = artifact
        if websocket_manager is None:
            continue
        persisted_artifact = persisted_entry["metadata"]["artifact"]
        event: Dict[str, Any] = {
            "event_type": "agent_task_artifact",
            "agent_task_id": agent_task_id,
            "agent_task_artifact": persisted_artifact,
            "timeline_entry": persisted_entry,
            "timestamp": timeline_timestamp(),
        }
        if root_task_id:
            event["root_task_id"] = root_task_id
        if previous_task_id:
            event["previous_task_id"] = previous_task_id
        try:
            await broadcast_workflow_notification(websocket_manager, event)
        except Exception as exc:  # noqa: BLE001 - durable state remains authoritative after send failure.
            logger.warning(
                "Artifact event broadcast failed task=%s artifact=%s error_type=%s",
                agent_task_id,
                artifact["artifact_id"],
                type(exc).__name__,
            )
    return did_persist
