"""Regression tests for prompt-based narrative synthesis model invocation."""

import asyncio
from typing import Any, Dict, Optional

import pytest

from api.core.models.model_invocation import call_model_with_prompt, supports_web_search
from api.services.zettel.narrative.prompt import MAX_NARRATIVE_CHARS, build_prompt
from api.services.zettel.narrative.synthesizer import (
    GENERATION_TOKEN_CEILING,
    SynthesisError,
    _parse,
    synthesize,
)


class _LocalFakeModel:
    """Mirrors LlamaCppModel: no enable_web_search in the signature."""

    model_name = "Qwen-qwen3-8b-instruct-q4km"
    name = model_name

    def __init__(self) -> None:
        self.last_kwargs: Dict[str, Any] = {}

    async def generate_response(
        self,
        prompt: str,
        context: Dict[str, Any] = None,
        max_tokens: int = 1024,
    ) -> str:
        self.last_kwargs = {
            "prompt": prompt,
            "context": context,
            "max_tokens": max_tokens,
        }
        return '{"narrative": "You finished the task.", "is_open": false}'


class _CloudFakeModel:
    model_name = "claude-sonnet-5"
    name = model_name

    def __init__(self) -> None:
        self.last_kwargs: Dict[str, Any] = {}

    def _supports_web_search(self) -> bool:
        return True

    async def generate_response(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
        enable_web_search: bool = True,
    ) -> str:
        self.last_kwargs = {
            "prompt": prompt,
            "context": context,
            "max_tokens": max_tokens,
            "enable_web_search": enable_web_search,
        }
        return '{"narrative": "Cloud summary.", "is_open": false}'


class _BrokenProbeModel:
    model_name = "claude-sonnet-5"

    def _supports_web_search(self):
        raise RuntimeError("probe failed")


@pytest.mark.asyncio
async def test_synthesize_local_model_does_not_pass_enable_web_search(monkeypatch):
    fake = _LocalFakeModel()

    async def _fake_get_model(*args, **kwargs):
        return fake

    monkeypatch.setattr(
        "api.dependencies.get_model_usage_service",
        lambda: type("S", (), {"get_model_for_task": _fake_get_model})(),
    )

    result = await synthesize(
        {"entry_id": "agent_task:t1", "title": "Task", "summary": "Did work"},
        {"result_data": "details"},
    )

    assert result.narrative == "You finished the task."
    assert "enable_web_search" not in fake.last_kwargs


@pytest.mark.asyncio
async def test_model_stage_semaphore_serializes_acquisition_not_generation(monkeypatch):
    active_acquisitions = 0
    max_concurrent_acquisitions = 0
    first_acquisition_entered = asyncio.Event()
    release_acquisition = asyncio.Event()
    active_generations = 0
    max_concurrent_generations = 0
    both_generating = asyncio.Event()

    async def fake_get_model_for_task(*args, **kwargs):
        nonlocal active_acquisitions, max_concurrent_acquisitions
        active_acquisitions += 1
        max_concurrent_acquisitions = max(
            max_concurrent_acquisitions,
            active_acquisitions,
        )
        first_acquisition_entered.set()
        await release_acquisition.wait()
        active_acquisitions -= 1
        return object()

    async def fake_call_model_with_prompt(
        model, *, prompt, purpose, max_tokens, enable_web_search
    ):
        nonlocal active_generations, max_concurrent_generations
        active_generations += 1
        max_concurrent_generations = max(
            max_concurrent_generations,
            active_generations,
        )
        if active_generations == 2:
            both_generating.set()
        await asyncio.wait_for(both_generating.wait(), timeout=5)
        active_generations -= 1
        return '{"narrative": "done"}'

    monkeypatch.setattr(
        "api.dependencies.get_model_usage_service",
        lambda: type("S", (), {"get_model_for_task": fake_get_model_for_task})(),
    )
    monkeypatch.setattr(
        "api.services.zettel.narrative.synthesizer.call_model_with_prompt",
        fake_call_model_with_prompt,
    )

    semaphore = asyncio.Semaphore(1)
    entry = {"entry_id": "agent_task:t1", "title": "Task", "summary": "Did work"}
    synthesis_task = asyncio.gather(
        synthesize(entry, {}, model_stage_semaphore=semaphore),
        synthesize(entry, {}, model_stage_semaphore=semaphore),
    )
    await asyncio.wait_for(first_acquisition_entered.wait(), timeout=5)
    await asyncio.sleep(0)
    assert max_concurrent_acquisitions == 1
    release_acquisition.set()
    results = await asyncio.wait_for(synthesis_task, timeout=5)

    assert max_concurrent_acquisitions == 1
    assert max_concurrent_generations == 2
    assert len(results) == 2


