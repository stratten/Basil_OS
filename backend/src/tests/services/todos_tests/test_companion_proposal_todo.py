from types import SimpleNamespace

import pytest

from api.services.todos.repository import TodoRepository
from api.services.todos.service import TodoService, TodoTransitionError


@pytest.fixture
def service(tmp_path) -> TodoService:
    return TodoService(repository=TodoRepository(str(tmp_path / "companion_proposals.db")), agent_task_service=SimpleNamespace())


async def create(service, *, proposal_id="pr-1", title="Add a renewal reminder", system_created=False, responsibility="unspecified"):
    return await service.create_todo_from_companion_proposal(
        session_key="sess1",
        proposal_id=proposal_id,
        title=title,
        description="Create a reminder for the renewal date.",
        excerpt="Create a reminder",
        responsibility=responsibility,
        system_created=system_created,
    )


@pytest.mark.asyncio
async def test_a_proposal_becomes_an_open_todo_with_its_source(service):
    detail = await create(service, responsibility="agent")
    assert detail.status == "open" and detail.title == "Add a renewal reminder" and detail.responsibility == "agent"
    assert detail.description == "Create a reminder for the renewal date." and detail.created_by_kind == "user"
    source = detail.sources[0]
    assert source.source_kind == "meeting_companion_proposal" and source.source_id == "sess1:pr-1" and source.source_excerpt == "Create a reminder"


@pytest.mark.asyncio
async def test_an_automatic_start_is_attributed_to_the_system(service):
    assert (await create(service, system_created=True)).created_by_kind == "system"


@pytest.mark.asyncio
async def test_creating_the_same_proposal_twice_returns_the_same_todo(service):
    first = await create(service)
    again = await create(service)
    other = await create(service, proposal_id="pr-2")
    assert again.id == first.id and other.id != first.id
    stored = await service.repository.find_todo_by_source(source_kind="meeting_companion_proposal", source_id="sess1:pr-1")
    assert stored is not None and stored.id == first.id


@pytest.mark.asyncio
async def test_the_title_is_bounded_and_a_blank_title_is_refused(service):
    assert len((await create(service, title="A" * 300)).title) == 240
    with pytest.raises(TodoTransitionError, match="must not be blank"):
        await create(service, proposal_id="pr-3", title="   ")
