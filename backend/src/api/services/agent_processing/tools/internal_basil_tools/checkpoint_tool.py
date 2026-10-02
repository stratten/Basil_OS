"""
Checkpoint Tool for Agent User Input Requests

Provides a tool that the agent can call when it needs user input or approval
before proceeding with the next steps.
"""

import json
import logging
from typing import Any, Dict, Literal, Optional
from langchain_core.tools import tool

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile

logger = logging.getLogger(__name__)


class CheckpointRequest(Exception):
    """
    Special exception raised when agent requests user input.
    Contains the checkpoint configuration.
    """
    def __init__(self, checkpoint_data: Dict[str, Any]):
        self.checkpoint_data = checkpoint_data
        super().__init__("Agent requested user input")


MAX_CHECKPOINT_ID_BYTES = 128
MAX_CHECKPOINT_METADATA_BYTES = 2_000


def _validate_checkpoint_extensions(
    checkpoint_id: Optional[str],
    metadata: Optional[Dict[str, Any]],
) -> None:
    if checkpoint_id is not None:
        if not isinstance(checkpoint_id, str) or not checkpoint_id.strip():
            raise ValueError("checkpoint_id must be a nonblank string")
        if len(checkpoint_id.strip().encode("utf-8")) > MAX_CHECKPOINT_ID_BYTES:
            raise ValueError(
                f"checkpoint_id must not exceed {MAX_CHECKPOINT_ID_BYTES} UTF-8 bytes"
            )
    if metadata is not None:
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        serialized = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        if len(serialized.encode("utf-8")) > MAX_CHECKPOINT_METADATA_BYTES:
            raise ValueError(
                f"metadata must not exceed {MAX_CHECKPOINT_METADATA_BYTES} UTF-8 bytes"
            )


@tool
def request_user_input(
    prompt: str,
    input_type: Literal[
        "text",
        "yes_no",
        "selection",
        "choice",
        "numeric",
        "voice",
    ] = "text",
    options: Optional[list] = None,
    context_summary: Optional[str] = None,
    checkpoint_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    allow_multiple: bool = False,
) -> str:
    """
    Request input or approval from the user before proceeding.
    
    Use this tool when you need:
    - User approval to proceed with a risky operation
    - User choice between multiple options
    - User clarification or refinement of requirements
    - User confirmation of generated content before sending

    Do not use this tool to ask for information that available tools can
    determine. If a tool family must be loaded to inspect the state (for
    example browser tabs, files, email, or app activity), load and use those
    tools first. Request user input only when inspection still leaves a real
    user-owned choice, approval, secret, permission repair, CAPTCHA, or
    destructive/irreversible decision.
    
    Args:
        prompt: Clear question or prompt for the user (e.g. "Should I proceed with sending this email?")
        input_type: Type of input expected - "text", "yes_no", "selection", "choice", "numeric", or "voice".
            Use "selection" or "choice" (with options) for a finite set of concrete choices; the UI renders
            these as clickable cards. Use "yes_no" for binary approval. Use "text" only for
            open-ended answers. The UI does not turn prompt-text lists into choices — only
            structured options become cards.
        options: Concise, user-facing labels when input_type is "selection" (e.g. ["Option A",
            "Option B"]). Keep each a few words; put shared context in prompt, not in options.
            Do not add an "Other" option; the UI always offers a typed Other answer.
        context_summary: Brief summary of what's been done so far to provide context
        allow_multiple: Set True only with "selection" or "choice" when the user may reasonably pick several options at once (for example, which reports to include). Leave False when exactly one answer drives the next step.
        
    Returns:
        The user's reply. A single pick arrives as the bare option value. Several picks, or a pick plus typed text, arrive as "Selected: A; B" and/or "Other: <typed text>" on separate lines. Act on every selected option, and treat "Other:" text as the user's own answer or as an added instruction that refines the selection.
        
    Examples:
        - request_user_input("Should I send this draft email?", "yes_no")
        - request_user_input("Which client should I prioritize?", "selection", ["Client A", "Client B", "Client C"])
        - request_user_input("Which reports should I include?", "selection", ["Sales", "Support", "Operations"], allow_multiple=True)
        - request_user_input("How many emails should I process?", "numeric")
        - request_user_input("Any changes to the draft before I save it?", "text")
    """
    _validate_checkpoint_extensions(checkpoint_id, metadata)
    checkpoint_data = {
        "checkpoint_id": checkpoint_id,
        "prompt": prompt,
        "input_type": input_type,
        "options": options or [],
        "allow_multiple": bool(allow_multiple) and input_type in ("selection", "choice"),
        "context_summary": context_summary or "",
        "metadata": metadata or {},
        "step_type": "user_input_request",
    }
    
    logger.info(f"🛑 Agent requesting user input: {prompt}")
    
    # Raise special exception that will be caught by workflow coordinator
    # The coordinator will:
    # 1. Send WebSocket checkpoint event to frontend
    # 2. Wait for user response via API
    # 3. Resume execution with user's response
    raise CheckpointRequest(checkpoint_data)


# Why this slim:
# - KEEPS: purpose (pause + wait for user reply), the four discriminating
#   use cases (approval / choice / clarification / pre-send confirmation),
#   and the load-bearing behavioral hint that the return is the USER'S
#   reply (so the agent must not call this just to insert its own commentary).
# - DROPS: per-arg explanations (the schema's Literal enum + Pydantic
#   descriptions cover input_type, options, context_summary), code examples,
#   verbose framing prose. The signature is rendered from the args_schema.
SLIM_DESCRIPTION = (
    "Pause execution and wait for the user to respond via UI; use for approvals, "
    "multiple-choice, clarifications, numeric inputs, or pre-send confirmation; "
    "do not use for state that tools can inspect after loading the right family; "
    "set allow_multiple=true with selection when several options may apply; "
    "the UI always offers a typed Other answer, and replies may read "
    "'Selected: A; B' and/or 'Other: <text>'; "
    "returns the user's reply (do NOT call to insert your own commentary)."
)


def create_checkpoint_tool(profile=None):
    """Factory function to create the checkpoint tool.

    Under a slim rendering profile the description is swapped to the
    hand-authored ``SLIM_DESCRIPTION`` companion above; otherwise the
    full ``@tool`` docstring flows through unchanged. The swap is done via
    Pydantic v2 ``model_copy(update={...})`` so the shared module-level
    ``request_user_input`` tool is never mutated.
    """
    full_description = request_user_input.description or ""
    chosen_description = select_description_for_profile(
        profile, full_description, SLIM_DESCRIPTION
    )
    if chosen_description == full_description:
        return request_user_input
    return request_user_input.model_copy(update={"description": chosen_description})

