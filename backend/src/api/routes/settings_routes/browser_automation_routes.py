"""Browser automation settings routes."""

import shutil
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...core.logging.api_logger import api_logger
from ...core.models.preferences import (
    BrowserAutomationSessionMode,
    BrowserAutomationSettings,
    BrowserForegroundControlPolicy,
    BrowserPreferredUserBrowser,
    BrowserSensitiveFillPolicy,
    Preferences,
)
from ...core.models.responses import SettingsResponse, StatusResponse, UpdateResponse

router = APIRouter(prefix="/browser-automation", tags=["browser-automation"])


def load_preferences() -> Preferences:
    """Load preferences from file or return defaults."""
    from api.core.preferences.preferences_io import load_preferences as _load_preferences
    return _load_preferences()


def save_preferences(preferences: Preferences) -> None:
    """Save preferences to file."""
    from api.core.preferences.preferences_io import save_preferences as _save_preferences
    return _save_preferences(preferences)


class BrowserAutomationSettingsUpdate(BaseModel):
    sensitive_fill_policy: Optional[BrowserSensitiveFillPolicy] = None
    foreground_control_policy: Optional[BrowserForegroundControlPolicy] = None
    default_session_mode: Optional[BrowserAutomationSessionMode] = None
    preferred_user_browser: Optional[BrowserPreferredUserBrowser] = None
    show_action_highlights: Optional[bool] = None
    record_browser_action_trace: Optional[bool] = None
    allow_visual_fallback: Optional[bool] = None


class BrowserSensitiveValueApprovalRequest(BaseModel):
    approval_id: str
    approved: bool
    remember_domain: bool = False
    sensitive_value: Optional[str] = None


@router.get("", response_model=SettingsResponse[BrowserAutomationSettings])
async def get_browser_automation_settings() -> SettingsResponse[BrowserAutomationSettings]:
    """Get current browser automation settings."""
    try:
        preferences = load_preferences()
        return SettingsResponse(settings=preferences.browser_automation)
    except Exception as e:
        api_logger.error(f"Error getting browser automation settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("", response_model=UpdateResponse[BrowserAutomationSettings])
async def update_browser_automation_settings(
    settings: BrowserAutomationSettingsUpdate,
) -> UpdateResponse[BrowserAutomationSettings]:
    """Update browser automation settings."""
    try:
        preferences = load_preferences()
        current = preferences.browser_automation

        updates = settings.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(current, field, value)

        save_preferences(preferences)

        return UpdateResponse(
            status="updated",
            updated_settings=current,
            message="Browser automation settings updated successfully",
        )
    except Exception as e:
        api_logger.error(f"Error updating browser automation settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sensitive-domains/{domain}", response_model=StatusResponse)
async def delete_browser_sensitive_domain_approval(domain: str) -> StatusResponse:
    """Remove a remembered sensitive-fill domain approval."""
    try:
        preferences = load_preferences()
        current = preferences.browser_automation
        before_count = len(current.approved_sensitive_fill_domains)
        current.approved_sensitive_fill_domains = [
            approval
            for approval in current.approved_sensitive_fill_domains
            if approval.domain != domain
        ]
        save_preferences(preferences)

        if len(current.approved_sensitive_fill_domains) == before_count:
            return StatusResponse(
                status="success",
                message=f"No browser sensitive-fill approval found for {domain}",
            )

        return StatusResponse(
            status="success",
            message=f"Removed browser sensitive-fill approval for {domain}",
        )
    except Exception as e:
        api_logger.error(f"Error deleting browser sensitive-fill domain approval: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/automation-browser-profile/clear", response_model=StatusResponse)
async def clear_basil_automation_browser_profile() -> StatusResponse:
    """Clear the app-owned Basil Automation Browser profile."""
    try:
        from api.services.agent_processing.tools.direct_application_interactions.browser_automation.basil_automation_browser_runtime import (
            get_default_basil_automation_browser_profile,
        )

        profile = get_default_basil_automation_browser_profile()
        if profile.profile_dir.exists():
            shutil.rmtree(profile.profile_dir)
        return StatusResponse(
            status="success",
            message="Basil Automation Browser profile cleared",
        )
    except Exception as e:
        api_logger.error(f"Error clearing Basil Automation Browser profile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sensitive-value/approve", response_model=StatusResponse)
async def approve_browser_sensitive_value(
    request: BrowserSensitiveValueApprovalRequest,
) -> StatusResponse:
    """Resolve a browser sensitive-fill approval and optionally store a one-time value."""
    try:
        from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_sensitive_approval import (
            BrowserSensitiveApprovalManager,
        )

        resolved = await BrowserSensitiveApprovalManager.resolve_browser_sensitive_fill_approval(
            approval_id=request.approval_id,
            approved=request.approved,
            remember_domain=request.remember_domain,
            sensitive_value=request.sensitive_value,
        )
        if not resolved:
            raise HTTPException(status_code=404, detail="Approval request not found or already resolved")

        return StatusResponse(
            status="success",
            message="Browser sensitive-fill approval processed",
        )
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"Error processing browser sensitive-fill approval: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

