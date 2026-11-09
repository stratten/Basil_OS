"""The Python side of browser_inspect: new options, focus modes, and carried fields."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import pytest
from pydantic import ValidationError

from api.services.agent_processing.tools.direct_application_interactions.browser_automation import (
    browser_inspect_extensions,
    browser_inspect_tool,
)


def page_json(**extra: Any) -> str:
    page: Dict[str, Any] = {
        "url": "https://example.com",
        "title": "Example",
        "ready": "complete",
        "buttons": [{"selector": "#buy", "text": "Buy"}],
        "inputs": [{"selector": "#q", "type": "text", "global_search": True, "region": "header"}],
        "links": [{"selector": "a#first", "text": "Result", "href": "https://r.com"}],
        "headings": ["Example Heading"],
        "skippedFrames": [],
        "requires_user_input": False,
        "safety_warnings": [],
        "mainText": "Body text.",
    }
    page.update(extra)
    return json.dumps(page)


@pytest.fixture
def captured_script(monkeypatch):
    captured: Dict[str, Optional[str]] = {"js": None, "page": None}

    def fake_build(browser, js_code, **_kwargs):
        captured["js"] = js_code
        return "script"

    async def fake_run_applescript(script: str, timeout_s: float = 30.0):
        return True, captured["page"] or page_json(), ""

    monkeypatch.setattr(browser_inspect_tool, "_build_applescript", fake_build)
    monkeypatch.setattr(browser_inspect_tool, "run_applescript", fake_run_applescript)
    return captured


def test_extension_placeholders_are_resolved_at_import_time():
    js = browser_inspect_tool._INSPECT_JS_CODE

    assert browser_inspect_extensions.EXTENSIONS_PLACEHOLDER not in js
    assert "basilDetectChallenge" in js
    assert "basilCollectFormState" in js
    assert "withoutPageChrome" in js
    # The options placeholder stays until a call fills it in.
    assert browser_inspect_extensions.OPTIONS_PLACEHOLDER in js


def test_existing_inspect_javascript_contract_is_preserved():
    js = browser_inspect_tool._INSPECT_JS_CODE

    for token in ("mainReadableText", "info.mainText", "12000", "shadowRoot", "contentDocument", "skippedFrames", "requires_user_input"):
        assert token in js


def test_apply_inspect_options_declares_a_json_options_object():
    js = browser_inspect_extensions.apply_inspect_options(
        browser_inspect_tool._INSPECT_JS_CODE,
        content_selector='  #main "x"  ',
        content_offset=-5,
        include_form_state=True,
    )

    assert browser_inspect_extensions.OPTIONS_PLACEHOLDER not in js
    declaration = next(line for line in js.splitlines() if "const BASIL_OPTIONS" in line)
    options = json.loads(declaration.split("=", 1)[1].strip().rstrip(";"))
    assert options == {"contentSelector": '#main "x"', "contentOffset": 0, "includeFormState": True}


def test_apply_inspect_options_defaults_to_no_selector():
    js = browser_inspect_extensions.apply_inspect_options(
        browser_inspect_tool._INSPECT_JS_CODE, content_selector=None, content_offset=0, include_form_state=False
    )

    assert '"contentSelector": null' in js
    assert '"includeFormState": false' in js


def test_schema_accepts_new_fields_and_rejects_bad_ones():
    parsed = browser_inspect_tool.BrowserInspectInput(focus="form_state", content_selector="#a", content_offset=5)

    assert parsed.focus == "form_state"
    assert parsed.content_offset == 5
    with pytest.raises(ValidationError):
        browser_inspect_tool.BrowserInspectInput(content_offset=-1)
    with pytest.raises(ValidationError):
        browser_inspect_tool.BrowserInspectInput(focus="everything")


@pytest.mark.asyncio
async def test_options_reach_the_script(captured_script):
    await browser_inspect_tool._browser_inspect_impl(
        browser="Chrome", focus="content", content_selector="#MainContent", content_offset=12000
    )

    assert '"contentSelector": "#MainContent"' in captured_script["js"]
    assert '"contentOffset": 12000' in captured_script["js"]
    assert '"includeFormState": false' in captured_script["js"]


@pytest.mark.asyncio
async def test_form_state_focus_requests_form_state_and_returns_it(captured_script):
    captured_script["page"] = page_json(
        formState=[{"selector": "#first", "label": "First name", "type": "text", "value": "Ada"}],
        validationMessages=["Required"],
        challenge={"kind": "login", "handoff_only": True},
    )

    parsed = json.loads(await browser_inspect_tool._browser_inspect_impl(browser="Chrome", focus="form_state"))

    assert '"includeFormState": true' in captured_script["js"]
    assert parsed["success"] is True
    assert parsed["formState"][0]["value"] == "Ada"
    assert parsed["validationMessages"] == ["Required"]
    assert parsed["challenge"]["kind"] == "login"
    for absent in ("buttons", "links", "inputs", "headings", "mainText"):
        assert absent not in parsed


@pytest.mark.asyncio
async def test_form_state_is_never_returned_for_other_focus_values(captured_script):
    captured_script["page"] = page_json(formState=[{"selector": "#first"}])

    parsed = json.loads(await browser_inspect_tool._browser_inspect_impl(browser="Chrome", focus="all"))

    assert "formState" not in parsed
    assert "mainText" not in parsed


@pytest.mark.asyncio
async def test_content_focus_carries_text_metadata_and_challenge(captured_script):
    captured_script["page"] = page_json(
        mainTextMeta={"truncated": True, "next_offset": 12000},
        challenge={"kind": "text_image", "handoff_only": False},
    )

    parsed = json.loads(await browser_inspect_tool._browser_inspect_impl(browser="Chrome", focus="content"))

    assert parsed["mainText"] == "Body text."
    assert parsed["mainTextMeta"]["next_offset"] == 12000
    assert parsed["challenge"]["kind"] == "text_image"
    assert "buttons" not in parsed


@pytest.mark.asyncio
async def test_content_focus_without_extension_fields_matches_the_old_shape(captured_script):
    parsed = json.loads(await browser_inspect_tool._browser_inspect_impl(browser="Chrome", focus="content"))

    assert {"url", "title", "ready", "mainText", "success", "browser"}.issubset(parsed)
    for absent in ("challenge", "frame_notice", "mainTextMeta", "formState", "validationMessages", "buttons", "links", "inputs", "headings"):
        assert absent not in parsed


@pytest.mark.asyncio
async def test_forms_focus_carries_frame_notice_and_challenge(captured_script):
    captured_script["page"] = page_json(frame_notice="1 frame(s) from another site cannot be read.", challenge=None)

    parsed = json.loads(await browser_inspect_tool._browser_inspect_impl(browser="Chrome", focus="forms"))

    assert parsed["inputs"][0]["global_search"] is True
    assert parsed["frame_notice"].startswith("1 frame(s)")
    assert "challenge" not in parsed
    assert "buttons" not in parsed


@pytest.mark.asyncio
async def test_all_focus_keeps_extension_fields_in_the_default_payload(captured_script):
    captured_script["page"] = page_json(frames=[{"selector": "iframe", "host": "pay.example", "accessible": False}], challenge=None)

    parsed = json.loads(await browser_inspect_tool._browser_inspect_impl(browser="Chrome", focus="all"))

    assert parsed["frames"][0]["host"] == "pay.example"
    assert parsed["buttons"] and parsed["links"]
