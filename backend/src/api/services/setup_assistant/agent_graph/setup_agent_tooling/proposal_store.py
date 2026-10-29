"""In-memory setup proposal storage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from api.routes.setup_assistant.models import SetupToolApprovalState, SetupToolCall


@dataclass
class SetupPendingProposalStore:
    """In-memory proposal store for the active setup session."""

    proposals: Dict[str, SetupToolCall] = field(default_factory=dict)

    def record_pending_setup_proposal(self, tool_call: SetupToolCall) -> SetupToolCall:
        self.proposals[tool_call.id] = tool_call
        return tool_call

    def get_pending_setup_proposal(self, proposal_id: str) -> Optional[SetupToolCall]:
        return self.proposals.get(proposal_id)

    def update_setup_proposal_state(
        self,
        proposal_id: str,
        approval_state: SetupToolApprovalState,
    ) -> Optional[SetupToolCall]:
        tool_call = self.proposals.get(proposal_id)
        if tool_call is None:
            return None
        updated = tool_call.model_copy(update={"approval_state": approval_state})
        self.proposals[proposal_id] = updated
        return updated