@pytest.mark.asyncio
async def test_call_model_with_prompt_passes_enable_web_search_for_cloud_model():
    fake = _CloudFakeModel()
    await call_model_with_prompt(
        fake,
        prompt="hello",
        max_tokens=400,
        enable_web_search=False,
    )
    assert fake.last_kwargs["enable_web_search"] is False
    assert fake.last_kwargs["max_tokens"] == 400


class _KwargTrackingModel:
    def __init__(self) -> None:
        self.passed_kwargs: Dict[str, Any] = {}

    async def generate_response(self, prompt: str, **kwargs: Any) -> str:
        self.passed_kwargs = {"prompt": prompt, **kwargs}
        return "ok"


@pytest.mark.asyncio
async def test_call_model_with_prompt_omits_max_tokens_when_none():
    fake = _KwargTrackingModel()
    await call_model_with_prompt(fake, prompt="hello", max_tokens=None)
    assert "max_tokens" not in fake.passed_kwargs


def test_supports_web_search_false_when_probe_raises():
    assert supports_web_search(_BrokenProbeModel()) is False


def test_supports_web_search_false_without_model_name():
    assert supports_web_search(object()) is False


def test_generation_ceiling_is_not_sized_to_the_answer():
    """A budget near the answer length starved reasoning models of room to think.

    The ceiling only guards against a runaway; length is the prompt's contract.
    """
    assert GENERATION_TOKEN_CEILING > MAX_NARRATIVE_CHARS


def test_prompt_states_the_length_limit_it_is_judged_against():
    """The model must be told the limit the synthesizer enforces on its reply."""
    rendered = build_prompt(
        {"source_kind": "agent_task", "title": "T", "occurred_at": "2026-01-01"},
        {"result_data": "details"},
    )
    assert str(MAX_NARRATIVE_CHARS) in rendered


def test_narrative_over_the_limit_is_rejected_not_truncated():
    payload = '{"narrative": "%s", "is_open": false}' % ("y" * (MAX_NARRATIVE_CHARS + 1))
    with pytest.raises(SynthesisError) as exc:
        _parse(payload, "m")
    assert str(MAX_NARRATIVE_CHARS) in str(exc.value)


def test_narrative_at_the_limit_is_accepted():
    payload = '{"narrative": "%s", "is_open": false}' % ("y" * MAX_NARRATIVE_CHARS)
    assert len(_parse(payload, "m").narrative) == MAX_NARRATIVE_CHARS


def test_json_is_found_when_the_reply_wraps_it_in_prose():
    reply = 'Sure:\n{"narrative": "You shipped it.", "is_open": false}\nHope that helps.'
    assert _parse(reply, "m").narrative == "You shipped it."


def test_non_ascii_narrative_survives_extraction():
    """extract_balanced_json is used precisely so prose is not mangled."""
    reply = '{"narrative": "You reviewed the café résumé — twice.", "is_open": false}'
    assert _parse(reply, "m").narrative == "You reviewed the café résumé — twice."


def test_legacy_closed_lifecycle_fields_are_ignored():
    result = _parse(
        '{"narrative": "You shipped the parser.", "is_open": false, '
        '"open_note": "Still needs review"}',
        "m",
    )

    assert result.narrative == "You shipped the parser."


def test_legacy_open_lifecycle_fields_are_ignored():
    result = _parse(
        '{"narrative": "You are mid-run.", "is_open": true, '
        '"open_note": "Still needs review"}',
        "m",
    )

    assert result.narrative == "You are mid-run."
