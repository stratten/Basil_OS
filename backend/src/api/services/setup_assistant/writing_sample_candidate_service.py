"""Writing sample candidate helpers for setup assistant onboarding."""

from __future__ import annotations

from typing import Dict


class SetupAssistantWritingSampleCandidateService:
    """Describe bounded writing-sample collection rules for Basil."""

    def build_sent_email_collection_contract(self) -> Dict[str, str]:
        """Return the high-trust collection contract for sent email samples."""

        return {
            "source": "sent_email",
            "default_window": "last_14_days",
            "review_mode": "excerpt_first",
            "approval_required": "true",
        }

