import asyncio

import pytest

from api.routes.websocket_routes.conversation_request_runtime import (
    ConversationRequestRuntime,
    ConversationRequestState,
)


@pytest.mark.asyncio
async def test_start_executes_worker_and_cleans_up():
    runtime = ConversationRequestRuntime()
    websocket = object()
    started = asyncio.Event()
    release = asyncio.Event()
    completed = asyncio.Event()

    async def worker(state):
        started.set()
        await release.wait()
        completed.set()

    assert runtime.start(websocket, "request-1", "conversation-1", worker) is True
    await asyncio.wait_for(started.wait(), timeout=1)
    release.set()
    await asyncio.wait_for(completed.wait(), timeout=1)
    assert runtime.request_cancel(websocket, "request-1") is None


@pytest.mark.asyncio
async def test_duplicate_request_ids_rejected_for_same_socket():
    runtime = ConversationRequestRuntime()
    websocket = object()
    gate = asyncio.Event()

    async def worker(_state):
        await gate.wait()

    assert runtime.start(websocket, "request-1", None, worker) is True
    assert runtime.start(websocket, "request-1", None, worker) is False
    gate.set()


@pytest.mark.asyncio
async def test_cancel_before_persistence_waits():
    runtime = ConversationRequestRuntime()
    websocket = object()
    entered = asyncio.Event()

    async def worker(state):
        entered.set()
        await asyncio.Event().wait()

    assert runtime.start(websocket, "request-1", None, worker) is True
    await asyncio.wait_for(entered.wait(), timeout=1)
    state = runtime.request_cancel(websocket, "request-1")
    assert state is not None
    assert state.cancel_requested is True
    assert state.persistence_ready is False
    assert state.task is not None
    assert state.task.done() is False
    state.task.cancel()
    await asyncio.gather(state.task, return_exceptions=True)


