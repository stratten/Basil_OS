"""The stored_result tool outlines, reads, and searches a result saved for the task chain."""

import json

import pytest

from api.core.config import api_settings
from api.services.agent_processing.shared.agent_runtime_context import reset_current_agent_context, set_current_agent_context
from api.services.agent_processing.tools.internal_basil_tools import stored_result_tool
from api.services.agent_processing.tools.internal_basil_tools.stored_result import store


def _document():
    steps = [{"stepNumber": number, "command": f"cmd {number}", "stdout": "o" * 2_000} for number in range(120)]
    steps[61]["stdout"] = "ERRNEEDLE " + "o" * 1_990
    steps[7]["command"] = "grep a.b(c file"
    return {"ok": True, "result": {"structured": {"request": {"requestNumber": "REQ-1"}}}, "steps": steps}


@pytest.fixture
def stored(monkeypatch, tmp_path):
    monkeypatch.setattr(api_settings.settings, "STORAGE_DIR", tmp_path)
    token = set_current_agent_context({"root_task_id": "chain-1", "agent_task_id": "turn-1"})
    document = _document()
    yield store.save_result(json.dumps(document))["result_id"], document
    reset_current_agent_context(token)


async def _call(**kwargs):
    return json.loads(await stored_result_tool.create_stored_result_tool().ainvoke(kwargs))


def _text(document, key):
    return json.dumps(document[key], ensure_ascii=False)


@pytest.mark.asyncio
async def test_an_unknown_result_id_is_reported_with_what_to_do(stored):
    result = await _call(action="outline", result_id="r-00000000")

    assert result["ok"] is False
    assert "No stored result" in result["error"]


@pytest.mark.asyncio
async def test_the_outline_shows_the_large_part_and_a_bad_path_is_explained(stored):
    result_id, _ = stored

    whole = await _call(action="outline", result_id=result_id)
    steps = await _call(action="outline", result_id=result_id, path="steps")
    bad = await _call(action="outline", result_id=result_id, path="steps[500]")

    assert whole["outline"]["largest"][0]["key"] == "steps"
    assert steps["outline"]["length"] == 120
    assert bad["ok"] is False and "120 items" in bad["error"]


@pytest.mark.asyncio
async def test_reading_pages_through_a_part_without_gaps_or_overlap(stored):
    result_id, document = stored

    first = await _call(action="read", result_id=result_id, path="steps", max_chars=500)
    second = await _call(action="read", result_id=result_id, path="steps", offset=first["next_offset"], max_chars=500)

    assert first["returned_chars"] == 500 and first["has_more"] is True and first["next_offset"] == 500
    assert second["offset"] == 500
    assert first["content"] + second["content"] == _text(document, "steps")[:1000]
    assert first["total_chars"] == len(_text(document, "steps"))


@pytest.mark.asyncio
async def test_read_limits_are_clamped_and_reading_past_the_end_is_empty(stored):
    result_id, _ = stored

    huge = await _call(action="read", result_id=result_id, path="steps", max_chars=999_999)
    tiny = await _call(action="read", result_id=result_id, path="steps", max_chars=1)
    negative = await _call(action="read", result_id=result_id, path="steps", offset=-50, max_chars=500)
    past = await _call(action="read", result_id=result_id, path="steps", offset=10**9)

    assert huge["returned_chars"] == 20_000
    assert tiny["returned_chars"] == 500
    assert negative["offset"] == 0
    assert past["returned_chars"] == 0 and past["has_more"] is False and past["next_offset"] is None


@pytest.mark.asyncio
async def test_a_single_item_is_read_whole(stored):
    result_id, _ = stored

    result = await _call(action="read", result_id=result_id, path="steps[3].command")

    assert result["content"] == "cmd 3"
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_search_finds_a_value_ignoring_case_and_points_at_it(stored):
    result_id, document = stored

    result = await _call(action="search", result_id=result_id, path="steps", query="errneedle", context_chars=40)

    assert result["total_matches"] == 1
    match = result["matches"][0]
    assert _text(document, "steps")[match["offset"]:match["offset"] + 9] == "ERRNEEDLE"
    assert "ERRNEEDLE" in match["snippet"]


@pytest.mark.asyncio
async def test_search_treats_the_query_literally_and_bounds_its_output(stored):
    result_id, _ = stored

    literal = await _call(action="search", result_id=result_id, path="steps", query="a.b(c")
    pattern = await _call(action="search", result_id=result_id, path="steps", query=".*")
    many = await _call(action="search", result_id=result_id, path="steps", query="o", max_matches=999, context_chars=99_999)

    assert literal["total_matches"] == 1
    assert pattern["total_matches"] == 0
    assert many["returned"] == 20 and many["total_matches"] > 20
    assert all(len(item["snippet"]) <= 1 + 2 * 500 for item in many["matches"])


@pytest.mark.asyncio
async def test_search_without_a_query_and_an_unknown_action_are_errors(stored):
    result_id, _ = stored

    assert (await _call(action="search", result_id=result_id))["ok"] is False
    unknown = json.loads(await stored_result_tool._stored_result_impl(action="bogus", result_id=result_id))
    assert unknown["ok"] is False and "Unknown action" in unknown["error"]


@pytest.mark.asyncio
async def test_a_plain_text_result_can_be_outlined_and_read_but_has_no_paths(stored):
    plain_id = store.save_result("alpha line\nbeta line")["result_id"]

    outline = await _call(action="outline", result_id=plain_id)
    read = await _call(action="read", result_id=plain_id)
    bad = await _call(action="read", result_id=plain_id, path="a.b")

    assert outline["outline"]["type"] == "string"
    assert read["content"] == "alpha line\nbeta line"
    assert bad["ok"] is False and "plain text" in bad["error"]


@pytest.mark.asyncio
async def test_the_tool_makes_no_model_call_and_offers_only_three_actions(stored):
    result_id, _ = stored

    unknown = json.loads(await stored_result_tool._stored_result_impl(action="digest", result_id=result_id))

    assert unknown["ok"] is False and "outline, read, or search" in unknown["error"]
    assert set(stored_result_tool.StoredResultInput.model_fields["action"].annotation.__args__) == {"outline", "read", "search"}


def test_the_slim_description_stays_short_and_the_tool_is_named_for_the_catalog():
    tool = stored_result_tool.create_stored_result_tool()

    assert tool.name == "stored_result" == stored_result_tool.TOOL_NAME
    assert len(stored_result_tool.SLIM_DESCRIPTION.split()) < 110
    assert "file in the task workspace" in stored_result_tool.SLIM_DESCRIPTION
