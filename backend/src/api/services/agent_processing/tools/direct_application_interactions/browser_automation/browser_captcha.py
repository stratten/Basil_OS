"""Capture and answer simple type-the-characters CAPTCHAs, handing everything else to the user."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple
from urllib.parse import urlparse

from api.services.capture.shared.window_capture_bridge import request_swift_window_capture

from .browser_challenge_js import CHALLENGE_DETECT_ONLY_JS
from .browser_challenge_state import (
    MAX_TEXT_CAPTCHA_ATTEMPTS,
    attempts_used,
    captcha_temp_directory,
    delete_images,
    record_attempt,
    remember_image,
    reset_attempts,
)
from .browser_page_settle import RunJs
from .browser_target_runtime import BrowserAutomationTarget
from .browser_window_capture_target import resolve_window_capture_target

logger = logging.getLogger(__name__)

VISION_PROMPT = (
    "This is a CAPTCHA image of a short code. Reply with only the characters you can read, "
    "with no spaces or punctuation. If you cannot read it confidently, reply with exactly UNREADABLE."
)

_DATA_URL_PREFIX = "data:image/png;base64,"
_VALID_CODE = re.compile(r"^[A-Za-z0-9]{3,12}$")

CAPTCHA_CAPTURE_JS = r'''// basil:captcha_capture
(function() {
    var img = document.querySelector('[data-basil-challenge="image"]');
    if (!img) {
        return JSON.stringify({success: false, error: 'No CAPTCHA image is marked on this page. Call browser_inspect first and confirm challenge.kind is text_image.'});
    }
    try {
        var tag = img.tagName.toLowerCase();
        var width = tag === 'img' ? (img.naturalWidth || img.width) : img.width;
        var height = tag === 'img' ? (img.naturalHeight || img.height) : img.height;
        if (!width || !height || (tag === 'img' && !img.complete)) {
            return JSON.stringify({success: false, error: 'The CAPTCHA image has not finished loading. Wait a moment and try again.'});
        }
        var scale = Math.max(1, Math.min(4, Math.round(300 / width)));
        var canvas = document.createElement('canvas');
        canvas.width = width * scale;
        canvas.height = height * scale;
        var context = canvas.getContext('2d');
        context.fillStyle = '#ffffff';
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.imageSmoothingEnabled = true;
        context.drawImage(img, 0, 0, canvas.width, canvas.height);
        return JSON.stringify({success: true, data_url: canvas.toDataURL('image/png'), width: width, height: height, scale: scale});
    } catch (error) {
        var tainted = String(error && error.name) === 'SecurityError';
        return JSON.stringify({success: false, tainted: tainted, error: 'Could not read the CAPTCHA image: ' + String(error && error.message ? error.message : error)});
    }
})();
'''

Perform = Callable[[str, str, Optional[str]], Awaitable[Dict[str, Any]]]


def host_of(url: Optional[str]) -> str:
    return (urlparse(url or "").hostname or "").lower()


def save_captcha_png(data_url: str) -> str:
    """Decode a PNG data URL into a private file under `~/.basil/data/temp` and return its path."""

    if not isinstance(data_url, str) or not data_url.startswith(_DATA_URL_PREFIX):
        raise ValueError("The page returned an unexpected image format.")
    try:
        raw = base64.b64decode(data_url[len(_DATA_URL_PREFIX):], validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("The page returned an unreadable image.") from error
    if len(raw) < 100 or len(raw) > 2_000_000:
        raise ValueError("The CAPTCHA image had an unexpected size.")
    directory = captcha_temp_directory()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"captcha_{int(time.time() * 1000)}.png"
    path.write_bytes(raw)
    path.chmod(0o600)
    return str(path)


async def capture_window_fallback(target: Optional[BrowserAutomationTarget]) -> Dict[str, Any]:
    """Capture the automation window when the canvas route is blocked. Never activates the browser."""

    if target is None or target.window_id is None:
        return {"success": False, "error": "The page blocks reading the CAPTCHA image and there is no Basil automation window to capture instead."}
    window_target, window_error = await resolve_window_capture_target(target)
    if window_target is None:
        return {"success": False, "error": window_error}
    capture = await request_swift_window_capture("browser_captcha", window_target=window_target)
    if not capture.get("success") or not capture.get("image_path"):
        return {"success": False, "error": capture.get("error") or capture.get("message") or "Window capture failed."}
    return {"success": True, "image_path": capture["image_path"]}


def handoff_result(action: str, challenge: Optional[Dict[str, Any]], reason: str) -> Dict[str, Any]:
    kind = (challenge or {}).get("kind")
    return {
        "success": False,
        "action": action,
        "handoff_required": True,
        "challenge_kind": kind,
        "error": reason,
        "next_step": (
            "Call browser_tabs with action request_human_help so the user can complete this step, "
            "then confirm with browser_inspect that it is gone."
        ),
    }


async def _detect(
    run_js: RunJs,
    browser: str,
    window_index: Optional[int],
    tab_index: Optional[int],
) -> Tuple[Optional[Dict[str, Any]], str, Optional[str]]:
    """Return `(challenge, host, error)` for the page as it is now."""

    result = await run_js(browser, CHALLENGE_DETECT_ONLY_JS, timeout=15.0, window_index=window_index, tab_index=tab_index)
    if not isinstance(result, dict) or not result.get("success"):
        error = (result or {}).get("error") if isinstance(result, dict) else None
        return None, "", error or "Could not inspect the page for a CAPTCHA."
    challenge = result.get("challenge")
    return (challenge if isinstance(challenge, dict) else None), host_of(result.get("url")), None


async def capture_captcha(
    run_js: RunJs,
    browser: str,
    *,
    window_index: Optional[int],
    tab_index: Optional[int],
    target: Optional[BrowserAutomationTarget],
) -> Dict[str, Any]:
    challenge, host, error = await _detect(run_js, browser, window_index, tab_index)
    if error:
        return {"success": False, "action": "capture_captcha", "error": error}
    if challenge is None:
        return {"success": False, "action": "capture_captcha", "error": "No CAPTCHA is showing on this page."}
    if challenge.get("kind") != "text_image" or challenge.get("handoff_only"):
        return handoff_result(
            "capture_captcha",
            challenge,
            f"This is a {str(challenge.get('kind')).replace('_', ' ')} step that only the user can complete.",
        )
    used = attempts_used(host)
    if used >= MAX_TEXT_CAPTCHA_ATTEMPTS:
        return handoff_result(
            "capture_captcha",
            challenge,
            f"Basil already tried this CAPTCHA {used} times on {host or 'this site'}. The user must complete it.",
        )

    image_path: Optional[str] = None
    image_source = "page_canvas"
    capture = await run_js(browser, CAPTCHA_CAPTURE_JS, timeout=20.0, window_index=window_index, tab_index=tab_index)
    capture = capture if isinstance(capture, dict) else {}
    if capture.get("success"):
        try:
            image_path = save_captcha_png(str(capture.get("data_url") or ""))
        except ValueError as problem:
            return {"success": False, "action": "capture_captcha", "error": str(problem)}
    elif capture.get("tainted"):
        fallback = await capture_window_fallback(target)
        if not fallback.get("success"):
            return {"success": False, "action": "capture_captcha", "error": fallback.get("error")}
        image_path = str(fallback["image_path"])
        image_source = "window_capture"
    else:
        return {"success": False, "action": "capture_captcha", "error": capture.get("error") or "Could not capture the CAPTCHA image."}

    remember_image(host, image_path)
    return {
        "success": True,
        "action": "capture_captcha",
        "image_path": image_path,
        "image_source": image_source,
        "prompt_on_page": challenge.get("prompt"),
        "attempts_used": used,
        "attempts_remaining": MAX_TEXT_CAPTCHA_ATTEMPTS - used,
        "vision_prompt": VISION_PROMPT,
        "next_step": (
            "Call analyze_with_vision with file_paths=[image_path] and the vision_prompt. If it returns characters, "
            "call browser_interact with action submit_captcha and value set to exactly those characters. "
            "If it returns UNREADABLE, call browser_tabs with action request_human_help."
            + (" The image is a capture of the whole browser window, so read only the CAPTCHA characters." if image_source == "window_capture" else "")
        ),
    }


async def submit_captcha_text(
    perform: Perform,
    run_js: RunJs,
    browser: str,
    value: Optional[str],
    *,
    window_index: Optional[int],
    tab_index: Optional[int],
) -> Dict[str, Any]:
    challenge, host, error = await _detect(run_js, browser, window_index, tab_index)
    if error:
        return {"success": False, "action": "submit_captcha", "error": error}
    if challenge is None:
        return {"success": False, "action": "submit_captcha", "error": "No CAPTCHA is showing on this page."}
    if challenge.get("kind") != "text_image" or challenge.get("handoff_only"):
        return handoff_result(
            "submit_captcha",
            challenge,
            f"This is a {str(challenge.get('kind')).replace('_', ' ')} step that only the user can complete.",
        )
    used = attempts_used(host)
    if used >= MAX_TEXT_CAPTCHA_ATTEMPTS:
        delete_images(host)
        return handoff_result(
            "submit_captcha",
            challenge,
            f"Basil already tried this CAPTCHA {used} times on {host or 'this site'}. The user must complete it.",
        )

    code = (value or "").strip()
    if code.upper() == "UNREADABLE" or not _VALID_CODE.match(code):
        return {
            "success": False,
            "action": "submit_captcha",
            "error": (
                "value must be only the 3 to 12 letters and digits shown in the image. "
                "If you cannot read the image, call browser_tabs with action request_human_help."
            ),
            "attempts_used": used,
            "attempts_remaining": MAX_TEXT_CAPTCHA_ATTEMPTS - used,
        }
    input_selector = challenge.get("input_selector")
    submit_selector = challenge.get("submit_selector")
    if not input_selector or not submit_selector:
        return handoff_result("submit_captcha", challenge, "Basil could not find the CAPTCHA's text box and submit button.")

    fill = await perform("fill", str(input_selector), code)
    if not fill.get("success"):
        return {"success": False, "action": "submit_captcha", "error": fill.get("error") or "Could not type the code.", "step": "fill"}
    attempt_number = record_attempt(host)
    click = await perform("click", str(submit_selector), None)
    delete_images(host)
    if not click.get("success"):
        return {
            "success": False,
            "action": "submit_captcha",
            "error": click.get("error") or "Could not press the submit button.",
            "step": "click",
            "attempts_used": attempt_number,
            "attempts_remaining": max(0, MAX_TEXT_CAPTCHA_ATTEMPTS - attempt_number),
        }

    page = click.get("page") if isinstance(click.get("page"), dict) else {}
    if page:
        challenge_after = page.get("challenge")
    else:
        challenge_after, _host_after, _detect_error = await _detect(run_js, browser, window_index, tab_index)
    still_blocked = isinstance(challenge_after, dict) and challenge_after.get("kind") == "text_image"
    result: Dict[str, Any] = {
        "success": True,
        "action": "submit_captcha",
        "solved": not still_blocked,
        "attempts_used": attempt_number,
        "attempts_remaining": max(0, MAX_TEXT_CAPTCHA_ATTEMPTS - attempt_number),
        "page": page,
        "navigated": bool(click.get("navigated")),
    }
    if not still_blocked:
        reset_attempts(host)
        result["next_step"] = "The CAPTCHA was accepted. Call browser_inspect to continue with the task."
    elif attempt_number >= MAX_TEXT_CAPTCHA_ATTEMPTS:
        result["handoff_required"] = True
        result["next_step"] = (
            "The code was not accepted and the attempts are used up. Call browser_tabs with action "
            "request_human_help so the user can complete it."
        )
    else:
        result["next_step"] = "The code was not accepted and a new image is probably showing. Call capture_captcha again for one more attempt."
    return result
