"""
LangGraph Progress Tracking and Live Streaming System

This module provides the real-time progress reporting infrastructure for LangGraph agent execution:
- LiveProgressCallbackHandler: Streams real-time progress via WebSockets using tool metadata templates
- Template rendering system: Converts tool metadata into user-friendly progress descriptions
- PlanningState: Typed state structure for LangGraph workflows

The progress system uses tool metadata to generate rich, contextual progress messages instead of
generic phrases, providing users with meaningful real-time updates during agent execution.

Note: Post-execution step parsing is handled separately in agent_step_parser.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

# Existing modules for state types
from ..planning.request_analyzer import RequestAnalysis
from ...service_capabilities.service_method_planner import ServiceCapabilityCache
from ..runtime.agent_timeline_contract import timeline_timestamp
from ..runtime.workflow_results import WorkflowExecutionResult

# Tool integration
from .service_tools import ToolCreationResult
from .tool_run_watchdog import get_tool_run_registry


# === LangChain callback system imports ===
try:
    from langchain_core.callbacks import BaseCallbackHandler  # type: ignore
except Exception:  # pragma: no cover - if callbacks unavailable, we simply won't stream
    BaseCallbackHandler = object  # type: ignore


@dataclass
class PlanningState:
    """
    Typed state carried through the streamlined agent graph.
    
    The agent creates execution steps dynamically - no pre-planned todos required.
    """

    user_agent_task: str
    context: Dict[str, Any]

    # Analysis phase
    request_analysis: Optional[RequestAnalysis] = None
    capability_cache: Optional[ServiceCapabilityCache] = None
    
    # Tool-based execution state
    available_tools: Optional[ToolCreationResult] = None
    tool_execution_results: Optional[List[Dict[str, Any]]] = None
    execution_result: Optional[WorkflowExecutionResult] = None

    # Agent-owned skill selection (decided before execution; primitives only)
    selected_skill_section: Optional[str] = None
    selected_skill_slug: Optional[str] = None

    # Finalization output (must persist so downstream can pass-through untouched)
    final_envelope: Optional[Dict[str, Any]] = None
    workflow_result: Optional[str] = None


class LiveProgressCallbackHandler(BaseCallbackHandler):
    """LangChain callback handler that streams intermediary progress to the frontend.

    Uses tool metadata templates to generate rich, contextual progress descriptions instead
    of generic phrases. Emits dynamic_step_added on tool start and dynamic_step_updated on tool end.
    """

    def __init__(self, notifier, todo_id, available_tools=None, turn_timing=None):
        import logging
        import time
        self.logger = logging.getLogger(__name__)
        self.notifier = notifier
        self.todo_id = todo_id
        self._turn_timing = turn_timing
        self._step_ids_by_run = {}
        self._agent_iteration_count = 0
        self._last_completed_tool_desc = None
        self._last_agent_action_msg = None
        self._last_agent_action_time = 0.0
        self._last_rich_message_time = 0.0
        self._last_tool_denied = False
        self._heartbeat_tasks_by_run = {}
        self._heartbeat_interval_seconds = 20
        self._finalizer_stream_text = ""
        self._finalizer_streamed_chars = 0
        # P1: live reasoning stream for the agent loop's own generation. Coalesced
        # so the frequent on_llm_new_token callbacks do not flood the websocket.
        # Reset per LLM call (on_llm_end) so a.thinking reflects the in-progress call.
        self._reasoning_stream_text = ""
        self._reasoning_buffer = ""
        self._reasoning_coalesce_min_chars = 80
        self._reasoning_first_token_marked = False
        self._thinking_history: List[Dict[str, Any]] = []
        self._execution_timeline: List[Dict[str, Any]] = []
        self._tool_run_registry = get_tool_run_registry()
        # Incremented only in on_llm_end (never on_chain_start, which fires
        # before the network call resolves). Used by execute_with_token_retry
        # to decide whether a first-attempt unreachable error is eligible for
        # local-model fallback: eligible only while this is still 0.
        self.completed_llm_calls = 0
        # Create tool lookup for metadata access
        self.tool_metadata = {}
        if available_tools:
            for tool in available_tools:
                if hasattr(tool, 'metadata') and tool.metadata:
                    self.tool_metadata[tool.name] = tool.metadata

    def _record_timeline_entry(self, entry_type: str, content: str, **extra) -> Dict[str, Any]:
        from datetime import datetime
        entry = {
            "type": entry_type,
            "timestamp": datetime.now().isoformat(),
            "content": content,
        }
        entry.update(extra)
        self._execution_timeline.append(entry)
        return entry

    def _record_step(self, message: str, is_tool: bool = False, is_complete: bool = False) -> None:
        entry_type = "tool_complete" if is_complete else ("tool_start" if is_tool else "step")
        self._record_timeline_entry(entry_type, message)

    def _summarize_value(self, value: Any, max_chars: int = 900) -> Any:
        """Return a readable, bounded representation safe for the detail tray."""
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            compact = value.strip()
            return compact[:max_chars] + "…" if len(compact) > max_chars else compact
        if isinstance(value, list):
            summarized = [self._summarize_value(item, max_chars=max(120, max_chars // 3)) for item in value[:8]]
            if len(value) > 8:
                summarized.append(f"… {len(value) - 8} more items")
            return summarized
        if isinstance(value, dict):
            blocked_keys = {"api_key", "authorization", "password", "secret", "token"}
            summarized: Dict[str, Any] = {}
            for key, item in list(value.items())[:12]:
                key_str = str(key)
                if key_str.lower() in blocked_keys:
                    summarized[key_str] = "[redacted]"
                else:
                    summarized[key_str] = self._summarize_value(item, max_chars=max(120, max_chars // 3))
            if len(value) > 12:
                summarized["_truncated"] = f"{len(value) - 12} more fields"
            return summarized
        compact = str(value).strip()
        return compact[:max_chars] + "…" if len(compact) > max_chars else compact

    def _format_detail_body(self, payload: Any) -> str:
        import json
        if payload is None:
            return ""
        if isinstance(payload, str):
            return payload
        try:
            return json.dumps(payload, indent=2, ensure_ascii=False)
        except Exception:
            return str(payload)

    async def _emit_step_detail(self, entry: Dict[str, Any], delta: Optional[str] = None) -> None:
        try:
            if self.notifier and hasattr(self.notifier, "send_step_detail_update"):
                await self.notifier.send_step_detail_update(entry=entry, delta=delta)
        except Exception as detail_err:
            self.logger.debug(f"⚠️ Step detail update failed: {detail_err}")

    def _make_detail_entry(
        self,
        entry_type: str,
        content: str,
        *,
        detail_kind: str,
        summary: str,
        body: Optional[str] = None,
        step_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        streaming: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
        **extra
    ) -> Dict[str, Any]:
        import uuid
        entry_id = extra.pop("id", None) or f"{detail_kind}_{uuid.uuid4().hex[:10]}"
        return self._record_timeline_entry(
            entry_type,
            content,
            id=entry_id,
            step_id=step_id,
            correlation_id=correlation_id or step_id,
            detail_kind=detail_kind,
            summary=summary,
            body=body if body is not None else content,
            metadata=metadata or {},
            streaming=streaming,
            **extra
        )

    def get_accumulated_steps(self) -> List[Dict[str, Any]]:
        return list(self._execution_timeline)

    def get_execution_timeline(self) -> List[Dict[str, Any]]:
        return list(self._execution_timeline)

    def _record_emitted_thinking_segment(
        self,
        iteration: int,
        text: str,
        is_complete: bool,
    ) -> None:
        """Retain the same completed segment emitted to the thinking UI."""
        segment = {
            "iteration": iteration,
            "text": text,
            "is_complete": is_complete,
            "recorded_at": timeline_timestamp(),
        }
        for index, existing in enumerate(self._thinking_history):
            if existing["iteration"] == iteration:
                segment["recorded_at"] = existing.get("recorded_at") or segment["recorded_at"]
                self._thinking_history[index] = segment
                return
        self._thinking_history.append(segment)

    def get_thinking_history(self) -> List[Dict[str, Any]]:
        """Return the provider-agnostic reasoning segments shown during this run."""
        return [dict(segment) for segment in self._thinking_history]

    def _extract_finalizer_visible_text(self, tool_args: Any) -> str:
        """Extract complete, user-visible strings from finalizer args without trusting partial JSON."""
        import json

        if isinstance(tool_args, dict):
            for key in ("user_visible_output", "summary_text"):
                value = tool_args.get(key)
                if isinstance(value, str) and value.strip():
                    return value

            messages = (
                tool_args.get("raw_messages")
                or tool_args.get("standardized_messages")
                or []
            )
            if isinstance(messages, list):
                return "\n\n".join(
                    item.strip()
                    for item in messages
                    if isinstance(item, str) and item.strip()
                )
            return ""

        if not isinstance(tool_args, str) or not tool_args:
            return ""

        try:
            parsed = json.loads(tool_args)
            return self._extract_finalizer_visible_text(parsed)
        except Exception:
            pass

        # Partial JSON fallback: decode only complete strings already present in
        # controlled finalizer string-list fields. Ignore incomplete trailing JSON.
        decoder = json.JSONDecoder()
        collected: List[str] = []
        for field_name in ("raw_messages", "standardized_messages"):
            marker = f'"{field_name}"'
            marker_pos = tool_args.find(marker)
            if marker_pos < 0:
                continue
            array_pos = tool_args.find("[", marker_pos)
            if array_pos < 0:
                continue
            index = array_pos + 1
            while index < len(tool_args):
                while index < len(tool_args) and tool_args[index] in " \r\n\t,":
                    index += 1
                if index >= len(tool_args) or tool_args[index] == "]":
                    break
                if tool_args[index] != '"':
                    index += 1
                    continue
                try:
                    value, next_index = decoder.raw_decode(tool_args[index:])
                except Exception:
                    break
                if isinstance(value, str) and value.strip():
                    collected.append(value.strip())
                index += next_index

        return "\n\n".join(collected)

    @staticmethod
    def _reasoning_text_from_content(content: Any) -> str:
        """Pull natural-language + extended-thinking text from a message content.

        Handles both the plain-string form and Anthropic/OpenAI content-block
        lists. Tool-call blocks (e.g. ``tool_use``/``input_json_delta``) are
        skipped so only reasoning text flows to the thinking UI.
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type in (None, "text"):
                    value = block.get("text")
                    if isinstance(value, str):
                        parts.append(value)
                elif block_type == "thinking":
                    value = block.get("thinking")
                    if isinstance(value, str):
                        parts.append(value)
            return "".join(parts)
        return ""

    def _extract_reasoning_text_delta(self, token: Any, *chunks: Any) -> str:
        """Pull user-visible text (and extended-thinking text) from a stream token.

        Ignores tool-call argument deltas (handled separately by the finalizer
        streamer) so only natural-language generation flows to the thinking UI.

        The ``chunk`` LangChain passes to ``on_llm_new_token`` for chat models is a
        ``ChatGenerationChunk`` whose payload is at ``.message.content`` / ``.text``
        (it has no ``.content`` itself); our own adapters pass an ``AIMessageChunk``
        directly (``.content``). Both shapes are handled here so every model path
        streams, not just the ones that hand us an ``AIMessageChunk``.
        """
        if isinstance(token, str) and token:
            return token
        for candidate in chunks:
            if candidate is None:
                continue
            # ChatGenerationChunk wraps the AIMessageChunk in .message; prefer it,
            # then fall back to a directly-passed AIMessageChunk's .content.
            message = getattr(candidate, "message", None)
            content = getattr(message, "content", None)
            if content is None:
                content = getattr(candidate, "content", None)
            text = self._reasoning_text_from_content(content)
            if text:
                return text
            # GenerationChunk / ChatGenerationChunk also expose plain .text.
            plain = getattr(candidate, "text", None)
            if isinstance(plain, str) and plain:
                return plain
        return ""

    async def _stream_reasoning_delta(self, delta: str) -> None:
        """Coalesce and broadcast live agent-loop text on the thinking channel."""
        if not delta:
            return
        ws_manager = getattr(self.notifier, "_websocket_manager", None)
        if ws_manager is None:
            return
        self._reasoning_buffer += delta
        if (
            len(self._reasoning_buffer) < self._reasoning_coalesce_min_chars
            and "\n\n" not in self._reasoning_buffer
        ):
            return
        self._reasoning_stream_text += self._reasoning_buffer
        self._reasoning_buffer = ""

        if not self._reasoning_first_token_marked:
            self._reasoning_first_token_marked = True
            try:
                if self._turn_timing is not None:
                    self._turn_timing.mark_point("first_reasoning_token")
            except Exception:
                pass

        import asyncio
        from datetime import datetime
        event = {
            "event_type": "agent_progress_update",
            "execution_method": "dynamic_agent",
            "agent_task_id": self.todo_id,
            "timestamp": datetime.now().isoformat(),
            "message": "Working…",
            "thinking": self._reasoning_stream_text,
            "thinking_complete": False,
        }
        asyncio.ensure_future(ws_manager.broadcast(event))

    async def _maybe_stream_finalizer_args(self, tool_name: Optional[str], tool_args: Any) -> None:
        if tool_name != "finalize_agent_task_result":
            return
        if not hasattr(self.notifier, "send_agent_result_streaming_chunk"):
            return

        visible_text = self._extract_finalizer_visible_text(tool_args)
        if len(visible_text) <= self._finalizer_streamed_chars:
            return

        delta = visible_text[self._finalizer_streamed_chars:]
        self._finalizer_stream_text = visible_text
        self._finalizer_streamed_chars = len(visible_text)
        await self.notifier.send_agent_result_streaming_chunk(
            token=delta,
            partial_result=visible_text,
            operation="multi_step_workflow",
            source="finalizer_args",
        )

    def _extract_rich_task_description(self, tool_name: str, tool_inputs: dict) -> str:
        """Extract meaningful task descriptions using tool metadata templates."""
        try:
            self.logger.debug(f"🔧 [RichDesc] tool_name={tool_name}, inputs_keys={list(tool_inputs.keys()) if tool_inputs else 'None'}")
            
            # Check if we have metadata for this tool
            metadata = self.tool_metadata.get(tool_name, {})
            shell_description = self._describe_shell_command(tool_name, tool_inputs)
            if shell_description:
                return shell_description

            if not metadata:
                self.logger.debug(f"🔧 [RichDesc] No metadata found for {tool_name}, using fallback")
                return self._friendly_tool_phrase(tool_name)
            
            self.logger.debug(f"🔧 [RichDesc] Found metadata: {list(metadata.keys())}")
            
            # Try primary template
            primary_template = metadata.get("progress_template")
            if primary_template:
                result = self._render_template(primary_template, tool_inputs)
                if result and len(result.strip()) > 5:  # Valid result
                    clean_result = result[:120].strip()  # Truncate if needed
                    self.logger.debug(f"🔧 [RichDesc] Using primary template result: {clean_result}")
                    return clean_result
            
            # Try fallback template
            fallback_template = metadata.get("fallback_template")
            if fallback_template:
                result = self._render_template(fallback_template, tool_inputs)
                if result and len(result.strip()) > 5:
                    clean_result = result[:120].strip()
                    self.logger.debug(f"🔧 [RichDesc] Using fallback template result: {clean_result}")
                    return clean_result
            
            # Use simple description
            simple_desc = metadata.get("simple_description", "Executing task")
            self.logger.debug(f"🔧 [RichDesc] Using simple description: {simple_desc}")
            return simple_desc
            
        except Exception as e:
            self.logger.debug(f"🔧 [RichDesc] Exception in template rendering: {e}")
            pass
            
        # Fallback to generic descriptions
        return self._friendly_tool_phrase(tool_name)

    def _extract_command_text(self, value: Any) -> str:
        """Find a shell command string in common tool input shapes."""
        if isinstance(value, str):
            return value.strip()
        if not isinstance(value, dict):
            return ""
        for key in ("command", "cmd", "script", "code", "input"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for nested_key in ("context_data", "arguments", "kwargs"):
            nested = value.get(nested_key)
            command = self._extract_command_text(nested)
            if command:
                return command
        return ""

    def _extract_written_file_name(self, command: str) -> Optional[str]:
        import os
        import re
        patterns = (
            r">\s*['\"]?([^'\"\s]+)['\"]?",
            r"open\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]w",
            r"Path\(\s*['\"]([^'\"]+)['\"]\s*\)\.write_",
            r"write_text\(\s*.*?\)\s*#\s*([^#\n]+)$",
        )
        for pattern in patterns:
            match = re.search(pattern, command)
            if match:
                return os.path.basename(match.group(1).strip())
        return None

    def _describe_shell_command(self, tool_name: str, tool_inputs: dict) -> Optional[str]:
        """Return a user-facing shell description when command intent is clear."""
        import shlex
        command = self._extract_command_text(tool_inputs)
        tool_label = (tool_name or "").lower()
        command_label = command.lower()
        if not command and not any(token in tool_label for token in ("shell", "bash", "terminal", "command")):
            return None
        if not any(token in tool_label for token in ("shell", "bash", "terminal", "command")) and not command:
            return None

        written_file = self._extract_written_file_name(command)
        if written_file:
            if self._last_tool_denied:
                self._last_tool_denied = False
                return f"Trying another write method for {written_file}"
            return f"Writing {written_file}"

        if command_label.startswith(("rg ", "grep ")):
            try:
                parts = shlex.split(command)
                query = next((part for part in parts[1:] if not part.startswith("-")), "")
            except Exception:
                query = ""
            return f"Searching project files for {query}" if query else "Searching project files"

        if command_label.startswith(("ls", "pwd", "tree ")):
            return "Inspecting project files"
        if command_label.startswith(("python ", "python3 ")):
            return "Running Python helper script"
        if command_label.startswith(("npm test", "npm run test", "pytest", "swift test")):
            return "Running focused tests"
        if command_label.startswith(("npm run build", "npm run typecheck", "tsc ")):
            return "Checking frontend build"
        if command_label.startswith(("git diff", "git status", "git log")):
            return "Inspecting repository changes"
        if command:
            return "Running shell command"
        return None
    
    def _render_template(self, template: str, data: dict) -> Optional[str]:
        """Render template with nested parameter access like {context_data.file_name}"""
        try:
            import re
            
            def replace_placeholder(match):
                path = match.group(1)  # e.g., "task_description" or "context_data.file_name"
                
                # Navigate nested structure
                current = data
                for part in path.split('.'):
                    if isinstance(current, dict) and part in current:
                        current = current[part]
                    else:
                        return ""  # Return empty if path not found (template will fail validation)
                
                return str(current) if current else ""
            
            result = re.sub(r'\{([^}]+)\}', replace_placeholder, template)
            self.logger.debug(f"🔧 [Template] '{template}' -> '{result}'")
            return result if result != template else None  # Return None if no substitutions made
            
        except Exception as e:
            self.logger.debug(f"🔧 [Template] Error rendering '{template}': {e}")
            return None

    def _friendly_tool_phrase(self, tool_name: str) -> str:
        """Fallback generic tool descriptions when rich context extraction fails."""
        name = (tool_name or "").lower()
        if any(token in name for token in ("shell", "bash", "terminal", "command")):
            return "Running shell command"
        if "applescript_service_generate_and_execute" in name:
            return "Generating automation script"
        elif "applescript_service_execute" in name:
            return "Running automation script"
        elif name.startswith("applescript_service"):
            return "Using macOS automation"
        elif "file_service" in name and ("create" in name or "find" in name):
            return "Creating file"
        elif name.startswith("file_service"):
            return "Working with files"
        elif "email_service_create" in name:
            return "Creating email draft"
        elif name.startswith("email_service"):
            return "Working with email"
        elif "router_service" in name and "suggestion" in name:
            return "Generating suggestions"
        elif "router_service" in name and "screen" in name:
            return "Capturing screen"
        elif name.startswith("router_service"):
            return "Planning next step"
        return "Executing task"

    async def _send_active_step_heartbeat(self, run_key: str, step_id: str, description: str) -> None:
        import asyncio
        try:
            while run_key in self._step_ids_by_run:
                await asyncio.sleep(self._heartbeat_interval_seconds)
                if run_key not in self._step_ids_by_run:
                    return
                assessment = self._tool_run_registry.assess(run_key)
                heartbeat_message = assessment.message
                if not assessment.should_continue:
                    if assessment.stale_reason == "declared_timeout_exceeded":
                        self._tool_run_registry.force_cancel(run_key, reason=heartbeat_message)
                    step_info = self._step_ids_by_run.pop(run_key, None)
                    if step_info:
                        self._stop_active_step_heartbeat(run_key)
                        await self.notifier.send_dynamic_step_updated(
                            todo_id=self.todo_id,
                            step_description=description,
                            status="failed",
                            completion_message=heartbeat_message,
                            step_id=step_id,
                        )
                        stale_entry = self._make_detail_entry(
                            "tool_error",
                            heartbeat_message,
                            id=f"{step_id}_stale",
                            detail_kind="tool_stale",
                            summary=heartbeat_message,
                            body=self._format_detail_body({
                                "stale_reason": assessment.stale_reason,
                                "metadata": assessment.metadata,
                            }),
                            step_id=step_id,
                            metadata={
                                "run_id": run_key,
                                "status": "stale",
                                "stale_reason": assessment.stale_reason,
                                **(assessment.metadata or {}),
                            },
                            streaming=False,
                        )
                        await self._emit_step_detail(stale_entry)
                        await self.notifier.send_agent_progress_update(
                            message=heartbeat_message,
                            details=assessment.stale_reason,
                        )
                    self._tool_run_registry.discard(run_key)
                    return
                await self.notifier.send_dynamic_step_updated(
                    todo_id=self.todo_id,
                    step_description=description,
                    status="in_progress",
                    completion_message=heartbeat_message,
                    step_id=step_id,
                )
                await self.notifier.send_agent_progress_update(
                    message=heartbeat_message,
                    details=None,
                )
                import time
                self._last_rich_message_time = time.time()
        except asyncio.CancelledError:
            return
        except Exception as heartbeat_err:
            self.logger.debug(f"⚠️ Active step heartbeat failed: {heartbeat_err}")

    def _start_active_step_heartbeat(self, run_id: Any, step_id: Optional[str], description: str) -> None:
        if not (run_id and step_id):
            return
        import asyncio
        try:
            run_key = str(run_id)
            previous_task = self._heartbeat_tasks_by_run.pop(run_key, None)
            if previous_task:
                previous_task.cancel()
            self._heartbeat_tasks_by_run[run_key] = asyncio.create_task(
                self._send_active_step_heartbeat(run_key, step_id, description)
            )
        except Exception as heartbeat_err:
            self.logger.debug(f"⚠️ Could not start active step heartbeat: {heartbeat_err}")

    def _stop_active_step_heartbeat(self, run_id: Any) -> None:
        if not run_id:
            return
        task = self._heartbeat_tasks_by_run.pop(str(run_id), None)
        if task:
            task.cancel()

    # Tool lifecycle callbacks
    async def on_tool_start(self, serialized, input_str=None, *, run_id=None, parent_run_id=None, tags=None, metadata=None, name=None, inputs=None, **kwargs):  # type: ignore[override]
        try:
            if not (self.notifier and self.todo_id):
                return
            tool_name = name or (serialized.get("name") if isinstance(serialized, dict) else None) or "tool"
            
            # Debug: Log all available callback data to understand the structure
            self.logger.info(f"🔧 [LiveProgress] on_tool_start: tool={tool_name}, run_id={run_id}")
            self.logger.debug(f"🔧 [LiveProgress] DEBUG serialized type: {type(serialized)}")
            self.logger.debug(f"🔧 [LiveProgress] DEBUG inputs type: {type(inputs)}, value preview: {str(inputs)[:200] if inputs else 'None'}")
            self.logger.debug(f"🔧 [LiveProgress] DEBUG kwargs keys: {list(kwargs.keys()) if kwargs else 'None'}")
            
            # Extract tool inputs for rich context (try multiple sources)
            tool_inputs = {}
            if inputs and isinstance(inputs, dict):
                tool_inputs = inputs
                self.logger.debug(f"🔧 [LiveProgress] Using inputs parameter: {list(tool_inputs.keys())}")
            elif isinstance(serialized, dict) and "kwargs" in serialized:
                tool_inputs = serialized.get("kwargs", {})
                self.logger.debug(f"🔧 [LiveProgress] Using serialized.kwargs: {list(tool_inputs.keys())}")
            elif kwargs:
                # Check if tool parameters are in kwargs
                tool_inputs = kwargs
                self.logger.debug(f"🔧 [LiveProgress] Using direct kwargs: {list(tool_inputs.keys())}")
            
            # Create a rich, context-aware step description
            description = self._extract_rich_task_description(tool_name, tool_inputs)
            step_id = await self.notifier.send_dynamic_step_added(
                todo_id=self.todo_id,
                step_description=description,
                status="in_progress",
            )
            input_summary = self._summarize_value(tool_inputs)
            detail_entry = self._make_detail_entry(
                "tool_start",
                description,
                id=step_id or None,
                detail_kind="tool_input",
                summary=description,
                body=self._format_detail_body(input_summary),
                step_id=step_id,
                metadata={
                    "tool_name": tool_name,
                    "run_id": str(run_id) if run_id else None,
                    "status": "in_progress",
                },
                streaming=False,
            )
            await self._emit_step_detail(detail_entry)
            self.logger.info(f"📡 [LiveProgress] dynamic_step_added sent: step_id={step_id}, desc={description}")
            # Only emit a progress update if the agent didn't already emit
            # a better STEP_START message within the last 5 seconds
            import time
            try:
                agent_msg_age = time.time() - self._last_agent_action_time
                if agent_msg_age > 5 or not self._last_agent_action_msg:
                    await self.notifier.send_agent_progress_update(
                        message=description,
                        details=None
                    )
                    self._last_rich_message_time = time.time()
                else:
                    self.logger.info(f"📡 [LiveProgress] Keeping agent message: '{self._last_agent_action_msg}' (age={agent_msg_age:.1f}s)")
            except Exception as _:
                pass
            if run_id and step_id:
                self._step_ids_by_run[str(run_id)] = (step_id, description)
                self._tool_run_registry.register(
                    run_id=str(run_id),
                    agent_task_id=self.todo_id,
                    step_id=step_id,
                    tool_name=tool_name,
                    description=description,
                )
                self._start_active_step_heartbeat(run_id, step_id, description)
        except Exception as e:  # pragma: no cover
            self.logger.warning(f"⚠️ LiveProgress on_tool_start failed: {e}")

    async def on_tool_end(self, output=None, *, run_id=None, parent_run_id=None, tags=None, metadata=None, name=None, **kwargs):  # type: ignore[override]
        try:
            if not (self.notifier and self.todo_id and run_id):
                return
            key = str(run_id)
            step_info = self._step_ids_by_run.pop(key, None)
            self._stop_active_step_heartbeat(run_id)
            self._tool_run_registry.mark_completed(key, output_preview=str(output)[:500] if output is not None else None)
            if not step_info:
                return
            step_id, description = step_info
            self._last_completed_tool_desc = description
            self.logger.info(f"🔧 [LiveProgress] on_tool_end: tool={name}, run_id={run_id}, step_id={step_id}")
            completion_message = None
            if isinstance(output, dict) and "output" in output:
                completion_message = str(output["output"])[:500]
            elif output is not None:
                completion_message = str(output)[:500]
            output_text = str(output).lower() if output is not None else ""
            if any(token in output_text for token in ("denied", "blocked", "not allowed", "rejected")):
                self._last_tool_denied = True
            await self.notifier.send_dynamic_step_updated(
                todo_id=self.todo_id,
                step_description=description,
                status="completed",
                completion_message=completion_message,
                step_id=step_id,
            )
            output_summary = self._format_detail_body(self._summarize_value(output))
            detail_entry = self._make_detail_entry(
                "tool_complete",
                f"Completed: {description}",
                id=f"{step_id}_result",
                detail_kind="tool_result",
                summary=f"Completed: {description}",
                body=output_summary or completion_message or "",
                step_id=step_id,
                metadata={
                    "tool_name": name,
                    "run_id": str(run_id),
                    "status": "completed",
                },
                streaming=False,
            )
            await self._emit_step_detail(detail_entry)
            self.logger.info(f"📡 [LiveProgress] dynamic_step_updated sent: step_id={step_id}, status=completed")
            import time
            try:
                await self.notifier.send_agent_progress_update(
                    message=f"Completed: {description}",
                    details=None
                )
                self._last_rich_message_time = time.time()
            except Exception as _:
                pass
        except Exception as e:  # pragma: no cover
            self.logger.warning(f"⚠️ LiveProgress on_tool_end failed: {e}")

    async def on_tool_error(self, error, *, run_id=None, parent_run_id=None, tags=None, metadata=None, name=None, **kwargs):  # type: ignore[override]
        try:
            if run_id:
                self._step_ids_by_run.pop(str(run_id), None)
                self._stop_active_step_heartbeat(run_id)
                self._tool_run_registry.mark_failed(str(run_id), error=str(error)[:500] if error is not None else None)
            error_text = str(error).lower() if error is not None else ""
            if any(token in error_text for token in ("denied", "blocked", "not allowed", "rejected")):
                self._last_tool_denied = True
        except Exception as e:  # pragma: no cover
            self.logger.debug(f"⚠️ LiveProgress on_tool_error cleanup failed: {e}")

    # Agent iteration lifecycle - these provide progress during agent thinking
    async def on_chain_start(self, serialized, inputs=None, *, run_id=None, parent_run_id=None, tags=None, metadata=None, name=None, **kwargs):  # type: ignore[override]
        """Called when an agent chain (iteration) starts."""
        try:
            if not (self.notifier and self.todo_id):
                return
            
            chain_name = name or (serialized.get("name") if isinstance(serialized, dict) else None) or "agent"
            
            if "agent" in chain_name.lower() or self._agent_iteration_count == 0:
                self._agent_iteration_count += 1
                
                if self._last_completed_tool_desc:
                    iteration_msg = f"Analyzing {self._last_completed_tool_desc} results…"
                    self._last_completed_tool_desc = None
                else:
                    import time
                    rich_age = time.time() - self._last_rich_message_time
                    if rich_age < 3.0:
                        self.logger.info(f"📈 [AgentIteration] Suppressed generic 'planning step {self._agent_iteration_count}' — rich message {rich_age:.1f}s ago")
                        return
                    iteration_msg = f"Agent planning step {self._agent_iteration_count}..."
                
                await self.notifier.send_agent_progress_update(
                    message=iteration_msg,
                    details=None
                )
                self._record_step(iteration_msg)
                self.logger.info(f"📈 [AgentIteration] Sent progress: {iteration_msg}")
                
        except Exception as e:  # pragma: no cover
            self.logger.warning(f"⚠️ LiveProgress on_chain_start failed: {e}")

    async def on_llm_new_token(self, token: str, *, chunk=None, run_id=None, parent_run_id=None, tags=None, **kwargs):  # type: ignore[override]
        """Stream live agent-loop reasoning text, plus finalizer tool-argument deltas."""
        try:
            if not (self.notifier and self.todo_id):
                return

            # P1: forward natural-language generation as live thinking so the user
            # sees real text within ~1-2s instead of a spinner until synthesis.
            reasoning_delta = self._extract_reasoning_text_delta(token, chunk, kwargs.get("chunk"))
            if reasoning_delta:
                await self._stream_reasoning_delta(reasoning_delta)

            candidates = []
            if chunk is not None:
                candidates.append(chunk)
            if "chunk" in kwargs and kwargs["chunk"] is not None:
                candidates.append(kwargs["chunk"])

            for candidate in candidates:
                for attr in ("tool_call_chunks", "tool_calls"):
                    tool_chunks = getattr(candidate, attr, None) or []
                    for tool_chunk in tool_chunks:
                        if isinstance(tool_chunk, dict):
                            tool_name = (
                                tool_chunk.get("name")
                                or (tool_chunk.get("function") or {}).get("name")
                            )
                            tool_args = (
                                tool_chunk.get("args")
                                or tool_chunk.get("arguments")
                                or tool_chunk.get("partial_json")
                                or (tool_chunk.get("function") or {}).get("arguments")
                            )
                        else:
                            tool_name = getattr(tool_chunk, "name", None)
                            tool_args = (
                                getattr(tool_chunk, "args", None)
                                or getattr(tool_chunk, "arguments", None)
                                or getattr(tool_chunk, "partial_json", None)
                            )
                        await self._maybe_stream_finalizer_args(tool_name, tool_args)
        except Exception as e:
            self.logger.debug(f"⚠️ Finalizer argument streaming failed: {e}")

    async def on_llm_end(self, response, *, run_id=None, parent_run_id=None, tags=None, **kwargs):  # type: ignore[override]
        """Surface cloud model intermediate content as thinking for the frontend."""
        self.completed_llm_calls += 1
        try:
            if not (self.notifier and self.todo_id):
                return
            # P1: flush any tail of the live reasoning buffer, then reset so the
            # next LLM call's live thinking starts clean. The existing segmented
            # thinking below (content + tool_calls) is unchanged.
            if self._reasoning_buffer:
                self._reasoning_stream_text += self._reasoning_buffer
                self._reasoning_buffer = ""
            self._reasoning_stream_text = ""
            generations = getattr(response, 'generations', None)
            if not generations or not generations[0]:
                return
            msg = generations[0][0].message if hasattr(generations[0][0], 'message') else None
            if msg is None:
                return
            content = getattr(msg, 'content', '') or ''
            completed_thinking = self._reasoning_text_from_content(content).strip()
            tool_calls = getattr(msg, 'tool_calls', None) or []
            # Only surface as thinking if the LLM produced content alongside tool calls
            # (indicating intermediate reasoning rather than a final answer)
            if len(completed_thinking) > 20 and tool_calls:
                self._agent_iteration_count += 1
                from datetime import datetime
                event = {
                    "event_type": "agent_progress_update",
                    "agent_task_id": self.todo_id,
                    "timestamp": datetime.now().isoformat(),
                    "message": f"Analyzing request… (step {self._agent_iteration_count})",
                    "thinking": completed_thinking,
                    "thinking_complete": True,
                    "thinking_iteration": self._agent_iteration_count,
                }
                self._record_emitted_thinking_segment(
                    iteration=self._agent_iteration_count,
                    text=completed_thinking,
                    is_complete=True,
                )
                import asyncio
                asyncio.ensure_future(self.notifier._websocket_manager.broadcast(event))
                detail_entry = self._make_detail_entry(
                    "thinking",
                    content.strip(),
                    id=f"thinking_{self._agent_iteration_count}",
                    detail_kind="thinking",
                    summary=f"Reasoning step {self._agent_iteration_count}",
                    body=content.strip(),
                    metadata={
                        "iteration": self._agent_iteration_count,
                        "tool_call_count": len(tool_calls),
                    },
                    iteration=self._agent_iteration_count,
                    streaming=False,
                )
                await self._emit_step_detail(detail_entry)
                self.logger.info(f"🧠 [CloudThinking] Surfaced {len(content)} chars of intermediate content as thinking (iteration {self._agent_iteration_count})")
        except Exception as e:
            self.logger.debug(f"⚠️ LiveProgress on_llm_end thinking extraction failed: {e}")

    async def on_agent_action(self, action, *, run_id=None, parent_run_id=None, tags=None, metadata=None, **kwargs):  # type: ignore[override]
        """Called when agent decides on an action (before tool execution)."""
        try:
            if not (self.notifier and self.todo_id):
                return
                
            progress_msg = None

            if getattr(action, "tool", None) == "finalize_agent_task_result":
                await self._maybe_stream_finalizer_args(
                    getattr(action, "tool", None),
                    getattr(action, "tool_input", None),
                )
            
            if hasattr(action, 'log') and action.log:
                log_text = str(action.log)
                
                # Extract STEP_START or STEP_COMPLETE messages from agent output
                import re
                
                # Look for STEP_START: <message> or STEP_COMPLETE: <message>
                # Stop at newlines, or JSON structure markers like ', 'type':' that indicate we've gone too far
                step_match = re.search(r"STEP_(?:START|COMPLETE):\s*([^'\"\n]+?)(?:\n|$|', '|\")", log_text)
                if step_match:
                    # Clean up the message - remove trailing punctuation artifacts
                    msg = step_match.group(1).strip().rstrip("',\"")
                    if len(msg) > 5:  # Only use if we got meaningful content
                        progress_msg = msg[:300]  # Limit to 300 chars
            
            # Fallback to tool name if no step message found
            if not progress_msg and hasattr(action, 'tool'):
                progress_msg = f"Using {action.tool.replace('_', ' ')}"
            
            if progress_msg:
                import time
                self._last_agent_action_msg = progress_msg
                self._last_agent_action_time = time.time()
                self._last_rich_message_time = time.time()
                await self.notifier.send_agent_progress_update(
                    message=progress_msg,
                    details=None
                )
                detail_entry = self._make_detail_entry(
                    "step",
                    progress_msg,
                    detail_kind="step_complete" if "STEP_COMPLETE:" in str(getattr(action, "log", "")) else "step_note",
                    summary=progress_msg,
                    body=progress_msg,
                    metadata={
                        "source": "agent_action",
                        "tool": getattr(action, "tool", None),
                    },
                    streaming=False,
                )
                await self._emit_step_detail(detail_entry)
                self.logger.info(f"🧠 [AgentProgress] Sent: {progress_msg}")
            
        except Exception as e:  # pragma: no cover
            self.logger.warning(f"⚠️ LiveProgress on_agent_action failed: {e}")


