"""Text-image CAPTCHA capture and submission, the attempt budget, and image cleanup."""

from __future__ import annotations

import base64
import json
import stat
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation import (
    browser_captcha,
    browser_challenge_state,
    browser_interact_tool,
    browser_page_settle,
)

TEXT_CHALLENGE = {
    "kind": "text_image",
    "handoff_only": False,
    "prompt": "What code is in the image?",
    "image_selector": '[data-basil-challenge="image"]',
    "input_selector": '[data-basil-challenge="input"]',
    "submit_selector": '[data-basil-challenge="submit"]',
}
PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 300).decode()
HOST = "wyoming.example"


@pytest.fixture(autouse=True)
def isolated_captcha_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    browser_challenge_state.clear_all_state()

    async def instant(_seconds):
        return None

    monkeypatch.setattr(browser_page_settle, "_sleep", instant)
    yield
    browser_challenge_state.clear_all_state()


class CaptchaRunJs:
    """Answers the challenge-detect and capture scripts. `challenges` is returned in order, repeating the last."""

    def __init__(self, challenges: List[Optional[Dict[str, Any]]], capture: Optional[Dict[str, Any]] = None):
        self.challenges = challenges
        self.capture = capture or {"success": True, "data_url": PNG_DATA_URL}
        self.detect_calls = 0
        self.calls: List[str] = []

    async def __call__(self, browser, js_code, timeout=30.0, *, window_index=None, tab_index=None):
        self.calls.append(js_code)
        if "basil:challenge_detect" in js_code:
            challenge = self.challenges[min(self.detect_calls, len(self.challenges) - 1)]
            self.detect_calls += 1
            return {"success": True, "url": f"https://{HOST}/search", "challenge": challenge}
        if "basil:captcha_capture" in js_code:
            return dict(self.capture)
        raise AssertionError(js_code[:80])


class Performer:
    """Records the fill and click sub-actions that submit_captcha_text performs."""

    def __init__(self, click_result: Dict[str, Any], fill_result: Optional[Dict[str, Any]] = None):
        self.click_result = click_result
        self.fill_result = fill_result or {"success": True}
        self.calls: List[tuple] = []

    async def __call__(self, action: str, selector: str, value: Optional[str]) -> Dict[str, Any]:
        self.calls.append((action, selector, value))
        return dict(self.fill_result if action == "fill" else self.click_result)


async def submit(run_js: CaptchaRunJs, performer: Performer, value: Optional[str]) -> Dict[str, Any]:
    return await browser_captcha.submit_captcha_text(
        performer, run_js, "Chrome", value, window_index=None, tab_index=None
    )


def test_attempt_counter_counts_resets_and_isolates_hosts():
    assert browser_challenge_state.attempts_used(HOST) == 0
    assert browser_challenge_state.record_attempt(HOST) == 1
    assert browser_challenge_state.record_attempt(HOST) == 2
    assert browser_challenge_state.attempts_used(HOST) == 2
    assert browser_challenge_state.attempts_used("other.example") == 0
    browser_challenge_state.reset_attempts(HOST)
    assert browser_challenge_state.attempts_used(HOST) == 0


def test_attempt_counter_is_per_task():
    token = set_current_agent_context({"root_task_id": "task-a"})
    try:
        browser_challenge_state.record_attempt(HOST)
        assert browser_challenge_state.attempts_used(HOST) == 1
    finally:
        reset_current_agent_context(token)
    token = set_current_agent_context({"root_task_id": "task-b"})
    try:
        assert browser_challenge_state.attempts_used(HOST) == 0
    finally:
        reset_current_agent_context(token)


def test_images_are_deleted_and_missing_files_are_ignored(tmp_path):
    image = tmp_path / "captcha.png"
    image.write_bytes(b"x")
    browser_challenge_state.remember_image(HOST, str(image))
    browser_challenge_state.remember_image(HOST, str(tmp_path / "already-gone.png"))

    assert browser_challenge_state.delete_images(HOST) == 1
    assert not image.exists()
    assert browser_challenge_state.delete_images(HOST) == 0


def test_save_captcha_png_writes_a_private_file_under_the_temp_directory(tmp_path):
    path = Path(browser_captcha.save_captcha_png(PNG_DATA_URL))

    assert path.parent == tmp_path / ".basil" / "data" / "temp"
    assert path.name.startswith("captcha_") and path.suffix == ".png"
    assert path.read_bytes().startswith(b"\x89PNG")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "bad",
    ["", "data:image/jpeg;base64,AAAA", "data:image/png;base64,!!!not-base64!!!", "data:image/png;base64," + base64.b64encode(b"tiny").decode()],
)
def test_save_captcha_png_rejects_unexpected_input(bad):
    with pytest.raises(ValueError):
        browser_captcha.save_captcha_png(bad)


