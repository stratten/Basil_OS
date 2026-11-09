"""fill_form: one call fills several fields, stops at the first failure, and reads values back."""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from api.services.agent_processing.tools.direct_application_interactions.browser_automation import (
    browser_interact_batch,
    browser_interact_tool,
)


def test_readback_script_embeds_selectors_as_json():
    selectors = ['input[name="q"]', "#a"]

    js = browser_interact_batch.build_form_readback_js(selectors)

    assert js.startswith("// basil:form_readback")
    assert json.dumps(selectors) in js
    assert "__SELECTORS__" not in js


@pytest.mark.asyncio
async def test_batch_rejects_missing_empty_and_oversized_fields():
    async def never(_selector, _value):
        raise AssertionError("fill must not run")

    async def never_read(_selectors):
        raise AssertionError("readback must not run")

    for bad in (None, {}, "not a dict", [("#a", "b")]):
        result = await browser_interact_batch.fill_form_batch(never, never_read, bad)
        assert result["success"] is False
        assert "requires a non-empty 'fields' object" in result["error"]

    too_many = {f"#f{i}": "x" for i in range(browser_interact_batch.MAX_FORM_FIELDS + 1)}
    result = await browser_interact_batch.fill_form_batch(never, never_read, too_many)
    assert "at most 25 fields" in result["error"]

    result = await browser_interact_batch.fill_form_batch(never, never_read, {"  ": "x"})
    assert "non-empty selector" in result["error"]


@pytest.mark.asyncio
async def test_batch_fills_in_order_and_reads_back():
    order: List[str] = []

    async def fill_one(selector: str, value: str) -> str:
        order.append(f"{selector}={value}")
        return json.dumps({"success": True, "action": "fill"})

    async def read_back(selectors: List[str]) -> Dict[str, Any]:
        return {"success": True, "fields": {selector: {"found": True, "value": "ok"} for selector in selectors}}

    result = await browser_interact_batch.fill_form_batch(fill_one, read_back, {"#a": "1", "#b": 2})

    assert order == ["#a=1", "#b=2"]
    assert result["success"] is True
    assert result["filled"] == ["#a", "#b"]
    assert result["readback"]["#b"]["value"] == "ok"
    assert "failed" not in result


@pytest.mark.asyncio
async def test_batch_stops_at_the_first_failure_and_lists_skipped_fields():
    async def fill_one(selector: str, value: str) -> str:
        if selector == "#missing":
            return json.dumps({"success": False, "error": "Element not found: #missing", "hint": "try again"})
        return json.dumps({"success": True})

    async def read_back(selectors: List[str]) -> Dict[str, Any]:
        return {"success": True, "fields": {selector: {"found": True} for selector in selectors}}

    result = await browser_interact_batch.fill_form_batch(
        fill_one, read_back, {"#first": "a", "#missing": "b", "#third": "c"}
    )

    assert result["success"] is False
    assert result["filled"] == ["#first"]
    assert result["failed"]["selector"] == "#missing"
    assert result["failed"]["hint"] == "try again"
    assert result["skipped"] == ["#third"]
    assert result["error"] == "Stopped at #missing: Element not found: #missing"
    assert list(result["readback"]) == ["#first"]


@pytest.mark.asyncio
async def test_batch_surfaces_user_input_requirements():
    async def fill_one(selector: str, value: str) -> str:
        return json.dumps({"success": False, "error": "approval needed", "requires_user_input": True, "sensitive_fill": True})

    async def read_back(selectors: List[str]) -> Dict[str, Any]:
        raise AssertionError("nothing was filled, so nothing is read back")

    result = await browser_interact_batch.fill_form_batch(fill_one, read_back, {"#password": "x"})

    assert result["requires_user_input"] is True
    assert result["failed"]["sensitive_fill"] is True
    assert "readback" not in result


@pytest.mark.asyncio
async def test_batch_survives_a_readback_failure():
    async def fill_one(selector: str, value: str) -> str:
        return json.dumps({"success": True})

    async def read_back(selectors: List[str]) -> Dict[str, Any]:
        raise RuntimeError("page closed")

    result = await browser_interact_batch.fill_form_batch(fill_one, read_back, {"#a": "1"})

    assert result["success"] is True
    assert result["readback_error"] == "page closed"


@pytest.mark.asyncio
async def test_fill_form_action_goes_through_the_single_fill_path(monkeypatch):
    calls: List[str] = []

    async def fake_run_browser_js(_browser, js_code, timeout=30.0, **_kwargs):
        calls.append(js_code)
        if "basil:form_readback" in js_code:
            return {"success": True, "fields": {"#first": {"found": True, "value": "Ada"}, "#email": {"found": True, "value": "ada@example.com"}}}
        if "Metadata inspect failed" in js_code:
            return {"success": True, "url": "https://example.com/form", "type": "text", "credentialLike": False}
        return {"success": True, "action": "fill", "found": True}

    monkeypatch.setattr(browser_interact_tool, "_run_browser_js", fake_run_browser_js)

    result = json.loads(
        await browser_interact_tool._browser_interact_impl(
            browser="Chrome",
            action="fill_form",
            fields={"#first": "Ada", "#email": "ada@example.com"},
        )
    )

    assert result["success"] is True
    assert result["filled"] == ["#first", "#email"]
    assert result["readback"]["#first"]["value"] == "Ada"
    assert result["browser"] == "Chrome"
    assert len([call for call in calls if "Metadata inspect failed" in call]) == 2


@pytest.mark.asyncio
async def test_fill_form_action_without_fields_is_a_structured_error():
    result = json.loads(await browser_interact_tool._browser_interact_impl(browser="Chrome", action="fill_form"))

    assert result["success"] is False
    assert "requires a non-empty 'fields' object" in result["error"]
