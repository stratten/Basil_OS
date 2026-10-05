"""Compact record of the tool steps an agent ran before pausing to ask the user a question."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

PAUSED_WORK_DIGEST_RESULT_KEY = "paused_work_digest"
PRIOR_PAUSED_WORK_CONTEXT_KEY = "prior_paused_work"
MAX_PAUSED_WORK_STEPS = 15
MAX_PAUSED_WORK_INPUT_CHARS = 240
MAX_PAUSED_WORK_RESULT_CHARS = 600
_CONTROL_TOOL_NAMES = frozenset({"request_user_input", "finalize_agent_task_result"})


def _redacted(value: Any) -> Any:
    from ..planning.agent_context_assembler import SENSITIVE_KEY_PARTS

    if isinstance(value, Mapping):
        return {
            str(key): (
                "[redacted]"
                if any(part in str(key).lower() for part in SENSITIVE_KEY_PARTS)
                else _redacted(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redacted(item) for item in value]
    return value


def _clip(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 12)].rstrip() + " [truncated]"


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    content = getattr(value, "content", None)
    if isinstance(content, str):
        return content
    try:
        return json.dumps(_redacted(value), ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def normalize_paused_work_digest(raw: Any) -> list[dict[str, str]]:
    """Return the canonical digest shape, dropping malformed entries and keeping the most recent steps."""
    if not isinstance(raw, list):
        return []
    steps: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        tool = entry.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            continue
        tool_input = entry.get("input")
        result = entry.get("result")
        steps.append({
            "tool": tool,
            "input": tool_input if isinstance(tool_input, str) else "",
            "result": result if isinstance(result, str) else "",
        })
    return steps[-MAX_PAUSED_WORK_STEPS:]


def build_paused_work_digest(agent_context: Any, prior: Any = None) -> list[dict[str, str]]:
    """Return the digest saved at earlier pauses followed by this run's completed tool steps."""
    from ..execution_graph.service_tooling.tool_call_repetition_guard import (
        captured_agent_actions_as_intermediate_steps,
    )

    steps = normalize_paused_work_digest(prior)
    if isinstance(agent_context, dict):
        for action, observation in captured_agent_actions_as_intermediate_steps(agent_context):
            if action.tool in _CONTROL_TOOL_NAMES:
                continue
            steps.append({
                "tool": action.tool,
                "input": _clip(_as_text(action.tool_input), MAX_PAUSED_WORK_INPUT_CHARS),
                "result": _clip(_as_text(observation), MAX_PAUSED_WORK_RESULT_CHARS),
            })
    return steps[-MAX_PAUSED_WORK_STEPS:]


def paused_work_digest_from_result_data(result_data: Any) -> list[dict[str, str]]:
    if isinstance(result_data, str):
        try:
            result_data = json.loads(result_data)
        except ValueError:
            return []
    if not isinstance(result_data, Mapping):
        return []
    return normalize_paused_work_digest(result_data.get(PAUSED_WORK_DIGEST_RESULT_KEY))


async def load_paused_work_digest(
    knowledge_service: Any,
    agent_task_id: str,
    agent_task: Any = None,
) -> list[dict[str, str]]:
    """Return the digest saved when the task paused; never raises."""
    try:
        if agent_task is None:
            agent_task_service = getattr(knowledge_service, "agent_task_service", None)
            if agent_task_service is None:
                return []
            agent_task = await agent_task_service.get_agent_task(agent_task_id)
        return paused_work_digest_from_result_data(getattr(agent_task, "result_data", None))
    except Exception:
        logger.warning("Could not read paused work for %s", agent_task_id, exc_info=True)
        return []


def format_paused_work_section(digest: list[dict[str, str]]) -> str:
    lines = [
        "Before pausing to ask the user a question, you already ran these tools in this same task. "
        "Reuse these results instead of repeating the calls, unless the user's answer changes what is needed.",
    ]
    for index, step in enumerate(digest, start=1):
        lines.append(f"{index}. {step['tool']} {step['input']}".rstrip())
        if step["result"]:
            lines.append(f"   Result: {step['result']}")
    return "\n".join(lines)
