"""Tests for narrative scheduler retrieval reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.services.zettel.narrative_scheduler import ZettelNarrativeScheduler


@dataclass
class _Result:
    finalized: int
    still_open: int
    failed: int
    errors: list[str]


@pytest.mark.asyncio
async def test_scheduled_pass_reconciles_after_finalizations():
    scheduler = ZettelNarrativeScheduler()
    runtime = MagicMock()
    runtime.reconcile_after_narrative_pass = AsyncMock()

    with patch(
        "api.services.zettel.narrative.enricher.get_zettel_enricher"
    ) as get_enricher, patch(
        "api.core.preferences.preferences_io.load_preferences"
    ) as load_preferences, patch(
        "api.services.retrieval.index_runtime.get_retrieval_index_runtime",
        return_value=runtime,
    ):
        enricher = MagicMock()
        enricher.run_pass = AsyncMock(return_value=_Result(finalized=2, still_open=1, failed=0, errors=[]))
        get_enricher.return_value = enricher
        settings = MagicMock()
        settings.narrative_batch_size = 10
        settings.narrative_max_attempts = 3
        settings.narrative_model = ""
        settings.narrative_max_records = 0
        load_preferences.return_value = MagicMock(zettel=settings)

        await scheduler._run_once()

    runtime.reconcile_after_narrative_pass.assert_awaited_once()


@pytest.mark.asyncio
async def test_open_only_pass_does_not_reconcile():
    scheduler = ZettelNarrativeScheduler()
    runtime = MagicMock()
    runtime.reconcile_after_narrative_pass = AsyncMock()

    with patch(
        "api.services.zettel.narrative.enricher.get_zettel_enricher"
    ) as get_enricher, patch(
        "api.core.preferences.preferences_io.load_preferences"
    ) as load_preferences, patch(
        "api.services.retrieval.index_runtime.get_retrieval_index_runtime",
        return_value=runtime,
    ):
        enricher = MagicMock()
        enricher.run_pass = AsyncMock(return_value=_Result(finalized=0, still_open=3, failed=0, errors=[]))
        get_enricher.return_value = enricher
        settings = MagicMock()
        settings.narrative_batch_size = 10
        settings.narrative_max_attempts = 3
        settings.narrative_model = ""
        settings.narrative_max_records = 0
        load_preferences.return_value = MagicMock(zettel=settings)

        await scheduler._run_once()

    runtime.reconcile_after_narrative_pass.assert_not_called()


@pytest.mark.asyncio
async def test_run_now_resolves_manual_backlog_policy():
    scheduler = ZettelNarrativeScheduler()
    runtime = MagicMock()
    runtime.reconcile_after_narrative_pass = AsyncMock()

    with patch(
        "api.services.zettel.narrative.enricher.get_zettel_enricher"
    ) as get_enricher, patch(
        "api.core.preferences.preferences_io.load_preferences"
    ) as load_preferences, patch(
        "api.services.retrieval.index_runtime.get_retrieval_index_runtime",
        return_value=runtime,
    ), patch(
        "api.services.zettel.narrative.narrative_processing_run_policy.get_model",
        lambda model_id: {"location": "cloud"} if model_id == "cloud-model" else None,
    ):
        enricher = MagicMock()
        enricher.run_pass = AsyncMock(
            return_value=_Result(finalized=1, still_open=0, failed=0, errors=[])
        )
        get_enricher.return_value = enricher
        settings = MagicMock()
        settings.narrative_batch_size = 10
        settings.narrative_max_attempts = 3
        settings.narrative_model = "cloud-model"
        settings.narrative_max_records = 0
        load_preferences.return_value = MagicMock(zettel=settings)

        await scheduler.run_now()

    _, kwargs = enricher.run_pass.await_args
    assert kwargs["run_policy"].processing_strategy == "api_parallel"
    assert kwargs["run_policy"].analysis_concurrency == 8


@pytest.mark.asyncio
async def test_scheduled_trigger_never_resolves_manual_policy():
    scheduler = ZettelNarrativeScheduler()
    runtime = MagicMock()
    runtime.reconcile_after_narrative_pass = AsyncMock()

    with patch(
        "api.services.zettel.narrative.enricher.get_zettel_enricher"
    ) as get_enricher, patch(
        "api.core.preferences.preferences_io.load_preferences"
    ) as load_preferences, patch(
        "api.services.retrieval.index_runtime.get_retrieval_index_runtime",
        return_value=runtime,
    ), patch(
        "api.services.zettel.narrative.narrative_processing_run_policy.get_model",
        lambda model_id: {"location": "cloud"} if model_id == "cloud-model" else None,
    ):
        enricher = MagicMock()
        enricher.run_pass = AsyncMock(
            return_value=_Result(finalized=0, still_open=0, failed=0, errors=[])
        )
        get_enricher.return_value = enricher
        settings = MagicMock()
        settings.narrative_batch_size = 10
        settings.narrative_max_attempts = 3
        settings.narrative_model = "cloud-model"
        settings.narrative_max_records = 0
        load_preferences.return_value = MagicMock(zettel=settings)

        await scheduler._run_once()

    _, kwargs = enricher.run_pass.await_args
    assert kwargs["run_policy"].processing_strategy == "sequential"
