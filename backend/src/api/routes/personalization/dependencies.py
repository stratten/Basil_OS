"""Shared dependencies for personalization routes."""

from api.core.knowledge.personalization_service import PersonalizationService


def get_personalization_service() -> PersonalizationService:
    """Dependency to get personalization service instance."""
    return PersonalizationService()
