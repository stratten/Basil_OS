"""Conversation pair projection and stale lifecycle reconciliation coverage."""

import json
from datetime import datetime, timedelta, timezone

from api.services.zettel import store
from api.services.zettel.conversation_turn_reconciler import (
    STALE_CONVERSATION_TURN_OUTCOME,
    reconcile_stale_conversation_turns,
)
from api.services.zettel.sources.conversation_turn_source import ConversationTurnSource


def _insert_pair(
    conn,
    *,
    conversation_id,
    user_id,
    assistant_id,
    lifecycle,
    timestamp,
    route="direct",
    agent_task_id=None,
    metadata=None,
):
    conn.execute(
        "INSERT OR IGNORE INTO conversations (id, title) VALUES (?, 'Conversation')",
        (conversation_id,),
    )
    conn.execute(
        """
        INSERT INTO conversation_messages (id, conversation_id, role, content, timestamp)
        VALUES (?, ?, 'user', ?, ?)
        """,
        (user_id, conversation_id, f"User {user_id}", timestamp),
    )
    metadata = metadata or {
        "conversation_turn": {
            "route": route,
            "lifecycle": lifecycle,
            "agent_task_id": agent_task_id,
            "terminal_outcome": f"{lifecycle} outcome",
            "user_message_id": user_id,
            "narration": {"lifecycle": "pending", "attempt_count": 0},
        }
    }
    conn.execute(
        """
        INSERT INTO conversation_messages
            (id, conversation_id, role, content, metadata, timestamp)
        VALUES (?, ?, 'assistant', ?, ?, ?)
        """,
        (
            assistant_id,
            conversation_id,
            f"Assistant {assistant_id}",
            json.dumps(metadata),
            timestamp,
        ),
    )


def test_source_projects_terminal_direct_and_delegated_pairs_with_pair_context(conn):
    _insert_pair(
        conn,
        conversation_id="direct",
        user_id="user-direct",
        assistant_id="assistant-direct",
        lifecycle="completed",
        timestamp="2026-08-10T10:00:00+00:00",
    )
    conn.execute(
        """
        INSERT INTO agent_tasks
            (id, timestamp, original_prompt, transcribed_prompt, status, result_data, created_at, updated_at)
        VALUES
            ('task-delegated', '2026-08-10T11:00:00+00:00', 'p', 'p', 'completed',
             '{"summary":"delegated result"}', '2026-08-10T11:00:00+00:00', '2026-08-10T11:00:00+00:00')
        """
    )
    _insert_pair(
        conn,
        conversation_id="delegated",
        user_id="user-delegated",
        assistant_id="assistant-delegated",
        lifecycle="failed",
        timestamp="2026-08-10T11:00:00+00:00",
        route="agent_task",
        agent_task_id="task-delegated",
    )

    source = ConversationTurnSource()
    drafts = source.find_uncarded(conn, since_iso=None, limit=10)

    assert [(draft.source_id, draft.source_status) for draft in drafts] == [
        ("assistant-direct", "completed"),
        ("assistant-delegated", "failed"),
    ]
    for draft in drafts:
        assert store.insert_card(conn, draft)
    context = source.gather_context(conn, ["assistant-delegated"])
    assert set(context["assistant-delegated"]) == {
        "user_message",
        "assistant_message",
        "route",
        "lifecycle",
        "terminal_outcome",
        "agent_task",
    }
    assert context["assistant-delegated"]["user_message"] == "User user-delegated"
    assert context["assistant-delegated"]["agent_task"]["result_data"] == {
        "summary": "delegated result"
    }
    direct_context = source.gather_context(conn, ["assistant-direct"])["assistant-direct"]
    assert set(direct_context) == {
        "user_message",
        "assistant_message",
        "route",
        "lifecycle",
        "terminal_outcome",
    }


