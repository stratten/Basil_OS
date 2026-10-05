"""Centralized guard against repeated invalid agent tool calls.

Local models sometimes re-issue the *same* malformed tool call over and over
(for example ``browser_interact({"color": "green"})`` with no ``action``). Each
call returns a recoverable structured error, but the model ignores it and loops
until the executor's wall-clock cap (``max_execution_time``) fires. That wastes
the whole budget and produces no result.

This module wraps agent-bound tools so the run can detect that pattern and react
*inside* the reasoning loop, without teaching individual tools to guess intent:

- Counts 1-2 of a repeated invalid signature: pass the tool's own error through.
- Counts 3-5: replace the observation with a stronger, explicit repair prompt.
- Count 6: raise :class:`RepeatedInvalidToolCallStop` to end the pass cleanly.

It deliberately does *not* relax any tool schema, infer default arguments, or add
browser-specific logic. It only recognizes already-recoverable invalid-argument
observations and applies loop control on top of them.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Iterable, Optional

from langchain_core.agents import AgentAction
from langchain_core.tools import StructuredTool

from ....shared.agent_runtime_context import get_current_agent_context
from .tool_ledger_capture import ToolLedgerCaptureCoordinator, next_tool_invocation_id

logger = logging.getLogger(__name__)


# Fixed loop-control thresholds. A single mistake must not stop a run, but a
# model that ignores repeated recoverable errors must not burn the full cap.
REPAIR_OBSERVATION_REPEAT_COUNT = 3
STOP_REPEAT_COUNT = 6

_GUARD_STATE_KEY = "tool_call_repetition_guard"
_GUARD_EVENTS_KEY = "tool_call_repetition_guard_events"
_ORIGINAL_TOOL_ATTR = "basil_original_tool"

_VALIDATION_PREFIX = "Tool input validation failed for field(s): "
_REQUIRED_ARGUMENT_TOKENS = ("selector", "value", "URL", "connection_id", "tool_name", "session_id")

_CAPTURED_ACTIONS_KEY = "captured_agent_tool_actions"


class RepeatedInvalidToolCallStop(Exception):
    """Raised to stop an agent pass after repeated identical invalid tool calls."""

    def __init__(
        self,
        tool_name: str,
        signature: str,
        repeat_count: int,
        diagnostic: dict[str, Any],
        agent_output: str,
    ) -> None:
        super().__init__(
            f"Repeated invalid tool call to '{tool_name}' "
            f"(signature={signature}, repeat_count={repeat_count})"
        )
        self.tool_name = tool_name
        self.signature = signature
        self.repeat_count = repeat_count
        self.diagnostic = diagnostic
        self.agent_output = agent_output


def _coerce_observation_to_text(observation: Any) -> Optional[str]:
    """Return observation text if it is a string-like tool output, else None."""

    if isinstance(observation, str):
        return observation
    # ToolMessage and similar carry their payload on ``.content``.
    content = getattr(observation, "content", None)
    if isinstance(content, str):
        return content
    return None


def _parse_json_object(text: str) -> Optional[dict[str, Any]]:
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _top_level_keys(tool_input: Any) -> list[str]:
    if isinstance(tool_input, dict):
        return sorted(str(key) for key in tool_input.keys())
    return []


def _extract_validation_fields(observation_text: str) -> list[str]:
    remainder = observation_text[len(_VALIDATION_PREFIX):]
    # The handler text is "<fields>. Pass each argument ...". Take up to the
    # first sentence break so trailing guidance is not mistaken for a field.
    field_segment = remainder.split(".", 1)[0]
    fields = [field.strip() for field in field_segment.split(",")]
    return [field for field in fields if field]


def classify_invalid_tool_observation(
    tool_name: str,
    tool_input: Any,
    observation: Any,
) -> Optional[dict[str, Any]]:
    """Classify a recoverable invalid-argument observation for guarding.

    Returns ``None`` for successful results, operational failures (element not
    found, permission blockers, browser/runtime errors, timeouts), and anything
    that is not a recognized malformed-argument response. Returns a diagnostic
    dict (without raw input values) for guardable invalid calls.
    """

    observation_text = _coerce_observation_to_text(observation)
    if observation_text is None:
        return None

    invalid_kind: Optional[str] = None
    validation_fields: list[str] = []
    error_text = ""

    payload = _parse_json_object(observation_text)
    if payload is not None:
        if payload.get("success") is not False:
            return None
        error_text = str(payload.get("error", "") or "")
        lowered = error_text.lower()
        if "requires an action" in lowered:
            invalid_kind = "missing_action"
        elif payload.get("valid_actions") is not None:
            invalid_kind = "missing_or_invalid_action"
        elif "requires" in lowered and any(
            token.lower() in lowered for token in _REQUIRED_ARGUMENT_TOKENS
        ):
            invalid_kind = "missing_required_argument"
        else:
            # Operational failures (element not found, permission blockers,
            # browser errors, timeouts) are real outcomes, not argument loops.
            return None
    elif observation_text.startswith(_VALIDATION_PREFIX):
        invalid_kind = "validation_error"
        validation_fields = _extract_validation_fields(observation_text)
        error_text = observation_text.strip()
    else:
        return None

    input_keys = _top_level_keys(tool_input)
    signature = build_tool_call_signature(
        tool_name,
        tool_input,
        invalid_kind,
        validation_fields=validation_fields,
    )
    diagnostic: dict[str, Any] = {
        "tool_name": tool_name,
        "invalid_kind": invalid_kind,
        "input_keys": input_keys,
        "input_hash": _input_hash(tool_input),
        "signature": signature,
        "error": error_text,
    }
    if validation_fields:
        diagnostic["validation_fields"] = validation_fields
    return diagnostic


def _input_hash(tool_input: Any) -> str:
    canonical = json.dumps(tool_input, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_tool_call_signature(
    tool_name: str,
    tool_input: Any,
    invalid_kind: str,
    *,
    validation_fields: Optional[list[str]] = None,
) -> str:
    """Build a stable, value-hashed signature for a repeated invalid call.

    The signature embeds the tool name, invalid kind, normalized top-level input
    keys, a SHA-256 of canonical JSON input, and (for validation errors) the
    failing field list so unrelated validation failures with overlapping keys do
    not share a counter. Raw input *values* never appear in the returned string.
    """

    keys = _top_level_keys(tool_input)
    material_parts = [tool_name, invalid_kind, ",".join(keys), _input_hash(tool_input)]
    if validation_fields:
        material_parts.append("fields:" + ",".join(sorted(validation_fields)))
    digest = hashlib.sha256("|".join(material_parts).encode("utf-8")).hexdigest()
    return f"{tool_name}:{invalid_kind}:{digest}"


def record_invalid_tool_call(
    agent_context: dict[str, Any],
    diagnostic: dict[str, Any],
) -> dict[str, Any]:
    """Increment the repeat counter for a signature and append a safe audit event.

    Returns a state dict for the signature including its current ``repeat_count``.
    No raw tool-input values are stored.
    """

    guard_state = agent_context.setdefault(_GUARD_STATE_KEY, {})
    counts: dict[str, int] = guard_state.setdefault("counts", {})
    signature = diagnostic["signature"]
    counts[signature] = counts.get(signature, 0) + 1
    repeat_count = counts[signature]

    event = {
        "tool_name": diagnostic.get("tool_name"),
        "invalid_kind": diagnostic.get("invalid_kind"),
        "input_keys": diagnostic.get("input_keys"),
        "input_hash": diagnostic.get("input_hash"),
        "signature": signature,
        "repeat_count": repeat_count,
    }
    if diagnostic.get("validation_fields"):
        event["validation_fields"] = diagnostic["validation_fields"]
    events: list[dict[str, Any]] = agent_context.setdefault(_GUARD_EVENTS_KEY, [])
    events.append(event)

    return {"signature": signature, "repeat_count": repeat_count}


def _next_actions_for_kind(diagnostic: dict[str, Any]) -> list[str]:
    invalid_kind = diagnostic.get("invalid_kind")
    if invalid_kind in {"missing_action", "missing_or_invalid_action"}:
        return [
            "Choose exactly one action from: click, fill, select, navigate, scroll, wait.",
            "If you are unsure which element to act on, call browser_inspect instead of browser_interact.",
        ]
    if invalid_kind == "missing_required_argument":
        return [
            "Re-send the call including the required argument named in the error text.",
            "Do not repeat the same incomplete arguments; if unsure, inspect the target first.",
        ]
    if invalid_kind == "validation_error":
        fields = diagnostic.get("validation_fields") or []
        field_text = ", ".join(fields) if fields else "the reported field(s)"
        return [
            f"Pass {field_text} as native JSON values matching the tool schema.",
            "For object arguments, send a JSON object, not a quoted JSON string.",
        ]
    return [
        "Stop repeating the same arguments; review the tool schema and send corrected input.",
    ]


def build_guard_repair_observation(diagnostic: dict[str, Any], repeat_count: int) -> str:
    """Build the stronger guard repair observation returned at the repair threshold."""

    return json.dumps(
        {
            "success": False,
            "guarded": True,
            "repeat_count": repeat_count,
            "tool_name": diagnostic.get("tool_name"),
            "invalid_kind": diagnostic.get("invalid_kind"),
            "input_keys": diagnostic.get("input_keys"),
            "error": (
                f"This call was rejected {repeat_count} times with the same invalid "
                f"arguments. Repeating it will not work."
            ),
            "next_actions": _next_actions_for_kind(diagnostic),
        },
        ensure_ascii=False,
    )


def _build_stop_agent_output(diagnostic: dict[str, Any], repeat_count: int) -> str:
    next_actions = _next_actions_for_kind(diagnostic)
    return (
        f"Stopped: the tool '{diagnostic.get('tool_name')}' was called with the same "
        f"invalid arguments {repeat_count} times without correction. "
        "I could not complete this task because the required tool input was never "
        "provided correctly. Suggested next steps: " + " ".join(next_actions)
    )


class RepetitionGuardedTool(StructuredTool):
    """A StructuredTool wrapper that applies repeated-invalid-call loop control.

    All validation, ``handle_validation_error`` handling, and execution happen in
    the wrapped original tool; this wrapper only intercepts the resulting
    observation to count and guard repeated invalid-argument calls.
    """

    basil_original_tool: Any = None

    async def arun(self, tool_input: Any, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        original = self.basil_original_tool
        agent_context = get_current_agent_context()
        invocation_id = next_tool_invocation_id(agent_context, self.name, tool_input)
        previous_invocation_id = agent_context.get("active_tool_invocation_id")
        agent_context["active_tool_invocation_id"] = invocation_id
        try:
            try:
                observation = await original.arun(tool_input, *args, **kwargs)
            except Exception as tool_error:
                await _capture_tool_observation(
                    tool_name=self.name,
                    tool_input=tool_input,
                    error=tool_error,
                    invocation_id=invocation_id,
                )
                _record_captured_action(agent_context, self.name, tool_input, str(tool_error))
                raise

            await _capture_tool_observation(
                tool_name=self.name,
                tool_input=tool_input,
                observation=observation,
                invocation_id=invocation_id,
            )
            _record_captured_action(agent_context, self.name, tool_input, observation)
            try:
                diagnostic = classify_invalid_tool_observation(
                    self.name, tool_input, observation
                )
            except Exception as classify_error:  # pragma: no cover - defensive
                logger.debug("Repetition guard classification failed: %s", classify_error)
                return observation

            if diagnostic is None:
                return observation

            state = record_invalid_tool_call(agent_context, diagnostic)
            repeat_count = state["repeat_count"]

            if repeat_count >= STOP_REPEAT_COUNT:
                agent_output = _build_stop_agent_output(diagnostic, repeat_count)
                logger.warning(
                    "🛑 Tool repetition guard stopping pass: tool=%s kind=%s repeat=%s",
                    diagnostic.get("tool_name"),
                    diagnostic.get("invalid_kind"),
                    repeat_count,
                )
                raise RepeatedInvalidToolCallStop(
                    tool_name=self.name,
                    signature=state["signature"],
                    repeat_count=repeat_count,
                    diagnostic=diagnostic,
                    agent_output=agent_output,
                )

            if repeat_count >= REPAIR_OBSERVATION_REPEAT_COUNT:
                logger.info(
                    "🧭 Tool repetition guard emitting repair observation: tool=%s kind=%s repeat=%s",
                    diagnostic.get("tool_name"),
                    diagnostic.get("invalid_kind"),
                    repeat_count,
                )
                return build_guard_repair_observation(diagnostic, repeat_count)

            return observation
        finally:
            if previous_invocation_id is None:
                agent_context.pop("active_tool_invocation_id", None)
            else:
                agent_context["active_tool_invocation_id"] = previous_invocation_id


async def _capture_tool_observation(**kwargs: Any) -> None:
    """Keep ledger-observer failures outside the wrapped tool's contract."""
    try:
        await ToolLedgerCaptureCoordinator().capture_observation(**kwargs)
    except Exception as capture_error:  # pragma: no cover - defensive isolation
        logger.warning("Work-ledger observation capture failed: %s", capture_error)


