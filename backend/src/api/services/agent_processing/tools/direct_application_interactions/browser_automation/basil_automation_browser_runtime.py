"""Planned Basil-owned background browser runtime.

This module intentionally avoids importing Playwright until the runtime is
enabled as a dependency. It defines the lifecycle contract that browser tools
will dispatch through when ``session_mode='basil_automation_browser'`` becomes
available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class BasilAutomationBrowserProfile:
    """Persistent profile configuration for the app-owned automation browser."""

    profile_dir: Path
    downloads_dir: Path
    screenshots_dir: Path


@dataclass(frozen=True)
class ManualAuthPause:
    """Description of a user-required browser step."""

    reason: str
    url: Optional[str] = None
    title: Optional[str] = None
    next_actions: List[str] = field(default_factory=list)

    def to_checkpoint_metadata(self) -> Dict[str, Any]:
        return {
            "source": "basil_automation_browser_manual_auth",
            "reason": self.reason,
            "url": self.url,
            "title": self.title,
            "next_actions": self.next_actions,
        }


class BasilAutomationBrowserRuntime:
    """Lifecycle contract for the future Playwright Chromium runtime."""

    def __init__(self, profile: BasilAutomationBrowserProfile):
        self.profile = profile

    async def start(self, *, cancel_event: Any = None) -> None:
        """Start Playwright and launch persistent Chromium context."""
        raise NotImplementedError("Basil Automation Browser runtime is not enabled yet.")

    async def stop(self) -> None:
        """Close browser context and Playwright process."""
        raise NotImplementedError("Basil Automation Browser runtime is not enabled yet.")

    async def clear_profile(self) -> None:
        """Clear persistent profile data after explicit user request."""
        raise NotImplementedError("Basil Automation Browser runtime is not enabled yet.")

    async def inspect_page(self, *, focus: str = "all", cancel_event: Any = None) -> Dict[str, Any]:
        """Return DOM metadata compatible with browser_inspect."""
        raise NotImplementedError("Basil Automation Browser runtime is not enabled yet.")

    async def interact_with_page(
        self,
        *,
        action: str,
        selector: str,
        value: Optional[str] = None,
        cancel_event: Any = None,
    ) -> Dict[str, Any]:
        """Run a DOM interaction compatible with browser_interact."""
        raise NotImplementedError("Basil Automation Browser runtime is not enabled yet.")

    async def capture_screenshot(self, *, cancel_event: Any = None) -> Dict[str, Any]:
        """Capture the current automation-browser page to a local image path."""
        raise NotImplementedError("Basil Automation Browser runtime is not enabled yet.")

    async def detect_manual_auth_pause(self) -> Optional[ManualAuthPause]:
        """Detect login, CAPTCHA, passkey, payment, or proof-of-presence blockers."""
        raise NotImplementedError("Basil Automation Browser runtime is not enabled yet.")


def get_default_basil_automation_browser_profile() -> BasilAutomationBrowserProfile:
    """Return the canonical app-owned automation browser profile paths."""
    from api.settings import get_settings

    root_dir = Path(get_settings().data_dir).expanduser() / "browser_automation" / "basil_automation_browser"
    return BasilAutomationBrowserProfile(
        profile_dir=root_dir / "profile",
        downloads_dir=root_dir / "downloads",
        screenshots_dir=root_dir / "screenshots",
    )
