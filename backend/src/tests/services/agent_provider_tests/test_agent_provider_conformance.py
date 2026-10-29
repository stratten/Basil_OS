from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import pytest

from api.services.agent_provider_conformance import (
    ACP_PROTOCOL_VERSION,
    MAX_STDERR_BYTES,
    AcpConformanceProtocolError,
    AcpConformanceTimeoutError,
    AcpStdioConformanceProbe,
)


SOURCE_ROOT = Path(__file__).resolve().parents[3]


def fixture_argv(mode: str) -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        "api.services.agent_provider_conformance",
        "--fixture-mode",
        mode,
    )


@pytest.mark.asyncio
async def test_initialize_returns_validated_v2_fixture_result():
    async with AcpStdioConformanceProbe(fixture_argv("success"), cwd=str(SOURCE_ROOT)) as probe:
        result = await probe.initialize()

    assert result.protocol_version == ACP_PROTOCOL_VERSION
    assert result.capabilities == {"session": {}}
    assert result.agent_info == {"name": "Basil ACP fixture", "version": "1.0.0"}
    assert result.notifications == ()
    assert result.stderr_text == ""


@pytest.mark.asyncio
async def test_initialize_preserves_pre_response_notification():
    async with AcpStdioConformanceProbe(
        fixture_argv("notification_then_success"),
        cwd=str(SOURCE_ROOT),
    ) as probe:
        result = await probe.initialize()

    assert result.notifications == (
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"sessionId": "fixture-session", "update": "ready"},
        },
    )


@pytest.mark.asyncio
async def test_initialize_preserves_response_deadline_after_a_notification():
    probe = AcpStdioConformanceProbe(
        fixture_argv("notification_then_no_response"),
        cwd=str(SOURCE_ROOT),
        response_timeout_seconds=0.05,
    )

    async with probe:
        with pytest.raises(AcpConformanceTimeoutError, match="timed out waiting for JSON-RPC response id 1"):
            await probe.initialize()

    assert probe._process is None


@pytest.mark.asyncio
async def test_initialize_rejects_mismatched_json_rpc_response_id():
    async with AcpStdioConformanceProbe(
        fixture_argv("mismatched_id"),
        cwd=str(SOURCE_ROOT),
    ) as probe:
        with pytest.raises(AcpConformanceProtocolError, match="expected JSON-RPC response id 1"):
            await probe.initialize()


@pytest.mark.asyncio
async def test_initialize_rejects_boolean_json_rpc_response_id():
    async with AcpStdioConformanceProbe(
        fixture_argv("boolean_id"),
        cwd=str(SOURCE_ROOT),
    ) as probe:
        with pytest.raises(AcpConformanceProtocolError, match="expected JSON-RPC response id 1"):
            await probe.initialize()


@pytest.mark.asyncio
async def test_initialize_rejects_malformed_json():
    async with AcpStdioConformanceProbe(
        fixture_argv("malformed_json"),
        cwd=str(SOURCE_ROOT),
    ) as probe:
        with pytest.raises(AcpConformanceProtocolError, match="invalid JSON-RPC payload"):
            await probe.initialize()


@pytest.mark.asyncio
async def test_initialize_rejects_an_oversized_json_rpc_line():
    async with AcpStdioConformanceProbe(
        fixture_argv("oversized_line"),
        cwd=str(SOURCE_ROOT),
    ) as probe:
        with pytest.raises(
            AcpConformanceProtocolError,
            match="fixture emitted a JSON-RPC line exceeding the stream limit",
        ):
            await probe.initialize()


@pytest.mark.asyncio
async def test_initialize_rejects_response_that_contains_a_method():
    async with AcpStdioConformanceProbe(
        fixture_argv("response_with_method"),
        cwd=str(SOURCE_ROOT),
    ) as probe:
        with pytest.raises(
            AcpConformanceProtocolError,
            match="fixture response must not contain method",
        ):
            await probe.initialize()


