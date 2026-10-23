"""Loopback-only control plane for the developer-local validation environment."""

from __future__ import annotations

import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from api.core.runtime.validation_profile import (
    ValidationRuntimeProfile,
    is_validation_runtime,
)
from api.services.agent_processing.lifecycle.runtime.conversation_progress_projection import (
    broadcast_workflow_notification,
)
from api.services.validation.fixture_service import ValidationFixtureService

router = APIRouter(prefix="/validation", tags=["validation"])


def _profile() -> ValidationRuntimeProfile:
    if not is_validation_runtime():
        raise HTTPException(status_code=404, detail="Validation runtime is disabled.")
    return ValidationRuntimeProfile.from_environment()


def _authorize(
    request: Request,
    validation_token: str | None = Header(default=None, alias="X-Basil-Validation-Token"),
) -> ValidationRuntimeProfile:
    profile = _profile()
    client_host = request.client.host if request.client else None
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="Validation control plane is loopback-only.")
    if validation_token is None or not hmac.compare_digest(
        validation_token,
        profile.manifest_token,
    ):
        raise HTTPException(status_code=401, detail="Validation session token is invalid.")
    return profile


def _fixture_service(request: Request) -> ValidationFixtureService:
    fixture_service = getattr(request.app.state, "validation_fixture_service", None)
    if fixture_service is None:
        raise HTTPException(status_code=503, detail="Validation fixtures are not ready.")
    return fixture_service


def _agent_task_routing_service(request: Request):
    wake_word_service = getattr(request.app.state, "wake_word_service", None)
    orchestrator = getattr(wake_word_service, "agent_task_orchestrator", None)
    routing_service = getattr(orchestrator, "routing_service", None)
    if routing_service is None:
        raise HTTPException(status_code=503, detail="Agent Task routing is not ready.")
    return routing_service


def _workflow_notification_manager(request: Request):
    websocket_manager = getattr(request.app.state, "wake_word_service", None)
    if websocket_manager is None or not callable(getattr(websocket_manager, "broadcast", None)):
        raise HTTPException(status_code=503, detail="Workflow notifications are not ready.")
    return websocket_manager


@router.get("/ready")
async def validation_ready(
    request: Request,
    _: ValidationRuntimeProfile = Depends(_authorize),
) -> dict:
    fixture_service = _fixture_service(request)
    return fixture_service.probe()


@router.get("/probe")
async def validation_probe(
    request: Request,
    _: ValidationRuntimeProfile = Depends(_authorize),
) -> dict:
    return _fixture_service(request).probe()


@router.post("/fixtures/reset")
async def seed_validation_fixtures(
    request: Request,
    _: ValidationRuntimeProfile = Depends(_authorize),
) -> dict:
    return await _fixture_service(request).seed()


@router.post("/fixtures/{fixture_id}/mutate")
async def mutate_validation_fixture(
    fixture_id: str,
    request: Request,
    _: ValidationRuntimeProfile = Depends(_authorize),
) -> dict:
    try:
        mutation = await _fixture_service(request).mutate(fixture_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if fixture_id in {
        ValidationFixtureService.html_fixture_id,
        ValidationFixtureService.local_preview_fixture_id,
    }:
        is_local_preview = fixture_id == ValidationFixtureService.local_preview_fixture_id
        artifact = {
            "artifact_id": (
                ValidationFixtureService.local_preview_artifact_id
                if is_local_preview
                else "validation-report"
            ),
            "display_name": "index.html" if is_local_preview else "report.html",
            "local_path": mutation["path"],
            "artifact_kind": "file",
            "operation": "modify",
            "lifecycle": "verified",
            "preview": {"capability": "unknown"},
            "verification": {
                "status": "verified",
                "summary": (
                    f"Validation local-preview fixture revision {mutation['revision']} is ready."
                    if is_local_preview
                    else f"Validation HTML fixture revision {mutation['revision']} is ready."
                ),
            },
        }
        await broadcast_workflow_notification(
            _workflow_notification_manager(request),
            {
                "event_type": "agent_task_artifact",
                "agent_task_id": fixture_id,
                "root_task_id": fixture_id,
                "agent_task_artifact": artifact,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
    elif fixture_id == ValidationFixtureService.managed_history_fixture_id:
        managed_artifacts = [
            {
                "artifact_id": "validation-managed-history-fixture",
                "display_name": "managed-history-fixture.txt",
                "local_path": mutation["path"],
                "artifact_kind": "file",
                "operation": "modify",
                "lifecycle": "verified",
                "preview": {"capability": "unknown"},
                "verification": {
                    "status": "verified",
                    "summary": f"Validation managed-history text fixture revision {mutation['version']} is ready.",
                },
            },
            {
                "artifact_id": "validation-managed-history-html-fixture",
                "display_name": "managed-history-html-fixture.html",
                "local_path": mutation["htmlPath"],
                "artifact_kind": "file",
                "operation": "modify",
                "lifecycle": "verified",
                "preview": {"capability": "unknown"},
                "verification": {
                    "status": "verified",
                    "summary": f"Validation managed-history HTML fixture revision {mutation['version']} is ready.",
                },
            },
        ]
        for artifact in managed_artifacts:
            await broadcast_workflow_notification(
                _workflow_notification_manager(request),
                {
                    "event_type": "agent_task_artifact",
                    "agent_task_id": fixture_id,
                    "root_task_id": fixture_id,
                    "agent_task_artifact": artifact,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
    return mutation


@router.post("/provider-interactions/{scenario}")
async def start_provider_interaction_validation(
    scenario: str,
    request: Request,
    _: ValidationRuntimeProfile = Depends(_authorize),
) -> dict:
    try:
        return await _fixture_service(request).start_provider_interaction_fixture(
            scenario=scenario,
            routing_service=_agent_task_routing_service(request),
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
