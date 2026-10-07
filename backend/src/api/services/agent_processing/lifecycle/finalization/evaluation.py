"""Independent LLM evaluation for agent task finalization."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from api.core.models.reasoning.base_reasoning import (
    _accepts_keyword,
    has_unterminated_reasoning,
    strip_inline_reasoning,
)
from api.core.models.reasoning.streaming_contract import (
    GenerationBudget,
    resolve_generation_budget,
)

logger = logging.getLogger(__name__)

EVALUATOR_TIMEOUT_SECONDS = 120
LOCAL_EVALUATOR_TIMEOUT_SECONDS = 45
# The evaluator judges the delivered response against the request; it never needs raw tool payloads, so each bounded section keeps the prompt small enough to prefill quickly on a local model.
MAX_DELIVERED_RESPONSE_CHARS = 24000
MAX_AGENT_ANSWER_CHARS = 8000
MAX_STEPS_METADATA_CHARS = 6000
MAX_STEP_RESULT_CHARS = 240
CHARS_PER_TOKEN_ESTIMATE = 3
# Negative iterations are reserved sentinels: -1 is the final-synthesis pass, -2 is outcome verification.
VERIFIER_THINKING_ITERATION = -2

ReasoningSink = Callable[[str, bool], Awaitable[None]]
# A reasoning model that opened <think> but ran out of budget before closing it
# gets exactly one retry at a larger budget before the evaluator gives up. Any
# more risks masking a persistently over-long thinker as repeated latency.
_MAX_BUDGET_RETRIES = 1
_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


def normalize_outcome(value: Any, success: Optional[bool] = None) -> str:
    """Normalize model/free-form outcome labels to the finalizer payload contract."""
    if isinstance(value, str):
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "ok": "success",
            "succeeded": "success",
            "complete": "success",
            "completed": "success",
            "warning": "success",
            "warnings": "success",
            "success_with_warnings": "success",
            "completed_with_warnings": "success",
            "partial_success": "partial",
            "partially_successful": "partial",
            "failed": "failure",
            "error": "failure",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized in {"success", "partial", "failure"}:
            return normalized

    if success is False:
        return "failure"
    return "success"


def success_from_outcome(outcome: str) -> bool:
    """Map the richer user-facing outcome to the legacy boolean success flag."""
    return outcome == "success"


def has_failed_steps(steps: Optional[List[Dict[str, Any]]]) -> bool:
    """Return True if structured step metadata contains a failed tool attempt."""
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        if step.get("success") is False:
            return True
        status = step.get("status")
        if isinstance(status, str) and status.lower() in {"failed", "error"}:
            return True
    return False


def default_outcome_reason(
    outcome: str,
    *,
    has_tool_errors: bool,
    has_failed_steps: bool,
    has_content: bool,
) -> str:
    """Plain-language fallback reason used when model evaluation cannot provide one."""
    if outcome == "partial":
        if has_tool_errors or has_failed_steps:
            return (
                "I tried multiple ways to complete the request, but some operations failed "
                "or timed out. The result below is what I was able to recover."
            )
        return "I was only able to complete part of the request."
    if outcome == "failure":
        if has_content:
            return "I could not fully complete the request, but I preserved the useful information I found."
        return "I was not able to complete the request."
    return ""


def compose_outcome_intro(outcome: str, outcome_reason: Optional[str]) -> str:
    """Create the short explanation shown before non-clean results."""
    reason = (outcome_reason or "").strip()
    if outcome == "partial":
        return f"Partial result: {reason}" if reason else "Partial result."
    if outcome == "failure":
        return f"Could not complete: {reason}" if reason else "Could not complete the request."
    return ""


@dataclass
class FinalizerEvaluation:
    outcome: str
    success: bool
    outcome_reason: str
    technical_reason: str
    llm_reasoning: str
    should_retry: bool
    failure_basis: str
    coverage_status: str = "not_applicable"
    requested_item_count: Optional[int] = None
    delivered_item_count: Optional[int] = None
    truncation_prevents_verification: bool = False


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and len(value.strip()) > 0


def format_tool_error_history(tool_error_history: Optional[List[Dict[str, str]]]) -> str:
    """Format tool errors for the finalizer evaluation prompt."""
    if not tool_error_history:
        return "(No tool errors recorded — all tools executed cleanly)"
    lines = []
    for entry in tool_error_history:
        error_type = entry.get("type", "unknown")
        tool = entry.get("tool", "unknown")
        error = entry.get("error", "")
        lines.append(f"- [{error_type}] {tool}: {error}")
    return "\n".join(lines)


def _resolve_max_output_chars(llm_model: Any) -> int:
    """Determine how much agent output can fit into the finalizer prompt."""
    max_output_chars = 50000
    try:
        if hasattr(llm_model, "context_window"):
            max_output_chars = int((llm_model.context_window * CHARS_PER_TOKEN_ESTIMATE) * 0.5)
        elif hasattr(llm_model, "get_metadata"):
            metadata = llm_model.get_metadata()
            if hasattr(metadata, "context_window"):
                max_output_chars = int((metadata.context_window * CHARS_PER_TOKEN_ESTIMATE) * 0.5)
    except Exception as ctx_err:
        logger.debug("Could not determine the evaluator context window: %s", ctx_err)
    return max(2000, min(max_output_chars, MAX_DELIVERED_RESPONSE_CHARS))


def format_steps_metadata(steps: Optional[List[Dict[str, Any]]]) -> str:
    """Compact one-line-per-step summary; raw tool payloads are cut so a file-reading run cannot bloat the evaluator prompt."""
    if not steps:
        return "(No steps recorded)"
    lines: List[str] = []
    used = 0
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            line = f"{index + 1}. {str(step)[:MAX_STEP_RESULT_CHARS]}"
        else:
            parts = [
                f"{key}={step[key]}"
                for key in ("service", "method", "tool", "success", "status", "error")
                if step.get(key) is not None
            ]
            result = step.get("result")
            if result is not None:
                result_text = str(result)
                if len(result_text) > MAX_STEP_RESULT_CHARS:
                    result_text = result_text[:MAX_STEP_RESULT_CHARS] + "..."
                parts.append(f"result={result_text}")
            line = f"{index + 1}. " + ", ".join(parts)
        if used + len(line) > MAX_STEPS_METADATA_CHARS:
            lines.append(f"... {len(steps) - index} more step(s) omitted")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def _build_evaluation_context_block(evaluation_context: Optional[str]) -> str:
    if not _is_non_empty_string(evaluation_context):
        return ""
    return f"""
