"""Let the agent start a separate, standalone Agent Task for work that should not stay in the current chain."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context

logger = logging.getLogger(__name__)

TOOL_NAME = "start_separate_agent_task"
SPLIT_ORIGIN_TYPE = "agent_split"
MAX_TASK_PROMPT_CHARS = 8_000
MAX_REFERENCE_PATHS = 20


class StartSeparateAgentTaskInput(BaseModel):
    """One self-contained piece of work to run as its own Agent Task."""

    model_config = ConfigDict(extra="forbid")

    task_prompt: str = Field(
        description=(
            "Everything the separate Agent Task needs, written as if to a new assistant: the goal, the exact items or "
            "identifiers involved (for example the email subject and sender), and what a finished result looks like."
        ),
        max_length=MAX_TASK_PROMPT_CHARS,
    )
    reference_paths: List[str] = Field(
        default_factory=list,
        max_length=MAX_REFERENCE_PATHS,
        description="Absolute local file or folder paths the separate task should be given, only when materially useful.",
    )


def _json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


async def _parent_model_id(agent_task_id: str) -> Optional[str]:
    """The model the current task runs on, so the separate task matches it; None means the default model."""
    try:
        from api.dependencies import get_sqlite_knowledge_service

        parent = await get_sqlite_knowledge_service().agent_task_service.get_agent_task(agent_task_id)
        artifacts = getattr(parent, "accumulated_artifacts", None)
        model_id = artifacts.get("model_id") if isinstance(artifacts, dict) else None
        return model_id if isinstance(model_id, str) and model_id.strip() else None
    except Exception as exc:
        logger.debug("Could not read the model of %s for a separate Agent Task: %s", agent_task_id, exc)
        return None


def _can_submit_directly(candidate: Any) -> bool:
    return callable(getattr(candidate, "process_agent_task_direct", None))


def _direct_submitter(submission_service: Any) -> Optional[Any]:
    """The service that can start a standalone Agent Task, or None.

    Running tasks are given the orchestrator's delegation wrapper, and what it wraps starts routed tasks but has no direct entry point. Only the application's top-level submission service does, so it is the last place looked.
    """
    for candidate in (submission_service, getattr(submission_service, "_submission_service", None)):
        if _can_submit_directly(candidate):
            return candidate
    try:
        from api.main import app  # late import to avoid an import cycle

        top_level = getattr(app.state, "agent_task_submission_service", None)
    except Exception as exc:
        logger.debug("Could not read the application's task submission service: %s", exc)
        return None
    return top_level if _can_submit_directly(top_level) else None


def _with_source_handoff(prompt: str, source_id: str, root_id: str) -> str:
    return (
        f"{prompt}\n\n"
        f"This Agent Task was split off from Agent Task {source_id} (chain root {root_id}) so the original chain could continue with other work. "
        "If prior conclusions, artifacts, or source-item identity matter, call "
        f"recall_agent_tasks(scope='detail', task_id='{source_id}') before broad rediscovery."
    )


def create_start_separate_agent_task_tool(
    *,
    agent_task_id: Optional[str],
    root_task_id: Optional[str],
    submission_service: Any,
) -> StructuredTool:
    """Create a turn-bound tool that submits one standalone Agent Task linked back to the task that started it."""
    started_by_prompt: Dict[str, str] = {}

    async def start_separate_agent_task(task_prompt: str, reference_paths: Optional[List[str]] = None) -> str:
        prompt = (task_prompt or "").strip()
        if not prompt:
            return _json({"success": False, "error": "task_prompt is required and must describe the work completely."})
        context = get_current_agent_context()
        source_id = agent_task_id or context.get("agent_task_id")
        root_id = root_task_id or context.get("root_task_id") or source_id
        if not source_id:
            return _json({"success": False, "error": f"{TOOL_NAME} is unavailable for this task."})
        submitter = _direct_submitter(submission_service)
        if submitter is None:
            logger.warning(
                "No submission service can start a separate Agent Task from %s (the tool was given %s)",
                source_id,
                type(submission_service).__name__,
            )
            return _json(
                {
                    "success": False,
                    "error": "Starting a separate Agent Task is unavailable right now. Do not retry; tell the user it could not be started and give them the prompt to paste into a new task.",
                }
            )
        submit = submitter.process_agent_task_direct

        prompt_key = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if prompt_key in started_by_prompt:
            return _json(
                {
                    "success": True,
                    "agent_task_id": started_by_prompt[prompt_key],
                    "already_started": True,
                    "message": "This work was already started as a separate Agent Task in this turn; no second task was created.",
                }
            )

        paths = [path.strip() for path in reference_paths or [] if isinstance(path, str) and path.strip()]
        new_task_id = str(uuid.uuid4())
        try:
            result = await submit(
                agent_task=_with_source_handoff(prompt, str(source_id), str(root_id)),
                agent_task_id=new_task_id,
                origin_type=SPLIT_ORIGIN_TYPE,
                origin_id=str(source_id),
                reference_paths=paths or None,
                model_id=await _parent_model_id(str(source_id)),
            )
        except Exception as exc:
            logger.warning("Could not start a separate Agent Task from %s: %s", source_id, exc, exc_info=True)
            return _json({"success": False, "error": str(exc)})
        if not isinstance(result, dict) or not result.get("success", False):
            reason = result.get("error") or result.get("message") if isinstance(result, dict) else None
            return _json({"success": False, "error": str(reason or "The separate Agent Task was not accepted.")})

        started_by_prompt[prompt_key] = new_task_id
        return _json(
            {
                "success": True,
                "agent_task_id": new_task_id,
                "message": (
                    "The work is now running as its own Agent Task and will appear in the Agent Task list. "
                    "Do not wait for it or repeat its work here; continue with the rest of this task and tell the user it was started."
                ),
            }
        )

    return StructuredTool.from_function(
        coroutine=start_separate_agent_task,
        name=TOOL_NAME,
        description=(
            "Start a new, separate top-level Agent Task for one piece of work, so this task's chain can continue with other work. "
            "Use it when the user asks to split work off, run something as its own task, or handle one item separately. "
            "Write task_prompt so it stands alone. The new task is linked back to this one and can recall it. "
            "Do not use it to wait or re-check later (use schedule_agent_follow_up), for a recurring schedule "
            "(use create_scheduled_agent_task_from_prompt), or for bounded parallel subtasks whose results this task needs (use delegated_agent)."
        ),
        args_schema=StartSeparateAgentTaskInput,
    )
