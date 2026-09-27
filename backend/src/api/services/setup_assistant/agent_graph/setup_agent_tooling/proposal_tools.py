"""Proposal-oriented setup-agent tool handlers."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from api.routes.setup_assistant.models import (
    SetupAgentEvent,
    SetupAgentEventKind,
    SetupConsentReceipt,
    SetupPrivacyImpact,
    SetupToolApprovalState,
    SetupToolCall,
)


async def propose_setup_mutation(
    factory,
    title: str,
    rationale: str,
    tool_name: str,
    payload: Dict[str, Any],
    proposal_id: Optional[str] = None,
    privacy_impact: SetupPrivacyImpact = SetupPrivacyImpact.none,
    mutates_external_state: bool = False,
    required_permissions: Optional[List[str]] = None,
) -> str:
    validate_setup_tool_name(factory, tool_name)
    payload = _stamp_setup_model_id_for_launch(factory, tool_name, payload)
    payload = _stamp_setup_source_email_id_for_launch(factory, tool_name, payload)
    resolved_proposal_id = proposal_id or f"proposal-{uuid.uuid4().hex[:12]}"
    tool_call = factory.proposal_store.record_pending_setup_proposal(
        SetupToolCall(
            id=resolved_proposal_id,
            tool_name=tool_name,
            payload=payload,
            approval_state=SetupToolApprovalState.proposed,
            user_visible_summary=title,
            privacy_impact=privacy_impact,
            mutates_external_state=mutates_external_state,
            required_permissions=required_permissions or [],
        )
    )
    receipt = SetupConsentReceipt(
        id=f"receipt-{resolved_proposal_id}",
        proposal_id=resolved_proposal_id,
        title=title,
        rationale=rationale,
        tool_call=tool_call,
        approval_state=SetupToolApprovalState.proposed,
    )
    await factory.event_emitter(
        SetupAgentEvent(
            kind=SetupAgentEventKind.inline_receipt_added,
            payload={"receipt": receipt.model_dump(mode="json")},
        )
    )
    return f"Proposal {resolved_proposal_id} is ready for user review."


async def propose_setup_consent_receipt(
    factory,
    title: str,
    rationale: str,
    mutation_tool_name: str,
    mutation_payload: Dict[str, Any],
    proposal_id: Optional[str] = None,
    privacy_impact: SetupPrivacyImpact = SetupPrivacyImpact.none,
    mutates_external_state: bool = False,
    required_permissions: Optional[List[str]] = None,
) -> str:
    return await propose_setup_mutation(
        factory,
        proposal_id=proposal_id,
        title=title,
        rationale=rationale,
        tool_name=mutation_tool_name,
        payload=mutation_payload,
        privacy_impact=privacy_impact,
        mutates_external_state=mutates_external_state,
        required_permissions=required_permissions,
    )


def build_setup_consent_receipt_payload(
    factory,
    *,
    proposal_id: Optional[str],
    title: str,
    rationale: str,
    mutation_tool_name: str,
    mutation_payload: Dict[str, Any],
    privacy_impact: SetupPrivacyImpact,
    mutates_external_state: bool,
    required_permissions: List[str],
) -> Dict[str, Any]:
    validate_setup_tool_name(factory, mutation_tool_name)
    mutation_payload = _stamp_setup_model_id_for_launch(
        factory, mutation_tool_name, mutation_payload
    )
    mutation_payload = _stamp_setup_source_email_id_for_launch(
        factory, mutation_tool_name, mutation_payload
    )
    resolved_proposal_id = proposal_id or f"proposal-{uuid.uuid4().hex[:12]}"
    tool_call = factory.proposal_store.record_pending_setup_proposal(
        SetupToolCall(
            id=resolved_proposal_id,
            tool_name=mutation_tool_name,
            payload=mutation_payload,
            approval_state=SetupToolApprovalState.proposed,
            user_visible_summary=title,
            privacy_impact=privacy_impact,
            mutates_external_state=mutates_external_state,
            required_permissions=required_permissions,
        )
    )
    return SetupConsentReceipt(
        id=f"receipt-{resolved_proposal_id}",
        proposal_id=resolved_proposal_id,
        title=title,
        rationale=rationale,
        tool_call=tool_call,
        approval_state=SetupToolApprovalState.proposed,
    ).model_dump(mode="json")


def validate_setup_tool_name(factory, tool_name: str) -> None:
    available_tool_names = {
        tool.name for tool in factory.context_catalog_service.build_available_tools()
    }
    if tool_name not in available_tool_names:
        raise ValueError(f"Setup tool '{tool_name}' is not available for approval.")


# Setup-launched task tools that inherit the setup agent's chosen model and
# the most recently pulled email id. Both Paprika (launch_agent_task) and Dill
# (launch_assistant_session) launches originated from setup go through this
# stamping path so they share the same route inheritance and email-grounding
# contract — without it, a Dill draft proposed from setup would silently fall
# back to the user's preferred reasoning model (potentially overflowing a
# local model) and would skip the source-email-id grounding that lets the
# downstream draft pipeline fetch the full body instead of improvising.
_SETUP_LAUNCH_TOOL_NAMES = frozenset({"launch_agent_task", "launch_assistant_session"})


def _stamp_setup_model_id_for_launch(
    factory,
    tool_name: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Ensure setup-launched task receipts carry the setup agent's current model.

    Applies to ``launch_agent_task`` (Paprika) and ``launch_assistant_session``
    (Dill). Launches originated from setup must inherit the route the setup
    agent itself is using (default = free proxy), so a user whose preferred
    reasoning model is local does not silently overflow that local model
    during onboarding. We only stamp when the agent has not already supplied
    its own model_id, so explicit overrides are honored.

    Defense in depth: if neither the agent nor the runtime supplied a model_id,
    we refuse to record the proposal rather than let it reach the user with a
    silent fallback to whatever reasoning model happens to be preferred.
    """
    if tool_name not in _SETUP_LAUNCH_TOOL_NAMES:
        return payload
    existing = payload.get("model_id")
    if isinstance(existing, str) and existing.strip():
        return payload
    selection = getattr(factory, "setup_model_selection", None)
    selection_model_id = getattr(selection, "model_id", None) if selection else None
    if not isinstance(selection_model_id, str) or not selection_model_id.strip():
        raise ValueError(
            f"Cannot stamp model_id onto {tool_name} receipt: "
            "setup_model_selection is unavailable on the tool factory. "
            "The setup runtime must pass setup_model_selection into "
            "SetupAgentToolFactory at turn build time so launch-from-setup "
            "tasks inherit the setup agent's chosen route."
        )
    stamped = dict(payload)
    stamped["model_id"] = selection_model_id
    return stamped


def _stamp_setup_source_email_id_for_launch(
    factory,
    tool_name: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Ensure setup-launched task receipts carry the email id when one was pulled.

    Applies to ``launch_agent_task`` (Paprika) and ``launch_assistant_session``
    (Dill). When the setup agent ran ``pull_inbox_email_for_dill`` earlier in
    the same turn, ``SetupAgentToolFactory.last_pulled_email_id`` is set. A
    follow-up launch proposal should be grounded in that exact message so
    the downstream route can fetch the full body, not improvise a
    hypothetical. We honor any ``source_email_id`` the agent itself put on
    the payload and only stamp when missing — and we are permissive: if no
    email was pulled this turn we leave the payload alone (some launch
    receipts are not email-grounded).
    """
    if tool_name not in _SETUP_LAUNCH_TOOL_NAMES:
        return payload
    existing = payload.get("source_email_id")
    if isinstance(existing, str) and existing.strip():
        return payload
    pulled_id = getattr(factory, "last_pulled_email_id", None)
    if not isinstance(pulled_id, str) or not pulled_id.strip():
        return payload
    stamped = dict(payload)
    stamped["source_email_id"] = pulled_id
    return stamped
