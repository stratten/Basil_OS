"""Coverage for the setup agent's live model-status check and its verify-first prompt rule."""

import asyncio
from types import SimpleNamespace

from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import (
    build_setup_agent_system_prompt,
)
from api.services.setup_assistant.agent_graph.setup_agent_tooling import discovery_tools
from api.services.setup_assistant.agent_graph.setup_agent_tooling.tool_registry import (
    create_setup_agent_tools_for_factory,
)

INSTALLED_REASONING_ID = "Qwen-qwen3-8b-instruct-q4km"
DOWNLOADING_ID = "NVIDIA-parakeet-tdt-0.6b-v3-quantized"


class FakeProgressTracker:
    def get_operation_status(self, model_id):
        return "downloading" if model_id == DOWNLOADING_ID else "unknown"

    def get_progress(self, model_id):
        return 0.42 if model_id == DOWNLOADING_ID else 0.0


class FakeDownloader:
    progress_tracker = FakeProgressTracker()

    def get_installed_models(self):
        return {"Qwen": {"variants": {"qwen3-8b-instruct-q4km": {}}}}


def factory_with_fake_downloader():
    return SimpleNamespace(
        discovery_service=SimpleNamespace(
            model_service=SimpleNamespace(model_downloader=FakeDownloader())
        )
    )


def test_status_reports_installed_models_and_in_flight_downloads():
    result = asyncio.run(discovery_tools.check_setup_model_status(factory_with_fake_downloader()))

    assert INSTALLED_REASONING_ID in result["installed_model_ids"]
    assert DOWNLOADING_ID not in result["installed_model_ids"]
    assert result["downloads_with_recorded_activity"] == [
        {"model_id": DOWNLOADING_ID, "operation_status": "downloading", "progress_percent": 42}
    ]


def test_status_omits_models_that_were_never_started():
    result = asyncio.run(discovery_tools.check_setup_model_status(factory_with_fake_downloader()))

    reported_ids = {entry["model_id"] for entry in result["downloads_with_recorded_activity"]}
    assert reported_ids == {DOWNLOADING_ID}


def test_check_model_status_is_registered_as_a_setup_tool():
    async def unused(*args, **kwargs):
        return {}

    class RegistryFactory:
        def __getattr__(self, name):
            return unused

    tool_names = {tool.name for tool in create_setup_agent_tools_for_factory(RegistryFactory())}

    assert "check_model_status" in tool_names


def test_system_prompt_requires_verifying_before_claiming_something_is_pending():
    prompt = build_setup_agent_system_prompt()

    assert "Verify before you say that something has not happened" in prompt
    assert "check_model_status" in prompt
