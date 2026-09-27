"""Agent-facing recall tool factory (agent-task history)."""

from __future__ import annotations

import json
import logging
from typing import List, Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile

from .agent_task_source import AgentTaskRecallSource
from .recall_core import register_recall_source

logger = logging.getLogger(__name__)


class RecallAgentTasksInput(BaseModel):
    """Input schema for recall_agent_tasks."""

    scope: Literal["current_chain", "history", "detail", "transcript", "transcript_text", "reasoning", "screen"] = Field(
        default="current_chain",
        description=(
            "'current_chain' (default): the earlier turns of THIS ongoing task "
            "thread - what you already did, decided, or resolved moments ago. "
            "'history': search ALL past agent tasks across every thread. "
            "'detail': fetch the full result for one task by id (use when a list "
            "result has result_truncated=true or when TODO WORKER HANDOFF provides "
            "a source Agent Task id). "
            "'transcript': cheap ordered overview of the tool calls one task made "
            "(tool names + short, possibly-truncated argument/result previews). Use "
            "this first to see WHAT was called and in what order. "
            "'transcript_text': the lossless content path - a window of the "
            "task's full agent log centered on a `contains` match. Use this when a "
            "prior turn's result/summary does not contain the actual content you "
            "produced (an email body, file text, a composed message) - especially "
            "after a failed/cancelled turn - instead of re-doing the work. "
            "'reasoning': fetch bounded, redacted emitted reasoning segments for "
            "one prior task. Use only when the user asks why that task made a "
            "decision or performed a particular step. "
            "'screen': fetch the text captured from the user's screen for THIS "
            "task (no id needed). Returns screen_text_status='pending' if the "
            "background capture is still running."
        ),
    )
    query: Optional[str] = Field(default=None, description="Search text; used only when scope='history'.")
    start_time: Optional[str] = Field(default=None, description="Lower time bound for scope='history': ISO or relative ('yesterday','last_week','this_month').")
    end_time: Optional[str] = Field(default=None, description="Upper time bound for scope='history': ISO or relative ('now','today').")
    limit: int = Field(default=20, description="Maximum turns/results/transcript entries/reasoning segments to return (clamped to 1-100; reasoning is capped at 20).")
    offset: int = Field(
        default=0,
        description=(
            "For scope='transcript': entry offset (skip N calls, oldest-first). "
            "For scope='transcript_text': character offset into the full log for paging. "
            "For scope='reasoning': segment offset (skip N segments, oldest-first)."
        ),
    )
    root_task_id: Optional[str] = Field(default=None, description="Advanced override for scope='current_chain'. Normally leave blank; the current thread is used automatically.")
    task_id: Optional[str] = Field(
        default=None,
        description=(
            "Required for scope='detail', scope='transcript', scope='transcript_text', "
            "and scope='reasoning': the id of a prior task from a list result "
            "or a source task named in TODO WORKER HANDOFF."
        ),
    )
    contains: Optional[str] = Field(
        default=None,
        description=(
            "For scope='transcript_text': return the window of the full "
            "agent log centered on the first occurrence of this substring "
            "(case-insensitive) - e.g. a distinctive phrase you wrote or a tool "
            "name. For scope='reasoning': filter emitted reasoning text "
            "case-insensitively before paging. Omit to page from offset."
        ),
    )


