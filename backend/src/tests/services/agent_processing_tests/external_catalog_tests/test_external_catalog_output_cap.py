"""external_catalog results are clipped to the service-tool limit so one connector response cannot fill the context window."""

import json

import pytest

from api.core.config import api_settings
from api.services.agent_processing.shared.agent_runtime_context import reset_current_agent_context, set_current_agent_context
from api.services.agent_processing.tools.external_services import external_catalog_tool
from api.services.agent_processing.tools.internal_basil_tools.stored_result import store
from api.services.agent_processing.tools.internal_basil_tools.stored_result.spill import spill_result
from api.services.agent_processing.tools.external_services.external_catalog.output_cap import (
    DEFAULT_MAX_RESULT_CHARS,
    cap_external_catalog_result,
)


@pytest.fixture(autouse=True)
def _isolated_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(api_settings.settings, "STORAGE_DIR", tmp_path)


def _spilled(result_id="r-12345678", outline=None):
    return lambda _encoded: {"result_id": result_id, "file": f".tool_results/{result_id}.txt", "outline": outline if outline is not None else {"type": "object", "keys": 1}}


def test_a_result_within_the_limit_is_returned_unchanged():
    encoded = json.dumps({"ok": True, "result": {"text": "small"}})

    assert cap_external_catalog_result(encoded, 60_000) is encoded


def test_an_oversized_result_becomes_a_bounded_envelope_that_says_how_to_ask_for_less():
    encoded = json.dumps({"ok": True, "result": {"text": "x" * 2_500_000}})

    capped = cap_external_catalog_result(encoded, 60_000)
    envelope = json.loads(capped)

    assert len(capped) <= 60_000
    assert envelope["truncated"] is True
    assert envelope["original_size_chars"] == len(encoded)
    assert envelope["kept_chars"] == len(envelope["content_preview"]) - len("\n...[TRUNCATED]...")
    assert "narrower arguments" in envelope["message"]
    assert "max_output_bytes does nothing" in envelope["message"]
    assert envelope["content_preview"].startswith('{"ok": true, "result": {"text": "xxx')


def test_special_characters_in_the_clipped_text_still_produce_valid_json():
    encoded = '{"ok": true, "text": "' + ("quote \\\" newline \\n unicode \u2603 " * 5_000) + '"}'

    capped = cap_external_catalog_result(encoded, 4_000)

    assert len(capped) <= 4_000
    assert json.loads(capped)["truncated"] is True


@pytest.mark.parametrize("limit", [None, 0, -5, 100, True, "60000"])
def test_a_missing_or_unusable_limit_falls_back_to_the_default(limit):
    small = "y" * (DEFAULT_MAX_RESULT_CHARS - 10)
    large = "y" * (DEFAULT_MAX_RESULT_CHARS + 10)

    assert cap_external_catalog_result(small, limit) is small
    assert json.loads(cap_external_catalog_result(large, limit))["truncated"] is True


@pytest.mark.asyncio
async def test_the_tool_clips_what_the_dispatcher_returns(monkeypatch):
    async def fake_impl(**_kwargs):
        return json.dumps({"ok": True, "result": {"text": "z" * 500_000}})

    monkeypatch.setattr(external_catalog_tool, "_external_catalog_impl", fake_impl)
    tool = external_catalog_tool.create_external_catalog_tool(max_output_chars=20_000)

    output = await tool.ainvoke(
        {
            "action": "call_tool",
            "connection_id": "c1",
            "tool_name": "speakeasy_get_request",
            "arguments": {"requestId": "r1"},
        }
    )

    assert len(output) <= 20_000
    assert json.loads(output)["truncated"] is True


@pytest.mark.asyncio
async def test_a_normal_result_passes_through_the_tool_untouched(monkeypatch):
    payload = json.dumps({"ok": True, "result": {"text": "fine"}})

    async def fake_impl(**_kwargs):
        return payload

    monkeypatch.setattr(external_catalog_tool, "_external_catalog_impl", fake_impl)
    tool = external_catalog_tool.create_external_catalog_tool(max_output_chars=20_000)

    assert await tool.ainvoke({"action": "list_servers"}) == payload


def test_an_oversized_result_that_can_be_stored_becomes_a_preview_an_outline_and_an_id():
    encoded = json.dumps({"ok": True, "result": {"text": "x" * 2_500_000}})

    capped = cap_external_catalog_result(encoded, 60_000, spill=_spilled())
    envelope = json.loads(capped)

    assert len(capped) <= 60_000
    assert envelope["stored"] is True and envelope["result_id"] == "r-12345678"
    assert envelope["original_size_chars"] == len(encoded)
    assert envelope["outline"] == {"type": "object", "keys": 1}
    assert envelope["preview"] == encoded[:6_000] and envelope["preview_chars"] == 6_000
    assert envelope["file"] == ".tool_results/r-12345678.txt" and "grep" in envelope["message"]
    assert "stored_result" in envelope["message"] and "max_output_bytes does nothing" in envelope["message"]
    assert "truncated" not in envelope


