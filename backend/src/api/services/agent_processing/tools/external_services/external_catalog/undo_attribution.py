"""Keeps the agent from reversing a mailbox change that Basil never made.

The user often works in the same mailbox while a task runs: archiving, trashing, or moving mail by hand. The agent then finds things "not as it left them" and may try to put them back, undoing the user's own work.

A restoration tool (``untrash_thread``, ``unmark_message_spam``, ...) is only an undo of Basil's own mistake when Basil earlier made the matching change. Every successful Gmail call Basil makes is already recorded in ``mcp_call_log`` with its arguments, so the check is a lookup: did Basil trash, or mark as spam, this exact thread or message, and has it not already been restored since?

The check covers only tools that are restorations by nature. ``label_thread`` and ``unlabel_thread`` are ordinary forward operations in both directions, so no call can be called an undo from its name alone; the agent's instructions cover those.

This is guidance for the agent, not a security gate: an unreadable call log lets the call proceed, and the approval prompt for the tool still applies. A call the user explicitly asked for passes by setting ``userRequested``, and that flag is removed before the call reaches Gmail.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from api.services.mcp_connectors.oauth_coordinator import is_google_gmail_mcp_url

from .envelopes import make_external_catalog_not_attributed

logger = logging.getLogger(__name__)

USER_REQUESTED_ARGUMENT = "userRequested"


@dataclass(frozen=True)
class _Forward:
    """A recorded call that makes the change a restoration reverses; ``label_option`` narrows the sensitive-label tools."""

    tool_name: str
    label_option: Optional[str] = None


@dataclass(frozen=True)
class _Restoration:
    item_argument: str
    same_item_forwards: Tuple[_Forward, ...]
    # A thread-wide change and a message-level restoration (or the reverse) name different ids, and Gmail ids cannot be mapped between them here. A change at the other level made by this same task is accepted as Basil's own.
    other_level_forwards: Tuple[_Forward, ...]


_RESTORATIONS: Dict[str, _Restoration] = {
    "untrash_thread": _Restoration(
        "threadId",
        (_Forward("trash_thread"), _Forward("apply_sensitive_thread_label", "TRASH")),
        (_Forward("trash_message"), _Forward("apply_sensitive_message_label", "TRASH")),
    ),
    "untrash_message": _Restoration(
        "messageId",
        (_Forward("trash_message"), _Forward("apply_sensitive_message_label", "TRASH")),
        (_Forward("trash_thread"), _Forward("apply_sensitive_thread_label", "TRASH")),
    ),
    "unmark_thread_spam": _Restoration(
        "threadId",
        (_Forward("mark_thread_spam"), _Forward("apply_sensitive_thread_label", "SPAM")),
        (_Forward("mark_message_spam"), _Forward("apply_sensitive_message_label", "SPAM")),
    ),
    "unmark_message_spam": _Restoration(
        "messageId",
        (_Forward("mark_message_spam"), _Forward("apply_sensitive_message_label", "SPAM")),
        (_Forward("mark_thread_spam"), _Forward("apply_sensitive_thread_label", "SPAM")),
    ),
}


def _tool_names(forwards: Tuple[_Forward, ...]) -> List[str]:
    return sorted({forward.tool_name for forward in forwards})


def _calls_matching(calls: List[Dict[str, Any]], forwards: Tuple[_Forward, ...]) -> List[Dict[str, Any]]:
    matching: List[Dict[str, Any]] = []
    for call in calls:
        arguments = call.get("arguments") or {}
        for forward in forwards:
            if call.get("tool_name") != forward.tool_name:
                continue
            if forward.label_option is not None and arguments.get("labelOption") != forward.label_option:
                continue
            matching.append(call)
            break
    return matching


def _latest_started_at(calls: List[Dict[str, Any]]) -> Optional[str]:
    started = [str(call["started_at"]) for call in calls if call.get("started_at")]
    return max(started) if started else None


def _current_agent_task_id() -> Optional[str]:
    try:
        from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context

        context = get_current_agent_context()
        task_id = context.get("agent_task_id") if isinstance(context, dict) else None
        return task_id if isinstance(task_id, str) and task_id else None
    except Exception:
        return None


def _default_call_log_repository() -> Any:
    from api.dependencies import get_sqlite_knowledge_service

    return get_sqlite_knowledge_service().mcp_call_log_repository


async def _basil_made_the_change(
    repo: Any,
    connection_id: str,
    tool_name: str,
    spec: _Restoration,
    item_id: str,
    agent_task_id: Optional[str],
) -> bool:
    forward_calls = await repo.list_successful_calls_for_item(
        connection_id, _tool_names(spec.same_item_forwards), spec.item_argument, item_id
    )
    latest_forward = _latest_started_at(_calls_matching(forward_calls, spec.same_item_forwards))
    if latest_forward is None and agent_task_id:
        other_level_calls = await repo.list_successful_calls_for_task(
            connection_id, _tool_names(spec.other_level_forwards), agent_task_id
        )
        latest_forward = _latest_started_at(_calls_matching(other_level_calls, spec.other_level_forwards))
    if latest_forward is None:
        return False
    restore_calls = await repo.list_successful_calls_for_item(connection_id, [tool_name], spec.item_argument, item_id)
    latest_restore = _latest_started_at(restore_calls)
    # A change Basil already reversed is not Basil's to reverse again.
    return latest_restore is None or latest_forward > latest_restore


async def check_restoration_attribution(
    record: Any,
    tool_name: str,
    arguments: Dict[str, Any],
    *,
    agent_task_id: Optional[str] = None,
    repo: Any = None,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Return the arguments to dispatch and, when the call must be refused, the refusal envelope.

    The returned arguments never carry ``userRequested``. Anything that is not a Gmail restoration tool passes through untouched.
    """
    spec = _RESTORATIONS.get(tool_name)
    if spec is None or not isinstance(arguments, dict) or not is_google_gmail_mcp_url(getattr(record, "server_url", "") or ""):
        return arguments, None
    cleaned = {key: value for key, value in arguments.items() if key != USER_REQUESTED_ARGUMENT}
    if arguments.get(USER_REQUESTED_ARGUMENT) is True:
        return cleaned, None
    item_id = arguments.get(spec.item_argument)
    if not isinstance(item_id, str) or not item_id.strip():
        # The connector reports a missing id with its own, clearer message.
        return cleaned, None
    try:
        attributed = await _basil_made_the_change(
            repo if repo is not None else _default_call_log_repository(),
            record.id,
            tool_name,
            spec,
            item_id.strip(),
            agent_task_id if agent_task_id is not None else _current_agent_task_id(),
        )
    except Exception as exc:
        logger.warning("Could not check whether Basil made the change %s would reverse; allowing the call: %s", tool_name, exc)
        return cleaned, None
    if attributed:
        return cleaned, None
    return cleaned, make_external_catalog_not_attributed(tool_name)
