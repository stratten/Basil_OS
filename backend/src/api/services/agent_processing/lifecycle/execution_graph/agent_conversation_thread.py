"""Store each agent task's model conversation and replay it into the next turn of the chain."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from api.core.logging.api_logger import api_logger

from .agent_loop_messages import deserialize_agent_messages, serialize_agent_messages
from .conversation_turns import (
    CURRENT_REQUEST_MARKER,
    clip_text,
    is_turn_input,
    mark_turn_input,
    message_text,
    request_text,
)

logger = api_logger.getChild("agent_conversation_thread")

THREAD_FORMAT_VERSION = 1
NEUTRAL_MODEL_FAMILY = "neutral"
MAX_STORED_TOOL_RESULT_CHARS = 12_000
MAX_STORED_THREAD_CHARS = 600_000
TRUNCATED_TOOL_RESULT_SUFFIX = "\n[Tool result truncated for storage.]"
REMOVED_TOOL_RESULT = "[Earlier tool result removed to keep the stored conversation small.]"
UNANSWERED_TOOL_CALL_RESULT = "This tool call did not finish before the turn ended, so it has no result."
FAST_LANE_TOOL_RESULT_CHARS = 2_000
FAST_LANE_TOOL_ARGS_CHARS = 400
FAST_LANE_DEFAULT_HISTORY_CHARS = 60_000
FAST_LANE_MIN_HISTORY_CHARS = 8_000
FAST_LANE_MAX_HISTORY_CHARS = 240_000


@dataclass(frozen=True)
class StoredConversationThread:
    agent_task_id: str
    model_family: str
    model_id: str
    messages: List[BaseMessage]


def model_identity(llm: Any) -> tuple[str, str]:
    try:
        family = str(getattr(llm, "_llm_type", "") or "")
    except Exception:
        family = ""
    model_id = ""
    for attribute in ("model", "model_name", "model_identifier"):
        value = getattr(llm, attribute, None)
        if isinstance(value, str) and value.strip():
            model_id = value.strip()
            break
    return family or "unknown", model_id


def _plain_tool_calls(message: AIMessage) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    for call in message.tool_calls or []:
        call_id = str(call.get("id") or "")
        name = str(call.get("name") or "")
        if not call_id or not name:
            continue
        args = call.get("args")
        calls.append({"name": name, "args": dict(args) if isinstance(args, dict) else {}, "id": call_id, "type": "tool_call"})
    return calls


def _plain_ai_message(message: AIMessage, tool_calls: Optional[List[Dict[str, Any]]] = None) -> Optional[AIMessage]:
    calls = _plain_tool_calls(message) if tool_calls is None else tool_calls
    text = message_text(message.content).strip()
    if not text and not calls:
        return None
    return AIMessage(content=text, tool_calls=calls)


def _plain_tool_message(message: ToolMessage) -> ToolMessage:
    return ToolMessage(
        content=message_text(message.content),
        tool_call_id=str(message.tool_call_id),
        name=message.name,
        status=getattr(message, "status", None) or "success",
    )


def _is_empty_ai(message: BaseMessage) -> bool:
    return isinstance(message, AIMessage) and not message.tool_calls and not message_text(message.content).strip()


def drop_orphan_tool_results(messages: Sequence[BaseMessage]) -> List[BaseMessage]:
    called: set[str] = set()
    kept: List[BaseMessage] = []
    for message in messages:
        if isinstance(message, AIMessage):
            called.update(str(call.get("id") or "") for call in message.tool_calls or [])
        if isinstance(message, ToolMessage) and str(message.tool_call_id) not in called:
            continue
        kept.append(message)
    return kept


def normalize_messages(messages: Sequence[BaseMessage]) -> List[BaseMessage]:
    """Provider-neutral copy: plain text plus tool calls; thinking, signatures, and metadata are dropped."""
    normalized: List[BaseMessage] = []
    for message in messages:
        if isinstance(message, SystemMessage):
            continue
        if isinstance(message, HumanMessage):
            rebuilt = HumanMessage(content=message_text(message.content))
            normalized.append(mark_turn_input(rebuilt) if is_turn_input(message) else rebuilt)
        elif isinstance(message, AIMessage):
            plain = _plain_ai_message(message)
            if plain is not None:
                normalized.append(plain)
        elif isinstance(message, ToolMessage):
            normalized.append(_plain_tool_message(message))
    return drop_orphan_tool_results(normalized)


def ensure_unique_tool_call_ids(messages: Sequence[BaseMessage]) -> List[BaseMessage]:
    """Rename tool-call ids reused across turns (local adapters reuse ids) and point their results at the new id."""
    seen: set[str] = set()
    remap: Dict[str, str] = {}
    result: List[BaseMessage] = []
    for message in messages:
        if isinstance(message, AIMessage) and message.tool_calls:
            calls = _plain_tool_calls(message)
            renamed = False
            for call in calls:
                original = call["id"]
                new_id = original
                suffix = 1
                while new_id in seen:
                    suffix += 1
                    new_id = f"{original}__{suffix}"
                seen.add(new_id)
                if new_id != original:
                    renamed = True
                    remap[original] = new_id
                    call["id"] = new_id
                else:
                    remap.pop(original, None)
            result.append(_plain_ai_message(message, tool_calls=calls) if renamed else message)
        elif isinstance(message, ToolMessage) and str(message.tool_call_id) in remap:
            result.append(message.model_copy(update={"tool_call_id": remap[str(message.tool_call_id)]}))
        else:
            result.append(message)
    return result


def close_unanswered_tool_calls(messages: Sequence[BaseMessage]) -> List[BaseMessage]:
    answered = {str(message.tool_call_id) for message in messages if isinstance(message, ToolMessage)}
    result: List[BaseMessage] = []
    for message in messages:
        result.append(message)
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls or []:
            call_id = str(call.get("id") or "")
            if call_id and call_id not in answered:
                answered.add(call_id)
                result.append(
                    ToolMessage(
                        content=UNANSWERED_TOOL_CALL_RESULT,
                        tool_call_id=call_id,
                        name=str(call.get("name") or "") or None,
                        status="error",
                    )
                )
    return result


def _message_size(message: BaseMessage) -> int:
    return len(json.dumps(serialize_agent_messages([message]), default=str))


def _truncate_tool_result(message: ToolMessage) -> ToolMessage:
    text = message_text(message.content)
    if len(text) <= MAX_STORED_TOOL_RESULT_CHARS:
        return message if isinstance(message.content, str) else message.model_copy(update={"content": text})
    return message.model_copy(update={"content": text[:MAX_STORED_TOOL_RESULT_CHARS] + TRUNCATED_TOOL_RESULT_SUFFIX})


def _next_turn_boundary(messages: Sequence[BaseMessage]) -> Optional[int]:
    flagged = any(is_turn_input(message) for message in messages)
    for index in range(1, len(messages)):
        message = messages[index]
        if is_turn_input(message) if flagged else isinstance(message, HumanMessage):
            return index
    return None


def cap_for_storage(messages: Sequence[BaseMessage], max_chars: int = MAX_STORED_THREAD_CHARS) -> List[BaseMessage]:
    """Cut long tool results, then blank the oldest results, then drop the oldest whole exchanges."""
    capped = [_truncate_tool_result(message) if isinstance(message, ToolMessage) else message for message in messages]
    sizes = [_message_size(message) for message in capped]
    total = sum(sizes)
    for index, message in enumerate(capped):
        if total <= max_chars:
            break
        if isinstance(message, ToolMessage) and message.content != REMOVED_TOOL_RESULT:
            stub = message.model_copy(update={"content": REMOVED_TOOL_RESULT})
            stub_size = _message_size(stub)
            total += stub_size - sizes[index]
            capped[index] = stub
            sizes[index] = stub_size
    while total > max_chars:
        cut = _next_turn_boundary(capped)
        if cut is None:
            break
        total -= sum(sizes[:cut])
        capped = capped[cut:]
        sizes = sizes[cut:]
    return capped


def build_thread_for_storage(messages: Sequence[BaseMessage], answer_text: str) -> List[BaseMessage]:
    """The stored thread ends with the answer the user saw and is valid input for any provider."""
    thread = [message for message in messages if not isinstance(message, SystemMessage)]
    answer = (answer_text or "").strip()
    if answer:
        if thread and isinstance(thread[-1], AIMessage) and not thread[-1].tool_calls:
            thread[-1] = AIMessage(content=answer)
        else:
            thread.append(AIMessage(content=answer))
    thread = [message for message in thread if not _is_empty_ai(message)]
    thread = ensure_unique_tool_call_ids(thread)
    thread = drop_orphan_tool_results(thread)
    thread = close_unanswered_tool_calls(thread)
    return cap_for_storage(thread)


def prepare_thread_for_model(thread: Optional[StoredConversationThread], llm: Any) -> List[BaseMessage]:
    if thread is None or not thread.messages:
        return []
    family, model_id = model_identity(llm)
    if thread.model_family != NEUTRAL_MODEL_FAMILY and thread.model_family == family and thread.model_id == model_id:
        return list(thread.messages)
    logger.info(
        "🧵 Normalizing the prior conversation from %s/%s for %s/%s",
        thread.model_family,
        thread.model_id or "unknown model",
        family,
        model_id or "unknown model",
    )
    return normalize_messages(thread.messages)


def _knowledge_thread_repository() -> Any:
    try:
        from api.dependencies import get_sqlite_knowledge_service

        service = get_sqlite_knowledge_service()
    except Exception as exc:
        logger.debug("Conversation thread storage is unavailable: %s", exc)
        return None
    return getattr(service, "agent_conversation_thread_repository", None)


async def load_thread_for_task(agent_task_id: Any, repository: Any = None) -> Optional[StoredConversationThread]:
    task_id = str(agent_task_id or "").strip()
    if not task_id:
        return None
    repo = repository if repository is not None else _knowledge_thread_repository()
    if repo is None:
        return None
    try:
        row = await repo.get_thread(task_id)
    except Exception as exc:
        logger.warning("Could not load the conversation thread for %s: %s", task_id, exc)
        return None
    if not row:
        return None
    if int(row.get("format_version") or 0) != THREAD_FORMAT_VERSION:
        logger.info("Ignoring the conversation thread for %s: unsupported format %s", task_id, row.get("format_version"))
        return None
    try:
        serialized = json.loads(row.get("messages_json") or "[]")
    except (TypeError, ValueError) as exc:
        logger.warning("Ignoring an unreadable conversation thread for %s: %s", task_id, exc)
        return None
    messages = deserialize_agent_messages(serialized)
    if not messages:
        return None
    return StoredConversationThread(
        agent_task_id=task_id,
        model_family=str(row.get("model_family") or ""),
        model_id=str(row.get("model_id") or ""),
        messages=messages,
    )


async def load_prior_thread(context: Any, repository: Any = None) -> Optional[StoredConversationThread]:
    if not isinstance(context, dict):
        return None
    previous_task_id = str(context.get("previous_task_id") or "").strip()
    if not previous_task_id:
        return None
    thread = await load_thread_for_task(previous_task_id, repository=repository)
    if thread is not None:
        logger.info(
            "🧵 Loaded the conversation thread from task %s (%s message(s), %s/%s)",
            previous_task_id,
            len(thread.messages),
            thread.model_family,
            thread.model_id or "unknown model",
        )
    return thread


async def save_thread(
    *,
    agent_task_id: Any,
    root_task_id: Any,
    model_family: str,
    model_id: str,
    messages: Sequence[BaseMessage],
    repository: Any = None,
) -> bool:
    task_id = str(agent_task_id or "").strip()
    if not task_id or not messages:
        return False
    repo = repository if repository is not None else _knowledge_thread_repository()
    if repo is None:
        return False
    try:
        messages_json = json.dumps(serialize_agent_messages(list(messages)), default=str)
        await repo.save_thread(
            agent_task_id=task_id,
            root_task_id=str(root_task_id or task_id),
            model_family=model_family,
            model_id=model_id,
            format_version=THREAD_FORMAT_VERSION,
            message_count=len(messages),
            messages_json=messages_json,
        )
    except Exception as exc:
        logger.warning("Could not save the conversation thread for %s: %s", task_id, exc)
        return False
    logger.info(
        "🧵 Saved the conversation thread for task %s (%s message(s), %s characters, %s/%s)",
        task_id,
        len(messages),
        len(messages_json),
        model_family,
        model_id or "unknown model",
    )
    return True


async def save_agent_turn_thread(
    *,
    context: Any,
    langchain_llm: Any,
    messages: Optional[Sequence[BaseMessage]],
    answer_text: str,
    repository: Any = None,
) -> bool:
    if not isinstance(context, dict) or not messages:
        return False
    agent_task_id = context.get("agent_task_id")
    try:
        thread = build_thread_for_storage(list(messages), answer_text)
        family, model_id = model_identity(langchain_llm)
    except Exception as exc:
        logger.warning("Could not prepare the conversation thread for %s: %s", agent_task_id, exc)
        return False
    return await save_thread(
        agent_task_id=agent_task_id,
        root_task_id=context.get("root_task_id") or agent_task_id,
        model_family=family,
        model_id=model_id,
        messages=thread,
        repository=repository,
    )


def fast_lane_history_char_budget(model: Any, model_id: Optional[str] = None) -> int:
    window = 0
    for attribute in ("max_context_length", "context_window"):
        value = getattr(model, attribute, None)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            window = value
            break
    if not window and model_id:
        try:
            from api.core.models.models_registry.schema import get_model

            value = (get_model(str(model_id)) or {}).get("context_window")
            window = int(value) if value else 0
        except Exception:
            window = 0
    if window <= 0:
        return FAST_LANE_DEFAULT_HISTORY_CHARS
    return max(FAST_LANE_MIN_HISTORY_CHARS, min(FAST_LANE_MAX_HISTORY_CHARS, window * 3 // 2))


def thread_to_chat_turns(messages: Sequence[BaseMessage], char_budget: int) -> List[Dict[str, str]]:
    """Alternating user/assistant turns for a no-tools model; tool calls and results become assistant text."""
    turns: List[Dict[str, str]] = []

    def _add(role: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] = f"{turns[-1]['content']}\n\n{text}"
        else:
            turns.append({"role": role, "content": text})

    normalized = normalize_messages(messages)
    flagged = any(is_turn_input(message) for message in normalized)
    for message in normalized:
        if isinstance(message, HumanMessage):
            if flagged and not is_turn_input(message):
                continue
            _add("user", request_text(message.content))
        elif isinstance(message, AIMessage):
            parts = [message_text(message.content)]
            for call in message.tool_calls or []:
                args = clip_text(json.dumps(call.get("args") or {}, default=str), FAST_LANE_TOOL_ARGS_CHARS)
                parts.append(f"[Called {call.get('name')} with {args}]")
            _add("assistant", "\n".join(part for part in parts if part))
        elif isinstance(message, ToolMessage):
            result = clip_text(message_text(message.content), FAST_LANE_TOOL_RESULT_CHARS)
            _add("assistant", f"[{message.name or 'tool'} returned: {result}]")
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    while len(turns) > 2 and sum(len(turn["content"]) for turn in turns) > char_budget:
        turns.pop(0)
        while turns and turns[0]["role"] != "user":
            turns.pop(0)
    return turns


def build_fast_lane_messages(system_prompt: str, history: Sequence[Dict[str, str]], user_content: str) -> List[Dict[str, str]]:
    turns = [dict(turn) for turn in history]
    if turns and turns[-1]["role"] == "user":
        turns[-1]["content"] = f"{turns[-1]['content']}\n\n{user_content}"
    else:
        turns.append({"role": "user", "content": user_content})
    return [{"role": "system", "content": system_prompt}, *turns]


async def save_fast_lane_thread(
    *,
    agent_task_id: str,
    root_task_id: Optional[str],
    prior_thread: Optional[StoredConversationThread],
    user_request: str,
    answer_text: str,
    repository: Any,
    history_text: str = "",
) -> bool:
    """Without a prior thread, the text history is kept in front of the request so later turns do not lose it."""
    prior = normalize_messages(prior_thread.messages) if prior_thread is not None else []
    request_line = f"{CURRENT_REQUEST_MARKER}{user_request}"
    history = (history_text or "").strip()
    content = f"{history}\n\n{request_line}" if history and prior_thread is None else request_line
    messages: List[BaseMessage] = [
        *prior,
        mark_turn_input(HumanMessage(content=content)),
        AIMessage(content=answer_text),
    ]
    return await save_thread(
        agent_task_id=agent_task_id,
        root_task_id=root_task_id or agent_task_id,
        model_family=NEUTRAL_MODEL_FAMILY,
        model_id="",
        messages=cap_for_storage(messages),
        repository=repository,
    )
