"""SQLite persistence for BasilBoard domain tables."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
)
from api.services.basil_board.models import (
    BasilBoardTab,
    BasilBoardTabKind,
    BasilBoardTabStatus,
    BoardInquirySummary,
    HomeState,
    HomeTurn,
    HomeTurnRouteKind,
    HomeTurnState,
)


class BasilBoardRepository:
    """All BasilBoard SQL lives in this module."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def ensure_home_tab(self) -> BasilBoardTab:
        def _sync() -> BasilBoardTab:
            conn = get_sync_connection(self.db_path)
            with conn:
                row = conn.execute(
                    "SELECT * FROM basil_board_tabs WHERE id = 'home'"
                ).fetchone()
                if not row:
                    conn.execute(
                        """
                        INSERT INTO basil_board_tabs (
                            id, title, icon_key, position, tab_kind, status,
                            configuration_json, created_by_kind
                        ) VALUES ('home', 'Home', 'home', 0, 'home', 'active', '{}', 'system')
                        """
                    )
                    row = conn.execute(
                        "SELECT * FROM basil_board_tabs WHERE id = 'home'"
                    ).fetchone()
                conn.commit()
            return self._row_to_tab(row)

        return await asyncio.to_thread(_sync)

    async def list_active_tabs(self) -> List[BasilBoardTab]:
        def _sync() -> List[BasilBoardTab]:
            conn = get_sync_connection(self.db_path)
            with conn:
                rows = conn.execute(
                    """
                    SELECT * FROM basil_board_tabs
                    WHERE status = 'active'
                    ORDER BY position ASC, created_at ASC
                    """
                ).fetchall()
            return [self._row_to_tab(row) for row in rows]

        return await asyncio.to_thread(_sync)

    async def get_home_state(self) -> Optional[HomeState]:
        def _sync() -> Optional[HomeState]:
            conn = get_sync_connection(self.db_path)
            with conn:
                row = conn.execute(
                    "SELECT * FROM basil_board_home_state WHERE id = 'default'"
                ).fetchone()
            return self._row_to_home_state(row) if row else None

        return await asyncio.to_thread(_sync)

    async def upsert_home_state(self, conversation_id: str) -> HomeState:
        def _sync() -> HomeState:
            conn = get_sync_connection(self.db_path)
            with conn:
                conn.execute(
                    """
                    INSERT INTO basil_board_home_state (id, conversation_id, updated_at)
                    VALUES ('default', ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(id) DO UPDATE SET
                        conversation_id = excluded.conversation_id,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (conversation_id,),
                )
                row = conn.execute(
                    "SELECT * FROM basil_board_home_state WHERE id = 'default'"
                ).fetchone()
                conn.commit()
            return self._row_to_home_state(row)

        return await asyncio.to_thread(_sync)

    async def create_home_turn(
        self,
        *,
        user_message_id: str,
        conversation_id: str,
        route_kind: HomeTurnRouteKind,
        route_reason: str,
        route_confidence: Optional[float],
        state: HomeTurnState,
        agent_task_id: Optional[str] = None,
        assistant_message_id: Optional[str] = None,
    ) -> HomeTurn:
        def _sync() -> HomeTurn:
            conn = get_sync_connection(self.db_path)
            with conn:
                conn.execute(
                    """
                    INSERT INTO basil_board_home_turns (
                        user_message_id, conversation_id, route_kind, route_reason,
                        route_confidence, agent_task_id, assistant_message_id, state
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_message_id,
                        conversation_id,
                        route_kind.value,
                        route_reason,
                        route_confidence,
                        agent_task_id,
                        assistant_message_id,
                        state.value,
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM basil_board_home_turns WHERE user_message_id = ?",
                    (user_message_id,),
                ).fetchone()
                conn.commit()
            return self._row_to_turn(row)

        return await asyncio.to_thread(_sync)

    async def update_home_turn(
        self,
        user_message_id: str,
        *,
        state: Optional[HomeTurnState] = None,
        agent_task_id: Optional[str] = None,
        assistant_message_id: Optional[str] = None,
        route_reason: Optional[str] = None,
        route_confidence: Optional[float] = None,
    ) -> Optional[HomeTurn]:
        updates: Dict[str, Any] = {}
        if state is not None:
            updates["state"] = state.value
        if agent_task_id is not None:
            updates["agent_task_id"] = agent_task_id
        if assistant_message_id is not None:
            updates["assistant_message_id"] = assistant_message_id
        if route_reason is not None:
            updates["route_reason"] = route_reason
        if route_confidence is not None:
            updates["route_confidence"] = route_confidence
        if not updates:
            return await self.get_home_turn(user_message_id)

        set_clause = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values()) + [user_message_id]

        def _sync() -> Optional[HomeTurn]:
            conn = get_sync_connection(self.db_path)
            with conn:
                conn.execute(
                    f"""
                    UPDATE basil_board_home_turns
                    SET {set_clause}, updated_at = CURRENT_TIMESTAMP
                    WHERE user_message_id = ?
                    """,
                    values,
                )
                row = conn.execute(
                    "SELECT * FROM basil_board_home_turns WHERE user_message_id = ?",
                    (user_message_id,),
                ).fetchone()
                conn.commit()
            return self._row_to_turn(row) if row else None

        return await asyncio.to_thread(_sync)

    async def get_home_turn(self, user_message_id: str) -> Optional[HomeTurn]:
        def _sync() -> Optional[HomeTurn]:
            conn = get_sync_connection(self.db_path)
            with conn:
                row = conn.execute(
                    "SELECT * FROM basil_board_home_turns WHERE user_message_id = ?",
                    (user_message_id,),
                ).fetchone()
            return self._row_to_turn(row) if row else None

        return await asyncio.to_thread(_sync)

    async def get_home_turn_by_agent_task(self, agent_task_id: str) -> Optional[HomeTurn]:
        def _sync() -> Optional[HomeTurn]:
            conn = get_sync_connection(self.db_path)
            with conn:
                row = conn.execute(
                    "SELECT * FROM basil_board_home_turns WHERE agent_task_id = ?",
                    (agent_task_id,),
                ).fetchone()
            return self._row_to_turn(row) if row else None

        return await asyncio.to_thread(_sync)

    async def list_home_turns(
        self,
        conversation_id: str,
        *,
        limit: int = 200,
    ) -> List[HomeTurn]:
        def _sync() -> List[HomeTurn]:
            conn = get_sync_connection(self.db_path)
            with conn:
                rows = conn.execute(
                    """
                    SELECT * FROM basil_board_home_turns
                    WHERE conversation_id = ?
                    ORDER BY created_at ASC
                    LIMIT ?
                    """,
                    (conversation_id, limit),
                ).fetchall()
            return [self._row_to_turn(row) for row in rows]

        return await asyncio.to_thread(_sync)

    async def list_nonterminal_home_turns(self, conversation_id: str) -> List[HomeTurn]:
        def _sync() -> List[HomeTurn]:
            conn = get_sync_connection(self.db_path)
            with conn:
                rows = conn.execute(
                    """
                    SELECT * FROM basil_board_home_turns
                    WHERE conversation_id = ?
                      AND state IN ('routing', 'running')
                    ORDER BY created_at ASC
                    """,
                    (conversation_id,),
                ).fetchall()
            return [self._row_to_turn(row) for row in rows]

        return await asyncio.to_thread(_sync)

    async def list_conversation_messages(
        self,
        conversation_id: str,
        *,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        def _sync() -> List[Dict[str, Any]]:
            conn = get_sync_connection(self.db_path)
            with conn:
                rows = conn.execute(
                    """
                    SELECT id, role, content, timestamp, metadata
                    FROM conversation_messages
                    WHERE conversation_id = ?
                    ORDER BY timestamp ASC
                    LIMIT ?
                    """,
                    (conversation_id, limit),
                ).fetchall()
            return [
                {
                    "id": row["id"],
                    "role": row["role"],
                    "content": row["content"],
                    "timestamp": row["timestamp"],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                }
                for row in rows
            ]

        return await asyncio.to_thread(_sync)

    async def create_conversation(
        self,
        *,
        title: str = "Basil Home",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        conversation_id = str(uuid.uuid4())

        def _sync() -> str:
            conn = get_sync_connection(self.db_path)
            with conn:
                conn.execute(
                    """
                    INSERT INTO conversations (id, title, metadata, created_at, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (conversation_id, title, json.dumps(metadata or {"surface": "basil_board_home"})),
                )
                conn.commit()
            return conversation_id

        return await asyncio.to_thread(_sync)

    _INQUIRY_UPDATABLE_FIELDS = {
        "route_kind",
        "route_reason",
        "route_confidence",
        "state",
        "conversation_id",
        "user_message_id",
        "assistant_message_id",
        "agent_task_id",
    }

    async def create_inquiry(
        self,
        *,
        prompt_text: str,
        display_prompt_markdown: Optional[str],
        reference_paths: List[str],
        state: HomeTurnState = HomeTurnState.ROUTING,
    ) -> BoardInquirySummary:
        inquiry_id = str(uuid.uuid4())

        def _sync() -> BoardInquirySummary:
            conn = get_sync_connection(self.db_path)
            with conn:
                conn.execute(
                    """
                    INSERT INTO basil_board_inquiries (
                        id, prompt_text, display_prompt_markdown, reference_paths_json, state
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (inquiry_id, prompt_text, display_prompt_markdown, json.dumps(reference_paths), state.value),
                )
                row = conn.execute(
                    "SELECT * FROM basil_board_inquiries WHERE id = ?", (inquiry_id,)
                ).fetchone()
                conn.commit()
            return self._row_to_inquiry(row)

        return await asyncio.to_thread(_sync)

    async def update_inquiry(self, inquiry_id: str, **fields: Any) -> Optional[BoardInquirySummary]:
        updates: Dict[str, Any] = {
            key: value for key, value in fields.items() if key in self._INQUIRY_UPDATABLE_FIELDS
        }
        if not updates:
            return await self.get_inquiry(inquiry_id)
        if isinstance(updates.get("state"), HomeTurnState):
            updates["state"] = updates["state"].value
        if isinstance(updates.get("route_kind"), HomeTurnRouteKind):
            updates["route_kind"] = updates["route_kind"].value

        set_clause = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values()) + [inquiry_id]

        def _sync() -> Optional[BoardInquirySummary]:
            conn = get_sync_connection(self.db_path)
            with conn:
                conn.execute(
                    f"""
                    UPDATE basil_board_inquiries
                    SET {set_clause}, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    values,
                )
                row = conn.execute(
                    "SELECT * FROM basil_board_inquiries WHERE id = ?", (inquiry_id,)
                ).fetchone()
                conn.commit()
            return self._row_to_inquiry(row) if row else None

        return await asyncio.to_thread(_sync)

    async def get_inquiry(self, inquiry_id: str) -> Optional[BoardInquirySummary]:
        def _sync() -> Optional[BoardInquirySummary]:
            conn = get_sync_connection(self.db_path)
            with conn:
                row = conn.execute(
                    "SELECT * FROM basil_board_inquiries WHERE id = ?", (inquiry_id,)
                ).fetchone()
            return self._row_to_inquiry(row) if row else None

        return await asyncio.to_thread(_sync)

    async def get_inquiry_by_user_message(self, user_message_id: str) -> Optional[BoardInquirySummary]:
        def _sync() -> Optional[BoardInquirySummary]:
            conn = get_sync_connection(self.db_path)
            with conn:
                row = conn.execute(
                    "SELECT * FROM basil_board_inquiries WHERE user_message_id = ?",
                    (user_message_id,),
                ).fetchone()
            return self._row_to_inquiry(row) if row else None

        return await asyncio.to_thread(_sync)

    async def list_recent_inquiries(self, *, limit: int = 50) -> List[BoardInquirySummary]:
        def _sync() -> List[BoardInquirySummary]:
            conn = get_sync_connection(self.db_path)
            with conn:
                rows = conn.execute(
                    """
                    SELECT * FROM basil_board_inquiries
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [self._row_to_inquiry(row) for row in rows]

        return await asyncio.to_thread(_sync)

    def _row_to_inquiry(self, row: Any) -> BoardInquirySummary:
        try:
            reference_paths = json.loads(row["reference_paths_json"] or "[]")
            if not isinstance(reference_paths, list):
                reference_paths = []
        except (TypeError, ValueError, json.JSONDecodeError):
            reference_paths = []
        return BoardInquirySummary(
            id=row["id"],
            promptText=row["prompt_text"],
            displayMarkdown=row["display_prompt_markdown"],
            referencePaths=[path for path in reference_paths if isinstance(path, str)],
            routeKind=HomeTurnRouteKind(row["route_kind"]) if row["route_kind"] else None,
            routeReason=row["route_reason"],
            routeConfidence=row["route_confidence"],
            state=HomeTurnState(row["state"]),
            conversationId=row["conversation_id"],
            agentTaskId=row["agent_task_id"],
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
        )

    def _row_to_tab(self, row: Any) -> BasilBoardTab:
        return BasilBoardTab(
            id=row["id"],
            title=row["title"],
            icon_key=row["icon_key"],
            position=row["position"],
            tab_kind=BasilBoardTabKind(row["tab_kind"]),
            status=BasilBoardTabStatus(row["status"]),
            configuration=json.loads(row["configuration_json"] or "{}"),
            created_by_kind=row["created_by_kind"],
            created_by_id=row["created_by_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_home_state(self, row: Any) -> HomeState:
        return HomeState(
            id=row["id"],
            conversation_id=row["conversation_id"],
            updated_at=row["updated_at"],
        )

    def _row_to_turn(self, row: Any) -> HomeTurn:
        return HomeTurn(
            user_message_id=row["user_message_id"],
            conversation_id=row["conversation_id"],
            route_kind=HomeTurnRouteKind(row["route_kind"]),
            route_reason=row["route_reason"],
            route_confidence=row["route_confidence"],
            agent_task_id=row["agent_task_id"],
            assistant_message_id=row["assistant_message_id"],
            state=HomeTurnState(row["state"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
