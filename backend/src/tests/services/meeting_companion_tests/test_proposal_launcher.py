from types import SimpleNamespace

import pytest

from api.services.meeting_companion.proposal_launcher import TodoProposalLauncher
from api.services.meeting_companion.proposals import ProposalLaunchError
from api.services.todos.service import TodoConflictError, TodoNotFoundError, TodoTransitionError


class FakeTodoService:
    def __init__(self) -> None:
        self.created = []
        self.launch_calls = []
        self.create_error = None
        self.detail_error = None
        self.launch_error = None
        self.references = []
        self.reference_errors = {}

    async def add_reference(self, todo_id, path, expected_revision=None, actor_agent_task_id=None):
        if path in self.reference_errors:
            raise self.reference_errors[path]
        self.references.append((todo_id, path))
        return SimpleNamespace(id=todo_id)

    async def create_todo_from_companion_proposal(self, **kwargs):
        if self.create_error is not None:
            raise self.create_error
        self.created.append(kwargs)
        return SimpleNamespace(id="todo-1")

    async def get_item_detail(self, todo_id):
        if self.detail_error is not None:
            raise self.detail_error
        return SimpleNamespace(id=todo_id, revision=4)

    async def launch_todo_worker(self, *, todo_id, expected_revision, launcher):
        if self.launch_error is not None:
            raise self.launch_error
        self.launch_calls.append((todo_id, expected_revision, launcher))
        return SimpleNamespace(agent_task_id="task-9")


def launcher_for(service, bridge="present"):
    bridge_object = SimpleNamespace(launch_todo_item_agent_task=lambda **kwargs: None) if bridge == "present" else None
    return TodoProposalLauncher(todo_service_provider=lambda: service, bridge_provider=lambda: bridge_object), bridge_object


async def create(launcher):
    return await launcher.create_todo(session_key="s", proposal_id="pr-1", title="T", description="D", excerpt="E", responsibility="agent", system_created=False)


@pytest.mark.asyncio
async def test_create_todo_passes_every_field_through_and_returns_the_id():
    service = FakeTodoService()
    launcher, _bridge = launcher_for(service)
    assert await create(launcher) == "todo-1"
    assert service.created == [{"session_key": "s", "proposal_id": "pr-1", "title": "T", "description": "D", "excerpt": "E", "responsibility": "agent", "system_created": False}]


@pytest.mark.asyncio
async def test_create_todo_turns_a_domain_refusal_into_a_launch_error():
    service = FakeTodoService()
    service.create_error = TodoTransitionError("Meeting proposal title must not be blank.")
    launcher, _bridge = launcher_for(service)
    with pytest.raises(ProposalLaunchError, match="must not be blank"):
        await create(launcher)


@pytest.mark.asyncio
async def test_launch_worker_uses_the_current_revision_and_the_bridge_launcher():
    service = FakeTodoService()
    launcher, bridge = launcher_for(service)
    assert await launcher.launch_worker("todo-1") == "task-9"
    assert service.launch_calls[0][:2] == ("todo-1", 4) and service.launch_calls[0][2] == bridge.launch_todo_item_agent_task


@pytest.mark.asyncio
async def test_launch_worker_reports_a_missing_bridge_politely():
    launcher, _bridge = launcher_for(FakeTodoService(), bridge="absent")
    with pytest.raises(ProposalLaunchError, match="not ready yet"):
        await launcher.launch_worker("todo-1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "message"),
    [
        (TodoConflictError("todo-1", SimpleNamespace()), "changed while it was starting"),
        (TodoNotFoundError("todo-1"), "no longer exists"),
        (TodoTransitionError("Cannot launch a worker for a terminal To-Do."), "terminal To-Do"),
    ],
)
async def test_launch_worker_maps_every_domain_error_to_a_user_facing_message(error, message):
    for attribute in ("detail_error", "launch_error"):
        service = FakeTodoService()
        setattr(service, attribute, error)
        launcher, _bridge = launcher_for(service)
        with pytest.raises(ProposalLaunchError, match=message):
            await launcher.launch_worker("todo-1")


@pytest.mark.asyncio
async def test_attach_references_adds_each_path_and_skips_one_the_domain_refuses():
    service = FakeTodoService()
    service.reference_errors = {"/bad": TodoTransitionError("Attachments must use absolute local paths.")}
    launcher, _bridge = launcher_for(service)
    await launcher.attach_references("todo-1", ["/tmp/proj", "/bad", "/tmp/notes.md"])
    assert service.references == [("todo-1", "/tmp/proj"), ("todo-1", "/tmp/notes.md")]
