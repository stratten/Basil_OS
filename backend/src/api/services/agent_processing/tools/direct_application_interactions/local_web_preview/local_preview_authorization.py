"""Authorization and evidence validation for task-owned local web previews."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

from fastapi import HTTPException

from api.routes.agent_tasks.projections.artifact_presentation import build_agent_task_presentation_summary
from api.routes.agent_tasks.utils import extract_result_data

_MAX_SCREENSHOT_BYTES = 8 * 1024 * 1024
_MAX_CONSOLE_CHARS = 8_000


@dataclass(frozen=True)
class AuthorizedLocalPreviewArtifact:
    requested_agent_task_id: str
    source_agent_task_id: str
    artifact_id: str
    display_name: str
    local_path: Path


def _task_artifacts(task: Any) -> list[Mapping[str, Any]]:
    _message, files, _references, _error, timeline = extract_result_data(task)
    summary = build_agent_task_presentation_summary(
        agent_task_id=task.id,
        lifecycle=task.status,
        result_data=task.result_data if isinstance(task.result_data, Mapping) else None,
        execution_timeline=timeline if isinstance(timeline, list) else None,
        files=files,
    )
    artifacts = summary.get("artifacts")
    return artifacts if isinstance(artifacts, list) else []


async def resolve_task_owned_preview_artifact(
    *,
    knowledge_service: Any,
    requested_agent_task_id: str,
    artifact_id: str,
) -> AuthorizedLocalPreviewArtifact:
    requested = await knowledge_service.agent_task_service.get_agent_task(requested_agent_task_id)
    if requested is None:
        raise HTTPException(status_code=404, detail="Agent Task not found.")
    root_task_id = requested.root_task_id or requested.id
    chain = await knowledge_service.agent_task_service.get_agent_task_chain(root_task_id)
    candidates = chain or [requested]
    for task in candidates:
        for artifact in _task_artifacts(task):
            if artifact.get("artifact_id") != artifact_id:
                continue
            if artifact.get("artifact_kind") != "file":
                break
            raw_path = artifact.get("local_path")
            if not isinstance(raw_path, str) or not raw_path.startswith("/"):
                break
            canonical_path = Path(raw_path).resolve(strict=False)
            if not canonical_path.is_file():
                break
            return AuthorizedLocalPreviewArtifact(
                requested_agent_task_id=requested_agent_task_id,
                source_agent_task_id=task.id,
                artifact_id=artifact_id,
                display_name=str(artifact.get("display_name") or canonical_path.name),
                local_path=canonical_path,
            )
    raise HTTPException(status_code=404, detail="Local preview artifact not found for this Agent Task.")


def require_artifact_within_working_directory(
    artifact: AuthorizedLocalPreviewArtifact,
    cwd: str,
) -> None:
    try:
        working_directory = Path(cwd).resolve(strict=True)
        artifact.local_path.relative_to(working_directory)
    except (OSError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="Preview working directory must contain the selected task artifact.",
        ) from None


def _allowed_screenshot_root() -> Path:
    from os import environ

    data_root = Path(environ.get("BASIL_DATA_DIR") or Path.home() / ".basil" / "data")
    return (data_root / "local_web_preview" / "screenshots").resolve(strict=False)


def validate_preview_screenshot_path(value: str | None) -> dict[str, str]:
    if not value:
        return {"status": "unavailable", "reason": "Native snapshot was unavailable."}
    try:
        candidate = Path(value).resolve(strict=True)
        candidate.relative_to(_allowed_screenshot_root())
        if candidate.suffix.lower() != ".png" or candidate.stat().st_size > _MAX_SCREENSHOT_BYTES:
            raise ValueError
    except (OSError, ValueError):
        return {"status": "unavailable", "reason": "Native snapshot reference was rejected."}
    return {"status": "available", "path": str(candidate)}


def validate_preview_url(mode: str, value: str, *, artifact_local_path: Path) -> str:
    parsed = urlsplit(value)
    # The native preview window serves static documents through a
    # `basil-preview-file://` WKURLSchemeHandler scoped to the artifact's own
    # directory (see AgentTaskLocalWebPreviewWindow.swift's
    # LocalPreviewFileSchemeHandler), not a plain `file://` navigation, so the
    # requested filename must match the artifact this feedback was authorized
    # against -- not merely any file the handler's directory scope would
    # otherwise serve.
    if mode == "static" and parsed.scheme == "basil-preview-file":
        requested_name = unquote(parsed.path).lstrip("/")
        if requested_name and requested_name == artifact_local_path.name:
            return value
        raise HTTPException(status_code=422, detail="Preview feedback URL is not a permitted local preview URL.")
    if mode == "devServer" and parsed.scheme == "http" and parsed.hostname == "127.0.0.1":
        return value
    raise HTTPException(status_code=422, detail="Preview feedback URL is not a permitted local preview URL.")


def build_local_preview_feedback_context(
    *,
    artifact: AuthorizedLocalPreviewArtifact,
    mode: str,
    preview_url: str,
    location_status: str,
    screenshot: dict[str, str],
    console_evidence: str,
    session_id: str | None,
    session_status: str | None,
) -> dict[str, Any]:
    return {
        "kind": "local_web_preview_feedback",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "source_agent_task_id": artifact.source_agent_task_id,
        "source_artifact_id": artifact.artifact_id,
        "source_artifact_name": artifact.display_name,
        "preview_mode": mode,
        "preview_url": preview_url,
        "location_status": location_status,
        "screenshot": screenshot,
        "console_evidence": console_evidence[:_MAX_CONSOLE_CHARS],
        "network_evidence": {"policy": "not_captured", "status": "not_captured"},
        "session": {"id": session_id, "status": session_status},
        "provenance": "native_local_web_preview",
    }