def agent_tool_action_capture_offset(agent_context: dict[str, Any]) -> int:
    """Length of the captured-action log right now, for later since_offset use."""
    return len(agent_context.get(_CAPTURED_ACTIONS_KEY, []))


def _record_captured_action(
    agent_context: dict[str, Any],
    tool_name: str,
    tool_input: Any,
    observation: Any,
) -> None:
    """Mirror a tool call/observation in-memory so it survives an aborted pass.

    LangChain's own ``intermediate_steps`` only exist on a clean
    ``AgentExecutor.ainvoke`` return; an exception raised mid-loop (for example
    RepeatedInvalidToolCallStop) discards them entirely. This is the one place
    every guarded tool call is recorded regardless of how the pass ends.
    """
    actions: list[dict[str, Any]] = agent_context.setdefault(_CAPTURED_ACTIONS_KEY, [])
    actions.append({
        "tool": tool_name,
        "tool_input": tool_input if isinstance(tool_input, dict) else {"value": tool_input},
        "observation": observation,
    })


def discard_captured_agent_actions(agent_context: dict[str, Any]) -> None:
    """Forget captured tool actions so a resumed run records only its own steps."""
    agent_context.pop(_CAPTURED_ACTIONS_KEY, None)


def captured_agent_actions_as_intermediate_steps(
    agent_context: dict[str, Any],
    since_offset: int = 0,
) -> list[tuple[AgentAction, Any]]:
    """Rebuild LangChain-shaped intermediate_steps from the in-memory log.

    Used to recover evidence for a pass that ended via RepeatedInvalidToolCallStop, whose own return value has no intermediate_steps, and to record the work done before a checkpoint pause.
    """
    actions = agent_context.get(_CAPTURED_ACTIONS_KEY, [])
    return [
        (AgentAction(tool=record["tool"], tool_input=record["tool_input"], log=""), record["observation"])
        for record in actions[since_offset:]
    ]


def _is_guardable_tool(tool: Any) -> bool:
    return all(
        hasattr(tool, attribute)
        for attribute in ("name", "description", "args_schema", "ainvoke")
    )


def wrap_tools_with_repetition_guard(tools: Iterable[Any]) -> list[Any]:
    """Wrap conforming agent tools with repeated-invalid-call loop control.

    Non-conforming objects and already-wrapped tools are returned unchanged. Each
    wrapper preserves the original tool's ``name``, ``description``, ``args_schema``,
    and ``handle_validation_error`` and stores the original on ``basil_original_tool``.
    """

    wrapped_tools: list[Any] = []
    for tool in tools:
        if isinstance(tool, RepetitionGuardedTool) or not _is_guardable_tool(tool):
            wrapped_tools.append(tool)
            continue

        wrapper = RepetitionGuardedTool(
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema,
            func=getattr(tool, "func", None),
            coroutine=getattr(tool, "coroutine", None),
            return_direct=getattr(tool, "return_direct", False),
            handle_validation_error=getattr(tool, "handle_validation_error", None),
            metadata=getattr(tool, "metadata", None),
            tags=getattr(tool, "tags", None),
            basil_original_tool=tool,
        )
        wrapped_tools.append(wrapper)
    return wrapped_tools