def test_a_result_within_the_limit_is_never_stored():
    encoded = json.dumps({"ok": True})
    calls = []

    assert cap_external_catalog_result(encoded, 60_000, spill=lambda text: calls.append(text)) is encoded
    assert calls == []


@pytest.mark.parametrize("spill", [lambda _encoded: None, lambda _encoded: (_ for _ in ()).throw(OSError("disk full"))])
def test_when_the_result_cannot_be_stored_it_is_clipped_as_before(spill):
    encoded = json.dumps({"ok": True, "result": {"text": "x" * 500_000}})

    capped = cap_external_catalog_result(encoded, 60_000, spill=spill)

    assert len(capped) <= 60_000
    assert json.loads(capped)["truncated"] is True


def test_a_stored_envelope_that_would_not_fit_the_limit_falls_back_to_clipping():
    encoded = json.dumps({"ok": True, "result": {"text": "x" * 500_000}})

    capped = cap_external_catalog_result(encoded, 4_000, spill=_spilled(outline={"big": "y" * 5_000}))

    assert len(capped) <= 4_000
    assert json.loads(capped)["truncated"] is True


def test_the_preview_is_a_tenth_of_the_limit_and_the_whole_envelope_still_fits():
    encoded = json.dumps({"ok": True, "result": {"text": "x" * 500_000}})

    capped = cap_external_catalog_result(encoded, 8_000, spill=_spilled())
    envelope = json.loads(capped)

    assert len(capped) <= 8_000
    assert envelope["stored"] is True
    assert envelope["preview_chars"] == 800 and envelope["preview"] == encoded[:800]


def _outline(entries, key_chars=10):
    return {"type": "object", "keys": entries, "largest": [{"key": f"{number:0{key_chars}d}", "type": "string", "chars": 1_000 - number} for number in range(entries)]}


def test_a_tight_limit_gives_up_preview_and_outline_detail_before_it_gives_up_the_id():
    encoded = json.dumps({"ok": True, "result": {"text": "x" * 500_000}})

    capped = cap_external_catalog_result(encoded, 3_000, spill=_spilled(outline=_outline(40)))
    envelope = json.loads(capped)

    assert len(capped) <= 3_000
    assert envelope["stored"] is True and envelope["result_id"] == "r-12345678"
    assert envelope["preview_chars"] == 166 and envelope["preview"] == encoded[:166]
    assert len(envelope["outline"]["largest"]) == 8
    assert envelope["file"] == ".tool_results/r-12345678.txt"


def test_the_last_step_keeps_four_outline_entries_and_no_preview():
    encoded = json.dumps({"ok": True, "result": {"text": "x" * 500_000}})

    capped = cap_external_catalog_result(encoded, 3_000, spill=_spilled(outline=_outline(10, key_chars=250)))
    envelope = json.loads(capped)

    assert len(capped) <= 3_000
    assert envelope["stored"] is True and "preview" not in envelope and "preview_chars" not in envelope
    assert len(envelope["outline"]["largest"]) == 4


def test_the_spill_saves_json_one_value_per_line_and_other_text_unchanged():
    token = set_current_agent_context({"root_task_id": "chain-1", "agent_task_id": "turn-1"})
    try:
        compact = json.dumps({"a": [1, 2], "b": "caf\u00e9"}, ensure_ascii=False)

        spilled = spill_result(compact)
        saved = store.load_result(spilled["result_id"])
        plain = spill_result("not json {")

        assert json.loads(saved) == json.loads(compact)
        assert saved.count("\n") > 3 and "caf\u00e9" in saved
        assert spilled["file"] == f".tool_results/{spilled['result_id']}.txt"
        assert spilled["outline"]["type"] == "object"
        assert store.load_result(plain["result_id"]) == "not json {"
        assert plain["outline"]["type"] == "string"
    finally:
        reset_current_agent_context(token)


def test_the_spill_returns_nothing_outside_an_agent_run():
    assert spill_result(json.dumps({"ok": True})) is None


@pytest.mark.asyncio
async def test_the_tool_stores_an_oversized_result_and_the_reader_gets_it_back_whole(monkeypatch, tmp_path):
    encoded = json.dumps({"ok": True, "result": {"structured": {"request": {"steps": ["s" * 1_000] * 300}}}})

    async def fake_impl(**_kwargs):
        return encoded

    monkeypatch.setattr(external_catalog_tool, "_external_catalog_impl", fake_impl)
    token = set_current_agent_context({"root_task_id": "chain-1", "agent_task_id": "turn-1"})
    try:
        tool = external_catalog_tool.create_external_catalog_tool(max_output_chars=60_000)
        output = json.loads(await tool.ainvoke({"action": "call_tool", "connection_id": "c1", "tool_name": "speakeasy_get_request", "arguments": {"requestId": "r1"}}))

        assert output["stored"] is True and len(json.dumps(output)) <= 60_000
        assert output["outline"]["largest"][0]["key"] == "result"
        saved = store.load_result(output["result_id"])
        assert json.loads(saved) == json.loads(encoded)
        assert saved.count("\n") > 300
        assert (tmp_path / "agent_task_workspaces" / "chain-1" / output["file"]).read_text(encoding="utf-8") == saved
    finally:
        reset_current_agent_context(token)
