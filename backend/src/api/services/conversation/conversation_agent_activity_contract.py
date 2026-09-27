"""Privacy-safe payload contract for Conversation-linked Agent Task activity."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final


MAX_CONVERSATION_AGENT_ACTIVITY_TEXT_CHARS: Final = 240
MAX_CONVERSATION_AGENT_ACTIVITY_IDENTIFIER_CHARS: Final = 256
MAX_CONVERSATION_AGENT_ACTIVITY_ARTIFACTS: Final = 6

_AGENT_TASK_LIFECYCLES: Final = frozenset({
    "capturing",
    "routing",
    "routed",
    "processing",
    "awaiting_provider_delegation",
    "awaiting_delegated_agents",
    "awaiting_user_input",
    "waiting_user_input",
    "needs_clarification",
    "clarification_added",
    "completed",
    "failed",
    "cancelled",
})
_ARTIFACT_KINDS: Final = frozenset({"file", "directory", "unknown"})
_ARTIFACT_LIFECYCLES: Final = frozenset({
    "discovered",
    "ready",
    "verified",
    "failed",
    "unavailable",
})
_ARTIFACT_VERIFICATION_STATUSES: Final = frozenset({
    "not_applicable",
    "pending",
    "verified",
    "failed",
    "unknown",
})
_SUMMARY_VERIFICATION_STATUSES: Final = frozenset({"pending", "resolved", "unknown"})


def _require_identifier(field_name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > MAX_CONVERSATION_AGENT_ACTIVITY_IDENTIFIER_CHARS:
        raise ValueError(f"{field_name} exceeds the identifier limit")
    return normalized


def _require_enum(field_name: str, value: Any, allowed_values: frozenset[str]) -> str:
    normalized = _require_identifier(field_name, value)
    if normalized not in allowed_values:
        raise ValueError(f"{field_name} is not supported")
    return normalized


def _optional_bounded_text(field_name: str, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string when provided")
    normalized = value.strip()
    return normalized[:MAX_CONVERSATION_AGENT_ACTIVITY_TEXT_CHARS] or None


def _require_non_negative_integer(field_name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _project_workflow(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise ValueError("summary.workflow must be an object")
    has_completed = "completed_steps" in value
    has_total = "total_steps" in value
    if not has_completed and not has_total:
        return {}
    if not has_completed or not has_total:
        raise ValueError("summary.workflow must provide both step counts")
    completed_steps = _require_non_negative_integer(
        "summary.workflow.completed_steps",
        value["completed_steps"],
    )
    total_steps = _require_non_negative_integer(
        "summary.workflow.total_steps",
        value["total_steps"],
    )
    if completed_steps > total_steps:
        raise ValueError("summary.workflow.completed_steps cannot exceed total_steps")
    return {"completed_steps": completed_steps, "total_steps": total_steps}


def _project_artifact(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("summary.artifacts entries must be objects")
    verification = value.get("verification")
    if not isinstance(verification, Mapping):
        raise ValueError("summary.artifacts[].verification must be an object")
    display_name = _optional_bounded_text("summary.artifacts[].display_name", value.get("display_name"))
    if display_name is None:
        raise ValueError("summary.artifacts[].display_name must be a non-empty string")
    return {
        "artifact_id": _require_identifier("summary.artifacts[].artifact_id", value.get("artifact_id")),
        "display_name": display_name,
        "artifact_kind": _require_enum(
            "summary.artifacts[].artifact_kind",
            value.get("artifact_kind"),
            _ARTIFACT_KINDS,
        ),
        "lifecycle": _require_enum(
            "summary.artifacts[].lifecycle",
            value.get("lifecycle"),
            _ARTIFACT_LIFECYCLES,
        ),
        "verification": {
            "status": _require_enum(
                "summary.artifacts[].verification.status",
                verification.get("status"),
                _ARTIFACT_VERIFICATION_STATUSES,
            )
        },
    }


def _project_summary(agent_task_id: str, summary: Any) -> dict[str, Any]:
    if not isinstance(summary, Mapping):
        raise ValueError("summary must be an object")
    if _require_identifier("summary.agent_task_id", summary.get("agent_task_id")) != agent_task_id:
        raise ValueError("summary.agent_task_id must match agent_task_id")
    artifacts = summary.get("artifacts")
    if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes, bytearray)):
        raise ValueError("summary.artifacts must be an array")
    if len(artifacts) > MAX_CONVERSATION_AGENT_ACTIVITY_ARTIFACTS:
        raise ValueError("summary.artifacts exceeds the artifact limit")
    projected_artifacts = [_project_artifact(artifact) for artifact in artifacts]
    artifact_count = _require_non_negative_integer("summary.artifact_count", summary.get("artifact_count"))
    if artifact_count < len(projected_artifacts):
        raise ValueError("summary.artifact_count cannot be less than emitted artifacts")
    requires_user_attention = summary.get("requires_user_attention")
    if not isinstance(requires_user_attention, bool):
        raise ValueError("summary.requires_user_attention must be a boolean")
    projected = {
        "agent_task_id": agent_task_id,
        "lifecycle": _require_enum("summary.lifecycle", summary.get("lifecycle"), _AGENT_TASK_LIFECYCLES),
        "workflow": _project_workflow(summary.get("workflow")),
        "artifacts": projected_artifacts,
        "artifact_count": artifact_count,
        "verification_status": _require_enum(
            "summary.verification_status",
            summary.get("verification_status"),
            _SUMMARY_VERIFICATION_STATUSES,
        ),
        "requires_user_attention": requires_user_attention,
    }
    latest_activity = _optional_bounded_text("summary.latest_activity", summary.get("latest_activity"))
    if latest_activity is not None:
        projected["latest_activity"] = latest_activity
    return projected


def build_conversation_agent_activity_payload(
    *,
    conversation_id: str,
    placeholder_message_id: str,
    agent_task_id: str,
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a selected activity event without exposing Agent Task-only fields."""
    normalized_agent_task_id = _require_identifier("agent_task_id", agent_task_id)
    return {
        "event_type": "conversation_agent_activity",
        "conversation_id": _require_identifier("conversation_id", conversation_id),
        "placeholder_message_id": _require_identifier(
            "placeholder_message_id",
            placeholder_message_id,
        ),
        "agent_task_id": normalized_agent_task_id,
        "summary": _project_summary(normalized_agent_task_id, summary),
    }
