from types import SimpleNamespace

import pytest

from api.core.models import model_invocation
from api.core.models.model_invocation import call_model_with_prompt, supports_system_prompt


class _RecordingModel:
    model_name = "test-model"

    def __init__(self):
        self.calls = []

    async def generate_response(self, **kwargs):
        self.calls.append(kwargs)
        return "ok"


@pytest.fixture
def profile(monkeypatch):
    def install(handler, features=None):
        monkeypatch.setattr(
            model_invocation,
            "resolve_runtime_model_profile",
            lambda _model: SimpleNamespace(model_id="test-model", handler=handler, location=None),
        )
        monkeypatch.setattr(
            model_invocation,
            "has_feature",
            lambda _model_id, _feature: bool(features),
        )

    return install


@pytest.mark.parametrize("handler", ["openai_api", "anthropic_api", "gemini_api"])
@pytest.mark.asyncio
async def test_cloud_handlers_support_system_prompt(profile, handler):
    profile(handler)
    model = _RecordingModel()
    assert supports_system_prompt(model) is True
    await call_model_with_prompt(model, prompt="hi", system_prompt="be terse")
    assert model.calls[0]["prompt"] == "hi"
    assert model.calls[0]["context"] == {"system_prompt": "be terse"}


@pytest.mark.asyncio
async def test_unproven_handler_falls_back_to_prepended_text(profile):
    profile("huggingface")
    model = _RecordingModel()
    assert supports_system_prompt(model) is False
    await call_model_with_prompt(model, prompt="hi", system_prompt="be terse")
    assert model.calls[0]["prompt"] == "be terse\n\nhi"
    assert "context" not in model.calls[0]


@pytest.mark.asyncio
async def test_custom_model_honors_registry_system_prompts_feature(profile):
    profile("openai_compatible", features=["system_prompts"])
    model = _RecordingModel()
    assert supports_system_prompt(model) is True


@pytest.mark.asyncio
async def test_no_system_prompt_leaves_kwargs_unchanged(profile):
    profile("gemini_api")
    model = _RecordingModel()
    await call_model_with_prompt(model, prompt="hi")
    assert model.calls[0]["prompt"] == "hi"
    assert "context" not in model.calls[0]
