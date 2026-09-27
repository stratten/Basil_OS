"""
Backend streamed final synthesis for agent tasks.

Turns tool-execution output into user-facing prose via a normal LLM text stream,
then hands the accumulated text to ``finalize_agent_task_result`` for deterministic
packaging (envelope / result_payload) without relying on partial tool-call args.
"""

from __future__ import annotations

import json
import logging
import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from api.core.models.reasoning.streaming_contract import (
    StreamTerminalMetadata,
    resolve_generation_budget,
    terminal_from_error,
    terminal_from_provider_reason,
)

# Same convention as the llama.cpp and DeepSeek reasoning adapters (base_reasoning.py
# documents why each adapter owns its own markers). The raw model/chat streaming
# primitives (stream_chat_completion / chat_completion_streaming) intentionally yield
# unfiltered tokens -- exactly like the agent-loop's LiveProgressCallbackHandler
# receives unfiltered tokens from on_llm_new_token -- and each consumer is
# responsible for recognizing its own reasoning markers and routing them to the
# "thinking" channel. This mirrors that same consumer-side split for the final
# synthesis phase instead of leaking <think> content into the answer or discarding it.
_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"
# Agent-loop reasoning segments (LiveProgressCallbackHandler) use iteration numbers
# starting at 1. Final synthesis is a distinct, later phase with no visibility into
# that counter, so it reserves this sentinel to guarantee no collision in the
# frontend's per-iteration ThinkingSegment keying.
_FINAL_SYNTHESIS_THINKING_ITERATION = -1


class _ReasoningTagRouter:
    """Splits a raw local-model text stream into (answer, reasoning) deltas.

    Tolerates ``<think>``/``</think>`` markers split across chunk boundaries by
    holding back a short tail that could be a partial marker prefix until enough
    text arrives to resolve it. Call ``feed()`` per chunk and ``flush()`` once at
    stream end to resolve any held-back tail (marks ``unterminated`` if the stream
    ended while still inside a reasoning block).
    """

    def __init__(self) -> None:
        self._pending = ""
        self._in_reasoning = False
        self.saw_reasoning = False
        self.unterminated = False

    @staticmethod
    def _partial_suffix_len(text: str, marker: str) -> int:
        """Longest suffix of ``text`` that could still grow into ``marker``."""
        max_check = min(len(text), len(marker) - 1)
        for length in range(max_check, 0, -1):
            if marker.startswith(text[-length:]):
                return length
        return 0

    def feed(self, raw: str) -> Tuple[str, str]:
        if not raw:
            return "", ""
        self._pending += raw
        answer_parts: List[str] = []
        reasoning_parts: List[str] = []
        while True:
            marker = _THINK_CLOSE if self._in_reasoning else _THINK_OPEN
            idx = self._pending.find(marker)
            if idx == -1:
                break
            before = self._pending[:idx]
            if self._in_reasoning:
                reasoning_parts.append(before)
            else:
                if before:
                    answer_parts.append(before)
                self.saw_reasoning = True
            self._in_reasoning = not self._in_reasoning
            self._pending = self._pending[idx + len(marker):]

        marker = _THINK_CLOSE if self._in_reasoning else _THINK_OPEN
        safe_len = self._partial_suffix_len(self._pending, marker)
        if safe_len:
            emit, self._pending = self._pending[:-safe_len], self._pending[-safe_len:]
        else:
            emit, self._pending = self._pending, ""
        if emit:
            (reasoning_parts if self._in_reasoning else answer_parts).append(emit)
        return "".join(answer_parts), "".join(reasoning_parts)

    def flush(self) -> Tuple[str, str]:
        """Resolve any held-back tail. A stream ending while still inside a
        reasoning block means the closing tag never arrived: unterminated."""
        remainder = self._pending
        self._pending = ""
        if self._in_reasoning:
            self.unterminated = True
            return "", remainder
        return remainder, ""

if TYPE_CHECKING:
    from .agent_progress_system import PlanningState

logger = logging.getLogger(__name__)
_LOCAL_RUNTIME_TRACE_ENV = "BASIL_LOCAL_RUNTIME_TRACE"

