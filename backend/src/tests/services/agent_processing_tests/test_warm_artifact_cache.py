"""Unit tests for P5 warm artifact cache."""

from __future__ import annotations

import asyncio

import pytest

from api.services.agent_processing.lifecycle.runtime.warm_artifact_cache import (
    WarmArtifactCache,
    compute_environment_signature,
)


def test_compute_environment_signature_is_stable_and_order_independent():
    sig_a = compute_environment_signature(
        model_id="claude-sonnet-5",
        tool_rendering="full_schema",
        available_service_names=("shell_service", "email_service"),
    )
    sig_b = compute_environment_signature(
        model_id="claude-sonnet-5",
        tool_rendering="full_schema",
        available_service_names=("email_service", "shell_service"),
    )
    assert sig_a == sig_b
    assert len(sig_a) == 64


def test_compute_environment_signature_changes_when_inputs_change():
    base = compute_environment_signature(
        model_id="m1",
        tool_rendering="full_schema",
        available_service_names=("a",),
    )
    other_model = compute_environment_signature(
        model_id="m2",
        tool_rendering="full_schema",
        available_service_names=("a",),
    )
    other_services = compute_environment_signature(
        model_id="m1",
        tool_rendering="full_schema",
        available_service_names=("a", "b"),
    )
    assert base != other_model
    assert base != other_services


@pytest.mark.asyncio
async def test_get_or_build_miss_then_hit():
    cache = WarmArtifactCache()
    calls = {"n": 0}

    async def builder():
        calls["n"] += 1
        return {"artifact": calls["n"]}

    sig = compute_environment_signature(
        model_id="",
        tool_rendering="",
        available_service_names=("svc",),
    )
    value1, hit1 = await cache.get_or_build(
        key="test_key", signature=sig, builder=builder
    )
    value2, hit2 = await cache.get_or_build(
        key="test_key", signature=sig, builder=builder
    )

    assert hit1 is False
    assert hit2 is True
    assert calls["n"] == 1
    assert value1 is value2
    assert value1 == {"artifact": 1}


@pytest.mark.asyncio
async def test_signature_change_forces_rebuild():
    cache = WarmArtifactCache()
    calls = {"n": 0}

    async def builder():
        calls["n"] += 1
        return calls["n"]

    sig_a = compute_environment_signature(
        model_id="",
        tool_rendering="",
        available_service_names=("a",),
    )
    sig_b = compute_environment_signature(
        model_id="",
        tool_rendering="",
        available_service_names=("a", "b"),
    )

    _, hit1 = await cache.get_or_build(key="cap", signature=sig_a, builder=builder)
    value2, hit2 = await cache.get_or_build(key="cap", signature=sig_b, builder=builder)

    assert hit1 is False
    assert hit2 is False
    assert calls["n"] == 2
    assert value2 == 2


@pytest.mark.asyncio
async def test_ttl_expiry_forces_rebuild():
    cache = WarmArtifactCache()
    calls = {"n": 0}

    async def builder():
        calls["n"] += 1
        return calls["n"]

    sig = compute_environment_signature(
        model_id="",
        tool_rendering="",
        available_service_names=("x",),
    )

    await cache.get_or_build(key="k", signature=sig, builder=builder, ttl_seconds=0)
    _, hit = await cache.get_or_build(key="k", signature=sig, builder=builder, ttl_seconds=0)

    assert calls["n"] == 2
    assert hit is False


@pytest.mark.asyncio
async def test_concurrent_builds_run_once():
    cache = WarmArtifactCache()
    calls = {"n": 0}
    gate = asyncio.Event()

    async def builder():
        calls["n"] += 1
        await gate.wait()
        return "shared"

    sig = compute_environment_signature(
        model_id="",
        tool_rendering="",
        available_service_names=("svc",),
    )

    tasks = [
        asyncio.create_task(
            cache.get_or_build(key="concurrent", signature=sig, builder=builder)
        )
        for _ in range(5)
    ]
    await asyncio.sleep(0.05)
    gate.set()
    results = await asyncio.gather(*tasks)

    assert calls["n"] == 1
    values = [r[0] for r in results]
    assert all(v == "shared" for v in values)
    assert results[0][1] is False
    assert sum(1 for _, hit in results if hit) == 4


def test_invalidate_key_and_all():
    cache = WarmArtifactCache()
    sig = compute_environment_signature(
        model_id="",
        tool_rendering="",
        available_service_names=("a",),
    )

    async def _run():
        await cache.get_or_build(key="a", signature=sig, builder=_async_val(1))
        await cache.get_or_build(key="b", signature=sig, builder=_async_val(2))
        cache.invalidate("a")
        value_a, hit_a = await cache.get_or_build(key="a", signature=sig, builder=_async_val(3))
        assert hit_a is False
        assert value_a == 3
        value_b, hit_b = await cache.get_or_build(key="b", signature=sig, builder=_async_val(99))
        assert hit_b is True
        assert value_b == 2
        cache.invalidate()
        assert not cache._entries

    asyncio.run(_run())


def _async_val(value):
    async def builder():
        return value
    return builder
