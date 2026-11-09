"""An oversized service-tool result is saved whole and read back through stored_result; it is clipped only when it cannot be saved."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from api.core.config import api_settings
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.models import BaseModel
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_execution import create_tool_function
from api.services.agent_processing.service_capabilities.service_execution_engine import ExecutionResult
from api.services.agent_processing.shared.agent_runtime_context import reset_current_agent_context, set_current_agent_context
from api.services.agent_processing.tools.internal_basil_tools.stored_result import store
from api.services.agent_processing.tools.internal_basil_tools.stored_result.service_cap import (
    cap_service_tool_output,
)

LIMIT = 60_000


@pytest.fixture(autouse=True)
def _isolated_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(api_settings.settings, "STORAGE_DIR", tmp_path)


@pytest.fixture
def chain():
    token = set_current_agent_context({"root_task_id": "chain-1", "agent_task_id": "turn-1"})
    yield
    reset_current_agent_context(token)


def _big_json(chars: int = 90_000) -> str:
    return json.dumps({"ok": True, "result": {"rows": ["row-%05d " % index + "x" * 40 for index in range(chars // 50)]}})


def test_a_result_within_the_limit_is_returned_unchanged(chain):
    output = json.dumps({"ok": True, "result": "small"})

    capped = cap_service_tool_output(output, LIMIT, context_tokens=200_000)

    assert capped.text is output
    assert capped.stored is False
    assert capped.result_id is None


def test_an_oversized_json_result_is_saved_whole_and_described_by_a_bounded_envelope(chain):
    output = _big_json()

    capped = cap_service_tool_output(output, LIMIT, context_tokens=200_000)
    envelope = json.loads(capped.text)

    assert capped.stored is True
    assert len(capped.text) <= LIMIT
    assert envelope["stored"] is True
    assert envelope["result_id"] == capped.result_id
    assert envelope["original_size_chars"] == len(output)
    assert envelope["limit_chars"] == LIMIT
    assert "stored_result" in envelope["message"]
    assert capped.result_id in envelope["message"]
    assert envelope["preview"] == output[: envelope["preview_chars"]]
    assert 500 <= envelope["preview_chars"] <= 6_000
    assert envelope["outline"] is not None
    assert "truncated" not in envelope
    assert json.loads(store.load_result(capped.result_id)) == json.loads(output)


def test_a_result_that_is_not_json_is_saved_exactly(chain):
    output = "line of plain text \u2603 \U0001F600\n" * 4_000

    capped = cap_service_tool_output(output, LIMIT, context_tokens=200_000)
    envelope = json.loads(capped.text)

    assert capped.stored is True
    assert envelope["original_size_bytes"] > envelope["original_size_chars"]
    assert store.load_result(capped.result_id) == output


def test_published_result_fields_stay_at_the_top_level_of_the_envelope(chain):
    fields = {"agent_task_artifact": {"path": "/tmp/report.txt"}, "material_operation": {"kind": "write"}}

    stored = json.loads(cap_service_tool_output(_big_json(), LIMIT, context_tokens=200_000, published_fields=fields).text)

    assert stored["agent_task_artifact"] == {"path": "/tmp/report.txt"}
    assert stored["material_operation"] == {"kind": "write"}


def test_without_a_task_chain_the_result_is_clipped_exactly_as_before():
    output = _big_json()

    capped = cap_service_tool_output(output, LIMIT, context_tokens=200_000, published_fields={"material_operation": {"kind": "write"}})
    envelope = json.loads(capped.text)

    assert capped.stored is False
    assert capped.result_id is None
    assert list(envelope)[:6] == ["truncated", "original_size_chars", "original_size_bytes", "truncated_to_chars", "context_limit_tokens", "message"]
    assert envelope["truncated"] is True
    assert envelope["truncated_to_chars"] == LIMIT
    assert envelope["original_size_chars"] == len(output)
    assert envelope["content_preview"] == output[: LIMIT - 1_500] + "\n\n...[CONTENT TRUNCATED]..."
    assert envelope["message"].startswith(f"Tool output truncated from {len(output):,} chars to {LIMIT:,} chars to fit context window (200,000 tokens).")
    assert envelope["material_operation"] == {"kind": "write"}


@pytest.mark.parametrize("spill", [lambda _text: None, lambda _text: (_ for _ in ()).throw(OSError("disk full"))])
def test_a_spill_that_returns_nothing_or_raises_falls_back_to_the_clipped_preview(spill):
    capped = cap_service_tool_output(_big_json(), LIMIT, context_tokens=200_000, spill=spill)

    assert capped.stored is False
    assert json.loads(capped.text)["truncated"] is True


def test_a_small_limit_still_gets_the_id_and_a_pointer_to_the_file(chain):
    output = _big_json(200_000)

    capped = cap_service_tool_output(output, 3_000, context_tokens=8_000)
    envelope = json.loads(capped.text)

    assert capped.stored is True
    assert len(capped.text) <= 3_000
    assert envelope["result_id"] == capped.result_id
    assert envelope["file"] == f".tool_results/{capped.result_id}.txt"


def test_a_stored_envelope_that_cannot_fit_the_limit_falls_back_to_the_clipped_preview(chain):
    huge_fields = {"material_operation": {"note": "y" * 5_000}}

    capped = cap_service_tool_output(_big_json(), 3_000, context_tokens=8_000, published_fields=huge_fields)

    assert capped.stored is False
    assert json.loads(capped.text)["truncated"] is True


class _Args(BaseModel):
    pass


class _Engine:
    def __init__(self, result):
        self._result = result

    async def execute_service_method(self, service_name, method_name, parameters):
        return self._result


def _tool(result, limit=LIMIT):
    factory = SimpleNamespace(
        service_execution_engine=_Engine(result),
        max_tool_output_chars=limit,
        max_context_tokens=200_000,
        tool_error_log=[],
    )
    return create_tool_function(factory, "svc_method", "desc", _Args, "svc", "method", {}), factory


def _result(payload):
    return ExecutionResult(success=True, result=payload, service="svc", method="method", parameters_used={}, execution_time=0.1)


@pytest.mark.asyncio
async def test_an_oversized_service_result_is_stored_and_not_logged_as_lost_data(chain, tmp_path):
    tool, factory = _tool(_result({"rows": ["r" * 100] * 900}))

    output = await tool.ainvoke({})
    envelope = json.loads(output)

    assert envelope["stored"] is True
    assert len(output) <= LIMIT
    assert factory.tool_error_log == []
    saved = store.load_result(envelope["result_id"])
    assert json.loads(saved)["result"]["rows"][899] == "r" * 100
    assert (tmp_path / "agent_task_workspaces" / "chain-1" / ".tool_results" / f"{envelope['result_id']}.txt").is_file()


@pytest.mark.asyncio
async def test_an_oversized_service_result_outside_a_chain_is_clipped_and_logged_as_before():
    tool, factory = _tool(_result({"rows": ["r" * 100] * 900}))

    output = await tool.ainvoke({})
    envelope = json.loads(output)

    assert envelope["truncated"] is True
    assert "stored" not in envelope
    assert [entry["type"] for entry in factory.tool_error_log] == ["truncation"]
    assert "agent may not see all results" in factory.tool_error_log[0]["error"]


@pytest.mark.asyncio
async def test_a_service_result_within_the_limit_is_untouched_and_nothing_is_saved(chain, tmp_path):
    tool, factory = _tool(_result({"rows": ["small"]}))

    output = await tool.ainvoke({})

    assert json.loads(output)["result"]["rows"] == ["small"]
    assert factory.tool_error_log == []
    assert not (tmp_path / "agent_task_workspaces").exists()
