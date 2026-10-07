"""Async service execution wrapper for LangChain StructuredTool instances."""

import asyncio
import json
import logging
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Type

from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context
from api.services.agent_processing.lifecycle.execution_graph.tool_run_watchdog import (
    ToolRunWatchdogStopped,
    attach_tool_cancel_handle,
    detach_tool_cancel_handle,
    record_tool_progress,
)

from .models import BaseModel, BaseTool


def classify_error(error_value: Any) -> str:
    lower_error = str(error_value or "").lower()
    if "timeout" in lower_error or "timed out" in lower_error:
        return "timeout"
    if "permission" in lower_error or "access not allowed" in lower_error:
        return "permission"
    if "coverage" in lower_error or "unverified" in lower_error:
        return "empty_unverified"
    return "exception"


def json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        payload = [json_safe(item) for item in value]
        coverage_metadata = getattr(value, "coverage_metadata", None)
        if coverage_metadata is not None:
            return {
                "items": payload,
                "coverage_metadata": coverage_metadata,
            }
        return payload
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return value


def redact_tool_parameters_for_log(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Avoid persisting direct text payloads in generic tool debug logs."""
    return {
        key: (
            f"<redacted text:{len(value.encode('utf-8'))} bytes>"
            if key == "content" and isinstance(value, str)
            else value
        )
        for key, value in parameters.items()
    }


def _get_result_field(result_payload: Any, field_name: str) -> Any:
    if isinstance(result_payload, dict):
        return result_payload.get(field_name)
    return getattr(result_payload, field_name, None)


def _summarize_outcome_review(result_payload: Any) -> str:
    review = _get_result_field(result_payload, "outcome_review")
    if isinstance(review, dict):
        summary = review.get("summary")
        if summary:
            return str(summary)
    status = _get_result_field(result_payload, "outcome_verification_status")
    return f"Material outcome requires review: {status or 'unverified'}"


def _maybe_record_prepared_file_read(
    result_payload: Any,
    file_read_log: List[Dict[str, str]],
) -> None:
    """Capture read/retrieved file references before tool output truncation."""
    if _get_result_field(result_payload, "result_kind") != "prepared":
        return

    file_path = _get_result_field(result_payload, "file_path")
    if not isinstance(file_path, str) or not file_path.strip():
        return

    full_path = file_path.strip()
    file_name = _get_result_field(result_payload, "file_name")
    if isinstance(file_name, str) and file_name.strip():
        name = file_name.strip()
    else:
        name = full_path.rsplit("/", 1)[-1] or full_path

    key = (name, full_path)
    seen = {(entry.get("name", ""), entry.get("full_path", "")) for entry in file_read_log}
    if key in seen:
        return

    file_read_log.append({
        "name": name,
        "full_path": full_path,
        "operation": "read",
    })


def create_tool_function(
    factory,
    tool_name: str,
    description: str,
    input_model: Type[BaseModel],
    service_name: str,
    method_name: str,
    progress_metadata: Dict[str, str],
) -> BaseTool:
    """Create a proper LangChain Tool using @tool decorator and closure pattern."""

    # Capture dependencies in closure for the tool function
    execution_engine = factory.service_execution_engine
    tool_logger = logging.getLogger(f"{__name__}.{tool_name}")
    max_output_chars = factory.max_tool_output_chars  # Capture for closure
    context_tokens = factory.max_context_tokens  # For logging context
    tool_error_log = factory.tool_error_log  # Shared mutable list for finalizer visibility
    file_read_log = getattr(factory, "file_read_log", [])  # Shared: retrieved/read files for finalizer

    # Create the actual tool function that will be wrapped by @tool
    # CRITICAL: Make this async so the agent executor properly awaits completion
    async def tool_function(**kwargs) -> str:
        """Execute the service method via the execution engine."""
        agent_context = get_current_agent_context()
        agent_task_id = agent_context.get("agent_task_id")
        registry_tool_name = tool_name
        try:
            tool_logger.info(f"🔧 TOOL EXECUTION: {service_name}.{method_name}")
            tool_logger.debug(
                "🔧 TOOL PARAMETERS: %s",
                redact_tool_parameters_for_log(kwargs),
            )
            record_tool_progress(
                agent_task_id=agent_task_id,
                tool_name=registry_tool_name,
                status="service_running",
                progress_kind="tool_coroutine_entered",
                service_name=service_name,
                method_name=method_name,
            )

            # Execute using existing service execution engine with proper async/await
            # This ensures the agent waits for long-running operations (like 10s AppleScript calls)
            record_tool_progress(
                agent_task_id=agent_task_id,
                tool_name=registry_tool_name,
                status="service_running",
                progress_kind="service_method_await_started",
                service_name=service_name,
                method_name=method_name,
            )
            service_task = asyncio.ensure_future(
                execution_engine.execute_service_method(service_name, method_name, kwargs)
            )
            watched_run = attach_tool_cancel_handle(
                agent_task_id=agent_task_id,
                tool_name=registry_tool_name,
                handle=service_task,
            )
            try:
                result = await service_task
            except asyncio.CancelledError:
                stop_reason = watched_run.force_cancel_reason if watched_run is not None else None
                current_task = asyncio.current_task()
                if stop_reason is None or (current_task is not None and current_task.cancelling()):
                    raise
                raise ToolRunWatchdogStopped(stop_reason) from None
            finally:
                detach_tool_cancel_handle(watched_run)
            record_tool_progress(
                agent_task_id=agent_task_id,
                tool_name=registry_tool_name,
                status="serializing",
                progress_kind="service_method_returned",
                service_name=service_name,
                method_name=method_name,
                success=getattr(result, "success", None),
            )
            if hasattr(result, "success") and getattr(result, "success") is False:
                result_error = getattr(result, "error", None)
                tool_error_log.append({
                    "tool": f"{service_name}.{method_name}",
                    "error": str(result_error)[:500],
                    "type": classify_error(result_error),
                })

            result_payload = getattr(result, "result", None)
            _maybe_record_prepared_file_read(result_payload, file_read_log)
            if _get_result_field(result_payload, "needs_outcome_review") is True:
                tool_error_log.append({
                    "tool": f"{service_name}.{method_name}",
                    "error": _summarize_outcome_review(result_payload)[:500],
                    "type": "outcome_unverified",
                })

            coverage_metadata = getattr(result_payload, "coverage_metadata", None)
            if isinstance(coverage_metadata, dict) and coverage_metadata:
                coverage_complete = str(coverage_metadata.get("coverage_complete", "")).lower()
                if coverage_complete in {"false", "0", "no"}:
                    tool_error_log.append({
                        "tool": f"{service_name}.{method_name}",
                        "error": (
                            "Email retrieval coverage is incomplete or uncertain: "
                            f"{coverage_metadata}"
                        )[:500],
                        "type": "coverage_uncertain",
                    })

            # Normalize ExecutionResult to JSON if present; otherwise serialize dicts/lists
            output_str = None
            record_tool_progress(
                agent_task_id=agent_task_id,
                tool_name=registry_tool_name,
                status="serializing",
                progress_kind="output_serialization_started",
                service_name=service_name,
                method_name=method_name,
            )
            try:
                if all(hasattr(result, attr) for attr in [
                    "success", "result", "data", "error", "service", "method", "parameters_used", "execution_time"
                ]):
                    envelope = {
                        "success": getattr(result, "success"),
                        "result": json_safe(getattr(result, "result")),
                        "data": json_safe(getattr(result, "data")),
                        "error": getattr(result, "error"),
                        "service": getattr(result, "service"),
                        "method": getattr(result, "method"),
                        "parameters_used": getattr(result, "parameters_used"),
                        "execution_time": getattr(result, "execution_time"),
                        **(
                            {
                                "agent_task_artifact": json_safe(
                                    getattr(result, "agent_task_artifact")
                                ),
                            }
                            if getattr(result, "agent_task_artifact", None) is not None
                            else {}
                        ),
                    }
                    output_str = json.dumps(envelope, ensure_ascii=False)
                # Prefer service-provided data dicts only when the result is not an ExecutionResult envelope.
                elif hasattr(result, "data") and isinstance(getattr(result, "data"), dict):
                    output_str = json.dumps(getattr(result, "data"), ensure_ascii=False)
                # Fall back to raw result if it's a dict/list
                elif isinstance(result, (dict, list)):
                    output_str = json.dumps(json_safe(result), ensure_ascii=False)
                elif hasattr(result, "result") and isinstance(getattr(result, "result"), (dict, list)):
                    output_str = json.dumps(json_safe(getattr(result, "result")), ensure_ascii=False)
            except Exception:
                pass

            # Fallback string representation
            if output_str is None:
                output_str = str(result)

            # TRUNCATION: Prevent oversized tool outputs from exceeding context limits
            # This is critical for preventing token limit errors when tools return large files
            if len(output_str) > max_output_chars:
                original_size = len(output_str)
                # Reserve space for truncation metadata (~1000 chars)
                preview_size = max_output_chars - 1500

                # Try to preserve structure - look for JSON boundaries
                preview_content = output_str[:preview_size]

                truncated_info = {
                    "truncated": True,
                    "original_size_chars": original_size,
                    "original_size_bytes": len(output_str.encode('utf-8')),
                    "truncated_to_chars": max_output_chars,
                    "context_limit_tokens": context_tokens,
                    "message": (
                        f"Tool output truncated from {original_size:,} chars to {max_output_chars:,} chars "
                        f"to fit context window ({context_tokens:,} tokens). "
                        f"The full content was too large to include in agent memory."
                    ),
                    "content_preview": preview_content + "\n\n...[CONTENT TRUNCATED]...",
                    **(
                        {
                            "agent_task_artifact": json_safe(
                                getattr(result, "agent_task_artifact")
                            ),
                        }
                        if getattr(result, "agent_task_artifact", None) is not None
                        else {}
                    ),
                }
                output_str = json.dumps(truncated_info, ensure_ascii=False)
                tool_logger.warning(
                    f"⚠️ TOOL OUTPUT TRUNCATED: {service_name}.{method_name} - "
                    f"{original_size:,} chars → {len(output_str):,} chars "
                    f"(limit: {max_output_chars:,} based on {context_tokens:,} token context)"
                )
                tool_error_log.append({
                    "tool": f"{service_name}.{method_name}",
                    "error": f"Output truncated from {original_size:,} to {max_output_chars:,} chars — agent may not see all results",
                    "type": "truncation"
                })

            record_tool_progress(
                agent_task_id=agent_task_id,
                tool_name=registry_tool_name,
                status="returned",
                progress_kind="tool_returned_to_langchain",
                service_name=service_name,
                method_name=method_name,
                output_chars=len(output_str or ""),
            )
            return output_str

        except Exception as e:
            error_msg = f"Tool execution failed for {service_name}.{method_name}: {str(e)}"
            tool_logger.error(error_msg)
            tool_error_log.append({
                "tool": f"{service_name}.{method_name}",
                "error": str(e)[:500],
                "type": "exception"
            })
            record_tool_progress(
                agent_task_id=agent_task_id,
                tool_name=registry_tool_name,
                status="returned",
                progress_kind="tool_exception_returned",
                service_name=service_name,
                method_name=method_name,
                error=str(e)[:500],
            )
            return f"ERROR: {error_msg}"

    # Set function metadata for better tool documentation
    tool_function.__name__ = tool_name
    tool_function.__doc__ = description

    # Use the @tool decorator to create a proper LangChain tool
    # Note: We create the tool dynamically by calling the decorator function
    from langchain_core.tools import StructuredTool

    # CRITICAL: Explicitly tell StructuredTool this is a coroutine function
    # so it uses arun instead of run, ensuring proper async/await handling
    return StructuredTool.from_function(
        func=tool_function,
        name=tool_name,
        description=description,
        args_schema=input_model,
        metadata=progress_metadata,
        coroutine=tool_function,
    )
