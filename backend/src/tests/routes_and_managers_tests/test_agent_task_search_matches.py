import pytest
import pytest_asyncio
from fastapi import HTTPException

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.routes.agent_tasks import history_routes

PROMPTS = {
    "t0": "Plan the offsite agenda for the Lisbon trip",
    "t1": "Compare vendor pricing for the projector rental",
    "t2": "Draft the quarterly budget summary with Q3 figures",
    "t3": "Book flights, hotels & dinner (50% deposit) for the team",
}


@pytest_asyncio.fixture
async def database(tmp_path):
    database = SQLiteKnowledgeService(tmp_path / "search_matches.db")
    previous = None
    for sequence, (task_id, prompt) in enumerate(PROMPTS.items()):
        await database.store_agent_task(
            agent_task_id=task_id,
            original_prompt=prompt,
            transcribed_prompt=prompt,
            status="completed",
            root_task_id=None if sequence == 0 else "t0",
            previous_task_id=previous,
            chain_sequence_number=sequence,
        )
        previous = task_id
    await database.store_agent_task(
        agent_task_id="other",
        original_prompt="Unrelated chain about the Lisbon weather",
        transcribed_prompt="Unrelated chain about the Lisbon weather",
        status="completed",
    )
    return database


async def _matches(database, query, root_task_id="t0"):
    return await history_routes.get_agent_task_search_matches(root_task_id, query, database)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query, expected",
    [
        ("lisbon", ["t0"]),
        ("projector", ["t1"]),
        ("Q3 figures", ["t2"]),
        ("DINNER", ["t3"]),
        ("the", ["t0", "t1", "t2", "t3"]),
    ],
)
async def test_match_in_first_middle_and_last_turn(database, query, expected):
    assert (await _matches(database, query)).matched_turn_ids == expected


@pytest.mark.asyncio
async def test_words_split_across_turns_return_the_turns_with_the_most_words(database):
    response = await _matches(database, "projector lisbon trip")
    assert response.tokens == ["projector", "lisbon", "trip"]
    assert response.matched_turn_ids == ["t0"]


@pytest.mark.asyncio
async def test_words_that_no_single_turn_shares_fall_back_to_the_best_partial_match(database):
    response = await _matches(database, "projector budget")
    assert response.matched_turn_ids == ["t1", "t2"]


@pytest.mark.asyncio
async def test_no_match_returns_the_tokens_and_no_turns(database):
    response = await _matches(database, "zebra")
    assert response.tokens == ["zebra"]
    assert response.matched_turn_ids == []


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["", "   ", "%%% ---", "\"'()*"])
async def test_blank_or_symbol_only_queries_return_empty_lists(database, query):
    response = await _matches(database, query)
    assert response.tokens == []
    assert response.matched_turn_ids == []


@pytest.mark.asyncio
async def test_special_characters_in_the_query_do_not_break_matching(database):
    response = await _matches(database, "50% deposit (hotels) & dinner")
    assert response.matched_turn_ids == ["t3"]


@pytest.mark.asyncio
async def test_a_very_long_query_is_handled(database):
    response = await _matches(database, "lisbon " * 2000)
    assert response.matched_turn_ids == ["t0"]


@pytest.mark.asyncio
async def test_unknown_root_is_a_404(database):
    with pytest.raises(HTTPException) as caught:
        await _matches(database, "lisbon", root_task_id="missing")
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_a_follow_up_id_is_not_a_chain_root(database):
    with pytest.raises(HTTPException) as caught:
        await _matches(database, "projector", root_task_id="t1")
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_only_the_requested_chain_is_searched(database):
    assert (await _matches(database, "weather", root_task_id="other")).matched_turn_ids == ["other"]
    assert (await _matches(database, "weather")).matched_turn_ids == []
