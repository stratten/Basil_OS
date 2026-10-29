"""Runtime availability gate.

Derives whether a candidate model can actually run in the *current* app
state (API key present, local weights downloaded, proxy reachable, etc.) by
calling the exact same oracle production code uses:
``ModelUsageService.get_model_for_task``. ``None`` means the model cannot be
exercised right now -> SKIP with a reason, not a FAIL.
"""

from __future__ import annotations

import gc
import logging
from dataclasses import dataclass
from typing import Optional

from api.core.models.base_model import BaseAIModel
from api.core.models.model_types import ModelCapability
from api.dependencies import get_model_usage_service
from api.services.model_usage_service import ModelUsageService

from .registry_enumeration import ModelCandidate

logger = logging.getLogger("model_scenario_smoke.availability")


@dataclass
class AvailabilityResult:
    model: Optional[BaseAIModel]
    reason: Optional[str] = None

    @property
    def available(self) -> bool:
        return self.model is not None


def shared_model_usage_service() -> ModelUsageService:
    """Return the process-wide cached ModelUsageService (same singleton the
    running app's DI graph hands to AssistantSession/AgentTask/etc.), so a
    model loaded here is actually reused by scenario invocations instead of
    being loaded into a throwaway ModelManager that immediately goes out of
    scope. ``get_model_usage_service`` is ``@lru_cache()``'d in api.dependencies.
    """
    return get_model_usage_service()


async def check_availability(candidate: ModelCandidate) -> AvailabilityResult:
    """Try to load the candidate the same way production code does."""
    usage_service = shared_model_usage_service()
    try:
        model = await usage_service.get_model_for_task(
            capabilities={ModelCapability.REASONING},
            explicit_model_id=candidate.model_id,
        )
    except Exception as exc:  # pragma: no cover - get_model_for_task already catches most errors
        return AvailabilityResult(model=None, reason=f"raised during load: {exc}")
    if model is None:
        return AvailabilityResult(
            model=None,
            reason="not available in current app state (missing API key / not downloaded / proxy unreachable)",
        )
    return AvailabilityResult(model=model)


async def release_if_local(candidate: ModelCandidate) -> None:
    """Best-effort unload of a local (llama.cpp) model after testing it.

    Only meaningful for models loaded through the shared ModelUsageService's
    ModelService (this harness's own availability check, and any scenario
    that was given that same instance). Some scenario code paths in the app
    (e.g. MeetingAnalyzer, the Setup Wizard's local model builder) construct
    their own throwaway ModelService via the uncached
    ``api.dependencies.get_model_service`` rather than the cached
    ``get_model_usage_service``, so a local model they load is NOT visible
    here and cannot be unloaded from this call -- it is released only when
    that throwaway ModelService/ModelManager is garbage collected. This is a
    pre-existing DI wrinkle in the app, not something this harness can fix;
    the explicit gc.collect() below is a defensive nudge for that case, not
    a guarantee.
    """
    if not candidate.is_local or "-" not in candidate.model_id:
        gc.collect()
        return
    model_type, variant = candidate.model_id.split("-", 1)
    try:
        model_service = shared_model_usage_service().model_service
        await model_service.unload_model(model_type, variant)
    except Exception as exc:
        logger.warning("Failed to unload local model %s after smoke test: %s", candidate.model_id, exc)
    gc.collect()
