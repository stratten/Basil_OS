"""Resolve immutable execution policy for a Zettel narrative (Memories) run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from api.core.models.models_registry import find_model_by_display_name, get_model


API_BACKLOG_NARRATIVE_CONCURRENCY = 8
SEQUENTIAL_NARRATIVE_CONCURRENCY = 1


@dataclass(frozen=True)
class NarrativeProcessingRunPolicy:
    """The selected model and bounded synthesis policy fixed at run admission."""

    model_id: Optional[str]
    analysis_concurrency: int
    processing_strategy: str


def resolve_narrative_processing_model_id(configured_model: str) -> Optional[str]:
    """Return the canonical registry identifier for an id or legacy display name."""
    if not configured_model:
        return None
    if get_model(configured_model) is not None:
        return configured_model
    match = find_model_by_display_name(configured_model)
    return match[0] if match is not None else None


def resolve_narrative_processing_run_policy(
    configured_model: str,
    *,
    is_manual_backlog_run: bool,
) -> NarrativeProcessingRunPolicy:
    """Allow bounded parallelism only for an explicitly requested cloud backlog.

    An empty configured_model means "use the default reasoning model", whose eventual identity depends on ModelUsageService's runtime fallback chain and is not knowable here, so it is treated the same as an unknown model: stays sequential.
    """
    canonical_model_id = resolve_narrative_processing_model_id(configured_model)
    model_id = canonical_model_id or (configured_model or None)
    model_config = get_model(canonical_model_id) if canonical_model_id is not None else None
    is_cloud_model = isinstance(model_config, dict) and model_config.get("location") == "cloud"
    if is_manual_backlog_run and is_cloud_model:
        return NarrativeProcessingRunPolicy(
            model_id=model_id,
            analysis_concurrency=API_BACKLOG_NARRATIVE_CONCURRENCY,
            processing_strategy="api_parallel",
        )
    return NarrativeProcessingRunPolicy(
        model_id=model_id,
        analysis_concurrency=SEQUENTIAL_NARRATIVE_CONCURRENCY,
        processing_strategy="sequential",
    )
