"""BasilBoard application service."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from api.dependencies import get_sqlite_knowledge_service
from api.services.basil_board.models import (
    BasilBoardHydration,
    BasilBoardTab,
    BoardInquiryDetail,
    BoardInquirySummary,
    HomeState,
    HomeTurn,
    HomeTurnRouteKind,
    HomeTurnState,
    LinkedAgentTaskSummary,
)
from api.services.basil_board.repository import BasilBoardRepository

logger = logging.getLogger(__name__)

_TERMINAL_AGENT_TASK_STATUSES = {"completed", "failed", "canceled"}


class BasilBoardService:
    """Validating facade above BasilBoardRepository."""

    def __init__(self, repository: Optional[BasilBoardRepository] = None) -> None:
        sqlite_service = get_sqlite_knowledge_service()
        self._repo = repository or BasilBoardRepository(str(sqlite_service.db_path))
        self._agent_tasks = sqlite_service.agent_task_service

    async def ensure_home_tab(self) -> BasilBoardTab:
        return await self._repo.ensure_home_tab()

    async def ensure_home_state(self) -> HomeState:
        await self.ensure_home_tab()
        existing = await self._repo.get_home_state()
        if existing:
            return existing
        conversation_id = await self._repo.create_conversation()
        return await self._repo.upsert_home_state(conversation_id)

    async def hydrate_board(self) -> BasilBoardHydration:
        tabs = await self._repo.list_active_tabs()
        recent_inquiries = await self._repo.list_recent_inquiries(limit=50)
        reconciled_inquiries: List[BoardInquirySummary] = []
        for inquiry in recent_inquiries:
            if inquiry.agentTaskId and inquiry.state not in {
                HomeTurnState.COMPLETED,
                HomeTurnState.FAILED,
                HomeTurnState.CANCELED,
            }:
                inquiry = await self._reconcile_inquiry_agent_task(inquiry)
            reconciled_inquiries.append(inquiry)
        return BasilBoardHydration(tabs=tabs, recent_inquiries=reconciled_inquiries)

    async def create_inquiry_conversation(self, prompt_text: str) -> str:
        """Every inquiry owns its own conversation row (never the shared
        Home conversation), so each Recent Inquiry is a genuinely
        independent, addressable record rather than a slice of one
        singleton scrollback."""
        stripped = prompt_text.strip()
        title = stripped.splitlines()[0][:80] if stripped else "Basil Inquiry"
        return await self._repo.create_conversation(
            title=title,
            metadata={"surface": "basil_board_inquiry"},
        )

    async def create_inquiry(
        self,
        *,
        prompt_text: str,
        display_prompt_markdown: Optional[str],
        reference_paths: List[str],
    ) -> BoardInquirySummary:
        return await self._repo.create_inquiry(
            prompt_text=prompt_text,
            display_prompt_markdown=display_prompt_markdown,
            reference_paths=reference_paths,
        )

    async def update_inquiry(self, inquiry_id: str, **fields: Any) -> Optional[BoardInquirySummary]:
        return await self._repo.update_inquiry(inquiry_id, **fields)

    async def get_inquiry(self, inquiry_id: str) -> Optional[BoardInquirySummary]:
        return await self._repo.get_inquiry(inquiry_id)

    async def list_recent_inquiries(self, *, limit: int = 50) -> List[BoardInquirySummary]:
        return await self._repo.list_recent_inquiries(limit=limit)

    async def hydrate_inquiry(self, inquiry_id: str) -> Optional[BoardInquiryDetail]:
        inquiry = await self._repo.get_inquiry(inquiry_id)
        if not inquiry:
            return None

        task_result: Optional[str] = None
        task_outcome: Optional[str] = None
        if inquiry.agentTaskId:
            inquiry = await self._reconcile_inquiry_agent_task(inquiry)
            task = await self._agent_tasks.get_agent_task(inquiry.agentTaskId)
            if task:
                task_result, task_outcome = self._extract_agent_task_result(task)

        messages: List[Dict[str, Any]] = []
        if inquiry.conversationId:
            messages = await self._repo.list_conversation_messages(inquiry.conversationId)

        timeline = self._build_inquiry_timeline(inquiry, messages, task_result, task_outcome)
        return BoardInquiryDetail(**inquiry.model_dump(), timeline=timeline)

    async def _reconcile_inquiry_agent_task(self, inquiry: BoardInquirySummary) -> BoardInquirySummary:
        agent_task_id = inquiry.agentTaskId
        if not agent_task_id:
            return inquiry
        task = await self._agent_tasks.get_agent_task(agent_task_id)
        if not task:
            return inquiry
        if task.status in _TERMINAL_AGENT_TASK_STATUSES:
            mapped = self._map_agent_task_state(task.status)
            if mapped != inquiry.state:
                updated = await self._repo.update_inquiry(inquiry.id, state=mapped)
                if updated:
                    return updated
        return inquiry

    def _build_inquiry_timeline(
        self,
        inquiry: BoardInquirySummary,
        messages: List[Dict[str, Any]],
        task_result: Optional[str],
        task_outcome: Optional[str],
    ) -> List[Dict[str, Any]]:
        user_message = next((message for message in messages if message["role"] == "user"), None)
        user_message_id = user_message["id"] if user_message else inquiry.id
        user_created_at = user_message["timestamp"] if user_message else inquiry.createdAt

        timeline: List[Dict[str, Any]] = [
            {
                "kind": "user_message",
                "messageId": user_message_id,
                "content": user_message["content"] if user_message else inquiry.promptText,
                "displayMarkdown": inquiry.displayMarkdown,
                "referencePaths": inquiry.referencePaths,
                "createdAt": user_created_at,
            }
        ]

        if inquiry.routeKind == HomeTurnRouteKind.AGENT_TASK and inquiry.agentTaskId:
            timeline.append(
                {
                    "kind": "agent_task",
                    "messageId": user_message_id,
                    "inReplyTo": user_message_id,
                    "agentTaskId": inquiry.agentTaskId,
                    "state": self._map_inquiry_ui_state(inquiry.state),
                    "result": task_result,
                    "outcome": task_outcome,
                    "createdAt": user_created_at,
                }
            )
        else:
            assistant_message = next(
                (message for message in messages if message["role"] in ("assistant", "error")),
                None,
            )
            if assistant_message:
                timeline.append(
                    {
                        "kind": "conversation_answer",
                        "messageId": assistant_message["id"],
                        "inReplyTo": user_message_id,
                        "content": assistant_message["content"],
                        "createdAt": assistant_message["timestamp"],
                    }
                )

        return timeline

    def _map_inquiry_ui_state(self, state: HomeTurnState) -> str:
        if state == HomeTurnState.ROUTING:
            return "queued"
        if state == HomeTurnState.RUNNING:
            return "running"
        if state == HomeTurnState.COMPLETED:
            return "completed"
        if state == HomeTurnState.FAILED:
            return "failed"
        return "canceled"

    async def reconcile_home_turn(self, user_message_id: str) -> Optional[HomeTurn]:
        turn = await self._repo.get_home_turn(user_message_id)
        if not turn or turn.route_kind.value != "agent_task" or not turn.agent_task_id:
            return turn
        await self._reconcile_single_turn(turn)
        return await self._repo.get_home_turn(user_message_id)

    async def _reconcile_linked_tasks(self, turns: List[HomeTurn]) -> List[LinkedAgentTaskSummary]:
        summaries: List[LinkedAgentTaskSummary] = []
        for turn in turns:
            if turn.route_kind.value != "agent_task" or not turn.agent_task_id:
                continue
            updated = await self._reconcile_single_turn(turn)
            summaries.append(updated)
        return summaries

    async def _reconcile_single_turn(self, turn: HomeTurn) -> LinkedAgentTaskSummary:
        agent_task_id = turn.agent_task_id
        assert agent_task_id is not None
        task = await self._agent_tasks.get_agent_task(agent_task_id)
        state = turn.state
        status = task.status if task else None
        result = None
        outcome = None

        if task:
            result, outcome = self._extract_agent_task_result(task)
            if status in _TERMINAL_AGENT_TASK_STATUSES:
                mapped = self._map_agent_task_state(status)
                if mapped != turn.state:
                    await self._repo.update_home_turn(turn.user_message_id, state=mapped)
                    state = mapped

        return LinkedAgentTaskSummary(
            agent_task_id=agent_task_id,
            user_message_id=turn.user_message_id,
            state=state,
            status=status,
            result=result,
            outcome=outcome,
        )

    def _extract_agent_task_result(self, task: Any) -> tuple[Optional[str], Optional[str]]:
        """Read the canonical final answer regardless of workflow result shape."""
        result_data = task.result_data if isinstance(task.result_data, dict) else {}
        nested_data = result_data.get("data") if isinstance(result_data.get("data"), dict) else {}
        final_envelope = result_data.get("final_envelope")
        finalizer_result = result_data.get("finalizer_result")
        final_envelope = final_envelope if isinstance(final_envelope, dict) else {}
        finalizer_result = finalizer_result if isinstance(finalizer_result, dict) else {}

        result = next(
            (
                value
                for value in (
                    result_data.get("agent_output"),
                    result_data.get("summary"),
                    result_data.get("final_answer"),
                    result_data.get("workflow_result"),
                    result_data.get("message"),
                    final_envelope.get("summary_text"),
                    finalizer_result.get("summary_text"),
                    nested_data.get("workflow_result"),
                )
                if isinstance(value, str) and value.strip()
            ),
            None,
        )
        outcome = next(
            (
                value
                for value in (
                    result_data.get("outcome"),
                    final_envelope.get("outcome"),
                    finalizer_result.get("outcome"),
                )
                if isinstance(value, str) and value.strip()
            ),
            None,
        )

        if result and outcome:
            return result, outcome

        timeline = result_data.get("execution_timeline")
        if not isinstance(timeline, list):
            return result, outcome
        final_summary = next(
            (
                entry
                for entry in reversed(timeline)
                if isinstance(entry, dict) and entry.get("id") == "final_summary"
            ),
            None,
        )
        if not isinstance(final_summary, dict):
            return result, outcome
        metadata = final_summary.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        return (
            result or final_summary.get("body") or final_summary.get("content"),
            outcome or metadata.get("outcome"),
        )

    def _map_agent_task_state(self, status: str) -> HomeTurnState:
        if status == "completed":
            return HomeTurnState.COMPLETED
        if status == "canceled":
            return HomeTurnState.CANCELED
        if status == "failed":
            return HomeTurnState.FAILED
        return HomeTurnState.RUNNING

    def _build_timeline(
        self,
        messages: List[Dict[str, Any]],
        turns: List[HomeTurn],
        linked_tasks: List[LinkedAgentTaskSummary],
    ) -> List[Dict[str, Any]]:
        turns_by_user_message = {turn.user_message_id: turn for turn in turns}
        linked_by_message = {item.user_message_id: item for item in linked_tasks}
        assistant_to_user: Dict[str, str] = {}
        for turn in turns:
            if turn.assistant_message_id:
                assistant_to_user[turn.assistant_message_id] = turn.user_message_id

        timeline: List[Dict[str, Any]] = []
        for message in messages:
            message_id = message["id"]
            role = message["role"]
            created_at = message["timestamp"]
            content = message["content"]

            if role == "user":
                metadata = message.get("metadata")
                metadata = metadata if isinstance(metadata, dict) else {}
                display_markdown = metadata.get("display_prompt_markdown")
                reference_paths = metadata.get("reference_paths")
                user_item: Dict[str, Any] = {
                    "kind": "user_message",
                    "messageId": message_id,
                    "content": content,
                    "createdAt": created_at,
                }
                if isinstance(display_markdown, str) and display_markdown.strip():
                    user_item["displayMarkdown"] = display_markdown
                if isinstance(reference_paths, list):
                    user_item["referencePaths"] = [
                        path for path in reference_paths if isinstance(path, str) and path.strip()
                    ]
                timeline.append(user_item)
                turn = turns_by_user_message.get(message_id)
                linked = linked_by_message.get(message_id)
                if turn and turn.route_kind.value == "agent_task" and turn.agent_task_id:
                    ui_state = self._timeline_agent_task_state(turn.state, linked)
                    timeline.append(
                        {
                            "kind": "agent_task",
                            "messageId": message_id,
                            "inReplyTo": message_id,
                            "agentTaskId": turn.agent_task_id,
                            "state": ui_state,
                            "result": linked.result if linked else None,
                            "outcome": linked.outcome if linked else None,
                            "createdAt": created_at,
                        }
                    )
                continue

            if role in {"assistant", "error"}:
                in_reply_to = assistant_to_user.get(message_id)
                if in_reply_to:
                    timeline.append(
                        {
                            "kind": "conversation_answer",
                            "messageId": message_id,
                            "inReplyTo": in_reply_to,
                            "content": content,
                            "createdAt": created_at,
                        }
                    )
                continue

        return timeline

    def _timeline_agent_task_state(
        self,
        turn_state: HomeTurnState,
        linked: Optional[LinkedAgentTaskSummary],
    ) -> str:
        if turn_state == HomeTurnState.ROUTING:
            return "queued"
        if turn_state == HomeTurnState.RUNNING:
            return "running"
        if turn_state == HomeTurnState.COMPLETED:
            return "completed"
        if turn_state == HomeTurnState.FAILED:
            return "failed"
        if turn_state == HomeTurnState.CANCELED:
            return "canceled"
        if linked and linked.status:
            if linked.status == "completed":
                return "completed"
            if linked.status == "canceled":
                return "canceled"
            if linked.status == "failed":
                return "failed"
        return "running"
