"""Artifact-oriented setup-agent tool handlers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from api.routes.setup_assistant.models import (
    SetupAgentEvent,
    SetupAgentEventKind,
    SetupArtifactKind,
)

from .proposal_tools import build_setup_consent_receipt_payload
from .schemas import SetupProposeConsentReceiptInput


async def open_setup_artifact(
    factory,
    artifact_id: str,
    kind: SetupArtifactKind,
    title: str,
    payload: Optional[Dict[str, Any]] = None,
) -> str:
    await factory.event_emitter(
        SetupAgentEvent(
            kind=SetupAgentEventKind.artifact_opened,
            payload={
                "id": artifact_id,
                "kind": kind.value if isinstance(kind, SetupArtifactKind) else str(kind),
                "title": title,
                "payload": payload or {},
                "rows": [],
                "is_open": True,
            },
        )
    )
    return f"Artifact {artifact_id} opened."


async def add_setup_artifact_row(
    factory,
    artifact_id: str,
    row_id: str,
    payload: Dict[str, Any],
    receipt: Optional[SetupProposeConsentReceiptInput] = None,
) -> str:
    receipt_payload = None
    if receipt is not None:
        receipt_payload = build_setup_consent_receipt_payload(
            factory,
            proposal_id=receipt.proposal_id,
            title=receipt.title,
            rationale=receipt.rationale,
            mutation_tool_name=receipt.mutation_tool_name,
            mutation_payload=receipt.mutation_payload,
            privacy_impact=receipt.privacy_impact,
            mutates_external_state=receipt.mutates_external_state,
            required_permissions=receipt.required_permissions,
        )

    await factory.event_emitter(
        SetupAgentEvent(
            kind=SetupAgentEventKind.artifact_row_added,
            payload={
                "artifact_id": artifact_id,
                "row": {
                    "id": row_id,
                    "payload": payload,
                    "receipt": receipt_payload,
                },
            },
        )
    )
    return f"Artifact row {row_id} added."


async def close_setup_artifact(factory, artifact_id: str) -> str:
    await factory.event_emitter(
        SetupAgentEvent(
            kind=SetupAgentEventKind.artifact_closed,
            payload={"artifact_id": artifact_id},
        )
    )
    return f"Artifact {artifact_id} closed."
