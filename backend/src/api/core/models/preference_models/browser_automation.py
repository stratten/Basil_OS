"""Browser automation preference models."""

from datetime import datetime
from enum import Enum
from typing import List

from pydantic import BaseModel, Field


class BrowserSensitiveFillPolicy(str, Enum):
    """Policy for filling sensitive browser form fields."""

    NEVER = "never"
    ASK_EVERY_TIME = "ask_every_time"
    APPROVED_DOMAINS = "approved_domains"


class BrowserForegroundControlPolicy(str, Enum):
    """Policy for browser automation that needs foreground keyboard or mouse control."""

    BACKGROUND_ONLY = "background_only"
    ASK_BEFORE_FOREGROUND = "ask_before_foreground"
    ALLOW_FOREGROUND_WHEN_NEEDED = "allow_foreground_when_needed"


class BrowserAutomationSessionMode(str, Enum):
    """Default browser runtime mode for automation tools."""

    USER_BROWSER = "user_browser"
    BASIL_AUTOMATION_BROWSER = "basil_automation_browser"


class BrowserPreferredUserBrowser(str, Enum):
    """Preferred AppleScript-controllable browser for user-browser automation."""

    SYSTEM_DEFAULT = "system_default"
    CHROME = "chrome"
    EDGE = "edge"
    SAFARI = "safari"


class BrowserDomainApproval(BaseModel):
    """Remembered browser sensitive-fill approval for an exact domain."""

    domain: str
    created_at: datetime = Field(default_factory=datetime.now)
    last_used: datetime = Field(default_factory=datetime.now)
    use_count: int = 0
    allow_sensitive_fill: bool = True


class BrowserAutomationSettings(BaseModel):
    """Settings for browser automation visibility and sensitive-fill behavior."""

    sensitive_fill_policy: BrowserSensitiveFillPolicy = BrowserSensitiveFillPolicy.NEVER
    foreground_control_policy: BrowserForegroundControlPolicy = (
        BrowserForegroundControlPolicy.ASK_BEFORE_FOREGROUND
    )
    default_session_mode: BrowserAutomationSessionMode = BrowserAutomationSessionMode.USER_BROWSER
    preferred_user_browser: BrowserPreferredUserBrowser = BrowserPreferredUserBrowser.SYSTEM_DEFAULT
    approved_sensitive_fill_domains: List[BrowserDomainApproval] = Field(default_factory=list)
    show_action_highlights: bool = True
    record_browser_action_trace: bool = True
    allow_visual_fallback: bool = True

