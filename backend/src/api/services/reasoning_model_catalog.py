"""Which reasoning models the user can run right now: the same list the model pickers show.

Installed local reasoning models plus the API and custom reasoning models the user has enabled. Callers that accept a
model id from the user, or replay a saved one later (scheduled tasks), check it here instead of finding out when a run fails.
"""

from __future__ import annotations


def _model_id(model: object) -> str:
    value = model.get("id") if isinstance(model, dict) else getattr(model, "id", "")
    return str(value or "")


async def available_reasoning_model_ids() -> frozenset[str]:
    """Ids of every reasoning model that is installed or enabled right now."""
    from api.core.services.model_service import get_model_service
    from api.routes.settings_routes.api_models.reasoning_routes import get_api_reasoning_models

    response = await get_api_reasoning_models(get_model_service())
    return frozenset(model_id for model_id in (_model_id(model) for model in response.models) if model_id)


async def is_reasoning_model_available(model_id: str) -> bool:
    chosen = (model_id or "").strip()
    return bool(chosen) and chosen in await available_reasoning_model_ids()
