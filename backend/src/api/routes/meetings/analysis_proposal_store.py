"""In-place persistence for suggested-action proposal outcomes.

The suggested-actions ("To-Do Candidates") analysis mode writes a list of
proposals into each saved analysis JSON. When the user starts, dismisses, or
restores a proposal we mutate just that proposal's outcome fields in place so a
reopened analysis reflects what was already handled.

Kept HTTP-agnostic so it can be unit-tested without spinning up FastAPI.
"""

import json
from typing import Any, Dict, Optional

from api.services.meetings.meeting_recorder import MeetingRecorder

from .analysis_summary import ANALYSIS_FILENAME_RE

# Outcome states the client is allowed to persist. Mirrors the local UI states
# in MeetingActionProposalStore; anything else is rejected as a bad request.
PROPOSAL_OUTCOME_STATUSES = {
    "proposed",
    "submitting",
    "submitted",
    "completed",
    "failed",
    "dismissed",
    "added_to_todos",
}


def update_proposal_outcome(
    meeting_id: str,
    filename: str,
    proposal_id: str,
    execution_status: str,
    submitted_agent_task_id: Optional[str],
    todo_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Update one proposal's outcome fields inside a saved analysis file.

    Args:
        meeting_id: Meeting UUID owning the analysis file.
        filename: Analysis filename (analysis_YYYYMMDD_HHMMSS.json).
        proposal_id: Stable backend id of the proposal to update.
        execution_status: New execution status (validated against
            PROPOSAL_OUTCOME_STATUSES).
        submitted_agent_task_id: Delegated agent task id, or None to clear it.

    Returns:
        The updated proposal dict.

    Raises:
        ValueError: filename is malformed or execution_status is not allowed.
        FileNotFoundError: the analysis file does not exist.
        KeyError: no proposal with proposal_id exists in the file.
    """
    if not ANALYSIS_FILENAME_RE.match(filename):
        raise ValueError(f"Invalid analysis filename: {filename}")
    if execution_status not in PROPOSAL_OUTCOME_STATUSES:
        raise ValueError(f"Invalid execution_status: {execution_status}")

    analysis_path = MeetingRecorder.get_meeting_directory(meeting_id) / filename
    if not analysis_path.exists():
        raise FileNotFoundError(
            f"Analysis {filename} not found for meeting {meeting_id}"
        )

    with open(analysis_path, "r") as f:
        data = json.load(f)

    proposals = data.get("suggested_actions") or []
    for proposal in proposals:
        if proposal.get("id") == proposal_id:
            proposal["execution_status"] = execution_status
            proposal["submitted_agent_task_id"] = submitted_agent_task_id
            if todo_id is not None:
                proposal["todo_id"] = todo_id
            with open(analysis_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
            return proposal

    raise KeyError(f"Proposal {proposal_id} not found in {filename}")