def test_source_skips_malformed_metadata_and_keeps_missing_linked_task_visible(conn):
    _insert_pair(
        conn,
        conversation_id="bad",
        user_id="user-bad",
        assistant_id="assistant-bad",
        lifecycle="completed",
        timestamp="2026-08-10T10:00:00+00:00",
        metadata={"conversation_turn": {"route": "unknown"}},
    )
    _insert_pair(
        conn,
        conversation_id="missing",
        user_id="user-missing",
        assistant_id="assistant-missing",
        lifecycle="cancelled",
        timestamp="2026-08-10T11:00:00+00:00",
        route="agent_task",
        agent_task_id="missing-task",
    )

    source = ConversationTurnSource()
    drafts = source.find_uncarded(conn, since_iso=None, limit=10)

    assert [draft.source_id for draft in drafts] == ["assistant-missing"]
    assert source.gather_context(conn, ["assistant-missing"])["assistant-missing"][
        "agent_task"
    ] == {"id": "missing-task", "status": "missing", "result_data": None}


def test_stale_turns_close_at_the_exact_six_hour_boundary_and_fail_stale_tasks(conn):
    now = datetime(2026, 8, 10, 18, tzinfo=timezone.utc)
    stale_at = (now - timedelta(hours=6)).isoformat()
    conn.execute(
        """
        INSERT INTO agent_tasks
            (id, timestamp, original_prompt, transcribed_prompt, status, created_at, updated_at)
        VALUES ('task-stale', ?, 'p', 'p', 'running', ?, ?)
        """,
        (stale_at, stale_at, stale_at),
    )
    _insert_pair(
        conn,
        conversation_id="stale",
        user_id="user-stale",
        assistant_id="assistant-stale",
        lifecycle="running",
        timestamp=stale_at,
        route="agent_task",
        agent_task_id="task-stale",
    )
    original_metadata = json.loads(
        conn.execute(
            "SELECT metadata FROM conversation_messages WHERE id = 'assistant-stale'"
        ).fetchone()["metadata"]
    )
    original_metadata["surface"] = "basil_board_chats"
    conn.execute(
        "UPDATE conversation_messages SET metadata = ? WHERE id = 'assistant-stale'",
        (json.dumps(original_metadata),),
    )

    result = reconcile_stale_conversation_turns(conn, now=now)

    assert result.closed_turns == 1
    assert result.failed_agent_tasks == 1
    metadata = json.loads(
        conn.execute(
            "SELECT metadata FROM conversation_messages WHERE id = 'assistant-stale'"
        ).fetchone()["metadata"]
    )
    assert metadata["conversation_turn"]["lifecycle"] == "cancelled"
    assert metadata["conversation_turn"]["terminal_outcome"] == STALE_CONVERSATION_TURN_OUTCOME
    assert metadata["surface"] == "basil_board_chats"
    task = conn.execute(
        "SELECT status, result_data FROM agent_tasks WHERE id = 'task-stale'"
    ).fetchone()
    assert task["status"] == "failed"
    task_result = json.loads(task["result_data"])
    assert task_result["stale_execution"] is True
    assert task_result["error"] == STALE_CONVERSATION_TURN_OUTCOME


def test_newer_agent_task_activity_defers_pair_timeout_and_later_turn_cards_independently(conn):
    now = datetime(2026, 8, 10, 18, tzinfo=timezone.utc)
    stale_at = (now - timedelta(hours=7)).isoformat()
    recent_at = (now - timedelta(hours=1)).isoformat()
    conn.execute(
        """
        INSERT INTO agent_tasks
            (id, timestamp, original_prompt, transcribed_prompt, status, created_at, updated_at)
        VALUES ('task-recent', ?, 'p', 'p', 'running', ?, ?)
        """,
        (stale_at, stale_at, recent_at),
    )
    _insert_pair(
        conn,
        conversation_id="same-conversation",
        user_id="user-active",
        assistant_id="assistant-active",
        lifecycle="running",
        timestamp=stale_at,
        route="agent_task",
        agent_task_id="task-recent",
    )
    _insert_pair(
        conn,
        conversation_id="same-conversation",
        user_id="user-later",
        assistant_id="assistant-later",
        lifecycle="completed",
        timestamp=recent_at,
    )

    result = reconcile_stale_conversation_turns(conn, now=now)

    assert result.closed_turns == 0
    source = ConversationTurnSource()
    assert [draft.source_id for draft in source.find_uncarded(conn, since_iso=None, limit=10)] == [
        "assistant-later"
    ]
