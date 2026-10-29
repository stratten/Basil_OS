from pathlib import Path

import pytest

from api.core.models.model_types import ModelCapability
from api.core.services.model_service import ModelService
from api.services.agent_processing.tools.vision.local_qwen_vl_loader import _LocalQwenVlLlamaWrapper


class FakeLlama:
    def create_chat_completion(self, **kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "content": f"text ok: {kwargs['messages'][0]['content'][:12]}",
                    },
                    "finish_reason": "stop",
                }
            ]
        }


@pytest.mark.asyncio
async def test_model_service_loads_llama_cpp_vision_handler(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = []

    def fake_loader(models_dir, model_id, required_capabilities=None):
        calls.append((models_dir, model_id, required_capabilities))
        return (
            _LocalQwenVlLlamaWrapper(
                FakeLlama(),
                tmp_path / "Qwen3VL-8B-Instruct-Q4_K_M.gguf",
                8192,
                model_id=model_id,
                required_capabilities=required_capabilities,
            ),
            None,
        )

    monkeypatch.setattr(
        "api.services.agent_processing.tools.vision.local_qwen_vl_loader.load_local_vision_wrapper",
        fake_loader,
    )
    service = ModelService(tmp_path)

    model = await service.load_model_by_id(
        "Qwen-qwen3vl-8b-instruct-q4km",
        {ModelCapability.VISION},
    )

    assert calls
    assert calls[0][1] == "Qwen-qwen3vl-8b-instruct-q4km"
    assert ModelCapability.VISION in model.get_metadata().capabilities


@pytest.mark.asyncio
async def test_llama_cpp_vision_adapter_supports_text_only_generation(tmp_path: Path) -> None:
    model = _LocalQwenVlLlamaWrapper(
        FakeLlama(),
        tmp_path / "Qwen3VL-8B-Instruct-Q4_K_M.gguf",
        8192,
        model_id="Qwen-qwen3vl-8b-instruct-q4km",
        required_capabilities={ModelCapability.REASONING},
    )

    response = await model.generate_response("Describe the current app state.", max_tokens=16)

    assert response.startswith("text ok:")
    assert model.validate_capabilities()


@pytest.mark.asyncio
async def test_model_service_vision_model_does_not_fail_unknown_handler(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_loader(models_dir, model_id, required_capabilities=None):
        return (
            _LocalQwenVlLlamaWrapper(
                FakeLlama(),
                tmp_path / "Qwen3VL-8B-Instruct-Q4_K_M.gguf",
                8192,
                model_id=model_id,
                required_capabilities=required_capabilities,
            ),
            None,
        )

    monkeypatch.setattr(
        "api.services.agent_processing.tools.vision.local_qwen_vl_loader.load_local_vision_wrapper",
        fake_loader,
    )
    service = ModelService(tmp_path)

    model = await service.load_model_by_id(
        "Qwen-qwen3vl-8b-instruct-q4km",
        {ModelCapability.REASONING, ModelCapability.VISION},
    )
    response = await model.generate_response("What is visible in this attached image path?")

    assert "text ok:" in response
