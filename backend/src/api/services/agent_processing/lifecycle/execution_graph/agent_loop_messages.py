"""Convert the inner agent loop's message list to Basil's step, output, and checkpoint shapes."""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

from langchain_core.agents import AgentAction
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
    messages_from_dict,
    messages_to_dict,
)

from .agent_result_synthesis import normalize_agent_executor_output

logger = logging.getLogger(__name__)

INTERRUPTED_TOOL_CALL_RESULT = (
    "This call was interrupted when the task paused for user input; its result was not recorded. "
    "Check whether it took effect before running it again."
)
EMPTY_RESUME_INPUT = "The user gave no response."


def ai_message_text(message: Any) -> str:
    if not isinstance(message, AIMessage):
        return ""
    text = message.text
    if isinstance(text, str):
        return text.strip()
    return normalize_agent_executor_output(message.content).strip()


def tool_message_text(message: ToolMessage) -> str:
    content = message.content
    return content if isinstance(content, str) else normalize_agent_executor_output(content)


def tool_call_log(tool_name: str, tool_input: Any, text: str) -> str:
    content_line = f"responded: {text}\n" if text else "\n"
    return f"\nInvoking: `{tool_name}` with `{tool_input}`\n{content_line}\n"


def tool_call_action(call: dict[str, Any], text: str) -> AgentAction:
    tool_name = str(call.get("name") or "")
    args = call.get("args")
    tool_input = args if isinstance(args, dict) else {}
    return AgentAction(tool=tool_name, tool_input=tool_input, log=tool_call_log(tool_name, tool_input, text))


def messages_to_intermediate_steps(messages: Sequence[BaseMessage]) -> list[tuple[AgentAction, str]]:
    """Pair each answered tool call with its result; calls without a result are skipped."""
    results_by_call_id = {
        str(message.tool_call_id): message
        for message in messages
        if isinstance(message, ToolMessage) and message.tool_call_id
    }
    steps: list[tuple[AgentAction, str]] = []
    for message in messages:
        if not isinstance(message, AIMessage) or not message.tool_calls:
            continue
        text = ai_message_text(message)
        for call in message.tool_calls:
            result = results_by_call_id.get(str(call.get("id") or ""))
            if result is not None:
                steps.append((tool_call_action(call, text), tool_message_text(result)))
    return steps


def final_agent_output(messages: Sequence[BaseMessage]) -> str:
    """Return the model's closing text, or the last tool result when a return_direct tool ended the loop."""
    for message in reversed(list(messages)):
        if isinstance(message, AIMessage):
            return "" if message.tool_calls else ai_message_text(message)
        if isinstance(message, ToolMessage):
            return tool_message_text(message)
        if isinstance(message, HumanMessage):
            return ""
    return ""


def first_human_text(messages: Sequence[BaseMessage]) -> str:
    for message in messages:
        if isinstance(message, HumanMessage):
            content = message.content
            return content if isinstance(content, str) else normalize_agent_executor_output(content)
    return ""


def count_ai_messages(messages: Sequence[BaseMessage]) -> int:
    return sum(1 for message in messages if isinstance(message, AIMessage))


def serialize_agent_messages(messages: Sequence[BaseMessage]) -> list[dict[str, Any]]:
    return messages_to_dict(list(messages))


def deserialize_agent_messages(serialized: Any) -> list[BaseMessage]:
    if not isinstance(serialized, list):
        return []
    try:
        return list(messages_from_dict([item for item in serialized if isinstance(item, dict)]))
    except Exception:
        logger.warning("Could not rebuild the paused agent conversation", exc_info=True)
        return []


def seed_resumed_messages(
    serialized: Any,
    resume_input: str,
    pending_tool_call_id: Optional[str],
) -> list[BaseMessage]:
    """Rebuild a paused conversation and answer the tool call that paused it with ``resume_input``.

    Other calls from the same model turn get an explicit "interrupted" result, because their results were lost when the pause ended the step. When no call is pending, the resume text becomes a new user message.
    """
    messages = deserialize_agent_messages(serialized)
    if not messages:
        return []
    resume_text = resume_input.strip() or EMPTY_RESUME_INPUT
    answered_ids = {str(message.tool_call_id) for message in messages if isinstance(message, ToolMessage)}
    last_ai = next((message for message in reversed(messages) if isinstance(message, AIMessage)), None)
    unanswered = [
        call
        for call in (last_ai.tool_calls if last_ai is not None else [])
        if str(call.get("id") or "") not in answered_ids
    ]
    if not unanswered:
        messages.append(HumanMessage(content=resume_text))
        return messages
    unanswered_ids = [str(call.get("id") or "") for call in unanswered]
    target_id = str(pending_tool_call_id) if str(pending_tool_call_id) in unanswered_ids else unanswered_ids[0]
    for call, call_id in zip(unanswered, unanswered_ids):
        messages.append(
            ToolMessage(
                content=resume_text if call_id == target_id else INTERRUPTED_TOOL_CALL_RESULT,
                tool_call_id=call_id,
                name=str(call.get("name") or ""),
            )
        )
    return messages


def is_pause_request(error: BaseException) -> bool:
    from api.services.agent_providers.targeting.delegation_service import ProviderDelegationWaitRequest

    from ...tools.internal_basil_tools.checkpoint_tool import CheckpointRequest

    return isinstance(error, (CheckpointRequest, ProviderDelegationWaitRequest))
