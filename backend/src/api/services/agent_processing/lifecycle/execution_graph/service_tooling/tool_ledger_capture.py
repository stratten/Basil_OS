"""Centralized, non-interfering capture of staged-agent tool evidence."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from api.services.agent_processing.shared.agent_runtime_context import (
    get_current_agent_context,
)
from api.services.agent_processing.lifecycle.runtime.ledger_json import (
    LedgerJSONNormalizationError,
)

logger = logging.getLogger(__name__)

_CAPTURE_STATE_KEY = "tool_ledger_capture"
_MAX_STRUCTURED_OBSERVATION_BYTES = 128_000


@dataclass(frozen=True)
class LedgerCaptureOutcome:
    """Whether a tool event resulted in a durable capture attempt."""

    attempted: bool
    deduplicated: bool = False
    persisted: bool = False


class ToolLedgerCaptureCoordinator:
    """Route raw-service and bounded-observation evidence to the work ledger."""

    async def capture_raw_service(
        self,
        *,
        service: str,
        method: str,
        parameters: Optional[Dict[str, Any]],
        result: Any,
    ) -> LedgerCaptureOutcome:
        """Capture an untruncated normalized service result."""
        return await self._capture(
            source="raw_service",
            service=service,
            method=method,
            tool_input=parameters or {},
            result=result,
        )

    async def capture_observation(
        self,
        *,
        tool_name: str,
        tool_input: Any,
        observation: Any = None,
        error: Optional[BaseException] = None,
        invocation_id: Optional[str] = None,
    ) -> LedgerCaptureOutcome:
        """Capture direct tool output without treating arbitrary text as evidence."""
        service, method = _tool_identity(tool_name)
        structured = _bounded_json_observation(observation)
        opaque_evidence = None
        if structured is None:
            recognized_invalid_call = _is_recognized_invalid_tool_call(
                tool_name=tool_name,
                tool_input=tool_input,
                observation=observation,
            )
            call_succeeded = error is None and not recognized_invalid_call
            opaque_evidence = _opaque_observation_evidence(
                tool_name=tool_name,
                observation=observation,
                error=error,
                succeeded=call_succeeded,
            )
            structured = {"success": call_succeeded, "result": {}}
        return await self._capture(
            source="normalized_observation",
            service=service,
            method=method,
            tool_input=tool_input,
            result=structured,
            error=error,
            invocation_id=invocation_id,
            opaque_evidence=opaque_evidence,
        )

    async def _capture(
        self,
        *,
        source: str,
        service: str,
        method: str,
        tool_input: Any,
        result: Any,
        error: Optional[BaseException] = None,
        invocation_id: Optional[str] = None,
        opaque_evidence: Optional[Dict[str, Any]] = None,
    ) -> LedgerCaptureOutcome:
        context = get_current_agent_context()
        root_task_id = context.get("root_task_id") or context.get("agent_task_id")
        if not root_task_id:
            return LedgerCaptureOutcome(attempted=False)

        canonical_id = _canonical_invocation_id(
            context=context,
            service=service,
            method=method,
            tool_input=tool_input,
            invocation_id=invocation_id,
        )
        capture_states = context.setdefault(_CAPTURE_STATE_KEY, {}).setdefault(
            "capture_states",
            {},
        )
        prior_state = capture_states.get(canonical_id)
        if prior_state in {"pending", "persisted_raw", "persisted_observation"}:
            return LedgerCaptureOutcome(attempted=False, deduplicated=True)
        if source == "normalized_observation" and prior_state == "failed_raw":
            pass
        elif prior_state == "failed_raw":
            return LedgerCaptureOutcome(attempted=False, deduplicated=True)
        capture_states[canonical_id] = "pending"
        receipt_key = _receipt_key(
            root_task_id=str(root_task_id),
            canonical_id=canonical_id,
            source=source,
            service=service,
            method=method,
        )
        try:
            from api.dependencies import get_sqlite_knowledge_service
            from api.services.agent_processing.lifecycle.runtime.agent_work_ledger_service import (
                AgentWorkLedgerService,
            )

            await AgentWorkLedgerService(
                get_sqlite_knowledge_service(),
            ).capture_tool_result(
                context=context,
                service=service,
                method=method,
                parameters=tool_input if isinstance(tool_input, dict) else {},
                result=result,
                error=error,
                receipt_key=receipt_key,
                evidence_source=source,
                opaque_evidence=opaque_evidence,
            )
        except (LedgerJSONNormalizationError, Exception) as capture_error:
            capture_states[canonical_id] = (
                "failed_raw" if source == "raw_service" else "failed_observation"
            )
            logger.warning(
                "Work-ledger capture failed task=%s service=%s method=%s source=%s "
                "invocation=%s error_type=%s: %s",
                root_task_id,
                service,
                method,
                source,
                canonical_id,
                type(capture_error).__name__,
                capture_error,
            )
            return LedgerCaptureOutcome(attempted=True)
        capture_states[canonical_id] = (
            "persisted_raw" if source == "raw_service" else "persisted_observation"
        )
        return LedgerCaptureOutcome(attempted=True, persisted=True)


def next_tool_invocation_id(
    context: Dict[str, Any],
    tool_name: str,
    tool_input: Any,
) -> str:
    """Allocate a task-local sequence shared by engine and guard capture."""
    state = context.setdefault(_CAPTURE_STATE_KEY, {})
    sequence = int(state.get("sequence", 0)) + 1
    state["sequence"] = sequence
    return f"{tool_name}:{_input_digest(tool_input)}:{sequence}"


def _tool_identity(tool_name: str) -> tuple[str, str]:
    marker = "_service_"
    if marker in tool_name:
        service, method = tool_name.rsplit(marker, 1)
        return f"{service}_service", method
    return "direct_tool", tool_name


def _canonical_invocation_id(
    *,
    context: Dict[str, Any],
    service: str,
    method: str,
    tool_input: Any,
    invocation_id: Optional[str],
) -> str:
    active_id = invocation_id or context.get("active_tool_invocation_id")
    if not active_id:
        active_id = context.get("tool_call_id") or _input_digest(tool_input)
    return f"{service}.{method}:{active_id}"


def _receipt_key(
    *,
    root_task_id: str,
    canonical_id: str,
    source: str,
    service: str,
    method: str,
) -> str:
    material = "|".join((root_task_id, canonical_id, service, method))
    return f"tool-ledger:{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


def _input_digest(value: Any) -> str:
    serialized = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:20]


def _bounded_json_observation(observation: Any) -> Optional[Any]:
    if isinstance(observation, (dict, list)):
        candidate = observation
    elif isinstance(observation, str):
        try:
            candidate = json.loads(observation)
        except (TypeError, ValueError):
            return None
    else:
        return None
    if not isinstance(candidate, (dict, list)):
        return None
    encoded = json.dumps(candidate, ensure_ascii=False, default=str).encode("utf-8")
    return candidate if len(encoded) <= _MAX_STRUCTURED_OBSERVATION_BYTES else None


def _is_recognized_invalid_tool_call(
    *,
    tool_name: str,
    tool_input: Any,
    observation: Any,
) -> bool:
    """True when ``observation`` is a known malformed-call response, not real work.

    LangChain's ``handle_validation_error`` converts a schema violation into a
    plain-text tool return instead of raising, so it never reaches ``error``
    here. Deferred import avoids a circular import with the guard module,
    which itself imports this module for ledger capture.
    """
    try:
        from .tool_call_repetition_guard import classify_invalid_tool_observation
    except Exception:  # pragma: no cover - defensive
        return False
    try:
        return classify_invalid_tool_observation(tool_name, tool_input, observation) is not None
    except Exception:  # pragma: no cover - defensive
        return False


def _opaque_observation_evidence(
    *,
    tool_name: str,
    observation: Any,
    error: Optional[BaseException],
    succeeded: bool,
) -> Dict[str, Any]:
    return {
        "tool_name": tool_name,
        "result_type": type(observation).__name__ if error is None else type(error).__name__,
        "result_size_bytes": _observation_size(observation),
        "success": succeeded,
    }


def _observation_size(value: Any) -> int:
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    try:
        return len(json.dumps(value, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        return 0
