"""Appearance routes for managing appearance and theming settings."""

from typing import List, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from ...core.models.preferences import Preferences
from ...core.models.preference_models.ui_and_capture import (
    CustomAppearanceTheme,
    CustomAppearanceThemeFields,
)
from ...core.models.responses import SettingsResponse, UpdateResponse
from ...core.logging.api_logger import api_logger
# Royal Purple processing-bubble defaults are sourced from the same generated
# module UIPreferences uses, so the API contract and the persisted
# preferences default to identical values. The generator runs as STEP 0 of
# the canonical asset builders and parses the Swift literals in
# AestheticSystem.swift -- never edit these defaults directly.
from ...core.models.generated_processing_colors import (
    DEFAULT_PROCESSING_BASE,
    DEFAULT_PROCESSING_ACCENT,
)
from ...services.appearance_broadcast import broadcast_appearance_update

# Create the appearance router
router = APIRouter(prefix="/appearance", tags=["appearance"])

# Import shared utilities from main settings
def load_preferences() -> Preferences:
    """Load preferences from file or return defaults."""
    from api.core.preferences.preferences_io import load_preferences as _load_preferences
    return _load_preferences()

def save_preferences(preferences: Preferences) -> None:
    """Save preferences to file."""
    from api.core.preferences.preferences_io import save_preferences as _save_preferences
    return _save_preferences(preferences)

# Models
class AppearanceSettings(BaseModel):
    """Model for appearance settings."""
    background_color_red: float = Field(default=0.0709251779736389, description="Background color red component (0.0-1.0)")
    background_color_green: float = Field(default=0.10432000903519285, description="Background color green component (0.0-1.0)")
    background_color_blue: float = Field(default=0.22791699626277573, description="Background color blue component (0.0-1.0)")
    primary_color_red: float = Field(default=0.21100852777444695, description="Primary color red component (0.0-1.0)")
    primary_color_green: float = Field(default=0.4699344845863317, description="Primary color green component (0.0-1.0)")
    primary_color_blue: float = Field(default=0.8893695758678611, description="Primary color blue component (0.0-1.0)")
    secondary_color_red: float = Field(default=0.376, description="Secondary color red component (0.0-1.0)")
    secondary_color_green: float = Field(default=0.647, description="Secondary color green component (0.0-1.0)")
    secondary_color_blue: float = Field(default=0.98, description="Secondary color blue component (0.0-1.0)")
    text_color_red: float = Field(default=0.9699399998499855, description="Text color red component (0.0-1.0)")
    text_color_green: float = Field(default=0.9902393003857255, description="Text color green component (0.0-1.0)")
    text_color_blue: float = Field(default=1.0, description="Text color blue component (0.0-1.0)")
    surface_finish: Literal["flat", "metal"] = Field(
        default="flat",
        description="Surface finish rendered by web-hosted panels: 'flat' (solid colors) or 'metal' (brushed-metal gradient and texture sheen layered over the active palette).",
    )

    # Processing bubble colors. Mirror UIPreferences so the API contract
    # exposes the same configurable Royal Purple pair used by AssistantSession/
    # AgentTask/Transcription "thinking" bubbles. Defaults are sourced from
    # the generated module above (currently #7C3AED / #DDD6FE).
    processing_color_red: float = Field(default=DEFAULT_PROCESSING_BASE[0], description="Processing bubble base red component (0.0-1.0)")
    processing_color_green: float = Field(default=DEFAULT_PROCESSING_BASE[1], description="Processing bubble base green component (0.0-1.0)")
    processing_color_blue: float = Field(default=DEFAULT_PROCESSING_BASE[2], description="Processing bubble base blue component (0.0-1.0)")
    processing_accent_color_red: float = Field(default=DEFAULT_PROCESSING_ACCENT[0], description="Processing bubble accent red component (0.0-1.0)")
    processing_accent_color_green: float = Field(default=DEFAULT_PROCESSING_ACCENT[1], description="Processing bubble accent green component (0.0-1.0)")
    processing_accent_color_blue: float = Field(default=DEFAULT_PROCESSING_ACCENT[2], description="Processing bubble accent blue component (0.0-1.0)")

    preferred_font: str = Field(default="Helvetica-Light", description="Preferred font family")

# Endpoints