FINAL_SYNTHESIS_SYSTEM = """You are the final response writer for Basil, a macOS assistant that already ran tools on the user's behalf.

Your job is to produce a clear, well-structured answer for the user in markdown when helpful.
- Lead with what was done and the outcome.
- Include important paths, quoted text, or numbers from tool results when relevant.
- If something failed or could not be completed, say so plainly and what was tried.
- Do not invent tool results or file paths that do not appear in the context.
- When material change evidence is present, state a change as completed only when that
  evidence marks it verified. Describe unverified changes as attempted or uncertain and
  failed changes plainly, but mention them only where they matter to the request. Do not
  enumerate entities or present counters.
- Do not call tools; your output is the user-visible answer only.
"""

# Coalesce streaming chunks so the UI updates smoothly without per-token churn.
_DEFAULT_COALESCE_MIN_CHARS = 80
_COALESCE_NEWLINE_FLUSH = "\n\n"


def _emit_synthesis_trace(event: str, **fields: Any) -> None:
    """Emit opt-in, prompt-free timing data for local final synthesis."""
    if os.getenv(_LOCAL_RUNTIME_TRACE_ENV) != "1":
        return
    logger.warning(
        "LOCAL_RUNTIME_TRACE %s",
        json.dumps(
            {"event": event, "monotonic_seconds": time.monotonic(), **fields},
            sort_keys=True,
        ),
    )


@dataclass
class SynthesisResult:
    """Final synthesis text and evidence about whether generation completed cleanly."""

    text: str
    terminal: StreamTerminalMetadata
    truncation_evidence: List[Dict[str, Any]] = field(default_factory=list)
    input_token_estimate: int = 0
    thinking_history: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def completed_cleanly(self) -> bool:
        return self.terminal.completed_cleanly and not self.truncation_evidence

    def to_evidence_dict(self) -> Dict[str, Any]:
        return {
            "terminal": self.terminal.to_dict(),
            "truncation_evidence": self.truncation_evidence,
            "input_token_estimate": self.input_token_estimate,
            "completed_cleanly": self.completed_cleanly,
        }


def normalize_agent_executor_output(output: Any) -> str:
    """
    LangChain + Claude may return ``str`` or Anthropic-style content blocks (list of dicts
    with ``text`` / ``type``). Final synthesis and the finalizer expect plain text.
    """
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        parts: List[str] = []
        for item in output:
            if isinstance(item, dict):
                t = item.get("text")
                if t is not None:
                    parts.append(str(t))
                elif "content" in item:
                    parts.append(str(item["content"]))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False)[:8000])
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(output)


def _split_tool_name(tool_name: Optional[str]) -> Tuple[str, str]:
    if not tool_name or not isinstance(tool_name, str):
        return ("unknown", "unknown")
    if "." in tool_name:
        svc, _, rest = tool_name.partition(".")
        return (svc or "unknown", rest or "invoke")
    return (tool_name, "invoke")


def _parse_observation_for_step(observation: Any) -> Tuple[Optional[bool], Any]:
    """Best-effort success flag and structured result from a tool observation string."""
    if observation is None:
        return None, None
    if isinstance(observation, dict):
        ok = observation.get("success")
        if isinstance(ok, bool):
            return ok, observation
        return None, observation
    if not isinstance(observation, str):
        s = str(observation)
    else:
        s = observation
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            ok = data.get("success")
            if isinstance(ok, bool):
                return ok, data
            return None, data
    except Exception:
        pass
    return None, {"raw": s[:8000]}


def _extract_outcome_review_fields(result: Any) -> Dict[str, Any]:
    """Expose material-outcome evidence from structured tool envelopes."""
    if not isinstance(result, dict):
        return {}

    candidate = result.get("result")
    if not isinstance(candidate, dict):
        candidate = result

    fields: Dict[str, Any] = {}
    for key in ("needs_outcome_review", "outcome_verification_status", "outcome_review"):
        if key in candidate:
            fields[key] = candidate[key]
    return fields


def _is_recognized_invalid_tool_call(tool_name: Any, tool_input: Any, observation: Any) -> bool:
    """True when ``observation`` is a known malformed-call response (guard-recognized),
    not a genuine tool result. Deferred import avoids importing execution-graph
    tool-wiring code at module load time for every consumer of this module."""
    from .service_tooling.tool_call_repetition_guard import classify_invalid_tool_observation

    try:
        return classify_invalid_tool_observation(tool_name, tool_input, observation) is not None
    except Exception:  # pragma: no cover - defensive
        return False


