"""Bring Basil's automation window forward so a person can finish a step, then put the desktop back."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional

from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import CheckpointRequest

from .browser_foreground_policy import authorize_browser_foreground
from .browser_pinned_target import browser_pin_key, pinned_browser_target
from .browser_runtime import run_applescript
from .browser_target_runtime import BrowserAutomationTarget
from .browser_window_capture_target import window_capture_owner_name

logger = logging.getLogger(__name__)

HANDOFF_ACTIONS = frozenset({"reveal_automation_window", "release_automation_window", "request_human_help"})


@dataclass
class RevealState:
    owner_name: str
    window_id: int
    previous_app_name: str
    previous_bundle_id: str


_revealed: Dict[str, RevealState] = {}
_revealed_lock = threading.Lock()


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_reveal_script(owner_name: str, window_id: int) -> str:
    return f'''
set previousName to ""
set previousBundle to ""
try
    tell application "System Events"
        set frontProcess to first application process whose frontmost is true
        set previousName to name of frontProcess
        try
            set previousBundle to (bundle identifier of frontProcess) as text
        end try
    end tell
end try
tell application "{_escape(owner_name)}"
    if not (exists window id {int(window_id)}) then return "error|window_missing"
    activate
    set index of window id {int(window_id)} to 1
end tell
return "ok|" & previousName & "|" & previousBundle
'''


def build_release_script(owner_name: str, previous_app_name: str, previous_bundle_id: str) -> str:
    if previous_bundle_id:
        restore_line = f'tell application id "{_escape(previous_bundle_id)}" to activate'
    else:
        restore_line = f'tell application "{_escape(previous_app_name)}" to activate'
    return f'''
tell application "System Events"
    set frontName to name of first application process whose frontmost is true
end tell
if frontName is not "{_escape(owner_name)}" then return "skipped|user_moved_on"
{restore_line}
return "restored"
'''


def parse_reveal_reply(reply: str) -> tuple[bool, str, str, Optional[str]]:
    """Return `(ok, previous_app_name, previous_bundle_id, error)`."""

    parts = (reply or "").strip().split("|", 2)
    if parts and parts[0] == "error":
        return False, "", "", "The Basil automation window no longer exists. Call browser_tabs with action ensure_automation_window to create it again."
    if len(parts) != 3 or parts[0] != "ok":
        return False, "", "", f"Unexpected reply while bringing the window forward: {(reply or '')[:200]}"
    return True, parts[1].strip(), parts[2].strip(), None


async def reveal_automation_window(
    browser: str,
    target: Optional[BrowserAutomationTarget],
    *,
    purpose: str,
    authorized: bool = False,
) -> Dict[str, Any]:
    """Bring the pinned window to the front when the foreground policy allows it."""

    if target is None or target.window_id is None:
        return {
            "success": False,
            "action": "reveal_automation_window",
            "error": "There is no Basil automation window to bring forward. Call browser_tabs with action ensure_automation_window first.",
        }
    owner_name = window_capture_owner_name(browser)
    if not authorized:
        decision = await authorize_browser_foreground(
            purpose=purpose,
            details=f"Bring the {owner_name} window (id {int(target.window_id)}) to the front.",
            browser=owner_name,
        )
        if not decision.allowed:
            return {"success": False, "action": "reveal_automation_window", "error": decision.message, **decision.to_result()}
    success, stdout, stderr = await run_applescript(build_reveal_script(owner_name, int(target.window_id)), timeout_s=15.0)
    if not success:
        return {"success": False, "action": "reveal_automation_window", "error": (stderr or stdout or "AppleScript failed.")[:300]}
    ok, previous_name, previous_bundle, error = parse_reveal_reply(stdout)
    if not ok:
        return {"success": False, "action": "reveal_automation_window", "error": error}
    if previous_name == owner_name:
        previous_name, previous_bundle = "", ""
    with _revealed_lock:
        _revealed[browser_pin_key() or "no-task"] = RevealState(owner_name, int(target.window_id), previous_name, previous_bundle)
    return {
        "success": True,
        "action": "reveal_automation_window",
        "revealed": True,
        "previous_app": previous_name or None,
        "note": "Call browser_tabs with action release_automation_window when the step is finished, so the previous app is restored.",
    }


async def release_automation_window(browser: str) -> Dict[str, Any]:
    """Restore the app that was frontmost before the reveal, but only if the browser is still frontmost."""

    with _revealed_lock:
        state = _revealed.pop(browser_pin_key() or "no-task", None)
    if state is None:
        return {"success": True, "action": "release_automation_window", "released": False, "note": "Nothing was brought forward, so there is nothing to restore."}
    if not state.previous_app_name and not state.previous_bundle_id:
        return {"success": True, "action": "release_automation_window", "released": False, "note": "The browser was already in front before it was revealed."}
    success, stdout, stderr = await run_applescript(
        build_release_script(state.owner_name, state.previous_app_name, state.previous_bundle_id),
        timeout_s=15.0,
    )
    if not success:
        return {"success": False, "action": "release_automation_window", "error": (stderr or stdout or "AppleScript failed.")[:300]}
    restored = stdout.strip() == "restored"
    return {
        "success": True,
        "action": "release_automation_window",
        "released": restored,
        "restored_app": state.previous_app_name if restored else None,
        "note": "The previous app was restored." if restored else "You had already switched away, so nothing was changed.",
    }


async def request_human_help(browser: str, target: Optional[BrowserAutomationTarget], reason: Optional[str]) -> None:
    """Bring the window forward when allowed, then ask the user to finish the step. Always raises CheckpointRequest."""

    reason_text = (reason or "").strip() or "This step needs you."
    reveal = await reveal_automation_window(browser, target, purpose=f"Hand the page to you: {reason_text[:120]}")
    shown = bool(reveal.get("success"))
    window_name = (target.expected_title if target is not None and target.expected_title else "") or "the Basil browser window"
    if shown:
        prompt = (
            f"I brought the Basil browser window to the front. {reason_text}\n\n"
            "When you have finished, choose **Done, continue**."
        )
    else:
        prompt = (
            f"{reason_text}\n\nI could not bring the browser window forward ({reveal.get('message') or reveal.get('error')}). "
            f"Please switch to the Basil browser window ({window_name}) yourself, finish the step there, "
            "then choose **Done, continue**."
        )
    raise CheckpointRequest({
        "prompt": prompt,
        "input_type": "choice",
        "options": [
            {
                "id": "done",
                "label": "Done, continue",
                "value": "browser_human_help_done",
                "description": "I finished the step in the browser window.",
                "variant": "primary",
            },
            {
                "id": "stop",
                "label": "Stop for now",
                "value": "browser_human_help_stop",
                "description": "Stop this browser task.",
                "variant": "danger",
            },
        ],
        "context_summary": reason_text,
        "metadata": {
            "source": "browser_human_help",
            "browser": browser,
            "reason": reason_text,
            "window_revealed": shown,
            "next_actions": [
                "After the user answers, call browser_inspect and confirm that `challenge` is gone.",
                "Then call browser_tabs with action release_automation_window.",
            ],
        },
    })


async def handle_handoff_action(action: str, *, browser: str, reason: Optional[str]) -> str:
    """Run one of the three handoff actions for the current task's pinned window and return the JSON result."""

    target = pinned_browser_target(browser)
    if action == "request_human_help":
        await request_human_help(browser, target, reason)
    if action == "reveal_automation_window":
        result = await reveal_automation_window(browser, target, purpose=(reason or "Show the Basil browser window.").strip()[:120])
    else:
        result = await release_automation_window(browser)
    result["browser"] = browser
    return json.dumps(result, ensure_ascii=False, indent=2)
