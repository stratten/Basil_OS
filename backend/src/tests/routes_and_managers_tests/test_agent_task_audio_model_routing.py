"""Tests for AgentTask audio model-selection routing."""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.datastructures import Headers, UploadFile

from api.routes.agent_tasks import audio_routes


@pytest.mark.asyncio
async def test_process_audio_forwards_selected_reasoning_model(monkeypatch: pytest.MonkeyPatch) -> None:
    transcription_service = SimpleNamespace(transcribe=AsyncMock(return_value="Draft the launch summary"))
    monkeypatch.setattr(audio_routes, "resolve_transcription_service", lambda: transcription_service)

    service = SimpleNamespace(
        get_current_screenshot_data=lambda: None,
        process_agent_task_direct=AsyncMock(return_value={"success": True}),
    )
    audio_file = UploadFile(
        file=BytesIO(b"\x00" * 64),
        filename="agent-task.wav",
        headers=Headers({"content-type": "audio/wav"}),
    )

    response = await audio_routes.process_agent_task_audio(
        audio_file=audio_file,
        agent_task_id=None,
        root_task_id=None,
        previous_task_id=None,
        reference_paths=None,
        model_id="reasoning-model-123",
        service=service,
    )

    assert response.success is True
    service.process_agent_task_direct.assert_awaited_once_with(
        agent_task="Draft the launch summary",
        clarification_agent_task=None,
        agent_task_id=None,
        root_task_id=None,
        previous_task_id=None,
        reference_paths=None,
        model_id="reasoning-model-123",
    )