def intermediate_steps_to_finalizer_steps(intermediate_steps: List[Any]) -> List[Dict[str, Any]]:
    """
    Convert LangChain-style ``intermediate_steps`` (AgentAction, observation) tuples into
    the structured ``steps`` list expected by ``finalize_agent_task_result``.
    Skips ``finalize_agent_task_result`` entries (legacy path).
    """
    out: List[Dict[str, Any]] = []
    for step in intermediate_steps or []:
        if not isinstance(step, tuple) or len(step) < 2:
            continue
        action, observation = step[0], step[1]
        tool_name = getattr(action, "tool", None)
        if tool_name == "finalize_agent_task_result":
            continue
        service, method = _split_tool_name(tool_name)
        tool_input = getattr(action, "tool_input", None) or {}
        if not isinstance(tool_input, dict):
            tool_input = {"value": tool_input}
        success, result = _parse_observation_for_step(observation)
        if success is None:
            if _is_recognized_invalid_tool_call(tool_name, tool_input, observation):
                success = False
            else:
                obs_s = observation if isinstance(observation, str) else str(observation)
                success = "error" not in obs_s.lower()[:200] and "traceback" not in obs_s.lower()[:200]
        step_record = {
            "service": service,
            "method": method,
            "success": bool(success),
            "duration_ms": None,
            "tool_input": tool_input,
            "result": result,
        }
        step_record.update(_extract_outcome_review_fields(result))
        out.append(step_record)
    return out


def _format_tool_trace_for_synthesis(intermediate_steps: List[Any]) -> str:
    """Compact text block of tool names, inputs, and observations for the synthesis model."""
    lines: List[str] = []
    for step in intermediate_steps or []:
        if not isinstance(step, tuple) or len(step) < 2:
            continue
        action, observation = step[0], step[1]
        tool_name = getattr(action, "tool", None)
        if tool_name == "finalize_agent_task_result":
            continue
        lines.append(f"--- Tool: {tool_name} ---")
        ti = getattr(action, "tool_input", None)
        if ti is not None:
            try:
                lines.append(f"Input: {json.dumps(ti, ensure_ascii=False)[:4000]}")
            except Exception:
                lines.append(f"Input: {str(ti)[:4000]}")
        obs = observation
        if isinstance(observation, str) and len(observation) > 12000:
            obs = observation[:12000] + "\n… [truncated]"
        lines.append(f"Observation: {obs}")
        lines.append("")
    return "\n".join(lines).strip() or "(No tool calls recorded.)"