_FULL_DESCRIPTION = """Recall Basil's own agent-task history.

WHEN TO USE:
- scope='current_chain' (default): re-read the earlier turns of the SAME task
  thread you are in right now - the files you already found, decisions you
  already made, results you already produced. Use this the moment you are
  unsure what "that file" / "it" / "the same one" refers to, INSTEAD of asking
  the user to repeat themselves.
- scope='history': search every past agent task (all threads) by text and/or
  time window - "have I done this before", "what did you do for me yesterday".
- scope='detail': fetch the full result for ONE task by id. Use this when a
  list result has result_truncated=true and you need the complete conclusion,
  file decision, or outcome from that turn. Pass task_id from the id field of
  a prior current_chain or history result. A standalone To-Do worker may also
  receive source Agent Task ids in TODO WORKER HANDOFF; pass one of those ids
  directly without first searching or creating a task chain.
- scope='transcript' (Tier 1, cheap): fetch the ordered TOOL CALLS of ONE task
  by id - each tool name plus a SHORT, possibly-truncated preview of the
  arguments it passed and the result it got back. Use this first to see WHAT a
  prior turn actually did, in what order, before deciding whether you need the
  exact content.
- scope='transcript_text' (Tier 2, lossless): fetch a window of the task's
  FULL agent log by id, centered on a `contains` match. Use this when the
  finalized result/summary (and the Tier 1 preview) do NOT contain the content
  you actually produced - the email body you drafted, the text you wrote to a
  file, the message you composed - because that content lived in a tool
  argument, not the final answer. This is the correct move for "give me the
  full text of what you wrote", ESPECIALLY when the prior turn failed or was
  cancelled, so you can quote your own prior work instead of redoing it. Pass
  `contains` with a distinctive phrase or the tool name; page with `offset`
  (a character offset) if `has_more` is true.
- scope='reasoning' (explicit, bounded): fetch redacted emitted reasoning
  segments for ONE task by id only when the user asks why a prior task made a
  decision or performed a step. Start with the bounded page, use `contains`
  for the named tool, decision, or phrase, and do not fetch reasoning
  opportunistically.

List results may truncate long prompts/results (result_truncated=true). When
that happens, call scope='detail' with the task's id instead of guessing.
Tier 1 transcript entries flag arguments_truncated/result_truncated; when set,
call scope='transcript_text' with a matching `contains` for the complete
content instead of assuming Tier 1 is the whole story.

This is NOT screen-activity (use query_activities for what was visible on
screen) and NOT user notes/preferences (use memory_search/memory_read). This
tool returns Basil's record of prior agent tasks: prompts, results, and files.

Time tokens for scope='history' start_time/end_time: ISO timestamps or
'today','yesterday','this_week','last_week','this_month','last_month','now'.
"""

SLIM_DESCRIPTION = (
    "Recall Basil's own prior agent tasks. scope='current_chain' (default) "
    "re-reads earlier turns of THIS thread (files/decisions/results you already "
    "produced) - use it instead of asking the user what 'that file'/'it' means. "
    "scope='history' searches all past tasks by query + time window. "
    "scope='detail' fetches the full result for one task id when a list result "
    "has result_truncated=true or TODO WORKER HANDOFF supplies a source task id. "
    "scope='transcript' gives a cheap ordered overview of one task's tool calls "
    "(short, possibly-truncated previews). scope='transcript_text' is the "
    "lossless follow-up: a window of the full agent log centered on a `contains` "
    "match - use it for 'give me the text you wrote' (the email body/text/message "
    "you composed lives here, not in the final result), especially after a "
    "failed/cancelled turn, instead of redoing the work. "
    "scope='reasoning' returns bounded, redacted emitted reasoning for one task "
    "only when the user asks why that task made a decision or performed a step; "
    "start bounded and target a named tool/decision/phrase with `contains`, "
    "never fetch it opportunistically. "
    "scope='screen' returns the text captured from "
    "the user's current screen for THIS task (no id needed). Not historical "
    "screen activity (query_activities) and not user notes (memory_*)."
)