def test_host_of_handles_urls_and_garbage():
    assert browser_captcha.host_of("https://Wyoming.Example/search?x=1") == "wyoming.example"
    assert browser_captcha.host_of(None) == ""
    assert browser_captcha.host_of("not a url") == ""


@pytest.mark.asyncio
async def test_capture_saves_the_canvas_image_and_reports_the_budget():
    run_js = CaptchaRunJs([TEXT_CHALLENGE])

    result = await browser_captcha.capture_captcha(run_js, "Chrome", window_index=None, tab_index=None, target=None)

    assert result["success"] is True
    assert result["image_source"] == "page_canvas"
    assert Path(result["image_path"]).exists()
    assert result["attempts_remaining"] == 2
    assert "analyze_with_vision" in result["next_step"]
    assert "UNREADABLE" in result["vision_prompt"]


@pytest.mark.asyncio
async def test_capture_falls_back_to_a_window_capture_when_the_canvas_is_tainted(tmp_path, monkeypatch):
    fallback_image = tmp_path / "window.png"
    fallback_image.write_bytes(b"png")

    async def fake_fallback(target):
        return {"success": True, "image_path": str(fallback_image)}

    monkeypatch.setattr(browser_captcha, "capture_window_fallback", fake_fallback)
    run_js = CaptchaRunJs([TEXT_CHALLENGE], capture={"success": False, "tainted": True, "error": "tainted"})

    result = await browser_captcha.capture_captcha(run_js, "Chrome", window_index=None, tab_index=None, target=None)

    assert result["success"] is True
    assert result["image_source"] == "window_capture"
    assert "whole browser window" in result["next_step"]


@pytest.mark.asyncio
async def test_capture_reports_a_failed_window_fallback(monkeypatch):
    async def fake_fallback(target):
        return {"success": False, "error": "no window"}

    monkeypatch.setattr(browser_captcha, "capture_window_fallback", fake_fallback)
    run_js = CaptchaRunJs([TEXT_CHALLENGE], capture={"success": False, "tainted": True, "error": "tainted"})

    result = await browser_captcha.capture_captcha(run_js, "Chrome", window_index=None, tab_index=None, target=None)

    assert result == {"success": False, "action": "capture_captcha", "error": "no window"}


@pytest.mark.asyncio
async def test_window_fallback_needs_a_pinned_window():
    result = await browser_captcha.capture_window_fallback(None)

    assert result["success"] is False
    assert "no Basil automation window" in result["error"]


@pytest.mark.asyncio
async def test_capture_hands_off_every_non_text_challenge():
    run_js = CaptchaRunJs([{"kind": "recaptcha", "handoff_only": True, "prompt": "p"}])

    result = await browser_captcha.capture_captcha(run_js, "Chrome", window_index=None, tab_index=None, target=None)

    assert result["handoff_required"] is True
    assert result["challenge_kind"] == "recaptcha"
    assert "request_human_help" in result["next_step"]


@pytest.mark.asyncio
async def test_capture_without_a_challenge_is_a_clear_error():
    result = await browser_captcha.capture_captcha(CaptchaRunJs([None]), "Chrome", window_index=None, tab_index=None, target=None)

    assert result["success"] is False
    assert result["error"] == "No CAPTCHA is showing on this page."


@pytest.mark.asyncio
async def test_capture_after_the_budget_is_used_hands_off():
    browser_challenge_state.record_attempt(HOST)
    browser_challenge_state.record_attempt(HOST)

    result = await browser_captcha.capture_captcha(CaptchaRunJs([TEXT_CHALLENGE]), "Chrome", window_index=None, tab_index=None, target=None)

    assert result["handoff_required"] is True
    assert "2 times" in result["error"]


@pytest.mark.asyncio
async def test_correct_code_is_typed_submitted_and_the_image_deleted():
    run_js = CaptchaRunJs([TEXT_CHALLENGE])
    captured = await browser_captcha.capture_captcha(run_js, "Chrome", window_index=None, tab_index=None, target=None)
    image_path = Path(captured["image_path"])
    performer = Performer({"success": True, "page": {"challenge": None}, "navigated": True})

    result = await submit(run_js, performer, " K7M2Q ")

    assert performer.calls == [
        ("fill", '[data-basil-challenge="input"]', "K7M2Q"),
        ("click", '[data-basil-challenge="submit"]', None),
    ]
    assert result["success"] is True
    assert result["solved"] is True
    assert result["attempts_used"] == 1
    assert not image_path.exists()
    assert browser_challenge_state.attempts_used(HOST) == 0
    assert "browser_inspect" in result["next_step"]


