"""Selector waits, click settling, empty replies, and not-found diagnostics through browser_interact."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

import pytest

from api.services.agent_processing.tools.direct_application_interactions.browser_automation import (
    browser_interact_tool,
    browser_page_settle,
)

NOT_VISIBLE = {"success": False, "action": "wait", "found": False, "error": "Element not visible yet: #ready"}
VISIBLE = {"success": True, "action": "wait", "found": True, "attempts": 1, "newUrl": "https://example.com", "newTitle": "Example"}


def complete_probe(text_length: int = 100, url: str = "https://example.com/b", title: str = "B") -> Dict[str, Any]:
    return {"success": True, "ready": "complete", "url": url, "title": title, "text_length": text_length}


def results_summary(challenge: Any = None) -> Dict[str, Any]:
    return {
        "success": True,
        "url": "https://example.com/results",
        "title": "Results",
        "ready": "complete",
        "headings": ["Search results"],
        "messages": [],
        "challenge": challenge,
    }


class HandlerRunJs:
    """A fake `_run_browser_js` that records every script and answers through a handler."""

    def __init__(self, handler: Callable[[str], Dict[str, Any]]):
        self.handler = handler
        self.calls: List[str] = []

    async def __call__(self, browser, js_code, timeout=30.0, *, window_index=None, tab_index=None):
        self.calls.append(js_code)
        return self.handler(js_code)

    def action_calls(self) -> List[str]:
        return [call for call in self.calls if "basil:" not in call]


@pytest.fixture(autouse=True)
def instant_settle_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(browser_page_settle, "_sleep", instant)


def test_selector_wait_javascript_is_synchronous():
    wait_js = browser_interact_tool._build_action_js("wait", "#ready", None)

    assert "setTimeout" not in wait_js
    assert "async function" not in wait_js
    assert "Promise" not in wait_js
    assert "Element not visible yet" in wait_js
    assert "queryDeep(selector)" in wait_js


@pytest.mark.asyncio
async def test_wait_for_selector_returns_on_first_success():
    run_js = HandlerRunJs(lambda js: dict(VISIBLE))

    result = await browser_page_settle.wait_for_selector(run_js, "Chrome", "probe", "#ready", window_index=None, tab_index=None)

    assert result["success"] is True
    assert result["attempts"] == 1
    assert len(run_js.calls) == 1


@pytest.mark.asyncio
async def test_wait_for_selector_retries_until_visible():
    answers = iter([dict(NOT_VISIBLE), dict(NOT_VISIBLE), dict(VISIBLE)])
    run_js = HandlerRunJs(lambda js: next(answers))

    result = await browser_page_settle.wait_for_selector(run_js, "Chrome", "probe", "#ready", window_index=None, tab_index=None)

    assert result["success"] is True
    assert result["attempts"] == 3


@pytest.mark.asyncio
async def test_wait_for_selector_tolerates_empty_replies_from_a_navigating_page():
    answers = iter([{"success": False, "empty_response": True, "error": "navigating"}, dict(VISIBLE)])
    run_js = HandlerRunJs(lambda js: next(answers))

    result = await browser_page_settle.wait_for_selector(run_js, "Chrome", "probe", "#ready", window_index=None, tab_index=None)

    assert result["success"] is True
    assert result["attempts"] == 2


@pytest.mark.asyncio
async def test_wait_for_selector_returns_other_errors_immediately():
    run_js = HandlerRunJs(lambda js: {"success": False, "error": "Apple Events blocked", "permission_blocked": True})

    result = await browser_page_settle.wait_for_selector(run_js, "Chrome", "probe", "#ready", window_index=None, tab_index=None)

    assert result["success"] is False
    assert result["permission_blocked"] is True
    assert len(run_js.calls) == 1


@pytest.mark.asyncio
async def test_wait_for_selector_gives_up_with_a_clear_error():
    run_js = HandlerRunJs(lambda js: dict(NOT_VISIBLE))

    result = await browser_page_settle.wait_for_selector(
        run_js, "Chrome", "probe", "#ready", window_index=None, tab_index=None, attempts=4, interval_s=0.5
    )

    assert result["success"] is False
    assert result["attempts"] == 4
    assert result["error"] == "Element not found after 2s: #ready"
    assert len(run_js.calls) == 4


@pytest.mark.asyncio
async def test_settle_waits_for_two_matching_complete_probes():
    probes = iter([
        {"success": True, "ready": "loading", "url": "u", "title": "t", "text_length": 1},
        complete_probe(),
        complete_probe(),
        complete_probe(),
    ])

    def handler(js: str) -> Dict[str, Any]:
        if "basil:settle_probe" in js:
            return next(probes)
        if "basil:page_summary" in js:
            return results_summary()
        raise AssertionError(js[:80])

    run_js = HandlerRunJs(handler)

    outcome = await browser_page_settle.settle_after_click(
        run_js, "Chrome", before_url="https://example.com/form", before_title="Form", window_index=None, tab_index=None
    )

    assert outcome["settled"] is True
    assert outcome["navigated"] is True
    assert outcome["page"]["headings"] == ["Search results"]
    assert "success" not in outcome["page"]
    assert len([call for call in run_js.calls if "basil:settle_probe" in call]) == 3


@pytest.mark.asyncio
async def test_settle_reports_a_page_that_never_stops_changing():
    counter = {"n": 0}

    def handler(js: str) -> Dict[str, Any]:
        if "basil:settle_probe" in js:
            counter["n"] += 1
            return complete_probe(text_length=counter["n"])
        return results_summary()

    run_js = HandlerRunJs(handler)

    outcome = await browser_page_settle.settle_after_click(
        run_js, "Chrome", before_url=None, before_title=None, window_index=None, tab_index=None, max_wait_s=1.0, interval_s=0.4
    )

    assert outcome["settled"] is False
    assert counter["n"] == 3


@pytest.mark.asyncio
async def test_settle_tolerates_empty_probes_while_the_page_navigates():
    probes = iter([
        {"success": False, "empty_response": True, "error": "navigating"},
        {"success": False, "empty_response": True, "error": "navigating"},
        complete_probe(),
        complete_probe(),
    ])
    run_js = HandlerRunJs(lambda js: next(probes) if "basil:settle_probe" in js else results_summary())

    outcome = await browser_page_settle.settle_after_click(
        run_js, "Chrome", before_url="a", before_title="a", window_index=None, tab_index=None
    )

    assert outcome["settled"] is True


@pytest.mark.asyncio
async def test_settle_survives_a_failed_page_summary():
    def handler(js: str) -> Dict[str, Any]:
        if "basil:settle_probe" in js:
            return complete_probe()
        return {"success": False, "error": "summary failed"}

    outcome = await browser_page_settle.settle_after_click(
        HandlerRunJs(handler), "Chrome", before_url="a", before_title="a", window_index=None, tab_index=None
    )

    assert outcome["page"] == {}
    assert outcome["page_summary_error"] == "summary failed"
    assert outcome["navigated"] is False


@pytest.mark.asyncio
async def test_click_returns_settled_page_summary(monkeypatch):
    def handler(js: str) -> Dict[str, Any]:
        if "basil:settle_probe" in js:
            return complete_probe()
        if "basil:page_summary" in js:
            return results_summary()
        return {"success": True, "action": "click", "type": "submit", "found": True, "newUrl": "https://example.com/form", "newTitle": "Form"}

    run_js = HandlerRunJs(handler)
    monkeypatch.setattr(browser_interact_tool, "_run_browser_js", run_js)

    result = json.loads(await browser_interact_tool._browser_interact_impl(browser="Chrome", action="click", selector="#go"))

    assert result["success"] is True
    assert result["settled"] is True
    assert result["navigated"] is True
    assert result["page"]["title"] == "Results"
    assert result["newUrl"] == "https://example.com/results"
    assert result["newTitle"] == "Results"


@pytest.mark.asyncio
async def test_click_on_a_checkbox_skips_settling(monkeypatch):
    run_js = HandlerRunJs(lambda js: {"success": True, "action": "click", "type": "checkbox", "found": True, "newUrl": "u", "newTitle": "t"})
    monkeypatch.setattr(browser_interact_tool, "_run_browser_js", run_js)

    result = json.loads(await browser_interact_tool._browser_interact_impl(browser="Chrome", action="click", selector="#agree"))

    assert result["success"] is True
    assert "page" not in result
    assert len(run_js.calls) == 1


@pytest.mark.asyncio
async def test_click_with_an_empty_reply_is_not_repeated(monkeypatch):
    def handler(js: str) -> Dict[str, Any]:
        if "basil:settle_probe" in js:
            return complete_probe()
        if "basil:page_summary" in js:
            return results_summary()
        return {"success": False, "empty_response": True, "error": "The browser returned no response"}

    run_js = HandlerRunJs(handler)
    monkeypatch.setattr(browser_interact_tool, "_run_browser_js", run_js)

    result = json.loads(await browser_interact_tool._browser_interact_impl(browser="Chrome", action="click", selector="#go"))

    assert len(run_js.action_calls()) == 1
    assert result["success"] is False
    assert result["outcome_unknown"] is True
    assert "navigated" not in result
    assert result["page"]["title"] == "Results"
    assert "did not repeat" in result["error"] or "not repeat" in result["error"]


@pytest.mark.asyncio
async def test_scroll_with_an_empty_reply_is_retried_once(monkeypatch):
    answers = iter([{"success": False, "empty_response": True, "error": "empty"}, {"success": True, "action": "scroll", "found": True}])
    run_js = HandlerRunJs(lambda js: next(answers))
    monkeypatch.setattr(browser_interact_tool, "_run_browser_js", run_js)

    async def instant(_seconds):
        return None

    monkeypatch.setattr(browser_interact_tool.asyncio, "sleep", instant)

    result = json.loads(await browser_interact_tool._browser_interact_impl(browser="Chrome", action="scroll", selector="#footer"))

    assert result["success"] is True
    assert len(run_js.calls) == 2


@pytest.mark.asyncio
async def test_selector_wait_polls_from_python(monkeypatch):
    answers = iter([dict(NOT_VISIBLE), dict(NOT_VISIBLE), dict(VISIBLE)])
    run_js = HandlerRunJs(lambda js: next(answers))
    monkeypatch.setattr(browser_interact_tool, "_run_browser_js", run_js)

    result = json.loads(await browser_interact_tool._browser_interact_impl(browser="Chrome", action="wait", selector="#ready"))

    assert result["success"] is True
    assert result["attempts"] == 3
    assert all("Element not visible yet" in call for call in run_js.calls)


@pytest.mark.asyncio
async def test_selector_wait_that_never_succeeds_reports_the_full_budget(monkeypatch):
    def handler(js: str) -> Dict[str, Any]:
        if "basil:not_found_diagnostics" in js:
            return {"success": False, "error": "no diagnostics"}
        return dict(NOT_VISIBLE)

    run_js = HandlerRunJs(handler)
    monkeypatch.setattr(browser_interact_tool, "_run_browser_js", run_js)

    result = json.loads(await browser_interact_tool._browser_interact_impl(browser="Chrome", action="wait", selector="#ready"))

    assert result["success"] is False
    assert result["error"] == "Element not found after 10s: #ready"
    assert len(run_js.action_calls()) == 20


@pytest.mark.asyncio
async def test_not_found_on_a_verification_page_explains_itself(monkeypatch):
    diagnostics = {
        "success": True,
        "url": "https://example.com/blocked",
        "title": "Just a moment...",
        "ready": "complete",
        "text_head": "Your support ID is: 123",
        "similar": [],
        "challenge": {"kind": "bot_interstitial", "handoff_only": True, "prompt": "Your support ID is: 123"},
    }

    def handler(js: str) -> Dict[str, Any]:
        if "basil:not_found_diagnostics" in js:
            return dict(diagnostics)
        return {"success": False, "found": False, "error": "Element not found: #MainContent_txtFilingName"}

    run_js = HandlerRunJs(handler)
    monkeypatch.setattr(browser_interact_tool, "_run_browser_js", run_js)

    result = json.loads(await browser_interact_tool._browser_interact_impl(browser="Chrome", action="click", selector="#MainContent_txtFilingName"))

    assert result["success"] is False
    assert result["page_state"]["title"] == "Just a moment..."
    assert "success" not in result["page_state"]
    assert "request_human_help" in result["hint"]
    assert len([call for call in run_js.calls if "basil:settle_probe" in call]) == 0


@pytest.mark.asyncio
async def test_successful_fill_makes_no_diagnostic_calls(monkeypatch):
    def handler(js: str) -> Dict[str, Any]:
        if "Metadata inspect failed" in js:
            return {"success": True, "url": "https://example.com", "type": "text", "credentialLike": False}
        return {"success": True, "action": "fill", "found": True}

    run_js = HandlerRunJs(handler)
    monkeypatch.setattr(browser_interact_tool, "_run_browser_js", run_js)

    result = json.loads(await browser_interact_tool._browser_interact_impl(browser="Chrome", action="fill", selector="#name", value="Ada"))

    assert result["success"] is True
    assert not [call for call in run_js.calls if "basil:" in call]