@pytest.mark.asyncio
async def test_initialize_rejects_non_integer_protocol_version():
    async with AcpStdioConformanceProbe(
        fixture_argv("non_integer_protocol_version"),
        cwd=str(SOURCE_ROOT),
    ) as probe:
        with pytest.raises(
            AcpConformanceProtocolError,
            match=f"expected ACP protocol version {ACP_PROTOCOL_VERSION}",
        ):
            await probe.initialize()


@pytest.mark.asyncio
async def test_probe_bounds_stderr_while_draining_fixture_output():
    async with AcpStdioConformanceProbe(
        fixture_argv("stderr_then_success"),
        cwd=str(SOURCE_ROOT),
    ) as probe:
        result = await probe.initialize()

    assert len(result.stderr_text) <= MAX_STDERR_BYTES
    assert len(probe.stderr_text.encode("utf-8")) == MAX_STDERR_BYTES


@pytest.mark.asyncio
async def test_initialize_rejects_unsupported_protocol_version():
    async with AcpStdioConformanceProbe(
        fixture_argv("unsupported_version"),
        cwd=str(SOURCE_ROOT),
    ) as probe:
        with pytest.raises(
            AcpConformanceProtocolError,
            match=f"expected ACP protocol version {ACP_PROTOCOL_VERSION}",
        ):
            await probe.initialize()


@pytest.mark.asyncio
async def test_initialize_times_out_and_context_manager_terminates_fixture():
    probe = AcpStdioConformanceProbe(
        fixture_argv("no_response"),
        cwd=str(SOURCE_ROOT),
        response_timeout_seconds=0.05,
    )

    async with probe:
        process = probe._process
        assert process is not None
        with pytest.raises(AcpConformanceTimeoutError, match="timed out waiting for JSON-RPC response id 1"):
            await probe.initialize()

    assert probe._process is None
    assert process.returncode is not None


@pytest.mark.asyncio
async def test_probe_rejects_reinitialization_and_restart():
    probe = AcpStdioConformanceProbe(fixture_argv("success"), cwd=str(SOURCE_ROOT))

    async with probe:
        await probe.initialize()
        with pytest.raises(RuntimeError, match="ACP conformance probe is already initialized"):
            await probe.initialize()

    with pytest.raises(RuntimeError, match="ACP conformance probe is already started"):
        await probe.start()


@pytest.mark.asyncio
async def test_probe_rejects_concurrent_start_without_spawning_a_second_fixture():
    probe = AcpStdioConformanceProbe(fixture_argv("success"), cwd=str(SOURCE_ROOT))

    start_results = await asyncio.gather(probe.start(), probe.start(), return_exceptions=True)

    assert start_results.count(None) == 1
    assert sum(
        isinstance(result, RuntimeError) and str(result) == "ACP conformance probe is already started"
        for result in start_results
    ) == 1
    process = probe._process
    assert process is not None

    await probe.close()

    assert process.returncode is not None


def test_probe_rejects_empty_or_invalid_argv():
    with pytest.raises(ValueError, match="argv must contain at least one non-empty string"):
        AcpStdioConformanceProbe([])
    with pytest.raises(ValueError, match="argv must contain at least one non-empty string"):
        AcpStdioConformanceProbe([""])


def test_probe_rejects_non_positive_timeout():
    with pytest.raises(ValueError, match="response_timeout_seconds must be greater than zero"):
        AcpStdioConformanceProbe(["fixture"], response_timeout_seconds=0)
    with pytest.raises(ValueError, match="response_timeout_seconds must be greater than zero"):
        AcpStdioConformanceProbe(["fixture"], response_timeout_seconds=float("nan"))
    with pytest.raises(ValueError, match="response_timeout_seconds must be greater than zero"):
        AcpStdioConformanceProbe(["fixture"], response_timeout_seconds=float("inf"))
