"""Send a few allow-listed navigation keys to Basil's browser window for choices DOM tools cannot reach."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Literal, Optional, Tuple

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile
from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import CheckpointRequest

from .browser_foreground_policy import authorize_browser_foreground
from .browser_pinned_target import pinned_browser_target
from .browser_runtime import build_browser_applescript, run_applescript
from .browser_target_runtime import resolve_browser_target_inputs, resolve_preferred_user_browser
from .browser_trace import record_browser_trace
from .browser_window_capture_target import window_capture_owner_name
from .browser_window_handoff import release_automation_window, reveal_automation_window

logger = logging.getLogger(__name__)

KEY_CODES = {"tab": 48, "return": 36, "escape": 53, "space": 49, "left": 123, "right": 124, "down": 125, "up": 126}
ALLOWED_KEYS = tuple(KEY_CODES) + ("shift_tab",)
MAX_TOTAL_PRESSES = 20
KEY_DELAY_S = 0.12
_sleep = asyncio.sleep

KeyName = Literal["tab", "shift_tab", "up", "down", "left", "right", "return", "escape", "space"]


class NativeKeyStep(BaseModel):
    key: KeyName = Field(description="One allow-listed key. No text can be typed.")
    count: int = Field(default=1, ge=1, le=10, description="How many times to press it.")


class BrowserNativeInputInput(BaseModel):
    """Input schema for browser_native_input."""

    purpose: str = Field(
        min_length=8,
        description="One plain sentence saying what this keyboard input does. It is shown to the user in the approval card.",
    )
    steps: List[NativeKeyStep] = Field(min_length=1, max_length=8, description="The key presses to send, in order.")
    focus_selector: Optional[str] = Field(
        default=None,
        description="Optional CSS selector to focus first, for example the iframe that holds a saved-card dropdown.",
    )
    browser: Optional[str] = Field(default=None, description="Browser name, or empty to use the pinned automation window's browser.")
    browser_automation_target: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured target returned by browser_tabs.ensure_automation_window.",
    )


def normalize_steps(steps: Any) -> Tuple[List[Tuple[str, int]], Optional[str]]:
    """Return `(steps, error)` after checking every key against the allow list and the total against the cap."""

    normalized: List[Tuple[str, int]] = []
    total = 0
    for item in steps or []:
        key = item.get("key") if isinstance(item, dict) else getattr(item, "key", None)
        count = item.get("count", 1) if isinstance(item, dict) else getattr(item, "count", 1)
        if key not in ALLOWED_KEYS:
            return [], f"Key '{key}' is not allowed. Allowed keys: {', '.join(ALLOWED_KEYS)}."
        try:
            count = int(count)
        except (TypeError, ValueError):
            return [], "Each step's count must be a whole number."
        if count < 1:
            return [], "Each step's count must be at least 1."
        total += count
        normalized.append((str(key), count))
    if not normalized:
        return [], "browser_native_input requires at least one step."
    if total > MAX_TOTAL_PRESSES:
        return [], f"At most {MAX_TOTAL_PRESSES} key presses are allowed per call; this call asked for {total}."
    return normalized, None


def build_key_script(owner_name: str, steps: List[Tuple[str, int]]) -> str:
    lines: List[str] = []
    for key, count in steps:
        for _ in range(count):
            lines.append("    key code 48 using shift down" if key == "shift_tab" else f"    key code {KEY_CODES[key]}")
            lines.append(f"    delay {KEY_DELAY_S}")
    body = "\n".join(lines)
    escaped_owner = owner_name.replace("\\", "\\\\").replace('"', '\\"')
    return f'''
tell application "System Events"
    set frontName to name of first application process whose frontmost is true
    if frontName is not "{escaped_owner}" then return "error|focus_lost|" & frontName
{body}
end tell
return "ok"
'''


ACCESSIBILITY_PROBE_SCRIPT = 'tell application "System Events" to return UI elements enabled'

_FOCUS_JS_TEMPLATE = r'''// basil:native_focus
(function() {
    var el = null;
    try { el = document.querySelector(__SELECTOR__); } catch (error) { el = null; }
    if (!el) return JSON.stringify({success: false, error: 'focus_selector matched no element.'});
    if (typeof el.scrollIntoView === 'function') el.scrollIntoView({block: 'center'});
    el.focus();
    return JSON.stringify({success: true, focused: document.activeElement === el});
})();
'''


def _accessibility_blocker() -> Dict[str, Any]:
    return {
        "success": False,
        "action": "native_input",
        "requires_user_input": True,
        "accessibility_blocked": True,
        "error": (
            "macOS has not allowed Basil to send keystrokes. Open System Settings, then Privacy and Security, then "
            "Accessibility, enable the app that runs Basil's backend, and try again."
        ),
    }


async def _focus_selector(browser: str, selector: str, window_index: Optional[int], tab_index: Optional[int]) -> Dict[str, Any]:
    js = _FOCUS_JS_TEMPLATE.replace("__SELECTOR__", json.dumps(selector))
    success, stdout, stderr = await run_applescript(
        build_browser_applescript(browser, js, window_index=window_index, tab_index=tab_index),
        timeout_s=15.0,
    )
    if not success:
        return {"success": False, "error": (stderr or stdout or "Could not focus the element.")[:300]}
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return {"success": False, "error": "Could not focus the element: the page did not answer."}
    return parsed if isinstance(parsed, dict) else {"success": False, "error": "Could not focus the element."}


async def _browser_native_input_impl(
    purpose: str = "",
    steps: Optional[List[Any]] = None,
    focus_selector: Optional[str] = None,
    browser: Optional[str] = None,
    browser_automation_target: Optional[Dict[str, Any]] = None,
) -> str:
    try:
        if len((purpose or "").strip()) < 8:
            return json.dumps({"success": False, "action": "native_input", "error": "browser_native_input requires a 'purpose' sentence."})
        normalized, step_error = normalize_steps(steps)
        if step_error:
            return json.dumps({"success": False, "action": "native_input", "error": step_error})

        browser, window_index, tab_index, target = resolve_browser_target_inputs(
            browser=browser,
            browser_automation_target=browser_automation_target,
        )
        if browser is None or not browser.strip():
            browser = await resolve_preferred_user_browser()
        if target is None:
            target = pinned_browser_target(browser)
        if target is None or target.window_id is None:
            return json.dumps({
                "success": False,
                "action": "native_input",
                "error": "Native input only works on Basil's own automation window. Call browser_tabs with action ensure_automation_window first.",
            })
        owner_name = window_capture_owner_name(browser)
        key_summary = ", ".join(f"{key} x{count}" for key, count in normalized)

        decision = await authorize_browser_foreground(
            purpose=purpose.strip()[:160],
            details=f"Send these keys to the {owner_name} window: {key_summary}" + (f" after focusing {focus_selector}" if focus_selector else ""),
            browser=owner_name,
        )
        if not decision.allowed:
            return json.dumps({
                "success": False,
                "action": "native_input",
                "error": decision.message,
                "next_step": "Tell the user which window to use and what to choose, or call browser_tabs with action request_human_help.",
                **decision.to_result(),
            }, ensure_ascii=False)

        probe_ok, probe_out, _probe_err = await run_applescript(ACCESSIBILITY_PROBE_SCRIPT, timeout_s=10.0)
        if probe_ok and probe_out.strip().lower() == "false":
            return json.dumps(_accessibility_blocker(), ensure_ascii=False)

        reveal = await reveal_automation_window(browser, target, purpose=purpose.strip()[:120], authorized=True)
        if not reveal.get("success"):
            return json.dumps(reveal, ensure_ascii=False)
        result: Dict[str, Any]
        try:
            await _sleep(0.4)
            if focus_selector and focus_selector.strip():
                focus = await _focus_selector(browser, focus_selector.strip(), window_index, tab_index)
                if not focus.get("success"):
                    result = {"success": False, "action": "native_input", "error": focus.get("error")}
                    return json.dumps(result, ensure_ascii=False)
                await _sleep(0.2)
            sent, stdout, stderr = await run_applescript(build_key_script(owner_name, normalized), timeout_s=30.0)
            blob = f"{stderr} {stdout}".lower()
            if not sent and ("not allowed to send keystrokes" in blob or "(1002)" in blob or "assistive" in blob):
                result = _accessibility_blocker()
            elif not sent:
                result = {"success": False, "action": "native_input", "error": (stderr or stdout or "Sending keys failed.")[:300]}
            elif stdout.strip().startswith("error|focus_lost"):
                result = {
                    "success": False,
                    "action": "native_input",
                    "error": "The browser was no longer in front, so no keys were sent.",
                }
            else:
                result = {
                    "success": True,
                    "action": "native_input",
                    "purpose": purpose.strip(),
                    "keys_sent": sum(count for _key, count in normalized),
                    "steps": [{"key": key, "count": count} for key, count in normalized],
                    "next_step": (
                        "Call browser_screenshot with the same browser_automation_target to confirm the page shows the "
                        "choice you intended. Do not read card numbers, and do not press Submit or Pay, unless the user "
                        "explicitly told you to."
                    ),
                }
        finally:
            released = await release_automation_window(browser)
        result["restored_previous_app"] = bool(released.get("released"))
        result["browser"] = browser
        record_browser_trace(
            action="native_input",
            browser=browser,
            success=bool(result.get("success")),
            warning=result.get("error"),
            metadata={"key_summary": key_summary, "purpose": purpose.strip()[:120]},
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
    except ValueError as error:
        return json.dumps({"success": False, "action": "native_input", "error": str(error)}, ensure_ascii=False)
    except CheckpointRequest:
        raise
    except Exception as error:
        logger.error("Browser native input failed: %s", error, exc_info=True)
        return json.dumps({"success": False, "action": "native_input", "error": f"Native input failed: {error}"}, ensure_ascii=False)


SLIM_DESCRIPTION = (
    "Send a few navigation keys (tab, shift_tab, up, down, left, right, return, escape, space; never text) to Basil's "
    "own browser window, for a choice that browser_inspect and browser_interact cannot reach, such as a saved-card "
    "dropdown inside a frame from another site (browser_inspect reports it in `frame_notice`). Needs a purpose sentence "
    "and steps=[{key, count}], optionally focus_selector for the frame. It follows the user's foreground policy and may "
    "ask for approval. Afterward verify with browser_screenshot. Never read card numbers, and never press Submit or Pay "
    "unless the user explicitly told you to."
)

_FULL_DESCRIPTION = """Send a few allow-listed navigation keys to Basil's automation window.

