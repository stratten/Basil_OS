"""Tests for bounded concurrency primitives used by meeting analysis."""

import asyncio
from types import SimpleNamespace

import pytest

from api.services.whisper_live_core.post_processing import (
    meeting_analysis_concurrency as concurrency,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_concurrency import (
    AnalysisCallLimiter,
    gather_cancel_on_error,
    resolve_analysis_concurrency,
)


@pytest.mark.asyncio
async def test_limiter_never_exceeds_its_bound():
    limiter = AnalysisCallLimiter(2)
    peak = 0
    active = 0

    async def work():
        nonlocal peak, active
        async with limiter.slot():
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(*(work() for _ in range(8)))

    assert peak == 2
    assert limiter.in_flight == 0


@pytest.mark.asyncio
async def test_lowering_the_limit_applies_to_calls_that_have_not_started():
    limiter = AnalysisCallLimiter(3)
    peak_after_lowering = 0
    active = 0
    lowered = asyncio.Event()

    async def work(index: int):
        nonlocal peak_after_lowering, active
        async with limiter.slot():
            active += 1
            if lowered.is_set():
                peak_after_lowering = max(peak_after_lowering, active)
            if index == 0:
                limiter.set_limit(1)
                lowered.set()
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(*(work(index) for index in range(6)))

    assert peak_after_lowering <= 3
    assert limiter.limit == 1
    assert limiter.in_flight == 0


@pytest.mark.asyncio
async def test_canceled_waiter_does_not_leak_a_slot():
    limiter = AnalysisCallLimiter(1)
    await limiter.acquire()

    async def waiter():
        async with limiter.slot():
            return "ran"

    task = asyncio.ensure_future(waiter())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    limiter.release()

    assert limiter.in_flight == 0
    async with limiter.slot():
        assert limiter.in_flight == 1


@pytest.mark.asyncio
async def test_gather_cancel_on_error_preserves_order_and_cancels_siblings():
    canceled = asyncio.Event()

    async def slow():
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            canceled.set()
            raise

    async def failing():
        await asyncio.sleep(0.01)
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await gather_cancel_on_error([slow(), failing()])

    assert canceled.is_set()


@pytest.mark.asyncio
async def test_gather_cancel_on_error_returns_results_in_input_order():
    async def value(number: int, delay: float):
        await asyncio.sleep(delay)
        return number

    results = await gather_cancel_on_error([value(1, 0.03), value(2, 0.0), value(3, 0.01)])

    assert results == [1, 2, 3]


def test_api_handlers_get_the_api_bound_and_others_are_serialized(monkeypatch):
    monkeypatch.delenv(concurrency.CONCURRENCY_ENV_VAR, raising=False)
    for handler, expected in (
        ("anthropic_api", concurrency.API_MODEL_CONCURRENCY),
        ("openai_api", concurrency.API_MODEL_CONCURRENCY),
        ("gemini_api", concurrency.API_MODEL_CONCURRENCY),
        ("llama_cpp", concurrency.LOCAL_MODEL_CONCURRENCY),
        (None, concurrency.LOCAL_MODEL_CONCURRENCY),
    ):
        monkeypatch.setattr(
            concurrency,
            "resolve_runtime_model_profile",
            lambda _model, handler=handler: SimpleNamespace(handler=handler),
        )
        assert resolve_analysis_concurrency(object()) == expected


def test_profile_resolution_failure_is_treated_as_local(monkeypatch):
    monkeypatch.delenv(concurrency.CONCURRENCY_ENV_VAR, raising=False)

    def explode(_model):
        raise RuntimeError("no profile")

    monkeypatch.setattr(concurrency, "resolve_runtime_model_profile", explode)

    assert resolve_analysis_concurrency(object()) == concurrency.LOCAL_MODEL_CONCURRENCY


def test_environment_override_wins_and_ignores_garbage(monkeypatch):
    monkeypatch.setattr(
        concurrency,
        "resolve_runtime_model_profile",
        lambda _model: SimpleNamespace(handler="anthropic_api"),
    )
    monkeypatch.setenv(concurrency.CONCURRENCY_ENV_VAR, "1")
    assert resolve_analysis_concurrency(object()) == 1
    monkeypatch.setenv(concurrency.CONCURRENCY_ENV_VAR, "0")
    assert resolve_analysis_concurrency(object()) == 1
    monkeypatch.setenv(concurrency.CONCURRENCY_ENV_VAR, "not-a-number")
    assert resolve_analysis_concurrency(object()) == concurrency.API_MODEL_CONCURRENCY


def test_suggested_actions_depends_only_on_action_items():
    assert concurrency.MODE_DEPENDENCIES == {"suggested_actions": ("action_items",)}