@router.get("", response_model=SettingsResponse[AppearanceSettings])
async def get_appearance_settings() -> SettingsResponse[AppearanceSettings]:
    """Get current appearance settings."""
    try:
        preferences = load_preferences()
        settings = AppearanceSettings(
            background_color_red=preferences.ui.background_color_red,
            background_color_green=preferences.ui.background_color_green,
            background_color_blue=preferences.ui.background_color_blue,
            primary_color_red=preferences.ui.primary_color_red,
            primary_color_green=preferences.ui.primary_color_green,
            primary_color_blue=preferences.ui.primary_color_blue,
            secondary_color_red=preferences.ui.secondary_color_red,
            secondary_color_green=preferences.ui.secondary_color_green,
            secondary_color_blue=preferences.ui.secondary_color_blue,
            text_color_red=preferences.ui.text_color_red,
            text_color_green=preferences.ui.text_color_green,
            text_color_blue=preferences.ui.text_color_blue,
            surface_finish=preferences.ui.surface_finish,
            processing_color_red=preferences.ui.processing_color_red,
            processing_color_green=preferences.ui.processing_color_green,
            processing_color_blue=preferences.ui.processing_color_blue,
            processing_accent_color_red=preferences.ui.processing_accent_color_red,
            processing_accent_color_green=preferences.ui.processing_accent_color_green,
            processing_accent_color_blue=preferences.ui.processing_accent_color_blue,
            preferred_font=preferences.ui.preferred_font
        )
        return SettingsResponse(settings=settings)
    except Exception as e:
        api_logger.error(f"❌ Error getting appearance settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.put("", response_model=UpdateResponse[AppearanceSettings])
async def update_appearance_settings(settings: AppearanceSettings) -> UpdateResponse[AppearanceSettings]:
    """Update appearance settings."""
    try:
        api_logger.debug("🎨 Received appearance settings update request")
        api_logger.debug(f"🎨 Raw settings data: {settings.model_dump()}")
        
        preferences = load_preferences()
        
        # Update appearance settings in UI preferences
        preferences.ui.background_color_red = settings.background_color_red
        preferences.ui.background_color_green = settings.background_color_green
        preferences.ui.background_color_blue = settings.background_color_blue
        preferences.ui.primary_color_red = settings.primary_color_red
        preferences.ui.primary_color_green = settings.primary_color_green
        preferences.ui.primary_color_blue = settings.primary_color_blue
        preferences.ui.secondary_color_red = settings.secondary_color_red
        preferences.ui.secondary_color_green = settings.secondary_color_green
        preferences.ui.secondary_color_blue = settings.secondary_color_blue
        preferences.ui.text_color_red = settings.text_color_red
        preferences.ui.text_color_green = settings.text_color_green
        preferences.ui.text_color_blue = settings.text_color_blue
        preferences.ui.surface_finish = settings.surface_finish
        preferences.ui.processing_color_red = settings.processing_color_red
        preferences.ui.processing_color_green = settings.processing_color_green
        preferences.ui.processing_color_blue = settings.processing_color_blue
        preferences.ui.processing_accent_color_red = settings.processing_accent_color_red
        preferences.ui.processing_accent_color_green = settings.processing_accent_color_green
        preferences.ui.processing_accent_color_blue = settings.processing_accent_color_blue
        preferences.ui.preferred_font = settings.preferred_font
        
        save_preferences(preferences)
        await broadcast_appearance_update(settings.model_dump())
        
        return UpdateResponse(
            status="updated",
            updated_settings=settings,
            message="Appearance settings updated successfully"
        )
    except Exception as e:
        api_logger.error(f"❌ Error updating appearance settings: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


MAX_CUSTOM_APPEARANCE_THEMES = 24
MAX_CUSTOM_APPEARANCE_THEME_NAME_LENGTH = 40


class CustomAppearanceThemeCreate(CustomAppearanceThemeFields):
    """Request body for saving the on-screen palette and finish as a named theme."""
    name: str = Field(min_length=1, max_length=MAX_CUSTOM_APPEARANCE_THEME_NAME_LENGTH)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CustomAppearanceThemesResponse(BaseModel):
    """Every saved custom theme, in creation order."""
    themes: List[CustomAppearanceTheme]


@router.get("/themes", response_model=CustomAppearanceThemesResponse)
async def list_custom_appearance_themes() -> CustomAppearanceThemesResponse:
    """List the user's saved custom Appearance themes."""
    try:
        preferences = load_preferences()
        return CustomAppearanceThemesResponse(themes=preferences.ui.custom_appearance_themes)
    except Exception as e:
        api_logger.error(f"❌ Error listing custom appearance themes: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/themes", response_model=CustomAppearanceThemesResponse)
async def create_custom_appearance_theme(theme: CustomAppearanceThemeCreate) -> CustomAppearanceThemesResponse:
    """Save a named custom theme without changing the active appearance. Responds 409 for a duplicate name and 400 when the theme limit is reached."""
    try:
        preferences = load_preferences()
        themes = list(preferences.ui.custom_appearance_themes)
        if any(existing.name.casefold() == theme.name.casefold() for existing in themes):
            raise HTTPException(status_code=409, detail="A custom theme with that name already exists.")
        if len(themes) >= MAX_CUSTOM_APPEARANCE_THEMES:
            raise HTTPException(status_code=400, detail=f"You can save up to {MAX_CUSTOM_APPEARANCE_THEMES} custom themes.")
        themes.append(CustomAppearanceTheme(id=f"custom-{uuid4().hex}", **theme.model_dump()))
        preferences.ui.custom_appearance_themes = themes
        save_preferences(preferences)
        return CustomAppearanceThemesResponse(themes=themes)
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ Error saving custom appearance theme: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/themes/{theme_id}", response_model=CustomAppearanceThemesResponse)
async def delete_custom_appearance_theme(theme_id: str) -> CustomAppearanceThemesResponse:
    """Delete one custom theme without changing the active appearance. Responds 404 when the theme does not exist."""
    try:
        preferences = load_preferences()
        existing_themes = preferences.ui.custom_appearance_themes
        themes = [theme for theme in existing_themes if theme.id != theme_id]
        if len(themes) == len(existing_themes):
            raise HTTPException(status_code=404, detail="Custom theme not found.")
        preferences.ui.custom_appearance_themes = themes
        save_preferences(preferences)
        return CustomAppearanceThemesResponse(themes=themes)
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ Error deleting custom appearance theme: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

