"""Transcription model swap route.

Exposes ``POST /settings/transcription/model/swap`` -- a single compound
endpoint that atomically (a) writes the new transcription model id to
preferences, (b) unloads whatever transcription model is currently loaded
in memory, and (c) loads the new one. Mirrors the user-facing mental
model of "change the model" in one round trip.

This exists because the existing PUT endpoints
(``/settings/transcription`` and ``/settings/models``) only persist the
preference -- ``ModelManager.load_model`` early-returns when a shared
model is already loaded and never re-reads the preference, so a plain
preference write has no live effect until the next process restart or a
coincidental unload. This endpoint forces the swap.
"""

import asyncio
import time
from typing import Optional, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...core.models.preferences import Preferences
from ...core.logging.api_logger import api_logger

# Reuse the widget-routes shared persistence helper so we don't
# diverge from the format the rest of the settings layer uses.
from .widget_routes import save_preferences, load_preferences


router = APIRouter(tags=["transcription-model"])


# --------------------------------------------------------------------------- #
# Request / response models
# --------------------------------------------------------------------------- #


class SwapTranscriptionModelRequest(BaseModel):
    """Body for ``POST /settings/transcription/model/swap``."""

    model_id: str = Field(
        ...,
        description=(
            "Identifier of the transcription model to swap to. Accepts the "
            "same value shape used elsewhere in preferences: a cloud-model "
            "id (e.g. 'whisper-1'), a Parakeet model id or display name, "
            "or a HuggingFace Whisper display name (e.g. 'Whisper Base')."
        ),
    )


class SwapTranscriptionModelResponse(BaseModel):
    """Result of a swap request."""

    model_id: str
    loaded: bool
    service_kind: Literal["huggingface", "parakeet", "openai_api"]
    elapsed_ms: int
    no_op: bool = Field(
        default=False,
        description=(
            "True when the requested model_id matched the active selection "
            "and no unload/reload was performed."
        ),
    )
    activation_status: Literal["active", "pending"] = Field(
        default="active",
        description=(
            "Whether the requested live model is active now or will activate "
            "after a borrowed local Whisper pipeline is released."
        ),
    )


# --------------------------------------------------------------------------- #
# Validation helpers
# --------------------------------------------------------------------------- #


def _classify_model_id(model_id: str) -> Optional[Literal["openai_api", "parakeet", "huggingface"]]:
    """Identify which transcription backend a given model_id resolves to.

    Returns None if the id matches none of the known registries -- the
    route uses this to reject unknown ids with HTTP 400 before touching
    any persisted state.
    """
    from ...core.models.models_registry import (
        get_cloud_transcription_models,
        get_parakeet_transcription_models,
        get_transcription_models,
    )

    if model_id in get_cloud_transcription_models():
        return "openai_api"

    parakeet_models = get_parakeet_transcription_models()
    for pid, cfg in parakeet_models.items():
        if pid == model_id or cfg.get("display_name") == model_id:
            return "parakeet"

    hf_models = get_transcription_models()
    for hid, cfg in hf_models.items():
        if hid == model_id or cfg.get("display_name") == model_id:
            return "huggingface"

    return None


# --------------------------------------------------------------------------- #
# Route
# --------------------------------------------------------------------------- #


