"""Regression tests for activity analysis token budget and honest failure reporting."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.core.models.model_types import ModelCapability
from api.services.capture.manual.capture_handler import CaptureHandler
from api.services.image_processing.image_models import (
    ActivityAnalysis,
    AnalysisError,
    ProcessingResponse,
    raise_if_analysis_unusable,
)
from api.services.image_processing.image_processing_service import (
    ANALYSIS_MAX_TOKENS,
    ImageProcessor,
)


class _FakeModel:
    def __init__(self, response: str = '{"activity_type":"coding","context":"x","content_summary":"y"}') -> None:
        self.response = response
        self.last_max_tokens: int | None = None

    async def generate_response(self, prompt: str, max_tokens: int | None = None, **kwargs) -> str:
        self.last_max_tokens = max_tokens
        return self.response


@pytest.fixture
def image_processor() -> ImageProcessor:
    model_service = MagicMock()
    processor = ImageProcessor(model_service)
    processor.logger = MagicMock()
    return processor


def test_parse_activity_analysis_raises_on_unparseable_response(image_processor: ImageProcessor):
    with pytest.raises(AnalysisError, match="no parseable activity analysis JSON"):
        image_processor._parse_activity_analysis("not json at all")


@pytest.mark.asyncio
async def test_analyze_text_only_passes_analysis_max_tokens(image_processor: ImageProcessor):
    model = _FakeModel()
    image_processor._get_model_for_task = AsyncMock(return_value=model)  # type: ignore[method-assign]

    result = await image_processor.analyze_text_only(
        "some screen text",
        "Cursor",
        pre_loaded_model=model,
    )

    assert model.last_max_tokens == ANALYSIS_MAX_TOKENS
    assert result["analysis_type"] == "text-only"
    assert result["analysis"].activity_type == "coding"


@pytest.mark.asyncio
async def test_analyze_text_only_uses_qwen35_activity_analysis_budget(image_processor: ImageProcessor):
    class _LocalQwen35Model(_FakeModel):
        handler = "llama_cpp"
        model_name = "Qwen-qwen35-4b-q4km"

    model = _LocalQwen35Model()
    image_processor._get_model_for_task = AsyncMock(return_value=model)  # type: ignore[method-assign]

    await image_processor.analyze_text_only(
        "some screen text",
        "Cursor",
        pre_loaded_model=model,
    )

    assert model.last_max_tokens == 1024


@pytest.mark.asyncio
async def test_analyze_text_only_logs_telemetry_for_local_model(image_processor: ImageProcessor, caplog):
    import logging
    from api.core.models.reasoning.llama_cpp_model import LocalCompletionTelemetry

    image_processor.logger = logging.getLogger("test.image_processor")

    class _LocalModel:
        handler = "llama_cpp"
        model_name = "Qwen-qwen35-4b-q4km"

        async def generate_response(self, **kwargs):
            callback = kwargs.get("telemetry_callback")
            if callback is not None:
                callback(
                    LocalCompletionTelemetry(
                        requested_output_tokens=kwargs.get("max_tokens", 0),
                        finish_reason="stop",
                        prompt_tokens=50,
                        completion_tokens=25,
                        total_tokens=75,
                        completion_token_source="usage",
                        raw_completion_tokens=25,
                        visible_completion_tokens=20,
                        lock_wait_ms=1,
                        native_duration_ms=10,
                        completed_at_monotonic_ms=1,
                    )
                )
            return '{"activity_type":"coding","context":"x","content_summary":"y"}'

    model = _LocalModel()
    image_processor._get_model_for_task = AsyncMock(return_value=model)  # type: ignore[method-assign]

    caplog.set_level("INFO")
    result = await image_processor.analyze_text_only(
        "some screen text",
        "Cursor",
        pre_loaded_model=model,
        activity_generation_context={
            "run_id": "run-1",
            "activity_id": "activity-1",
            "analysis_model_id": "Qwen-qwen35-4b-q4km",
            "analysis_requested_tokens": ANALYSIS_MAX_TOKENS,
            "unsafe_field": "must not appear",
        },
    )

    assert result["generation_telemetry"]["completion_tokens"] == 25
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "activity_local_generation_completed" in messages
    assert "completion_tokens=25" in messages
    assert "unsafe_field" not in messages


@pytest.mark.asyncio
async def test_analyze_text_only_logs_fallback_tokens_and_cap_hit(
    image_processor: ImageProcessor,
    caplog,
):
    import logging
    from api.core.models.reasoning.llama_cpp_model import LocalCompletionTelemetry

    image_processor.logger = logging.getLogger("test.image_processor_fallback")

    class _LocalModel:
        handler = "llama_cpp"
        model_name = "Qwen-qwen35-4b-q4km"

        async def generate_response(self, **kwargs):
            kwargs["telemetry_callback"](
                LocalCompletionTelemetry(
                    requested_output_tokens=kwargs["max_tokens"],
                    finish_reason="length",
                    prompt_tokens=None,
                    completion_tokens=None,
                    total_tokens=None,
                    completion_token_source="tokenizer_fallback",
                    raw_completion_tokens=4096,
                    visible_completion_tokens=12,
                    lock_wait_ms=2,
                    native_duration_ms=20,
                    completed_at_monotonic_ms=2,
                )
            )
            return '{"activity_type":"coding","context":"x","content_summary":"y"}'

    model = _LocalModel()
    caplog.set_level("INFO")
    await image_processor.analyze_text_only(
        "some screen text",
        "Cursor",
        pre_loaded_model=model,
        activity_generation_context={
            "run_id": "run-2",
            "activity_id": "activity-2",
            "analysis_model_id": "Qwen-qwen35-4b-q4km",
            "analysis_requested_tokens": ANALYSIS_MAX_TOKENS,
        },
    )

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "completion_token_source=tokenizer_fallback" in messages
    assert "raw_completion_tokens=4096" in messages
    assert "visible_completion_tokens=12" in messages
    assert "cap_hit=True" in messages


@pytest.mark.asyncio
async def test_analyze_text_only_does_not_invoke_telemetry_for_cloud_like_model(
    image_processor: ImageProcessor,
):
    captured: list[object] = []

    class _CloudModel:
        handler = "openai_api"
        model_name = "gpt-test"

        async def generate_response(self, **kwargs):
            callback = kwargs.get("telemetry_callback")
            if callback is not None:
                captured.append(callback)
            return '{"activity_type":"coding","context":"x","content_summary":"y"}'

    model = _CloudModel()
    image_processor._get_model_for_task = AsyncMock(return_value=model)  # type: ignore[method-assign]

    result = await image_processor.analyze_text_only(
        "some screen text",
        "Cursor",
        pre_loaded_model=model,
        activity_generation_context={
            "run_id": "run-1",
            "activity_id": "activity-1",
            "analysis_model_id": "gpt-test",
            "analysis_requested_tokens": ANALYSIS_MAX_TOKENS,
        },
    )

    assert result["analysis_type"] == "text-only"
    assert captured == []
    assert "generation_telemetry" not in result


@pytest.mark.asyncio
async def test_analyze_text_only_returns_error_envelope_on_parse_failure(
    image_processor: ImageProcessor,
    caplog,
):
    import logging

    image_processor.logger = logging.getLogger("test.image_processor_parse_failure")
    model = _FakeModel(response="garbage output")
    image_processor._get_model_for_task = AsyncMock(return_value=model)  # type: ignore[method-assign]

    caplog.set_level("INFO")
    result = await image_processor.analyze_text_only(
        "some screen text",
        "Cursor",
        pre_loaded_model=model,
        activity_generation_context={
            "run_id": "run-parse",
            "activity_id": "activity-parse",
            "analysis_model_id": "Qwen-qwen35-4b-q4km",
            "analysis_requested_tokens": ANALYSIS_MAX_TOKENS,
        },
    )

    assert result["analysis_type"] == "error"
    assert result["analysis"].activity_type == "error"
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "parse_outcome=error" in messages
    assert "error_category=parse" in messages


def _response(analysis_type: str, error: str | None = None) -> ProcessingResponse:
    return ProcessingResponse(
        extracted_text="screen text",
        analysis=ActivityAnalysis(context="c", content_summary="s"),
        analysis_type=analysis_type,
        error=error,
    )


@pytest.mark.parametrize("analysis_type", ["error", "none"])
def test_raise_if_analysis_unusable_rejects_failed_analysis(analysis_type: str):
    with pytest.raises(AnalysisError, match=f"analysis_type={analysis_type}"):
        raise_if_analysis_unusable(_response(analysis_type))


def test_raise_if_analysis_unusable_includes_underlying_error():
    with pytest.raises(AnalysisError, match="parse failure"):
        raise_if_analysis_unusable(_response("error", error="parse failure"))


def test_raise_if_analysis_unusable_accepts_a_real_analysis():
    raise_if_analysis_unusable(_response("text-only"))


def _handler_for_capture(processing_result: ProcessingResponse) -> CaptureHandler:
    handler = CaptureHandler.__new__(CaptureHandler)
    handler.logger = MagicMock()
    handler.storage = MagicMock()
    handler.knowledge_base = MagicMock()
    handler.knowledge_base.store_activity = AsyncMock(return_value="activity-1")
    handler.capture_service = MagicMock()
    handler.capture_service.capture_temp_window = AsyncMock(
        return_value=("/tmp/shot.png", "Cursor", "main.py", {})
    )
    handler.image_processor = MagicMock()
    handler.image_processor.process_image = AsyncMock(return_value=processing_result)
    return handler


@pytest.mark.asyncio
async def test_manual_capture_does_not_store_a_failed_analysis():
    """A failed analysis is reported, not written to disk or the knowledge base."""
    handler = _handler_for_capture(_response("error", error="parse failure"))

    result = await handler.capture_and_process(temporary=True)

    assert result["success"] is False
    assert "parse failure" in result["error"]
    handler.knowledge_base.store_activity.assert_not_awaited()
    handler.storage.get_processed_path.assert_not_called()


@pytest.mark.asyncio
async def test_manual_capture_still_stores_a_successful_analysis():
    """The gate must not disturb the normal capture flow."""
    handler = _handler_for_capture(_response("text-only"))

    result = await handler.capture_and_process(temporary=True)

    assert result.get("success") is not False
    assert result["activity_id"] == "activity-1"
    handler.knowledge_base.store_activity.assert_awaited_once()
