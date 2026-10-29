"""`handle_todo_workspace_message` coverage: the full validation matrix
(blank ids, empty/oversized selection, duplicate ids, malformed transcript
roles/lengths, oversized aggregate transcript), the accepted-turn happy
path, and turn-manager exception surfacing as a structured error event."""

from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from api.routes.websocket_routes.todo_workspace import handle_todo_workspace_message


class FakeWebSocket:
    def __init__(self) -> None:
        self.send_json = AsyncMock()


class FakeTurnManager:
    def __init__(self, *, result: Dict[str, Any] = None, raise_exc: Exception = None) -> None:
        self.result = result if result is not None else {"agent_task_id": "task-1"}
        self.raise_exc = raise_exc
        self.calls: List[Dict[str, Any]] = []

    async def submit_turn(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_exc:
            raise self.raise_exc
        return self.result


def _valid_message(**overrides) -> Dict[str, Any]:
    base = {
        "workspace_id": "ws-1", "request_id": "req-1", "message": "What's the status?",
        "selected_todo_ids": ["todo-1"], "reference_paths": [], "transcript": [], "model_id": None,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_accepted_turn_sends_todo_workspace_accepted_with_the_agent_task_id() -> None:
    ws = FakeWebSocket()
    turn_manager = FakeTurnManager(result={"agent_task_id": "task-42"})

    await handle_todo_workspace_message(ws, _valid_message(), turn_manager=turn_manager)

    ws.send_json.assert_awaited_once()
    sent = ws.send_json.await_args.args[0]
    assert sent == {
        "event_type": "todo_workspace_accepted", "workspace_id": "ws-1", "request_id": "req-1",
        "agent_task_id": "task-42",
    }


@pytest.mark.asyncio
async def test_turn_manager_exception_sends_a_structured_error_event() -> None:
    ws = FakeWebSocket()
    turn_manager = FakeTurnManager(raise_exc=RuntimeError("selection contains a dismissed To-Do"))

    await handle_todo_workspace_message(ws, _valid_message(), turn_manager=turn_manager)

    sent = ws.send_json.await_args.args[0]
    assert sent["event_type"] == "todo_workspace_error"
    assert "dismissed" in sent["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"workspace_id": ""},
        {"request_id": "  "},
        {"message": ""},
        {"reference_paths": ["relative.txt"]},
        {"reference_paths": None},
        {"selected_todo_ids": ["a"] * 101},
        {"selected_todo_ids": ["a", ""]},
        {"selected_todo_ids": ["a", "a"]},
        {"selected_todo_ids": "not-a-list"},
        {"transcript": [{"role": "system", "content": "x"}]},
        {"transcript": [{"role": "user", "content": "x" * 4001}]},
        {"transcript": [{"role": "user"}]},
        {"transcript": [{"role": "user", "content": "x"}] * 21},
    ],
)
async def test_validation_rejects_malformed_input_without_calling_the_turn_manager(overrides: Dict[str, Any]) -> None:
    ws = FakeWebSocket()
    turn_manager = FakeTurnManager()

    await handle_todo_workspace_message(ws, _valid_message(**overrides), turn_manager=turn_manager)

    assert turn_manager.calls == []
    sent = ws.send_json.await_args.args[0]
    assert sent["event_type"] == "todo_workspace_error"


@pytest.mark.asyncio
async def test_validation_rejects_oversized_aggregate_transcript_content() -> None:
    ws = FakeWebSocket()
    turn_manager = FakeTurnManager()
    big_transcript = [{"role": "user", "content": "x" * 4000} for _ in range(5)]  # 20000 > 16000 cap

    await handle_todo_workspace_message(
        ws, _valid_message(transcript=big_transcript), turn_manager=turn_manager,
    )

    assert turn_manager.calls == []
    sent = ws.send_json.await_args.args[0]
    assert sent["event_type"] == "todo_workspace_error"
    assert "16000" in sent["message"]


@pytest.mark.asyncio
async def test_multi_item_selection_is_passed_through_to_the_turn_manager() -> None:
    ws = FakeWebSocket()
    turn_manager = FakeTurnManager()

    await handle_todo_workspace_message(
        ws, _valid_message(selected_todo_ids=["todo-1", "todo-2", "todo-3"]), turn_manager=turn_manager,
    )

    assert turn_manager.calls[0]["selected_todo_ids"] == ["todo-1", "todo-2", "todo-3"]


@pytest.mark.asyncio
async def test_empty_selection_and_reference_paths_are_passed_through_to_the_turn_manager() -> None:
    ws = FakeWebSocket()
    turn_manager = FakeTurnManager()

    await handle_todo_workspace_message(
        ws,
        _valid_message(selected_todo_ids=[], reference_paths=["/tmp/action-items.pdf"]),
        turn_manager=turn_manager,
    )

    assert turn_manager.calls[0]["selected_todo_ids"] == []
    assert turn_manager.calls[0]["reference_paths"] == ["/tmp/action-items.pdf"]
