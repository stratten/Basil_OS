"""Persists interaction preferences into the user profile's standing instructions."""

from __future__ import annotations

from api.services.setup_assistant.interaction_preferences import merge_interaction_preferences


async def save_interaction_preferences(preferences_text: str) -> None:
    """Replace the managed interaction-preferences block in the profile's custom instructions, keeping every other profile field and any text the user wrote.

    Raises ValueError for empty or oversized preferences.
    """
    # Imported here so the personalization service is resolved when saving, not when this module loads.
    from api.core.knowledge.personalization_models import UserProfileCreate
    from api.core.knowledge.personalization_service import PersonalizationService

    personalization = PersonalizationService()
    existing = await personalization.get_user_profile()
    merged = merge_interaction_preferences(existing.custom_instructions if existing else None, preferences_text)
    profile_data = UserProfileCreate(
        full_name=existing.full_name if existing else None,
        preferred_name=existing.preferred_name if existing else None,
        email=existing.email if existing else None,
        job_title=existing.job_title if existing else None,
        company_name=existing.company_name if existing else None,
        industry=existing.industry if existing else None,
        default_formality=existing.default_formality if existing else None,
        default_tone=existing.default_tone if existing else None,
        custom_instructions=merged,
    )
    await personalization.create_or_update_user_profile(profile_data)
