"""Profile prepopulation helpers for setup assistant recommendations."""

from __future__ import annotations

from typing import Dict, List


class SetupAssistantProfilePrepopulationService:
    """Expose editable personalization fields to Basil's setup flow."""

    def build_editable_profile_field_contract(self) -> List[Dict[str, str]]:
        """Return the initial profile fields Basil may propose updating."""

        return [
            {"field": "full_name", "label": "Full name"},
            {"field": "preferred_name", "label": "Preferred name"},
            {"field": "email", "label": "Email"},
            {"field": "job_title", "label": "Job title"},
            {"field": "company_name", "label": "Company"},
            {"field": "industry", "label": "Industry"},
            {"field": "default_formality", "label": "Default formality"},
            {"field": "default_tone", "label": "Default tone"},
        ]

