"""Coverage for approved Setup Assistant model-download proposals."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from api.services.setup_assistant import action_execution_service
from api.routes.setup_assistant.models import (
    SetupExecutionStatus,
    SetupToolApprovalState,
    SetupToolCall,
)
from api.services.setup_assistant.action_execution_service import (
    SetupAssistantActionExecutionService,
)
from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import (
    build_setup_agent_system_prompt,
)


MODEL_ID = "Qwen-qwen3-8b-instruct-q4km"
PARAKEET_MODEL_ID = "NVIDIA-parakeet-tdt-0.6b-v3-quantized"


def model_service_with_catalog() -> SimpleNamespace:
    available_models = {
        "Qwen": {
            "variants": {
                "qwen3-8b-instruct-q4km": {"model_id": MODEL_ID},
            },
        },
    }
    return SimpleNamespace(
        model_downloader=SimpleNamespace(get_available_models=lambda: available_models)
    )


def approved_model_download_proposal(model_ids: list[str]) -> SetupToolCall:
    return SetupToolCall(
        id="proposal-model-download",
        tool_name="start_model_downloads",
        payload={"model_ids": model_ids},
        approval_state=SetupToolApprovalState.approved,
        user_visible_summary="Download the recommended local model.",
        mutates_external_state=True,
    )


@pytest.mark.asyncio
async def test_approved_model_download_proposal_starts_the_matching_model() -> None:
    download_manager = SimpleNamespace(
        start=AsyncMock(return_value=SimpleNamespace(status="queued"))
    )
    service = SetupAssistantActionExecutionService(
        download_manager=download_manager,
        model_service=model_service_with_catalog(),
    )

    results = await service.execute_approved_setup_actions(
        actions=[],
        tool_calls=[approved_model_download_proposal([MODEL_ID])],
    )

    download_manager.start.assert_awaited_once_with("Qwen", "qwen3-8b-instruct-q4km")
    assert len(results) == 1
    assert results[0].status == SetupExecutionStatus.applied
    assert results[0].result_payload == {
        "model_id": MODEL_ID,
        "model_type": "Qwen",
        "variant": "qwen3-8b-instruct-q4km",
        "download_status": "queued",
    }


@pytest.mark.asyncio
async def test_model_download_proposal_propagates_manager_failure_status() -> None:
    download_manager = SimpleNamespace(
        start=AsyncMock(return_value=SimpleNamespace(status="failed"))
    )
    service = SetupAssistantActionExecutionService(
        download_manager=download_manager,
        model_service=model_service_with_catalog(),
    )

    results = await service.execute_approved_setup_actions(
        actions=[],
        tool_calls=[approved_model_download_proposal([MODEL_ID])],
    )

    assert results[0].status == SetupExecutionStatus.failed


@pytest.mark.asyncio
async def test_transcription_download_becomes_the_default_after_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    available_models = {
        "NVIDIA": {
            "variants": {
                "parakeet-tdt-0.6b-v3-quantized": {"model_id": PARAKEET_MODEL_ID},
            },
        },
    }
    download_manager = SimpleNamespace(
        start=AsyncMock(
            return_value=SimpleNamespace(
                model_id=PARAKEET_MODEL_ID,
                status="queued",
            )
        ),
        wait_for_terminal_status=AsyncMock(
            return_value=SimpleNamespace(status="completed")
        ),
    )
    preferences = SimpleNamespace(
        models=SimpleNamespace(transcription_model="base")
    )
    save_preferences = Mock()
    scheduled_tasks: list[asyncio.Task[object]] = []
    original_create_task = asyncio.create_task

    def capture_task(coro, *, name=None):
        task = original_create_task(coro, name=name)
        scheduled_tasks.append(task)
        return task

    monkeypatch.setattr(action_execution_service.asyncio, "create_task", capture_task)
    monkeypatch.setattr(
        "api.core.preferences.preferences_io.load_preferences",
        lambda: preferences,
    )
    monkeypatch.setattr(
        "api.core.preferences.preferences_io.save_preferences",
        save_preferences,
    )
    service = SetupAssistantActionExecutionService(
        download_manager=download_manager,
        model_service=SimpleNamespace(
            model_downloader=SimpleNamespace(
                get_available_models=lambda: available_models
            )
        ),
    )

    await service.execute_approved_setup_actions(
        actions=[],
        tool_calls=[approved_model_download_proposal([PARAKEET_MODEL_ID])],
    )
    await asyncio.gather(*scheduled_tasks)

    assert preferences.models.transcription_model == PARAKEET_MODEL_ID
    save_preferences.assert_called_once_with(preferences)


@pytest.mark.asyncio
async def test_model_download_proposal_rejects_an_unknown_model() -> None:
    download_manager = SimpleNamespace(start=AsyncMock())
    service = SetupAssistantActionExecutionService(
        download_manager=download_manager,
        model_service=model_service_with_catalog(),
    )

    results = await service.execute_approved_setup_actions(
        actions=[],
        tool_calls=[approved_model_download_proposal(["Missing-no-such-model"])],
    )

    download_manager.start.assert_not_awaited()
    assert results[0].status == SetupExecutionStatus.failed
    assert "not available for download" in results[0].message


@pytest.mark.asyncio
async def test_model_download_proposal_requires_runtime_services() -> None:
    service = SetupAssistantActionExecutionService()

    results = await service.execute_approved_setup_actions(
        actions=[],
        tool_calls=[approved_model_download_proposal([MODEL_ID])],
    )

    assert results[0].status == SetupExecutionStatus.failed
    assert results[0].message == "Model download execution is unavailable."


def test_setup_agent_prompt_requires_hardware_fit_model_recommendations() -> None:
    prompt = build_setup_agent_system_prompt()

    assert "hardware_fits_memory_budget" in prompt
    assert '`mutation_tool_name="start_model_downloads"`' in prompt
    assert "first couple of `agent_synthesis` turns" in prompt
