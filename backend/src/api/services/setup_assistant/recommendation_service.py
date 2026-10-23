"""Validation helpers for setup-agent proposals."""

from __future__ import annotations

from typing import Any

from api.routes.setup_assistant.models import (
    SetupAgentContractResponse,
    SetupAgentModelPost,
    SetupAgentOutput,
    SetupAgentValidationResponse,
    SetupDiscoveryFact,
    SetupToolApprovalState,
)


SETUP_AGENT_SYSTEM_PROMPT = "Basil setup now runs through the LangChain setup-agent runtime."


class SetupAgentValidationError(ValueError):
    """Structured validation failure suitable for setup-agent callers."""

    def __init__(self, message: str, feedback: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.feedback = feedback


class SetupAssistantRecommendationService:
    """Validate setup proposal contracts without synthesizing recommendations."""

    def build_setup_agent_contract(self) -> SetupAgentContractResponse:
        return SetupAgentContractResponse(
            system_prompt=SETUP_AGENT_SYSTEM_PROMPT,
            required_output_schema=SetupAgentOutput.model_json_schema(),
            validation_rules=[
                "Setup intelligence is emitted through LangChain tools.",
                "Mutating setup proposals must remain pending until approved by the user.",
                "Tool calls must start proposed or approved.",
            ],
        )

    def validate_setup_agent_model_post(
        self,
        payload: dict[str, Any],
        discovery_facts: list[SetupDiscoveryFact] | None = None,
    ) -> SetupAgentModelPost:
        try:
            model_post = SetupAgentModelPost.validate_model_post(payload)
            self.validate_setup_agent_output(model_post.output, discovery_facts=discovery_facts)
            return model_post
        except Exception as exc:
            raise SetupAgentValidationError(
                "Setup agent model post failed validation.",
                self._build_validation_feedback(exc),
            ) from exc

    def validate_setup_agent_output(
        self,
        output: SetupAgentOutput,
        discovery_facts: list[SetupDiscoveryFact] | None = None,
    ) -> SetupAgentValidationResponse:
        self._validate_unique_ids("tool call", [tool_call.id for tool_call in output.tool_calls])
        self._validate_unique_ids("inline receipt", [receipt.id for receipt in output.inline_receipts])
        self._validate_unique_ids("artifact", [artifact.id for artifact in output.artifacts])

        for tool_call in output.tool_calls:
            if tool_call.approval_state not in {
                SetupToolApprovalState.proposed,
                SetupToolApprovalState.approved,
            }:
                raise ValueError(f"Tool call '{tool_call.id}' must start proposed or approved.")

        for receipt in output.inline_receipts:
            if receipt.approval_state != SetupToolApprovalState.proposed:
                raise ValueError(f"Receipt '{receipt.id}' must start proposed.")

        return SetupAgentValidationResponse(valid=True, output=output)

    def _build_validation_feedback(self, exc: Exception) -> list[dict[str, Any]]:
        errors = getattr(exc, "errors", None)
        if callable(errors):
            return [
                {
                    "location": ".".join(str(part) for part in error.get("loc", [])) or "response",
                    "message": str(error.get("msg", "Invalid value.")),
                    "expected": str(error.get("type", "valid setup proposal schema")),
                }
                for error in errors()[:12]
            ]

        return [
            {
                "location": "response",
                "message": str(exc),
                "expected": "valid setup proposal schema",
            }
        ]

    def _validate_unique_ids(self, label: str, ids: list[str]) -> None:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for item_id in ids:
            if item_id in seen:
                duplicates.add(item_id)
            seen.add(item_id)
        if duplicates:
            raise ValueError(f"Duplicate {label} ids: {', '.join(sorted(duplicates))}")

