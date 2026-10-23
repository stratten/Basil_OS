"""Tests for MeetingAnalyzer's one-time local fallback retry when the preferred
reasoning model is completely unreachable before any analysis mode has succeeded."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.services.whisper_live_core.post_processing.meeting_analyzer import MeetingAnalyzer
from api.services.whisper_live_core.post_processing.meeting_analysis_models import AnalysisMode
from api.core.models.model_types import ModelCapability


def _make_analyzer(model) -> MeetingAnalyzer:
    analyzer = MeetingAnalyzer.__new__(MeetingAnalyzer)
    analyzer.meeting_id = "meeting-1"
    analyzer.model_id = None
    analyzer.prompt_builder = MagicMock()
    analyzer.transcript = {}
    analyzer.metadata = None
    analyzer._identity_block = None
    analyzer._capability_digest = None
    analyzer.model = model
    analyzer._structured_output_enforcement = {}
    analyzer._safety_omissions = []
    analyzer._any_mode_succeeded = False
    analyzer.fallback_model_used = None
    return analyzer


@pytest.mark.asyncio
async def test_analyze_mode_retries_local_fallback_on_unreachable_model():
    primary_model = AsyncMock()
    analyzer = _make_analyzer(primary_model)

    fallback_model = AsyncMock()
    fallback_model.model_name = "local-fallback-model"

    call_count = {"n": 0}

    async def fake_analyze_mode(*, model, **kwargs):
        call_count["n"] += 1
        if model is primary_model:
            raise ConnectionError("nodename nor servname provided, or not known")
        assert model is fallback_model
        return "mode result from local fallback"

    mock_executor = MagicMock()
    mock_executor.analyze_mode = AsyncMock(side_effect=fake_analyze_mode)
    mock_executor.safety_omissions = []
    mock_executor.enforcement_modes = set()

    mock_model_usage_service = MagicMock()
    mock_model_usage_service.get_designated_local_fallback_model = AsyncMock(return_value=fallback_model)

    with patch(
        "api.services.whisper_live_core.post_processing.meeting_analyzer.MeetingAnalysisExecutor",
        return_value=mock_executor,
    ), patch(
        "api.services.whisper_live_core.post_processing.meeting_analyzer.ModelUsageService",
        return_value=mock_model_usage_service,
    ):
        result = await analyzer._analyze_mode(mode=AnalysisMode.SUMMARY, custom_instructions=None)

    assert result == "mode result from local fallback"
    assert analyzer.fallback_model_used == "local-fallback-model"
    assert analyzer.model is fallback_model
    assert analyzer._any_mode_succeeded is True
    assert call_count["n"] == 2
    mock_model_usage_service.get_designated_local_fallback_model.assert_awaited_once_with(
        {ModelCapability.REASONING}
    )


@pytest.mark.asyncio
async def test_analyze_mode_does_not_fallback_once_a_prior_mode_succeeded():
    primary_model = AsyncMock()
    analyzer = _make_analyzer(primary_model)
    analyzer._any_mode_succeeded = True  # a prior mode already produced a result this run

    original_error = ConnectionError("nodename nor servname provided, or not known")
    mock_executor = MagicMock()
    mock_executor.analyze_mode = AsyncMock(side_effect=original_error)
    mock_executor.safety_omissions = []
    mock_executor.enforcement_modes = set()

    mock_model_usage_service = MagicMock()
    mock_model_usage_service.get_designated_local_fallback_model = AsyncMock()

    with patch(
        "api.services.whisper_live_core.post_processing.meeting_analyzer.MeetingAnalysisExecutor",
        return_value=mock_executor,
    ), patch(
        "api.services.whisper_live_core.post_processing.meeting_analyzer.ModelUsageService",
        return_value=mock_model_usage_service,
    ):
        with pytest.raises(RuntimeError):
            await analyzer._analyze_mode(mode=AnalysisMode.SUMMARY, custom_instructions=None)

    mock_model_usage_service.get_designated_local_fallback_model.assert_not_awaited()
    assert analyzer.model is primary_model
    assert analyzer.fallback_model_used is None