def build_final_synthesis_messages(
    *,
    user_agent_task: str,
    final_input: str,
    agent_output: Any,
    intermediate_steps: List[Any],
    context: Optional[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """
    Build chat messages for the streaming synthesis call.
    """
    handoff_text = normalize_agent_executor_output(agent_output).strip()
    ctx = context or {}
    active_app = ctx.get("active_app")
    if not active_app and isinstance(ctx.get("app_context"), dict):
        active_app = (ctx.get("app_context") or {}).get("app_name")
    ref_paths = ctx.get("reference_paths") or ctx.get("reference_paths_for_task")
    ref_block = ""
    if ref_paths:
        try:
            ref_block = "\nReference paths / context:\n" + json.dumps(ref_paths, ensure_ascii=False)[:4000]
        except Exception:
            ref_block = "\nReference paths / context:\n" + str(ref_paths)[:4000]

    tool_block = _format_tool_trace_for_synthesis(intermediate_steps)
    user_parts = [
        f"User request:\n{user_agent_task.strip()}",
    ]
    if final_input and final_input.strip() and final_input.strip() != user_agent_task.strip():
        user_parts.append(f"Follow-up / chain context (may include parent task details):\n{final_input.strip()}")
    if active_app:
        user_parts.append(f"Active app at request time: {active_app}")
    user_parts.append(ref_block)
    user_parts.append(
        "Agent execution handoff (what the tool agent reports it did — may be terse; prefer tool observations below):\n"
        + (handoff_text or "(empty)")
    )
    user_parts.append("Tool trace (authoritative for facts):\n" + tool_block)

    tool_err = ctx.get("tool_errors")
    if tool_err:
        try:
            user_parts.append("Tool wiring / setup issues (if any):\n" + json.dumps(tool_err, ensure_ascii=False)[:4000])
        except Exception:
            user_parts.append("Tool wiring / setup issues (if any):\n" + str(tool_err)[:4000])

    staged_diagnostics = ctx.get("staged_tool_loading_diagnostics")
    if staged_diagnostics:
        try:
            staged_body = json.dumps(staged_diagnostics, ensure_ascii=False)[:4000]
        except Exception:
            staged_body = str(staged_diagnostics)[:4000]
        user_parts.append(
            "Staged tool loading diagnostics:\n"
            + staged_body
            + "\nThese diagnostics are evidence about tool-family routing only. "
            "Do not infer that an external service connection is missing unless an external_catalog tool observation says so."
        )

    user_content = "\n\n".join(p for p in user_parts if p)

    return [
        {"role": "system", "content": FINAL_SYNTHESIS_SYSTEM},
        {"role": "user", "content": user_content},
    ]


def derive_self_assessment_from_handoff(agent_output: Any) -> str:
    """Compact self-assessment string for the finalizer from the tool-execution handoff."""
    text = normalize_agent_executor_output(agent_output).strip()
    if not text:
        return "Handoff was empty; success should be judged from tool trace and synthesis."
    return f"Execution handoff from tool agent (for packaging; user-facing text is synthesized separately):\n{text[:8000]}"


async def _broadcast_synthesis_thinking(
    stream_notifier: Any,
    text: str,
    *,
    complete: bool,
) -> None:
    """Broadcast final-synthesis reasoning on the same channel/shape the agent-loop's
    LiveProgressCallbackHandler uses (agent_progress_update with thinking /
    thinking_complete / thinking_iteration), so the frontend's existing
    ThinkingSegments UI renders it as a live, collapsible reasoning entry instead of
    it being leaked into or stripped from the visible answer."""
    ws_manager = getattr(stream_notifier, "_websocket_manager", None)
    if ws_manager is None or not hasattr(ws_manager, "broadcast"):
        return
    from datetime import datetime

    event = {
        "event_type": "agent_progress_update",
        "execution_method": "dynamic_agent",
        "agent_task_id": getattr(stream_notifier, "_agent_task_id", None),
        "timestamp": datetime.now().isoformat(),
        "message": "Working…",
        "thinking": text,
        "thinking_complete": complete,
        "thinking_iteration": _FINAL_SYNTHESIS_THINKING_ITERATION,
    }
    try:
        await ws_manager.broadcast(event)
    except Exception as exc:
        logger.debug("Synthesis thinking broadcast failed (non-fatal): %s", exc)


def infer_success_flag_for_direct_finalize(
    intermediate_steps: List[Any],
    context: Optional[Dict[str, Any]],
) -> Optional[bool]:
    """
    Return a mechanical success override for direct finalization.

    Tool failures are intentionally not a hard veto here. The result finalizer
    receives the failed steps and tool error history as evidence, then reasons
    about whether later recovery satisfied the user's actual request.
    """
    return None


async def stream_synthesized_final_answer(
    *,
    llm_model: Any,
    messages: List[Dict[str, str]],
    stream_notifier: Any,
    coalesce_min_chars: int = _DEFAULT_COALESCE_MIN_CHARS,
    stream_source: str = "final_synthesis",
    operation: str = "multi_step_workflow",
    cancel_event: Any = None,
    budget: Any = None,
    truncation_evidence: Optional[List[Dict[str, Any]]] = None,
    input_token_estimate: int = 0,
) -> SynthesisResult:
    """
    Stream the synthesized answer via ``send_agent_result_streaming_chunk`` (cumulative
    ``partial_result``) and complete with ``send_agent_result_streaming_complete``.
    Returns the full accumulated string.
    """
    if not llm_model or not messages:
        return SynthesisResult(text="", terminal=terminal_from_provider_reason("unknown"))

    full_response = ""
    buffer = ""
    thinking_text = ""
    thinking_buffer = ""
    router = _ReasoningTagRouter()
    terminal = terminal_from_provider_reason("unknown")
    evidence = list(truncation_evidence or [])

    def _is_cancelled() -> bool:
        return bool(cancel_event is not None and hasattr(cancel_event, "is_set") and cancel_event.is_set())

    if _is_cancelled():
        raise asyncio.CancelledError()

    if stream_notifier and hasattr(stream_notifier, "send_agent_progress_update"):
        try:
            await stream_notifier.send_agent_progress_update(
                message="Checking the work and preparing your result…",
                details="Writing the final answer from the completed tool results.",
            )
        except Exception as exc:
            logger.debug("Synthesis progress send failed (non-fatal): %s", exc)

    async def _flush_buffer(*, force: bool = False) -> None:
        nonlocal full_response, buffer
        if not buffer:
            return
        if not force and len(buffer) < coalesce_min_chars and _COALESCE_NEWLINE_FLUSH not in buffer:
            return
        full_response += buffer
        to_send = full_response
        buffer = ""
        if stream_notifier and hasattr(stream_notifier, "send_agent_result_streaming_chunk"):
            try:
                await stream_notifier.send_agent_result_streaming_chunk(
                    token=to_send[-400:] if len(to_send) > 400 else to_send,
                    partial_result=to_send,
                    operation=operation,
                    source=stream_source,
                )
            except Exception as exc:
                logger.debug("Streaming chunk send failed (non-fatal): %s", exc)

    async def _flush_thinking(*, force: bool = False) -> None:
        nonlocal thinking_text, thinking_buffer
        if not thinking_buffer:
            return
        if not force and len(thinking_buffer) < coalesce_min_chars and _COALESCE_NEWLINE_FLUSH not in thinking_buffer:
            return
        thinking_text += thinking_buffer
        thinking_buffer = ""
        await _broadcast_synthesis_thinking(stream_notifier, thinking_text, complete=False)

    async def _route_token(token: str) -> None:
        nonlocal buffer, thinking_buffer
        answer_delta, reasoning_delta = router.feed(token)
        if reasoning_delta:
            thinking_buffer += reasoning_delta
            if len(thinking_buffer) >= coalesce_min_chars or _COALESCE_NEWLINE_FLUSH in thinking_buffer:
                await _flush_thinking()
        if answer_delta:
            buffer += answer_delta
            if len(buffer) >= coalesce_min_chars or _COALESCE_NEWLINE_FLUSH in buffer:
                await _flush_buffer()

    if not hasattr(llm_model, "stream_chat_completion") and not hasattr(llm_model, "chat_completion_streaming"):
        # Single-shot fallback: no token stream on this object
        raw_response = ""
        try:
            if _is_cancelled():
                raise asyncio.CancelledError()
            if hasattr(llm_model, "chat_completion"):
                out = await llm_model.chat_completion(messages)
                if isinstance(out, dict):
                    raw_response = (out.get("content") or "").strip()
                else:
                    raw_response = str(out or "")
            elif hasattr(llm_model, "generate_response"):
                combined = "\n".join(
                    f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages
                )
                resolved_budget = budget or resolve_generation_budget(
                    llm_model,
                    purpose="final_synthesis",
                    input_token_estimate=input_token_estimate,
                )
                raw_response = await llm_model.generate_response(
                    combined,
                    max_tokens=resolved_budget.effective_output_tokens,
                )
                terminal = terminal_from_provider_reason("unknown")
            else:
                raw_response = ""
        except Exception as exc:
            logger.warning("Synthesis non-streaming fallback failed: %s", exc)
            raw_response = ""
        answer_delta, reasoning_delta = router.feed(raw_response)
        buffer += answer_delta
        thinking_buffer += reasoning_delta
        full_response = buffer
        buffer = ""
        if full_response and stream_notifier and hasattr(
            stream_notifier, "send_agent_result_streaming_chunk"
        ):
            try:
                await stream_notifier.send_agent_result_streaming_chunk(
                    token=full_response,
                    partial_result=full_response,
                    operation=operation,
                    source=stream_source,
                )
            except Exception as exc:
                logger.debug("Synthesis fallback chunk send failed: %s", exc)
    else:
        try:
            resolved_budget = budget or resolve_generation_budget(
                llm_model,
                purpose="final_synthesis",
                input_token_estimate=input_token_estimate,
            )
            if hasattr(llm_model, "stream_chat_completion"):
                async for event in llm_model.stream_chat_completion(messages, resolved_budget):
                    if _is_cancelled():
                        raise asyncio.CancelledError()
                    if event.is_terminal:
                        terminal = event.terminal or terminal_from_provider_reason("unknown")
                        continue
                    if event.text:
                        await _route_token(event.text)
            else:
                async for token in llm_model.chat_completion_streaming(messages):
                    if _is_cancelled():
                        raise asyncio.CancelledError()
                    if token:
                        await _route_token(token)
                terminal = terminal_from_provider_reason("unknown")
        except Exception as exc:
            logger.error("Synthesis streaming failed: %s", exc)
            terminal = terminal_from_error(exc)
            if not full_response and buffer:
                full_response = buffer
            buffer = ""

    tail_answer, tail_reasoning = router.flush()
    if tail_answer:
        buffer += tail_answer
    if tail_reasoning:
        thinking_buffer += tail_reasoning

    if buffer:
        await _flush_buffer(force=True)
    if thinking_buffer:
        await _flush_thinking(force=True)
    if router.unterminated:
        evidence.append(
            {
                "source": "synthesis.reasoning_block",
                "original_length": len(thinking_text),
                "retained_length": len(thinking_text),
                "affects_coverage": True,
                "reason": "unterminated_reasoning_block",
            }
        )
    if router.saw_reasoning:
        await _broadcast_synthesis_thinking(stream_notifier, thinking_text, complete=True)

    if stream_notifier and hasattr(stream_notifier, "send_agent_progress_update"):
        try:
            await stream_notifier.send_agent_progress_update(
                message="Reviewing the result before marking it complete…",
                details="Confirming the final answer matches the work that was performed.",
            )
        except Exception as exc:
            logger.debug("Finalizer progress send failed (non-fatal): %s", exc)

    if stream_notifier and hasattr(stream_notifier, "send_agent_result_streaming_complete"):
        try:
            await stream_notifier.send_agent_result_streaming_complete(
                final_result=full_response,
                operation=operation,
                source=stream_source,
            )
        except Exception as exc:
            logger.debug("Streaming complete send failed: %s", exc)

    return SynthesisResult(
        text=full_response,
        terminal=terminal,
        truncation_evidence=evidence,
        input_token_estimate=input_token_estimate,
        thinking_history=(
            [{
                "iteration": _FINAL_SYNTHESIS_THINKING_ITERATION,
                "text": thinking_text,
                "is_complete": True,
            }]
            if router.saw_reasoning and thinking_text
            else []
        ),
    )


async def run_final_synthesis_for_state(
    *,
    state: "PlanningState",
    final_input: str,
    agent_output: str,
    intermediate_steps: List[Any],
    llm_model: Any,
    stream_notifier: Any,
    cancel_event: Any = None,
) -> SynthesisResult:
    """
    High-level entry: build messages from state and stream synthesis.
    """
    ctx = state.context if isinstance(getattr(state, "context", None), dict) else {}
    from .synthesis_budget import build_budgeted_synthesis_input

    synthesis_input = build_budgeted_synthesis_input(
        llm_model=llm_model,
        system_prompt=FINAL_SYNTHESIS_SYSTEM,
        user_agent_task=getattr(state, "user_agent_task", "") or "",
        final_input=final_input,
        agent_output=agent_output,
        intermediate_steps=intermediate_steps,
        context=ctx,
    )
    _emit_synthesis_trace(
        "final_synthesis_started",
        model_type=type(llm_model).__name__,
        model_path=str(getattr(llm_model, "model_path", "")),
        requested_output_tokens=synthesis_input.budget.requested_output_tokens,
        effective_output_tokens=synthesis_input.budget.effective_output_tokens,
        input_token_estimate=synthesis_input.input_token_estimate,
        message_count=len(synthesis_input.messages),
    )
    result = await stream_synthesized_final_answer(
        llm_model=llm_model,
        messages=synthesis_input.messages,
        stream_notifier=stream_notifier,
        cancel_event=cancel_event,
        budget=synthesis_input.budget,
        truncation_evidence=synthesis_input.truncation_evidence,
        input_token_estimate=synthesis_input.input_token_estimate,
    )
    _emit_synthesis_trace(
        "final_synthesis_returned",
        model_type=type(llm_model).__name__,
        output_characters=len(result.text),
        terminal_reason=result.terminal.reason,
        terminal_provider_reason=result.terminal.provider_reason,
    )
    return result
