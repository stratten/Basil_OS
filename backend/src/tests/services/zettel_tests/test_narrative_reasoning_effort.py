"""The narrative reasoning-effort override: scoped to the run, inherited by spawned tasks, and limited to models that expose reasoning effort."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.core.models.reasoning import openai_model as openai_model_module
from api.core.models.reasoning.effort_override import (
    current_reasoning_effort_override,
    reasoning_effort_override,
)
from api.core.models.reasoning.openai_model import OpenAIModel
from api.services.zettel.narrative_scheduler import ZettelNarrativeScheduler


def test_override_is_scoped_and_nests():
    assert current_reasoning_effort_override() is None
    with reasoning_effort_override("low"):
        assert current_reasoning_effort_override() == "low"
        with reasoning_effort_override("none"):
            assert current_reasoning_effort_override() == "none"
        assert current_reasoning_effort_override() == "low"
    assert current_reasoning_effort_override() is None


def test_none_override_leaves_the_registry_default_in_force():
    with reasoning_effort_override(None):
        assert current_reasoning_effort_override() is None


@pytest.mark.asyncio
async def test_tasks_spawned_inside_the_block_see_it_and_siblings_outside_do_not():
    seen = []

    async def observe():
        await asyncio.sleep(0)
        seen.append(current_reasoning_effort_override())

    with reasoning_effort_override("low"):
        inside = asyncio.create_task(observe())
        await inside
    outside = asyncio.create_task(observe())
    await outside
    assert seen == ["low", None]


def _model_named(name: str) -> OpenAIModel:
    model = OpenAIModel.__new__(OpenAIModel)
    model.model_name = name
    return model


def test_override_replaces_the_registry_default_only_for_reasoning_effort_models(monkeypatch):
    monkeypatch.setattr(openai_model_module, "get_reasoning_effort_default", lambda name: "medium" if name == "reasoner" else None)
    monkeypatch.setattr(openai_model_module, "get_model", lambda name: {} if name == "reasoner" else None)
    reasoner = _model_named("reasoner")
    plain = _model_named("gpt-4o-mini")
    assert reasoner._get_reasoning_effort() == "medium"
    with reasoning_effort_override("low"):
        assert reasoner._get_reasoning_effort() == "low"
        assert plain._get_reasoning_effort() is None
    assert reasoner._get_reasoning_effort() == "medium"


@pytest.mark.parametrize(
    "raw, expected",
    [("low", "low"), (" None ", "none"), ("HIGH", "high"), ("", None), ("turbo", None), (None, None), (SimpleNamespace(), None)],
)
def test_configured_effort_accepts_only_supported_levels(raw, expected):
    settings = SimpleNamespace(narrative_reasoning_effort=raw)
    assert ZettelNarrativeScheduler._configured_reasoning_effort(settings) == expected


@pytest.mark.asyncio
async def test_scheduler_run_applies_the_override_to_the_whole_pass(monkeypatch):
    observed = []

    async def run_pass(**_kwargs):
        child = asyncio.create_task(asyncio.sleep(0, result=current_reasoning_effort_override()))
        observed.append(await child)
        return SimpleNamespace(finalized=0, still_open=0, failed=0, discarded=0, completed=True, errors=[])

    fake_enricher = SimpleNamespace(run_pass=AsyncMock(side_effect=run_pass))
    monkeypatch.setattr("api.services.zettel.narrative.enricher.get_zettel_enricher", lambda: fake_enricher)
    scheduler = ZettelNarrativeScheduler()
    scheduler._settings = lambda: SimpleNamespace(
        narrative_enabled=True, narrative_model="", narrative_reasoning_effort="low"
    )
    await scheduler._run_once()
    assert observed == ["low"]
    assert current_reasoning_effort_override() is None
