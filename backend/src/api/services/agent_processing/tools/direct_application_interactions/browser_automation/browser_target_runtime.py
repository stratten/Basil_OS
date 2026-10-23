"""Browser target helpers for user-browser automation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional

from api.core.models.preference_models.browser_automation import (
    BrowserPreferredUserBrowser,
)

from .browser_pinned_target import pin_browser_target, pinned_browser_target


@dataclass(frozen=True)
class BrowserAutomationTarget:
    """Specific browser tab Basil should continue to use for a task."""

    browser: str
    window_index: int = 1
    tab_index: int = 1
    expected_url: Optional[str] = None
    expected_title: Optional[str] = None
    created_by_basil: bool = False
    agent_task_id: Optional[str] = None
    window_id: Optional[int] = None

    def to_result(self) -> dict[str, Any]:
        return asdict(self)


def normalize_browser_name(browser: str) -> str:
    """Return the browser label accepted by AppleScript browser tools."""

    normalized = (browser or "").strip().lower()
    if normalized in {"chrome", "google chrome"}:
        return "Chrome"
    if normalized in {"edge", "microsoft edge"}:
        return "Edge"
    if normalized == "safari":
        return "Safari"
    raise ValueError(f"Unsupported browser: {browser}. Use 'Safari', 'Chrome', or 'Edge'.")


def parse_browser_automation_target(value: Any) -> Optional[BrowserAutomationTarget]:
    """Parse a JSON-like target payload from model/tool input."""

    if isinstance(value, BrowserAutomationTarget):
        return value
    if not isinstance(value, Mapping):
        return None
    browser = value.get("browser")
    if not browser:
        return None
    try:
        return BrowserAutomationTarget(
            browser=normalize_browser_name(str(browser)),
            window_index=int(value.get("window_index") or 1),
            tab_index=int(value.get("tab_index") or 1),
            expected_url=str(value["expected_url"]) if value.get("expected_url") else (
                str(value["url"]) if value.get("url") else None
            ),
            expected_title=str(value["expected_title"]) if value.get("expected_title") else (
                str(value["title"]) if value.get("title") else None
            ),
            created_by_basil=bool(value.get("created_by_basil")),
            agent_task_id=str(value["agent_task_id"]) if value.get("agent_task_id") else None,
            window_id=int(value["window_id"]) if value.get("window_id") else None,
        )
    except Exception:
        return None


def resolve_browser_target_inputs(
    *,
    browser: Optional[str],
    window_index: Optional[int] = None,
    tab_index: Optional[int] = None,
    browser_automation_target: Any = None,
) -> tuple[Optional[str], Optional[int], Optional[int], Optional[BrowserAutomationTarget]]:
    """Resolve browser/window/tab inputs while preserving backwards compatibility."""

    target = parse_browser_automation_target(browser_automation_target)
    if target is not None and target.window_id is not None:
        pin_browser_target(target)
    if target is None and window_index is None and tab_index is None:
        target = pinned_browser_target(browser)
    resolved_browser = browser
    resolved_window_index = window_index
    resolved_tab_index = tab_index
    if target is not None:
        resolved_browser = target.browser
        resolved_window_index = target.window_index
        resolved_tab_index = target.tab_index
    return resolved_browser, resolved_window_index, resolved_tab_index, target


async def resolve_preferred_user_browser() -> str:
    """Resolve the configured user-browser preference with system-default fallback."""

    try:
        from api.core.preferences.preferences_io import load_preferences

        preference = load_preferences().browser_automation.preferred_user_browser
        if preference == BrowserPreferredUserBrowser.CHROME:
            return "Chrome"
        if preference == BrowserPreferredUserBrowser.EDGE:
            return "Edge"
        if preference == BrowserPreferredUserBrowser.SAFARI:
            return "Safari"
    except Exception:
        pass

    from .browser_runtime import get_default_browser

    return await get_default_browser()
