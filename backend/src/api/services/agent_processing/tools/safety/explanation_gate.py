"""One-time request for the agent to explain a command before the user is asked to approve it."""

from typing import Any, Mapping

from .whitelist_eligibility import normalize_purpose

EXPLANATION_REQUIRED_STATUS = "explanation_required"

EXPLANATION_REQUIRED_MESSAGE = (
    "This command needs the user's approval, and the approval card must say what it does. "
    "Call the same tool again with `purpose` (one or two plain sentences on what this command or script does and why) "
    "and `whitelist_advice` ({\"recommend\": true or false, \"reason\": \"...\"}) on whether the user should let Basil remember it. "
    "The user was not asked yet and nothing was denied."
)

_MAX_TRACKED = 2000
_already_requested: set[tuple[str, str]] = set()


def should_request_explanation(command: str, context: Mapping[str, Any]) -> bool:
    """Return True once per task and command when a caller that must explain itself did not.

    The second attempt returns False so the approval is shown with a notice instead of looping.
    """
    if not context.get("purpose_required") or normalize_purpose(context.get("purpose")) is not None:
        return False
    task_id = context.get("agent_task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        return False
    key = (task_id.strip(), command)
    if key in _already_requested:
        return False
    if len(_already_requested) >= _MAX_TRACKED:
        _already_requested.clear()
    _already_requested.add(key)
    return True