FOLLOW-UP / CHAIN CONTEXT:
{evaluation_context[:8000]}

Use this block to resolve references such as "that", "it", "the previous output", "same one", or "turn this into" before judging success.
"""


def build_evaluation_prompt(
    *,
    original_prompt: str,
    self_assessment: Optional[str],
    full_agent_output: str,
    max_output_chars: int,
    steps: List[Dict[str, Any]],
    tool_error_history: Optional[List[Dict[str, str]]],
    evaluation_context: Optional[str],
    material_outcome_brief: Optional[str] = None,
    agent_final_answer: Optional[str] = None,
) -> str:
    """Build the independent finalizer prompt."""
    evaluator_context_block = _build_evaluation_context_block(evaluation_context)
    agent_answer_block = ""
    if _is_non_empty_string(agent_final_answer):
        agent_answer_block = (
            "\nTHE AGENT'S OWN FINAL ANSWER (written by the agent loop before the delivered response was composed):\n"
            f"{agent_final_answer[:MAX_AGENT_ANSWER_CHARS]}\n"
        )
    material_outcome_block = ""
    if _is_non_empty_string(material_outcome_brief):
        material_outcome_block = (
            "\nMATERIAL CHANGE EVIDENCE (receipt-grounded):\n"
            f"{material_outcome_brief}\n"
        )
    return f"""You are an independent finalizer evaluating whether a agent_task execution was successful.

USER'S ORIGINAL REQUEST:
{original_prompt}
{evaluator_context_block}

AGENT'S SELF-ASSESSMENT:
{self_assessment or "(No self-assessment provided)"}

COMPLETE AGENT OUTPUT — THE DELIVERED RESPONSE (exactly what the user is shown):
{full_agent_output[:max_output_chars]}
{agent_answer_block}
EXECUTION STEPS METADATA (compact per-step summary):
{format_steps_metadata(steps)}