@router.post(
    "/transcription/model/swap",
    response_model=SwapTranscriptionModelResponse,
)
async def swap_transcription_model(
    request: SwapTranscriptionModelRequest,
) -> SwapTranscriptionModelResponse:
    """Swap the active transcription model: unload current, set pref, load new.

    Behavior:
      1. Validate ``model_id`` against the union of cloud, Parakeet, and
         HuggingFace transcription registries. Reject with 400 if unknown.
      2. If the requested id already matches the persisted preference,
         return a no-op response without touching any model state. This
         keeps the endpoint idempotent and cheap to spam.
      3. Resolve the *current* transcription service via
         ``resolve_transcription_service()`` and call ``unload_model()``.
         For the API service this is a no-op; for HuggingFace / Parakeet
         this frees the loaded weights.
      4. Persist the new ``preferences.models.transcription_model``.
      5. Resolve again (now picks up the new id) and call ``load_model()``.
         If this raises, attempt a best-effort revert: restore the previous
         preference and reload the prior service so the user isn't left
         with no model loaded.
      6. Broadcast a ``transcription_model_changed`` WebSocket status so
         other surfaces (e.g. the Settings tab) can refresh.

    Args:
        request: ``SwapTranscriptionModelRequest`` with the target model id.

    Returns:
        ``SwapTranscriptionModelResponse`` with the resolved id, load
        status, which backend kind handled the load, and elapsed wall time.

    Raises:
        HTTPException: 400 if the model id is not found in any registry,
            500 if the swap fails and the revert also fails.
    """
    start = time.monotonic()
    target_model_id = request.model_id.strip()

    if not target_model_id:
        raise HTTPException(status_code=400, detail="model_id must not be empty")

    service_kind = _classify_model_id(target_model_id)
    if service_kind is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown transcription model id '{target_model_id}'. Must "
                f"match a cloud, Parakeet, or HuggingFace transcription "
                f"registry entry (by id or display name)."
            ),
        )

    preferences = load_preferences()
    previous_model_id = preferences.models.transcription_model

    # No-op short-circuit -- preference already matches request. We don't
    # also assert the model is currently loaded; a follow-up
    # init_transcription will handle that if needed. The point of this
    # endpoint is "swap to X", and we are already at X.
    if previous_model_id == target_model_id:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        api_logger.info(
            f"⚡ Transcription model swap is a no-op (already on '{target_model_id}')"
        )
        return SwapTranscriptionModelResponse(
            model_id=target_model_id,
            loaded=True,
            service_kind=service_kind,
            elapsed_ms=elapsed_ms,
            no_op=True,
            activation_status="active",
        )

    from ...dependencies import resolve_transcription_service
    from ...services.transcription.local_model.warm_whisper_pipeline import (
        WarmWhisperPipeline,
    )

    async def broadcast_model_status(status: str) -> None:
        try:
            from ..websocket_routes.transcription import send_transcription_status

            await send_transcription_status(
                status,
                {"model_id": target_model_id, "service_kind": service_kind},
            )
        except Exception as exc:
            api_logger.warning("Could not broadcast %s event: %s", status, exc)

    if WarmWhisperPipeline.has_active_inference():
        preferences.models.transcription_model = target_model_id
        try:
            save_preferences(preferences)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to save preference: {exc}",
            ) from exc

        async def activate_after_inference() -> None:
            try:
                await asyncio.to_thread(WarmWhisperPipeline.wait_for_idle)
                current_service = resolve_transcription_service()
                await asyncio.to_thread(current_service.unload_model)
                new_service = resolve_transcription_service()
                await asyncio.to_thread(new_service.load_model)
                await broadcast_model_status("transcription_model_activated")
            except Exception as exc:
                api_logger.error(
                    "Deferred transcription model activation for '%s' failed: %s",
                    target_model_id,
                    exc,
                    exc_info=True,
                )

        asyncio.create_task(activate_after_inference())
        await broadcast_model_status("transcription_model_activation_pending")
        return SwapTranscriptionModelResponse(
            model_id=target_model_id,
            loaded=False,
            service_kind=service_kind,
            elapsed_ms=int((time.monotonic() - start) * 1000),
            no_op=False,
            activation_status="pending",
        )

    # --- Unload current ----------------------------------------------------
    try:
        current_service = resolve_transcription_service()
        api_logger.info(
            f"🔁 Swapping transcription model '{previous_model_id}' -> '{target_model_id}'; "
            f"unloading current service ({type(current_service).__name__})"
        )
        await asyncio.to_thread(current_service.unload_model)
    except Exception as exc:
        # An unload failure is not fatal -- we'll still attempt the swap.
        # The new load below is the operation that actually has to succeed.
        api_logger.warning(
            f"⚠️ Failed to cleanly unload current transcription service before swap: {exc}"
        )

    # --- Persist new preference -------------------------------------------
    preferences.models.transcription_model = target_model_id
    try:
        save_preferences(preferences)
    except Exception as exc:
        api_logger.error(
            f"❌ Failed to persist new transcription model preference: {exc}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to save preference: {exc}"
        )

    # --- Load new ---------------------------------------------------------
    try:
        new_service = resolve_transcription_service()
        api_logger.info(
            f"📥 Loading new transcription service ({type(new_service).__name__}) "
            f"for model '{target_model_id}'"
        )
        await asyncio.to_thread(new_service.load_model)
        loaded = new_service.is_model_loaded()
    except Exception as exc:
        api_logger.error(
            f"❌ Failed to load new transcription model '{target_model_id}': {exc}",
            exc_info=True,
        )

        # Best-effort revert so the user isn't left with no model loaded.
        try:
            api_logger.warning(
                f"↩️ Reverting transcription model preference back to '{previous_model_id}'"
            )
            preferences.models.transcription_model = previous_model_id
            save_preferences(preferences)
            revert_service = resolve_transcription_service()
            await asyncio.to_thread(revert_service.load_model)
        except Exception as revert_exc:
            api_logger.error(
                f"❌ Revert also failed -- system is left without a loaded "
                f"transcription model: {revert_exc}",
                exc_info=True,
            )

        raise HTTPException(
            status_code=500,
            detail=(
                f"Failed to load model '{target_model_id}': {exc}. Reverted "
                f"preference to '{previous_model_id}'."
            ),
        )

    # --- Broadcast --------------------------------------------------------
    await broadcast_model_status("transcription_model_changed")

    elapsed_ms = int((time.monotonic() - start) * 1000)
    api_logger.info(
        f"✅ Transcription model swap complete: '{target_model_id}' loaded={loaded} "
        f"({service_kind}, {elapsed_ms}ms)"
    )

    return SwapTranscriptionModelResponse(
        model_id=target_model_id,
        loaded=loaded,
        service_kind=service_kind,
        elapsed_ms=elapsed_ms,
        no_op=False,
        activation_status="active",
    )
