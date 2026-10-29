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


def _field(model: object, name: str) -> object:
    return model.get(name) if isinstance(model, dict) else getattr(model, name, None)


def choose_effective_reasoning_model_id(stored_model_id: str, models: list, use_api_models: bool) -> str:
    """The reasoning model that will really run: the stored choice when it is available, otherwise the first picker entry.

    ``models`` is the picker list (installed local models, then enabled API and custom models, in picker order). A stored id that is not in
    that list, such as the local default on a machine that never installed it, would otherwise be shown as one model and used as another.
    The first entry of the kind the user selected wins, then any entry. With nothing available the stored id is returned unchanged.
    """
    ids = [str(_field(model, "id") or "") for model in models]
    if stored_model_id and stored_model_id in ids:
        return stored_model_id
    for model, model_id in zip(models, ids):
        if model_id and bool(_field(model, "is_api_model")) == bool(use_api_models):
            return model_id
    for model_id in ids:
        if model_id:
            return model_id
    return stored_model_id


def reconcile_stored_reasoning_model(preferences, models: list) -> str:
    """Save the effective reasoning model over an unavailable stored one and return the effective id.

    A deliberate choice that is still available is never changed. A save failure never propagates because callers are read paths.
    """
    stored = preferences.models.reasoning_model
    effective = choose_effective_reasoning_model_id(stored, models, preferences.models.use_api_models)
    if effective and effective != stored:
        try:
            from api.core.preferences.preferences_io import save_preferences

            preferences.models.reasoning_model = effective
            save_preferences(preferences)
        except Exception:
            import logging

            logging.getLogger(__name__).warning("Could not save the reconciled reasoning model", exc_info=True)
    return effective


async def heal_stored_reasoning_model() -> str | None:
    """Reconcile the stored reasoning model with what is available now and return the effective id (None if it cannot be determined)."""
    try:
        from api.core.services.model_service import get_model_service
        from api.routes.settings_routes.api_models.reasoning_routes import get_api_reasoning_models

        return (await get_api_reasoning_models(get_model_service())).current_model
    except Exception:
        import logging

        logging.getLogger(__name__).warning("Could not reconcile the stored reasoning model with the available models", exc_info=True)
        return None