TOOL ERROR HISTORY (independent of agent's self-report — recorded by the tool execution layer):
{format_tool_error_history(tool_error_history)}
{material_outcome_block}

YOUR ROLE AS FINALIZER:
You are an independent observer with complete visibility into what the agent did. Your job is to determine:
1. Did the agent actually deliver what the user wanted?
2. If not, should the agent retry?

FIRST CHECK (BEFORE ANYTHING ELSE): does the DELIVERED RESPONSE answer the USER'S ORIGINAL REQUEST?
- Read the DELIVERED RESPONSE as the user will read it. If it does not address the request — for example it asks the user to restate or provide a request they already gave, says it has no request or no context, or is unrelated to the request — classify failure_basis "content_mismatch" with outcome=failure and should_retry=true. This overrides the ground-truth rule below, even when tools ran cleanly and THE AGENT'S OWN FINAL ANSWER looks correct, because the user never received that answer.
- Only after the delivered response is confirmed to address the request do the remaining guidelines apply.

TOOL OUTPUT IS GROUND TRUTH (HIGHEST PRIORITY):
- COMPLETE AGENT OUTPUT and EXECUTION STEPS METADATA contain facts the agent gathered with tools (web search, file reads, app queries). Treat those facts as authoritative.
- Your own training knowledge has a fixed cutoff and is NOT a reliable source of current facts. Do NOT mark a result failed, fabricated, speculative, hallucinated, or "not real" because a named entity (a product, model version, price, person, date, or event) is unfamiliar to you or appears newer than what you remember. Unfamiliarity and recency are NOT evidence of failure.
- If the tools executed without errors (see TOOL ERROR HISTORY) and returned substantive content that answers the request, you MUST NOT classify the outcome as failure or partial on the grounds that you personally doubt the gathered facts.
- The only admissible evidence of failure is the tool trace and error history, never your prior beliefs about what exists.

EVALUATION GUIDELINES:
- IGNORE technical step counts - focus on USER'S ACTUAL INTENT
- If user wanted "email summary" and you see a comprehensive summary in the output → SUCCESS
- If user wanted "email summary" but you only see error messages or empty results → FAILURE
- If agent produced substantial useful content that directly answers the request → SUCCESS
- If the request names an explicit number of deliverables, count the actual delivered numbered items. A sentence claiming "all N" is not evidence.
- If output ends mid-item or truncation evidence prevents verification, classify as partial with should_retry=true.
- Tool failures are evidence, not an automatic failure. If earlier tools failed but a later fallback verified the requested scope and satisfies the request, classify as success.
- An internal retry or fallback that produced a complete, verified result is SUCCESS, not a warning. Do not downgrade it merely because an earlier attempt failed before a later one succeeded; that is a normal implementation detail with no user-visible consequence.
- If a real residual gap remains after useful work was delivered, such as missing coverage, partial scope, an unverified side effect, or a required follow-up step, classify the result as partial. A failed-then-recovered attempt with no residual gap is success.
- Use partial when some useful content was delivered but a meaningful part of the user's request remains incomplete.
- Use failure only when the request was not delivered in a useful way.
- A successful process exit or script "SUCCESS" string is not enough for a user-visible write. If structured tool output says a material write is unverified or failed, classify as partial or failure unless later tool evidence verifies the same intended outcome through any path.
- LOOK FOR ACTUAL CONTENT: summaries, analyses, file creations, data, answers
- Don't be fooled by agent's self-assessment - check if content actually exists
- For follow-up requests, resolve pronouns and references against FOLLOW-UP / CHAIN CONTEXT before deciding whether the output matches the user's intent.

"NOT FOUND" FOR THE USER'S OWN DATA IS SUSPICIOUS (scope: local/app retrieval only):
- Applies ONLY when the agent searched the USER'S OWN data via local/app tools (emails, files, messages, calendar, notes) and reported "not found" / "no results" / "none matching". Silent tool failure is common there.
- Does NOT apply to web search, research, or external lookups whose deliverable is information the agent gathers. For those, returning substantive gathered information IS success, even if the topic is unfamiliar to you.
- In scope: "not found" is a clean success only if the agent tried MULTIPLE distinct approaches (different tools, parameters, or strategies) and still found nothing. If it tried only 1-2, or its output mentions errors/exceptions/truncation, or it offers to "search elsewhere", treat as failure with should_retry=true.
- Red flags of tool failure vs genuine absence: "error", "failed", "truncated", "exception", agent offering to "try again" or "search other folders".
- If TOOL ERROR HISTORY includes timeout, truncation, coverage_uncertain, or empty_unverified for the retrieval that supports a "none found" answer, treat the answer as partial/failure unless the later output explicitly verifies equivalent coverage through another strategy.

RESEARCH THAT ESTABLISHES THE EXACT THING DOES NOT EXIST IS SUCCESS (scope: web search, research, and external lookups):
- If the agent searched thoroughly with tools that ran cleanly, transparently reported that the exact item the user described does not exist or could not be found in the real world (for example no dedicated shop of that kind in that area), and delivered the closest useful alternatives, classify the outcome as success with failure_basis "none".
- The non-existence of the exact item is a finding about the world, not a residual gap in the agent's work. Do not classify it as partial merely because the literal ask could not be satisfied as phrased.
- This does not apply when the agent stopped early, when tools errored or truncated, when alternatives are missing or unrelated, or when part of the request the agent could have completed was left undone.

DECISION:
- If the agent clearly delivered what was requested → outcome=success, success=true (this INCLUDES cases where the agent delivered a complete, verified result after an internal retry or fallback — a recovered failure is still a clean success)
- If the agent delivered useful work BUT there is a genuine residual gap the user should act on or know about (missing coverage, partial scope, an unverified side effect, or a required follow-up step) → outcome=partial, success=false.
- If the agent produced useful but incomplete output → outcome=partial, success=false
- If the agent failed or produced insufficient output → outcome=failure, success=false (and consider requesting retry)
- If the agent reports "not found" for a search/retrieval request → LEAN TOWARD should_retry=true unless overwhelming evidence of genuine absence

failure_basis (REQUIRED): the single primary reason the outcome is not a clean success.
- "none": outcome is success.
- "tool_failure": tools errored/timed out/were truncated and the request was not recovered.
- "content_missing": tools worked but the requested content genuinely does not exist in the searched source.
- "content_mismatch": the produced output does not actually address what the user asked for.
    - "model_plausibility_doubt": your ONLY reservation is that tool-returned facts seem unfamiliar, too new, implausible, or "not real" to you. In this case you MUST prefer outcome=success, because tool output is ground truth and your training knowledge is not admissible evidence.
    - "context_ambiguity": your ONLY reservation is that you could not resolve a pronoun or reference (such as "that", "it", or "the previous output") against FOLLOW-UP / CHAIN CONTEXT, while the delivered content is otherwise substantive and there are no tool errors, no failed steps, and no unresolved material-write review issues.

Respond with ONLY a JSON object:
{{
  "outcome": "success" | "partial" | "failure",
  "success": true/false,
  "failure_basis": "none" | "tool_failure" | "content_missing" | "content_mismatch" | "model_plausibility_doubt" | "context_ambiguity",
  "user_reason": "plain-language explanation for the user when outcome is not success; empty string for clean success",
  "technical_reason": "brief internal explanation of why this outcome was chosen",
  "should_retry": true/false (whether agent should try again),
  "coverage_status": "complete" | "incomplete" | "not_applicable" | "indeterminate",
  "requested_item_count": number|null,
  "delivered_item_count": number|null,
  "truncation_prevents_verification": true|false
}}"""


def _extract_json_object(text: str) -> str:
    """Locate a brace-balanced JSON object inside text that may carry leftover
    prose around it. Structural scanning only (brace depth counting), never
    prose/keyword matching, mirroring the extraction step in
    local_tool_call_parser.safe_parse_json."""
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def parse_evaluation_response(llm_response: str) -> FinalizerEvaluation:
    """Parse the finalizer LLM JSON response into normalized fields.

    A reasoning model's response may still carry a complete <think> block
    ahead of the JSON verdict (the caller requests preserve_thinking so it can
    detect an unterminated block itself before this ever runs). Strip a
    complete block the same way every other consumer of this tag does before
    attempting to parse.
    """
    response_text = llm_response.strip()
    if _THINK_OPEN in response_text:
        response_text = strip_inline_reasoning(response_text, _THINK_OPEN, _THINK_CLOSE).strip()
    if "```json" in response_text:
        response_text = response_text.split("```json")[1].split("```")[0].strip()
    elif "```" in response_text:
        response_text = response_text.split("```")[1].split("```")[0].strip()

    try:
        evaluation = json.loads(response_text)
    except json.JSONDecodeError:
        evaluation = json.loads(_extract_json_object(response_text))
    raw_success = evaluation.get("success")
    outcome = normalize_outcome(
        evaluation.get("outcome"),
        raw_success if isinstance(raw_success, bool) else None,
    )
    if isinstance(raw_success, bool):
        success = raw_success
    else:
        success = success_from_outcome(outcome)
    if outcome in {"success", "partial", "failure"}:
        success = success_from_outcome(outcome)

    outcome_reason = str(
        evaluation.get("user_reason")
        or evaluation.get("reasoning")
        or ""
    ).strip()
    technical_reason = str(
        evaluation.get("technical_reason")
        or evaluation.get("reasoning")
        or ""
    ).strip()
    llm_reasoning = technical_reason or outcome_reason
    should_retry = bool(evaluation.get("should_retry", False))

    failure_basis = str(evaluation.get("failure_basis") or "").strip().lower().replace("-", "_").replace(" ", "_")
    if failure_basis not in {
        "none",
        "tool_failure",
        "content_missing",
        "content_mismatch",
        "model_plausibility_doubt",
        "context_ambiguity",
    }:
        failure_basis = ""

    return FinalizerEvaluation(
        outcome=outcome,
        success=success,
        outcome_reason=outcome_reason,
        technical_reason=technical_reason,
        llm_reasoning=llm_reasoning,
        should_retry=should_retry,
        failure_basis=failure_basis,
        coverage_status=str(evaluation.get("coverage_status") or "not_applicable"),
        requested_item_count=(
            int(evaluation["requested_item_count"])
            if isinstance(evaluation.get("requested_item_count"), int)
            else None
        ),
        delivered_item_count=(
            int(evaluation["delivered_item_count"])
            if isinstance(evaluation.get("delivered_item_count"), int)
            else None
        ),
        truncation_prevents_verification=bool(evaluation.get("truncation_prevents_verification", False)),
    )


async def evaluate_finalizer_with_llm(
    *,
    llm_model: Any,
    original_prompt: str,
    self_assessment: Optional[str],
    full_agent_output: str,
    steps: List[Dict[str, Any]],
    tool_error_history: Optional[List[Dict[str, str]]],
    evaluation_context: Optional[str],
    material_outcome_brief: Optional[str] = None,
    agent_final_answer: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    on_reasoning: Optional[ReasoningSink] = None,
) -> Optional[FinalizerEvaluation]:
    """Run independent LLM finalization, returning None when fallback is needed.

    ``timeout_seconds`` is a total deadline across the budget-doubling retry. ``on_reasoning`` receives the verifier's growing reasoning text (and a final ``complete=True`` call) when the model can stream.
    """
    max_output_chars = _resolve_max_output_chars(llm_model)
    evaluation_prompt = build_evaluation_prompt(
        original_prompt=original_prompt,
        self_assessment=self_assessment,
        full_agent_output=full_agent_output,
        max_output_chars=max_output_chars,
        steps=steps,
        tool_error_history=tool_error_history,
        evaluation_context=evaluation_context,
        material_outcome_brief=material_outcome_brief,
        agent_final_answer=agent_final_answer,
    )
    prompt_tokens_estimate = len(evaluation_prompt) // CHARS_PER_TOKEN_ESTIMATE
    timeout = timeout_seconds if timeout_seconds is not None else EVALUATOR_TIMEOUT_SECONDS
    deadline = time.monotonic() + timeout
    relay = _ReasoningRelay(on_reasoning) if on_reasoning is not None else None
    use_streaming = relay is not None and hasattr(llm_model, "stream_chat_completion")
    logger.info(
        "Outcome evaluation starting: prompt_chars=%d prompt_tokens~%d timeout=%.0fs streaming=%s",
        len(evaluation_prompt),
        prompt_tokens_estimate,
        timeout,
        use_streaming,
    )
    try:
        return await _run_evaluation_attempts(
            llm_model=llm_model,
            evaluation_prompt=evaluation_prompt,
            prompt_tokens_estimate=prompt_tokens_estimate,
            deadline=deadline,
            timeout=timeout,
            relay=relay if use_streaming else None,
        )
    finally:
        if relay is not None:
            await relay.close()


class _ReasoningRelay:
    """Forwards the verifier's reasoning to the UI in coalesced updates and guarantees a final complete=True call."""

    _MIN_CHARS_BETWEEN_SENDS = 80

    def __init__(self, sink: ReasoningSink) -> None:
        self._sink = sink
        self.text = ""
        self._sent_length = 0
        self._closed = False

    async def push(self, delta: str) -> None:
        if not delta or self._closed:
            return
        self.text += delta
        if len(self.text) - self._sent_length >= self._MIN_CHARS_BETWEEN_SENDS:
            await self._send(False)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.text:
            await self._send(True)

    async def _send(self, complete: bool) -> None:
        self._sent_length = len(self.text)
        try:
            await self._sink(self.text, complete)
        except Exception as exc:
            logger.debug("Verifier reasoning relay failed (non-fatal): %s", exc)


async def _stream_evaluation_text(
    llm_model: Any,
    prompt: str,
    budget: GenerationBudget,
    max_tokens: int,
    relay: _ReasoningRelay,
) -> str:
    """Stream the evaluator call, relaying reasoning live, and return the raw text including any think block so the caller's unterminated-reasoning handling still applies."""
    from api.services.agent_processing.lifecycle.execution_graph.agent_result_synthesis import (
        _ReasoningTagRouter,
    )

    router = _ReasoningTagRouter()
    raw = ""
    attempt_budget = dataclasses.replace(budget, effective_output_tokens=max_tokens)
    messages = [{"role": "user", "content": prompt}]
    async for event in llm_model.stream_chat_completion(messages, attempt_budget):
        if event.is_terminal:
            terminal = event.terminal
            if terminal is not None and terminal.error_message:
                raise RuntimeError(terminal.error_message)
            continue
        if not event.text:
            continue
        raw += event.text
        _, reasoning_delta = router.feed(event.text)
        await relay.push(reasoning_delta)
    _, tail_reasoning = router.flush()
    await relay.push(tail_reasoning)
    return raw


async def _run_evaluation_attempts(
    *,
    llm_model: Any,
    evaluation_prompt: str,
    prompt_tokens_estimate: int,
    deadline: float,
    timeout: float,
    relay: Optional[_ReasoningRelay],
) -> Optional[FinalizerEvaluation]:
    budget = resolve_generation_budget(
        llm_model,
        purpose="structured",
        input_token_estimate=prompt_tokens_estimate,
    )
    # Only llama.cpp-family adapters accept this kwarg; passing it to a model
    # that doesn't declare it raises TypeError (same hazard enable_web_search
    # caused elsewhere), so gate it the same way base_reasoning.py does.
    supports_preserve_thinking = relay is not None or _accepts_keyword(
        llm_model.generate_response, "preserve_thinking"
    )
    max_tokens = budget.effective_output_tokens
    token_ceiling = budget.model_max_output_tokens or max_tokens

    attempt = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(f"⚠️ FINALIZER LLM EVALUATION TIMED OUT (limit {timeout:.0f}s), falling back to mechanical check")
            return None
        started_at = time.monotonic()
        try:
            if relay is not None:
                generation = _stream_evaluation_text(llm_model, evaluation_prompt, budget, max_tokens, relay)
            else:
                call_kwargs: Dict[str, Any] = {"max_tokens": max_tokens}
                if supports_preserve_thinking:
                    # Without this, an adapter that interleaves reasoning with the
                    # answer raises instead of returning text once the budget runs
                    # out mid-thought, which this function needs to see itself to
                    # retry with more budget rather than treating it as an error.
                    call_kwargs["preserve_thinking"] = True
                generation = llm_model.generate_response(evaluation_prompt, **call_kwargs)
            llm_response = await asyncio.wait_for(generation, timeout=remaining)
            duration_s = time.monotonic() - started_at
        except asyncio.TimeoutError:
            duration_s = time.monotonic() - started_at
            print(
                f"⚠️ FINALIZER LLM EVALUATION TIMED OUT after {duration_s:.2f}s "
                f"(limit {timeout:.0f}s), falling back to mechanical check"
            )
            return None
        except Exception as e:
            duration_s = time.monotonic() - started_at
            print(f"⚠️ FINALIZER LLM EVALUATION FAILED after {duration_s:.2f}s: {e}, falling back to mechanical check")
            return None

        ran_out_of_budget_mid_thought = (
            supports_preserve_thinking
            and _THINK_OPEN in llm_response
            and has_unterminated_reasoning(llm_response, _THINK_OPEN, _THINK_CLOSE)
        )
        if ran_out_of_budget_mid_thought and attempt < _MAX_BUDGET_RETRIES and max_tokens < token_ceiling:
            attempt += 1
            max_tokens = min(token_ceiling, max_tokens * 2)
            print(
                f"⚠️ FINALIZER LLM EVALUATION: reasoning consumed the entire "
                f"{duration_s:.2f}s budget before answering; retrying once with "
                f"max_tokens={max_tokens}"
            )
            continue

        try:
            result = parse_evaluation_response(llm_response)
        except Exception as e:
            print(
                f"⚠️ FINALIZER LLM EVALUATION: could not parse a verdict after {duration_s:.2f}s "
                f"({'reasoning never closed' if ran_out_of_budget_mid_thought else e}), "
                "falling back to mechanical check"
            )
            return None

        print(
            f"🤖 FINALIZER LLM EVALUATION ({duration_s:.2f}s): outcome={result.outcome}, "
            f"success={result.success}, reasoning={result.llm_reasoning}, should_retry={result.should_retry}"
        )
        return result