@pytest.mark.asyncio
async def test_wrong_codes_use_the_budget_and_then_hand_off():
    run_js = CaptchaRunJs([TEXT_CHALLENGE])
    performer = Performer({"success": True, "page": {"challenge": dict(TEXT_CHALLENGE)}, "navigated": False})

    first = await submit(run_js, performer, "AAAA")
    second = await submit(run_js, performer, "BBBB")
    third = await submit(run_js, performer, "CCCC")

    assert first["solved"] is False and first["attempts_remaining"] == 1
    assert "capture_captcha" in first["next_step"] and "handoff_required" not in first
    assert second["solved"] is False and second["attempts_remaining"] == 0
    assert second["handoff_required"] is True
    assert third["handoff_required"] is True and third["success"] is False
    assert len(performer.calls) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, "", "UNREADABLE", "ab", "a b c d", "abc!", "x" * 13])
async def test_malformed_values_never_touch_the_page_or_the_budget(value):
    performer = Performer({"success": True})

    result = await submit(CaptchaRunJs([TEXT_CHALLENGE]), performer, value)

    assert result["success"] is False
    assert "request_human_help" in result["error"]
    assert performer.calls == []
    assert browser_challenge_state.attempts_used(HOST) == 0


@pytest.mark.asyncio
async def test_submit_hands_off_non_text_challenges_and_missing_challenges():
    performer = Performer({"success": True})

    login = await submit(CaptchaRunJs([{"kind": "login", "handoff_only": True}]), performer, "ABCD")
    none = await submit(CaptchaRunJs([None]), performer, "ABCD")

    assert login["handoff_required"] is True
    assert none["success"] is False and "handoff_required" not in none
    assert performer.calls == []


@pytest.mark.asyncio
async def test_submit_hands_off_when_the_submit_button_is_missing():
    challenge = {key: value for key, value in TEXT_CHALLENGE.items() if key != "submit_selector"}
    performer = Performer({"success": True})

    result = await submit(CaptchaRunJs([challenge]), performer, "ABCD")

    assert result["handoff_required"] is True
    assert performer.calls == []


@pytest.mark.asyncio
async def test_a_failed_fill_does_not_consume_an_attempt():
    performer = Performer({"success": True}, fill_result={"success": False, "error": "approval needed"})

    result = await submit(CaptchaRunJs([TEXT_CHALLENGE]), performer, "ABCD")

    assert result["success"] is False
    assert result["step"] == "fill"
    assert browser_challenge_state.attempts_used(HOST) == 0


@pytest.mark.asyncio
async def test_a_failed_click_consumes_an_attempt_and_deletes_the_image():
    run_js = CaptchaRunJs([TEXT_CHALLENGE])
    captured = await browser_captcha.capture_captcha(run_js, "Chrome", window_index=None, tab_index=None, target=None)
    performer = Performer({"success": False, "error": "button gone"})

    result = await submit(run_js, performer, "ABCD")

    assert result["success"] is False
    assert result["step"] == "click"
    assert result["attempts_used"] == 1
    assert not Path(captured["image_path"]).exists()


@pytest.mark.asyncio
async def test_without_a_page_summary_the_page_is_inspected_again():
    run_js = CaptchaRunJs([TEXT_CHALLENGE, None])
    performer = Performer({"success": True})

    result = await submit(run_js, performer, "ABCD")

    assert result["solved"] is True
    assert run_js.detect_calls == 2


@pytest.mark.asyncio
async def test_capture_and_submit_work_through_the_interact_tool(monkeypatch):
    async def fake_run_browser_js(browser, js_code, timeout=30.0, *, window_index=None, tab_index=None):
        if "basil:challenge_detect" in js_code:
            return {"success": True, "url": f"https://{HOST}/search", "challenge": TEXT_CHALLENGE}
        if "basil:captcha_capture" in js_code:
            return {"success": True, "data_url": PNG_DATA_URL}
        if "basil:settle_probe" in js_code:
            return {"success": True, "ready": "complete", "url": f"https://{HOST}/results", "title": "Results", "text_length": 10}
        if "basil:page_summary" in js_code:
            return {"success": True, "url": f"https://{HOST}/results", "title": "Results", "ready": "complete", "headings": [], "messages": [], "challenge": None}
        if "Metadata inspect failed" in js_code:
            return {"success": True, "url": f"https://{HOST}/search", "type": "text", "credentialLike": False}
        return {"success": True, "action": "step", "found": True, "type": "submit", "newUrl": f"https://{HOST}/search", "newTitle": "Search"}

    monkeypatch.setattr(browser_interact_tool, "_run_browser_js", fake_run_browser_js)

    captured = json.loads(await browser_interact_tool._browser_interact_impl(browser="Chrome", action="capture_captcha"))
    submitted = json.loads(
        await browser_interact_tool._browser_interact_impl(browser="Chrome", action="submit_captcha", value="K7M2Q")
    )
    missing_value = json.loads(await browser_interact_tool._browser_interact_impl(browser="Chrome", action="submit_captcha"))

    assert captured["success"] is True and captured["browser"] == "Chrome"
    assert captured["image_path"].endswith(".png")
    assert submitted["success"] is True and submitted["solved"] is True
    assert submitted["navigated"] is True
    assert missing_value["success"] is False
    assert "requires a 'value'" in missing_value["error"]
