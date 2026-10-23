from __future__ import annotations

from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_highlight_tool import (
    _build_highlight_js,
)


def test_highlight_js_contains_basil_owned_overlay_marker():
    js_code = _build_highlight_js("highlight", "#submit", "Submit", 2500)

    assert "data-basil-browser-highlight" in js_code
    assert "queryDeep" in js_code
    assert "#0A84FF" in js_code


def test_clear_js_removes_basil_owned_overlays():
    js_code = _build_highlight_js("clear", None, None, 2500)

    assert "clearHighlights" in js_code
    assert "document.querySelectorAll('[' + marker + ']')" in js_code

