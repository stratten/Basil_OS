"""Unit coverage for the not-found diagnostics helpers."""

from __future__ import annotations

import pytest

from api.services.agent_processing.tools.direct_application_interactions.browser_automation import (
    browser_interact_diagnostics as diagnostics,
)


def test_similar_token_picks_the_longest_word_like_fragment():
    assert diagnostics.similar_token("#MainContent_txtFilingName") == "txtfilingname"
    assert diagnostics.similar_token("input[name='q']") == "input"
    assert diagnostics.similar_token("#a1") == ""
    assert diagnostics.similar_token("") == ""


def test_diagnostics_script_embeds_the_token_as_a_json_literal():
    js = diagnostics.build_not_found_diagnostics_js("#MainContent_txtFilingName")

    assert js.startswith("// basil:not_found_diagnostics")
    assert 'var token = "txtfilingname";' in js
    assert "__TOKEN__" not in js
    assert "basilDetectChallenge" in js


def test_is_not_found_result_only_matches_plain_not_found_failures():
    assert diagnostics.is_not_found_result({"success": False, "error": "Element not found: #x"}) is True
    assert diagnostics.is_not_found_result({"success": False, "error": "Element not found after 10s: #x"}) is True
    assert diagnostics.is_not_found_result({"success": True, "error": "Element not found"}) is False
    assert diagnostics.is_not_found_result({"success": False, "error": "Fill failed"}) is False
    assert diagnostics.is_not_found_result({"success": False, "error": "Element not found", "sensitive_fill": True}) is False
    assert diagnostics.is_not_found_result({"success": False, "error": "Element not found", "requires_user_input": True}) is False
    assert diagnostics.is_not_found_result("not a dict") is False  # type: ignore[arg-type]


def test_hint_covers_handoff_text_image_similar_and_plain_cases():
    handoff = diagnostics.build_not_found_hint({"challenge": {"kind": "recaptcha", "handoff_only": True}})
    text_image = diagnostics.build_not_found_hint({"challenge": {"kind": "text_image", "handoff_only": False}})
    similar = diagnostics.build_not_found_hint({"challenge": None, "similar": [{"selector": "#x"}]})
    plain = diagnostics.build_not_found_hint({"challenge": None, "similar": []})

    assert "request_human_help" in handoff
    assert "recaptcha" in handoff
    assert "capture_captcha" in text_image and "submit_captcha" in text_image
    assert "page_state.similar" in similar
    assert "browser_inspect" in plain


@pytest.mark.asyncio
async def test_attach_never_raises_when_the_diagnostic_call_fails():
    async def failing_run_js(browser, js_code, timeout=30.0, *, window_index=None, tab_index=None):
        raise RuntimeError("browser gone")

    result = {"success": False, "error": "Element not found: #x"}

    await diagnostics.attach_not_found_diagnostics(failing_run_js, "Chrome", "#x", result, window_index=None, tab_index=None)

    assert "page_state" not in result
    assert result["success"] is False
