from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest


def _load_validator_module():
    script_path = Path(__file__).resolve().parents[4] / "scripts" / "validate_slack_local_server.py"
    spec = importlib.util.spec_from_file_location("validate_slack_local_server", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(**overrides: Any) -> argparse.Namespace:
    defaults = {
        "allow_writes": True,
        "allow_canvas_write": False,
        "allow_channel_create": False,
        "skip_read_only_preflight": False,
        "write_tool": None,
        "rate_limit_retries": 2,
        "rate_limit_buffer_seconds": 1,
        "max_rate_limit_wait_seconds": 180,
        "test_channel": "USELF",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.mark.asyncio
async def test_write_validator_reuses_send_result_for_reaction(monkeypatch):
    validator = _load_validator_module()
    calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_read_only_mode(args, access_token):
        return {"mode": "read-only", "rows": []}

    async def fake_call_tool(*, tool_name, arguments, access_token):
        calls.append((tool_name, arguments))
        if tool_name == "slack_send_message":
            return {
                "ok": True,
                "result": {
                    "text": "Message posted",
                    "structured": {"channel": "DSELF", "ts": "1.000000", "message": {}},
                },
            }
        if tool_name == "slack_add_reaction":
            return {"ok": True, "result": {"text": "Reaction added", "structured": {}}}
        raise AssertionError(f"Unexpected tool call: {tool_name}")

    monkeypatch.setattr(validator, "run_read_only_mode", fake_read_only_mode)
    monkeypatch.setattr(validator, "call_tool", fake_call_tool)

    summary = await validator.run_all_mode(_args(), "xoxp-test")

    send_calls = [call for call in calls if call[0] == "slack_send_message"]
    assert len(send_calls) == 1
    assert ("slack_add_reaction", {
        "channel": "DSELF",
        "timestamp": "1.000000",
        "name": "white_check_mark",
    }) in calls
    assert summary["write_artifacts"]["posted_message"] == {
        "channel": "DSELF",
        "ts": "1.000000",
    }


@pytest.mark.asyncio
async def test_write_validator_preserves_created_artifacts(monkeypatch):
    validator = _load_validator_module()

    async def fake_read_only_mode(args, access_token):
        return {"mode": "read-only", "rows": []}

    async def fake_call_tool(*, tool_name, arguments, access_token):
        if tool_name == "slack_send_message":
            return {
                "ok": True,
                "result": {
                    "text": "Message posted",
                    "structured": {"channel": "DSELF", "ts": "1.000000", "message": {}},
                },
            }
        if tool_name == "slack_create_channel":
            return {
                "ok": True,
                "result": {
                    "text": "Created channel",
                    "structured": {"channel": {"id": "CNEW", "name": arguments["name"]}},
                },
            }
        if tool_name == "slack_create_canvas":
            return {
                "ok": True,
                "result": {
                    "text": "Created canvas",
                    "structured": {"canvas_id": "FCANVAS"},
                },
            }
        if tool_name == "slack_read_canvas":
            return {
                "ok": True,
                "result": {
                    "text": "Read canvas",
                    "structured": {"file": {"id": arguments["canvas_id"]}},
                },
            }
        if tool_name == "slack_add_reaction":
            return {"ok": True, "result": {"text": "Reaction added", "structured": {}}}
        raise AssertionError(f"Unexpected tool call: {tool_name}")

    monkeypatch.setattr(validator, "run_read_only_mode", fake_read_only_mode)
    monkeypatch.setattr(validator, "call_tool", fake_call_tool)

    summary = await validator.run_all_mode(
        _args(allow_canvas_write=True, allow_channel_create=True),
        "xoxp-test",
    )

    assert summary["write_artifacts"]["created_channel"]["id"] == "CNEW"
    assert summary["write_artifacts"]["created_channel"]["name"].startswith("basil-validator-")
    assert summary["write_artifacts"]["created_canvas"] == {
        "canvas_id": "FCANVAS",
        "readback_status": "passed",
    }


@pytest.mark.asyncio
async def test_write_validator_targets_canvas_without_read_preflight(monkeypatch):
    validator = _load_validator_module()
    calls: list[str] = []

    async def fail_read_only_mode(args, access_token):
        raise AssertionError("read-only preflight should not run")

    async def fake_call_tool(*, tool_name, arguments, access_token):
        calls.append(tool_name)
        if tool_name == "slack_create_canvas":
            return {
                "ok": True,
                "result": {"text": "Created canvas", "structured": {"canvas_id": "FCANVAS"}},
            }
        if tool_name == "slack_read_canvas":
            return {
                "ok": True,
                "result": {"text": "Read canvas", "structured": {"file": {"id": "FCANVAS"}}},
            }
        raise AssertionError(f"Unexpected tool call: {tool_name}")

    monkeypatch.setattr(validator, "run_read_only_mode", fail_read_only_mode)
    monkeypatch.setattr(validator, "call_tool", fake_call_tool)

    summary = await validator.run_all_mode(
        _args(skip_read_only_preflight=True, test_channel=None, write_tool=["slack_create_canvas"]),
        "xoxp-test",
    )

    assert calls == ["slack_create_canvas", "slack_read_canvas"]
    assert summary["write_artifacts"]["created_canvas"]["readback_status"] == "passed"


@pytest.mark.asyncio
async def test_write_validator_targets_channel_without_read_preflight(monkeypatch):
    validator = _load_validator_module()
    calls: list[str] = []

    async def fail_read_only_mode(args, access_token):
        raise AssertionError("read-only preflight should not run")

    async def fake_call_tool(*, tool_name, arguments, access_token):
        calls.append(tool_name)
        if tool_name == "slack_create_channel":
            return {
                "ok": True,
                "result": {
                    "text": "Created channel",
                    "structured": {"channel": {"id": "CNEW", "name": arguments["name"]}},
                },
            }
        raise AssertionError(f"Unexpected tool call: {tool_name}")

    monkeypatch.setattr(validator, "run_read_only_mode", fail_read_only_mode)
    monkeypatch.setattr(validator, "call_tool", fake_call_tool)

    summary = await validator.run_all_mode(
        _args(skip_read_only_preflight=True, test_channel=None, write_tool=["slack_create_channel"]),
        "xoxp-test",
    )

    assert calls == ["slack_create_channel"]
    assert summary["write_artifacts"]["created_channel"]["id"] == "CNEW"


@pytest.mark.asyncio
async def test_rate_limited_tool_retries_after_retry_after(monkeypatch):
    validator = _load_validator_module()
    calls = 0
    sleeps: list[int] = []

    async def fake_call_tool(*, tool_name, arguments, access_token):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "ok": False,
                "error": {
                    "kind": "rate_limited",
                    "raw": {"retry_after": "2", "body": {"error": "ratelimited"}},
                },
            }
        return {"ok": True, "result": {"text": "ok", "structured": {"value": True}}}

    async def fake_sleep(wait_seconds):
        sleeps.append(wait_seconds)

    monkeypatch.setattr(validator, "call_tool", fake_call_tool)
    monkeypatch.setattr(validator, "_sleep_for_rate_limit", fake_sleep)

    row = await validator._run_tool(
        "slack_read_channel_history",
        {"channel": "C1"},
        "xoxp-test",
        rate_limit_retries=2,
        rate_limit_buffer_seconds=1,
        max_rate_limit_wait_seconds=10,
    )

    assert row.status == "passed"
    assert row.attempts == 2
    assert row.rate_limit_waits_seconds == [3]
    assert sleeps == [3]


@pytest.mark.asyncio
async def test_rate_limited_tool_reports_exhausted_retry_budget(monkeypatch):
    validator = _load_validator_module()
    sleeps: list[int] = []

    async def fake_call_tool(*, tool_name, arguments, access_token):
        return {
            "ok": False,
            "error": {
                "kind": "rate_limited",
                "raw": {"retry_after": "2", "body": {"error": "ratelimited"}},
            },
        }

    async def fake_sleep(wait_seconds):
        sleeps.append(wait_seconds)

    monkeypatch.setattr(validator, "call_tool", fake_call_tool)
    monkeypatch.setattr(validator, "_sleep_for_rate_limit", fake_sleep)

    row = await validator._run_tool(
        "slack_read_channel_history",
        {"channel": "C1"},
        "xoxp-test",
        rate_limit_retries=1,
        rate_limit_buffer_seconds=1,
        max_rate_limit_wait_seconds=10,
    )

    assert row.status == "failed"
    assert row.error_kind == "rate_limited"
    assert row.attempts == 2
    assert row.rate_limit_waits_seconds == [3]
    assert row.rate_limit_exhausted is True


@pytest.mark.asyncio
async def test_write_validator_requires_write_gate():
    validator = _load_validator_module()

    with pytest.raises(SystemExit, match="--mode all requires --allow-writes"):
        await validator.run_all_mode(_args(allow_writes=False), "xoxp-test")

    with pytest.raises(SystemExit, match="--mode all --allow-writes requires --test-channel"):
        await validator.run_all_mode(_args(test_channel=None), "xoxp-test")
