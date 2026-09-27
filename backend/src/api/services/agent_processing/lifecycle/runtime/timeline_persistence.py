"""Durable persistence for normalized agent activity entries."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from .agent_timeline_contract import normalize_timeline_entry


async def persist_timeline_entry(
    agent_task_id: str | None,
    entry: Mapping[str, Any],
    *,
    replace_existing: bool = False,
) -> None:
    """Append or replace one complete contract entry without losing legacy fields."""
    if not agent_task_id:
        return

    from api.dependencies import get_sqlite_knowledge_service

    knowledge_service = get_sqlite_knowledge_service()
    agent_task_record = await knowledge_service.get_agent_task(agent_task_id)
    if not agent_task_record:
        return

    timeline = list(agent_task_record.execution_timeline or [])
    persisted_entry = normalize_timeline_entry(entry)
    if replace_existing:
        timeline = [
            existing
            for existing in timeline
            if not isinstance(existing, dict) or existing.get("id") != persisted_entry["id"]
        ]

    timeline.append(persisted_entry)
    await knowledge_service.agent_task_service._mutations.update_execution_timeline(
        agent_task_id,
        timeline,
    )


async def persist_artifact_timeline_entry(
    agent_task_id: str | None,
    entry: Mapping[str, Any],
    *,
    artifact_id: str,
    revision_capture: Any = None,
    local_path: str | None = None,
    display_name: str | None = None,
) -> Dict[str, Any] | None:
    """Atomically upsert one selected artifact entry for an active Agent Task.

    ``revision_capture``, ``local_path``, and ``display_name`` are forwarded
    unchanged to the durable mutation so a captured snapshot is inserted in
    the same write transaction as the timeline upsert. They are optional and
    have no effect on entries that do not carry a fresh local text write.
    """
    if not agent_task_id or not artifact_id:
        return None

    metadata = entry.get("metadata")
    artifact = metadata.get("artifact") if isinstance(metadata, Mapping) else None
    if not isinstance(artifact, Mapping) or artifact.get("artifact_id") != artifact_id:
        return None

    from api.dependencies import get_sqlite_knowledge_service

    persisted_entry = normalize_timeline_entry(entry)
    knowledge_service = get_sqlite_knowledge_service()
    persisted = await knowledge_service.agent_task_service._mutations.upsert_execution_timeline_artifact(
        agent_task_id,
        persisted_entry,
        artifact_id,
        revision_capture=revision_capture,
        local_path=local_path,
        display_name=display_name,
    )
    if not persisted:
        return None
    return await _entry_with_matching_review(persisted_entry, agent_task_id, artifact_id)


async def _entry_with_matching_review(
    entry: Dict[str, Any],
    agent_task_id: str,
    artifact_id: str,
) -> Dict[str, Any]:
    from api.dependencies import get_sqlite_knowledge_service

    knowledge_service = get_sqlite_knowledge_service()
    record = await knowledge_service.get_agent_task(agent_task_id)
    if record and record.execution_timeline:
        for timeline_entry in record.execution_timeline:
            if not isinstance(timeline_entry, dict):
                continue
            metadata = timeline_entry.get("metadata")
            if not isinstance(metadata, Mapping):
                continue
            artifact = metadata.get("artifact")
            if (
                isinstance(artifact, Mapping)
                and artifact.get("artifact_id") == artifact_id
                and isinstance(artifact.get("review"), Mapping)
            ):
                return timeline_entry

    revisions = await knowledge_service.agent_task_service.list_artifact_revisions(
        agent_task_id,
        artifact_id,
    )
    if not revisions:
        return entry
    latest = revisions[0]
    metadata = entry.get("metadata")
    if not isinstance(metadata, Mapping):
        return entry
    artifact = metadata.get("artifact")
    if not isinstance(artifact, Mapping):
        return entry
    review = {
        "revision": latest["revision"],
        "revision_count": len(revisions),
        "kind": latest["content_kind"],
        "snapshot_status": "available",
    }
    return {**entry, "metadata": {**metadata, "artifact": {**artifact, "review": review}}}