def create_recall_tools(
    profile=None,
    root_task_id: Optional[str] = None,
    current_agent_task_id: Optional[str] = None,
) -> List[StructuredTool]:
    """Build the recall tool set, capturing the current chain root for scope='current_chain' and the current turn id for scope='screen'."""
    source = AgentTaskRecallSource()
    register_recall_source(source)
    captured_root = root_task_id
    captured_agent_task_id = current_agent_task_id

    async def _recall_agent_tasks(
        scope: str = "current_chain",
        query: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
        root_task_id: Optional[str] = None,
        task_id: Optional[str] = None,
        contains: Optional[str] = None,
    ) -> str:
        try:
            bounded = max(1, min(int(limit or 20), 100))
            if scope == "screen":
                target_id = task_id or captured_agent_task_id
                if not target_id:
                    return json.dumps({
                        "success": False,
                        "scope": "screen",
                        "error": "No current task id is available for scope='screen'.",
                    }, ensure_ascii=False)
                screen = await source.screen_context(target_id)
                if screen is None:
                    return json.dumps({
                        "success": False,
                        "scope": "screen",
                        "error": f"No agent task found with id {target_id!r}.",
                    }, ensure_ascii=False)
                return json.dumps({"success": True, "scope": "screen", "screen": screen}, ensure_ascii=False)
            if scope == "detail":
                if not task_id:
                    return json.dumps({
                        "success": False,
                        "scope": "detail",
                        "error": "task_id is required for scope='detail'. Pass the id from a prior current_chain or history result.",
                    }, ensure_ascii=False)
                detail = await source.detail(task_id)
                if detail is None:
                    return json.dumps({
                        "success": False,
                        "scope": "detail",
                        "error": f"No agent task found with id {task_id!r}.",
                    }, ensure_ascii=False)
                return json.dumps({"success": True, "scope": "detail", "task": detail}, ensure_ascii=False)
            if scope == "transcript":
                if not task_id:
                    return json.dumps({
                        "success": False,
                        "scope": "transcript",
                        "error": "task_id is required for scope='transcript'. Pass the id from a prior current_chain or history result.",
                    }, ensure_ascii=False)
                transcript = await source.transcript(task_id, bounded, max(0, int(offset or 0)))
                if transcript is None:
                    return json.dumps({
                        "success": False,
                        "scope": "transcript",
                        "error": f"No agent task found with id {task_id!r}.",
                    }, ensure_ascii=False)
                return json.dumps({"success": True, "scope": "transcript", **transcript}, ensure_ascii=False)
            if scope == "transcript_text":
                if not task_id:
                    return json.dumps({
                        "success": False,
                        "scope": "transcript_text",
                        "error": "task_id is required for scope='transcript_text'. Pass the id from a prior current_chain or history result.",
                    }, ensure_ascii=False)
                text = await source.transcript_text(task_id, contains, max(0, int(offset or 0)))
                if text is None:
                    return json.dumps({
                        "success": False,
                        "scope": "transcript_text",
                        "error": f"No agent task found with id {task_id!r}.",
                    }, ensure_ascii=False)
                return json.dumps({"success": True, "scope": "transcript_text", **text}, ensure_ascii=False)
            if scope == "reasoning":
                if not task_id:
                    return json.dumps({
                        "success": False,
                        "scope": "reasoning",
                        "error": "task_id is required for scope='reasoning'. Pass the id of the task whose decision or step the user asked about.",
                    }, ensure_ascii=False)
                reasoning = await source.reasoning(
                    task_id,
                    bounded,
                    max(0, int(offset or 0)),
                    contains,
                )
                if reasoning is None:
                    return json.dumps({
                        "success": False,
                        "scope": "reasoning",
                        "error": f"No agent task found with id {task_id!r}.",
                    }, ensure_ascii=False)
                return json.dumps({"success": True, "scope": "reasoning", **reasoning}, ensure_ascii=False)
            if scope == "history":
                from api.dependencies import get_sqlite_knowledge_service
                from api.services.retrieval.contracts import RetrievalSearchRequest
                from api.services.retrieval.factory import get_unified_retrieval_service

                knowledge_service = get_sqlite_knowledge_service()
                if not hasattr(knowledge_service, "db_path"):
                    # Test/injected compatibility seam: production always has
                    # a canonical SQLite path and uses unified retrieval.
                    results = await source.search(query, start_time, end_time, bounded)
                else:
                    retrieval = get_unified_retrieval_service().search(
                        RetrievalSearchRequest(
                            query=query or "",
                            source_kinds=["agent_task"],
                            start=start_time,
                            end=end_time,
                            mode="exact",
                            limit=bounded,
                        )
                    )
                    results = [
                        {
                            "id": item["source_id"],
                            "timestamp": item["occurred_at"],
                            "title": item["title"],
                            "prompt": item["metadata"].get("prompt", ""),
                            "status": item["metadata"].get("status"),
                            "result": item["metadata"].get("result_preview", ""),
                            "result_truncated": False,
                            "file_count": item["metadata"].get("file_count", 0),
                            "follow_up_count": item["metadata"].get("follow_up_count", 0),
                        }
                        for item in retrieval["results"]
                    ]
                return json.dumps({"success": True, "scope": "history", "count": len(results), "results": results}, ensure_ascii=False)
            resolved_root = captured_root or root_task_id
            if not resolved_root:
                return json.dumps({
                    "success": False,
                    "scope": "current_chain",
                    "error": "No current task chain is available (likely the first turn). Use scope='history' with a query to search past tasks.",
                    "results": [],
                }, ensure_ascii=False)
            results = await source.chain(resolved_root, bounded)
            return json.dumps({"success": True, "scope": "current_chain", "root_task_id": resolved_root, "count": len(results), "results": results}, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001 - tool must always return a string
            logger.error("recall_agent_tasks failed: %s", exc, exc_info=True)
            return json.dumps({"success": False, "error": str(exc), "results": []}, ensure_ascii=False)

    description = select_description_for_profile(profile, _FULL_DESCRIPTION, SLIM_DESCRIPTION)
    return [
        StructuredTool.from_function(
            func=_recall_agent_tasks,
            coroutine=_recall_agent_tasks,
            name="recall_agent_tasks",
            description=description,
            args_schema=RecallAgentTasksInput,
        )
    ]
