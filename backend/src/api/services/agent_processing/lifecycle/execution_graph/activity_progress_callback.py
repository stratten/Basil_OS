"""Contract-aware LangChain progress callback for agent activity summaries."""

from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import uuid4

from ..runtime.agent_timeline_contract import (
    normalize_timeline_entry,
    sanitize_timeline_title,
)
from .agent_progress_system import LiveProgressCallbackHandler


_TOOL_TITLE_DESCRIPTORS = {
    "shell": "Running project command",
    "bash": "Running project command",
    "terminal": "Running project command",
    "search": "Searching available information",
    "file": "Working with files",
    "email": "Working with email",
    "calendar": "Working with calendar",
    "browser": "Using browser automation",
    "vision": "Analyzing visual context",
    "finalize": "Preparing final result",
}


class ActivityProgressCallbackHandler(LiveProgressCallbackHandler):
    """Emit safe, correlated lifecycle activity without changing legacy callbacks."""

    def __init__(
        self,
        notifier: Any,
        todo_id: str,
        available_tools: Any = None,
        turn_timing: Any = None,
    ) -> None:
        super().__init__(
            notifier=notifier,
            todo_id=todo_id,
            available_tools=available_tools,
            turn_timing=turn_timing,
        )
        self._activity_correlation_id = f"agent_run_{uuid4().hex}"

    def _record_timeline_entry(self, entry_type: str, content: str, **extra: Any) -> Dict[str, Any]:
        """Normalize callback entries while retaining every legacy extension field."""
        normalized = normalize_timeline_entry(
            extra,
            phase=extra.pop("phase", "execution"),
            state=extra.pop("state", None),
            source="langchain_callback",
            title=content,
            correlation_id=extra.pop("correlation_id", self._activity_correlation_id),
        )
        normalized.pop("content", None)
        return super()._record_timeline_entry(
            entry_type,
            sanitize_timeline_title(content),
            **normalized,
        )

    def _extract_rich_task_description(self, tool_name: str, tool_inputs: dict) -> str:
        """Use static descriptors; interpolate only a sanitized allowlisted value."""
        normalized_name = (tool_name or "").lower()
        title = next(
            (descriptor for token, descriptor in _TOOL_TITLE_DESCRIPTORS.items() if token in normalized_name),
            "Executing approved tool",
        )
        filename = tool_inputs.get("file_name") or tool_inputs.get("path")
        if isinstance(filename, str) and filename.strip():
            return f"{title}: {sanitize_timeline_title(filename, fallback='item')[:80]}"
        return title

    async def _emit_phase(self, phase: str, state: str, title: str, error: Optional[Any] = None) -> None:
        """Publish a durable phase transition under the run correlation."""
        entry = normalize_timeline_entry(
            {
                "id": f"{self._activity_correlation_id}_{phase}_{state}",
                "type": "phase",
                "detail_kind": "phase_transition",
                "content": sanitize_timeline_title(title),
                "body": sanitize_timeline_title(error, fallback="") if error else sanitize_timeline_title(title),
                "metadata": {"error": str(error)[:500] if error else None},
                "streaming": False,
            },
            phase=phase,
            state=state,
            source="langchain_callback",
            title=title,
            correlation_id=self._activity_correlation_id,
        )
        await self.notifier.send_step_detail_update(entry=entry)

    async def on_chain_start(self, serialized: Any, inputs: Any = None, **kwargs: Any) -> None:
        await self._emit_phase("agent_execution", "started", "Starting agent execution")
        await super().on_chain_start(serialized, inputs, **kwargs)

    async def on_tool_start(self, serialized: Any, input_str: Any = None, **kwargs: Any) -> None:
        await self._emit_phase("tool_execution", "started", "Executing approved tool")
        await super().on_tool_start(serialized, input_str, **kwargs)

    async def on_tool_end(self, output: Any = None, **kwargs: Any) -> None:
        run_id = kwargs.get("run_id")
        step_info = self._step_ids_by_run.get(str(run_id)) if run_id else None
        await super().on_tool_end(output, **kwargs)
        if step_info is not None and hasattr(self.notifier, "publish_agent_task_artifact"):
            await self.notifier.publish_agent_task_artifact(
                output=output,
                source_step_id=step_info[0],
            )
        await self._emit_phase("tool_execution", "completed", "Completed approved tool")

    async def on_tool_error(self, error: Any, **kwargs: Any) -> None:
        await super().on_tool_error(error, **kwargs)
        await self._emit_phase("tool_execution", "failed", "Approved tool failed", error)