@pytest.mark.asyncio
async def test_mark_persistence_ready_then_cancels():
    runtime = ConversationRequestRuntime()
    websocket = object()
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def worker(state):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    assert runtime.start(websocket, "request-1", None, worker) is True
    await asyncio.wait_for(entered.wait(), timeout=1)
    state = runtime._requests[(id(websocket), "request-1")]
    runtime.request_cancel(websocket, "request-1")
    runtime.mark_persistence_ready(state, "user-1", "assistant-1")
    await asyncio.wait_for(cancelled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_cancel_after_persistence_cancels_immediately():
    runtime = ConversationRequestRuntime()
    websocket = object()
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def worker(state):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    assert runtime.start(websocket, "request-1", None, worker) is True
    await asyncio.wait_for(entered.wait(), timeout=1)
    state = runtime._requests[(id(websocket), "request-1")]
    runtime.mark_persistence_ready(state, "user-1", "assistant-1")
    runtime.request_cancel(websocket, "request-1")
    await asyncio.wait_for(cancelled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_another_socket_cannot_cancel():
    runtime = ConversationRequestRuntime()
    websocket_a = object()
    websocket_b = object()
    gate = asyncio.Event()

    async def worker(_state):
        await gate.wait()

    assert runtime.start(websocket_a, "request-1", None, worker) is True
    assert runtime.request_cancel(websocket_b, "request-1") is None
    gate.set()


@pytest.mark.asyncio
async def test_disconnect_cancels_all_and_waits():
    runtime = ConversationRequestRuntime()
    websocket = object()
    started_a = asyncio.Event()
    started_b = asyncio.Event()
    cancelled_a = asyncio.Event()
    cancelled_b = asyncio.Event()

    async def worker_a(_state):
        started_a.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled_a.set()
            raise

    async def worker_b(_state):
        started_b.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled_b.set()
            raise

    assert runtime.start(websocket, "request-1", None, worker_a) is True
    assert runtime.start(websocket, "request-2", None, worker_b) is True
    await asyncio.wait_for(started_a.wait(), timeout=1)
    await asyncio.wait_for(started_b.wait(), timeout=1)
    state_a = runtime._requests[(id(websocket), "request-1")]
    state_b = runtime._requests[(id(websocket), "request-2")]
    runtime.mark_persistence_ready(state_a, "user-1", "assistant-1")
    runtime.mark_persistence_ready(state_b, "user-2", "assistant-2")
    await runtime.cancel_for_websocket(websocket)
    await asyncio.wait_for(cancelled_a.wait(), timeout=1)
    await asyncio.wait_for(cancelled_b.wait(), timeout=1)


def test_bind_agent_task_then_claim_returns_the_agent_task_id():
    runtime = ConversationRequestRuntime()
    websocket = object()

    runtime.bind_agent_task(websocket, "request-1", "task-1")

    assert runtime.claim_agent_task_cancellation(websocket, "request-1") == "task-1"


@pytest.mark.parametrize(
    ("request_id", "agent_task_id", "error"),
    [
        ("", "task-1", "request_id"),
        ("request-1", "", "agent_task_id"),
    ],
)
def test_bind_agent_task_rejects_empty_identifiers(
    request_id: str,
    agent_task_id: str,
    error: str,
):
    runtime = ConversationRequestRuntime()

    with pytest.raises(ValueError, match=error):
        runtime.bind_agent_task(object(), request_id, agent_task_id)


def test_claim_agent_task_cancellation_is_one_shot():
    runtime = ConversationRequestRuntime()
    websocket = object()
    runtime.bind_agent_task(websocket, "request-1", "task-1")

    first = runtime.claim_agent_task_cancellation(websocket, "request-1")
    second = runtime.claim_agent_task_cancellation(websocket, "request-1")

    assert first == "task-1"
    assert second is None


def test_claim_agent_task_cancellation_is_scoped_to_the_matching_socket():
    runtime = ConversationRequestRuntime()
    websocket_a = object()
    websocket_b = object()
    runtime.bind_agent_task(websocket_a, "request-1", "task-1")

    assert runtime.claim_agent_task_cancellation(websocket_b, "request-1") is None
    assert runtime.claim_agent_task_cancellation(websocket_a, "request-1") == "task-1"


@pytest.mark.asyncio
async def test_bind_agent_task_survives_after_the_worker_task_completes():
    runtime = ConversationRequestRuntime()
    websocket = object()
    completed = asyncio.Event()

    async def worker(_state):
        completed.set()

    assert runtime.start(websocket, "request-1", None, worker) is True
    await asyncio.wait_for(completed.wait(), timeout=1)
    await asyncio.sleep(0)
    assert (id(websocket), "request-1") not in runtime._requests

    runtime.bind_agent_task(websocket, "request-1", "task-1")

    assert runtime.claim_agent_task_cancellation(websocket, "request-1") == "task-1"


def test_release_agent_task_removes_both_indexes():
    runtime = ConversationRequestRuntime()
    websocket = object()
    runtime.bind_agent_task(websocket, "request-1", "task-1")

    runtime.release_agent_task("task-1")

    assert runtime.claim_agent_task_cancellation(websocket, "request-1") is None
    assert "task-1" not in runtime._agent_task_link_keys


def test_release_agent_task_tolerates_unknown_ids():
    runtime = ConversationRequestRuntime()
    runtime.release_agent_task("does-not-exist")


@pytest.mark.asyncio
async def test_different_conversations_start_concurrently():
    runtime = ConversationRequestRuntime()
    websocket = object()
    gate = asyncio.Event()

    async def worker(_state):
        await gate.wait()

    assert runtime.start(websocket, "request-1", "conversation-1", worker) is True
    assert runtime.start(websocket, "request-2", "conversation-2", worker) is True
    gate.set()


@pytest.mark.asyncio
async def test_second_socket_cannot_start_the_same_conversation():
    runtime = ConversationRequestRuntime()
    websocket_a = object()
    websocket_b = object()
    gate = asyncio.Event()

    async def worker(_state):
        await gate.wait()

    assert runtime.start(websocket_a, "request-1", "conversation-1", worker) is True
    assert runtime.start(websocket_b, "request-2", "conversation-1", worker) is False
    gate.set()


@pytest.mark.asyncio
async def test_direct_completion_releases_the_conversation_reservation():
    runtime = ConversationRequestRuntime()
    websocket = object()
    completed = asyncio.Event()

    async def worker(_state):
        completed.set()

    assert runtime.start(websocket, "request-1", "conversation-1", worker) is True
    await asyncio.wait_for(completed.wait(), timeout=1)
    await asyncio.sleep(0)
    assert runtime.is_conversation_active("conversation-1") is False


@pytest.mark.asyncio
async def test_agent_task_binding_retains_the_reservation_after_the_worker_exits():
    runtime = ConversationRequestRuntime()
    websocket = object()
    completed = asyncio.Event()

    async def worker(state):
        runtime.bind_agent_task(websocket, state.request_id, "task-1")
        completed.set()

    assert runtime.start(websocket, "request-1", "conversation-1", worker) is True
    await asyncio.wait_for(completed.wait(), timeout=1)
    await asyncio.sleep(0)
    assert runtime.is_conversation_active("conversation-1") is True


@pytest.mark.asyncio
async def test_new_conversation_agent_task_transfers_its_reservation_before_worker_exit():
    runtime = ConversationRequestRuntime()
    websocket = object()
    completed = asyncio.Event()

    async def worker(state):
        assert runtime.associate_conversation(state, "conversation-new") is True
        runtime.bind_agent_task(websocket, state.request_id, "task-new")
        completed.set()

    assert runtime.start(websocket, "request-new", None, worker) is True
    await asyncio.wait_for(completed.wait(), timeout=1)
    await asyncio.sleep(0)

    assert runtime.is_conversation_active("conversation-new") is True
    assert runtime.request_cancel_for_conversation("conversation-new")[1] == "task-new"


@pytest.mark.asyncio
async def test_release_agent_task_frees_the_bound_conversation_reservation():
    runtime = ConversationRequestRuntime()
    websocket = object()
    gate = asyncio.Event()

    async def worker(_state):
        await gate.wait()

    assert runtime.start(websocket, "request-1", "conversation-1", worker) is True
    runtime.bind_agent_task(websocket, "request-1", "task-1")

    runtime.release_agent_task("task-1")

    assert runtime.is_conversation_active("conversation-1") is False
    gate.set()


def test_associate_conversation_reserves_a_newly_created_conversation():
    runtime = ConversationRequestRuntime()
    websocket = object()
    state = ConversationRequestState(websocket=websocket, request_id="request-1", conversation_id=None)

    assert runtime.associate_conversation(state, "conversation-new") is True
    assert runtime.is_conversation_active("conversation-new") is True


def test_associate_conversation_rejects_a_conflicting_owner():
    runtime = ConversationRequestRuntime()
    websocket_a = object()
    websocket_b = object()
    state_a = ConversationRequestState(websocket=websocket_a, request_id="request-1", conversation_id=None)
    state_b = ConversationRequestState(websocket=websocket_b, request_id="request-2", conversation_id=None)

    assert runtime.associate_conversation(state_a, "conversation-1") is True
    assert runtime.associate_conversation(state_b, "conversation-1") is False


@pytest.mark.asyncio
async def test_request_cancel_for_conversation_cancels_the_owning_direct_request():
    runtime = ConversationRequestRuntime()
    websocket = object()
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def worker(state):
        entered.set()
        runtime.mark_persistence_ready(state, "user-1", "assistant-1")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    assert runtime.start(websocket, "request-1", "conversation-1", worker) is True
    await asyncio.wait_for(entered.wait(), timeout=1)
    state, agent_task_id = runtime.request_cancel_for_conversation("conversation-1")
    assert state is not None
    assert agent_task_id is None
    await asyncio.wait_for(cancelled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_request_cancel_for_conversation_returns_the_bound_agent_task_id():
    runtime = ConversationRequestRuntime()
    websocket = object()
    gate = asyncio.Event()

    async def worker(_state):
        await gate.wait()

    assert runtime.start(websocket, "request-1", "conversation-1", worker) is True
    runtime.bind_agent_task(websocket, "request-1", "task-1")

    _state, agent_task_id = runtime.request_cancel_for_conversation("conversation-1")

    assert agent_task_id == "task-1"
    gate.set()


def test_request_cancel_for_conversation_ignores_an_unrelated_conversation():
    runtime = ConversationRequestRuntime()

    state, agent_task_id = runtime.request_cancel_for_conversation("conversation-unknown")

    assert state is None
    assert agent_task_id is None


@pytest.mark.asyncio
async def test_claiming_foreign_agent_task_cancellation_preserves_its_reservation():
    runtime = ConversationRequestRuntime()
    owner_websocket = object()
    completed = asyncio.Event()

    async def worker(state):
        runtime.bind_agent_task(owner_websocket, state.request_id, "task-1")
        completed.set()

    assert runtime.start(owner_websocket, "owner-request", "conversation-1", worker) is True
    await asyncio.wait_for(completed.wait(), timeout=1)
    await asyncio.sleep(0)

    assert runtime.claim_agent_task_cancellation_for_conversation("conversation-1") == "task-1"
    assert runtime.is_conversation_active("conversation-1") is True
    runtime.release_agent_task("task-1")
    assert runtime.is_conversation_active("conversation-1") is False


@pytest.mark.asyncio
async def test_disconnect_does_not_touch_bound_agent_task_mappings():
    runtime = ConversationRequestRuntime()
    websocket = object()
    runtime.bind_agent_task(websocket, "request-1", "task-1")

    await runtime.cancel_for_websocket(websocket)

    assert runtime.claim_agent_task_cancellation(websocket, "request-1") == "task-1"