Use this only for a choice that DOM tools cannot reach: browser_inspect reports a `frame_notice` for a frame from another site (for example a payment form's saved-card dropdown), and a screenshot shows the choice is waiting. It never types text and never reads the page.

Arguments:
- purpose: one plain sentence saying what the keys do. The user sees it in the approval card.
- steps: a list of {key, count}. Keys: tab, shift_tab, up, down, left, right, return, escape, space. At most 20 presses per call.
- focus_selector (optional): a CSS selector to focus first, such as the iframe element.

Behavior: it follows the user's foreground policy (blocked under Background only, an approval card under Ask before foreground, allowed under Allow foreground when needed). It brings Basil's window to the front, optionally focuses the element, checks that the browser is in front, sends the keys, and then restores the app that was in front before. It only works on Basil's own pinned automation window.

After it succeeds, call browser_screenshot with the same browser_automation_target and look at the result. Never read card numbers, and never press Submit or Pay unless the user explicitly told you to. If it reports foreground_blocked or accessibility_blocked, tell the user exactly what to do instead.
"""


def create_browser_native_input_tool(profile=None) -> StructuredTool:
    tool_description = select_description_for_profile(profile, _FULL_DESCRIPTION, SLIM_DESCRIPTION)
    return StructuredTool.from_function(
        func=_browser_native_input_impl,
        name="browser_native_input",
        description=tool_description,
        args_schema=BrowserNativeInputInput,
        coroutine=_browser_native_input_impl,
    )
