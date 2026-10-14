"""Executing a service method must not re-run capability discovery or consult a dead validator."""

from __future__ import annotations

import pytest

from api.services.agent_processing.service_capabilities.service_capability_analyzer import ServiceCapabilityAnalyzer
from api.services.agent_processing.service_capabilities.service_execution_engine import ServiceExecutionEngine


class _EchoService:
    async def echo(self, text: str = "") -> str:
        return f"echo:{text}"


class _ExplodingAnalyzer(ServiceCapabilityAnalyzer):
    def discover_available_services(self, *args, **kwargs):
        raise AssertionError("discover_available_services must not run per call")


def test_analyzer_no_longer_exposes_the_dead_validator():
    assert not hasattr(ServiceCapabilityAnalyzer, "validate_service_method")
    assert not hasattr(ServiceExecutionEngine, "set_cached_capabilities")


@pytest.mark.asyncio
async def test_execute_does_not_run_discovery_and_still_executes():
    engine = ServiceExecutionEngine(_ExplodingAnalyzer())
    engine.register_service("echo_service", _EchoService())

    result = await engine.execute_service_method("echo_service", "echo", {"text": "hi"})

    assert result.success is True
    assert result.result == "echo:hi"


@pytest.mark.asyncio
async def test_unknown_method_reports_a_failed_result_instead_of_raising():
    engine = ServiceExecutionEngine(_ExplodingAnalyzer())
    engine.register_service("echo_service", _EchoService())

    result = await engine.execute_service_method("echo_service", "missing", {})

    assert result.success is False
    assert result.error
