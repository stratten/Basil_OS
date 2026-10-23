"""Regression coverage for feature-aware model-scenario invocation."""

import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from model_scenario_smoke_core.registry_enumeration import ModelCandidate
from model_scenario_smoke_core.scenarios import run_assistant_session


class _LocalModelWithoutWebSearch:
    def __init__(self) -> None:
        self.call_kwargs: dict[str, object] = {}

    async def generate_response(self, *, prompt: str) -> str:
        self.call_kwargs = {"prompt": prompt}
        return "DONE"


@pytest.mark.asyncio
async def test_assistant_session_omits_cloud_only_web_search_kwarg_for_local_models():
    model = _LocalModelWithoutWebSearch()
    candidate = ModelCandidate(
        model_id="local-test-model",
        display_name="Local Test Model",
        provider="local",
        location="local",
        handler="llama_cpp",
        is_custom=False,
        supports_function_calling=False,
        supports_openrouter_proxy=False,
    )

    outcome = await run_assistant_session(model, candidate)

    assert outcome.verdict == "PASS"
    assert model.call_kwargs == {"prompt": "Reply with exactly the single word: DONE"}
