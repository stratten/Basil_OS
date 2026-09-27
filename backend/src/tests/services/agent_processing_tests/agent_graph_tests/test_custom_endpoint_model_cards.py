from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from langchain_core.messages import HumanMessage

from api.core.models.model_types import ModelCapability
from api.core.models.reasoning.model_runtime_profile import (
    TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS,
    TOOL_RENDERING_SLIM_SCHEMA,
    resolve_runtime_model_profile,
)
from api.core.models.reasoning.openai_compatible_model import OpenAICompatibleModel
from api.core.services.custom_models.schemas import CustomModelCreate, CustomModelUpdate
from api.routes.model_routes import custom_routes
from api.services.agent_processing.lifecycle.execution_graph.agent_executor_factory import (
    create_langchain_llm,
)


def _custom_model_create_payload() -> dict:
    return {
        "model_id": "custom-qwen35",
        "display_name": "Custom Qwen3.5",
        "handler": "openai_compatible",
        "base_url": "https://qwen35.example/v1",
        "model_identifier": "Qwen3.5-32B-Instruct",
        "context_window": 131072,
        "max_output_tokens": 8192,
        "requires_auth": False,
        "capabilities": ["reasoning", "function_calling"],
        "features": ["streaming", "system_prompts", "function_calling"],
        "feature_config": {"request_parameters": {"omit": ["top_p"]}},
        "tool_rendering": TOOL_RENDERING_SLIM_SCHEMA,
        "tool_call_format": TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS,
        "description": "Railway-hosted Qwen3.5 endpoint",
    }


@pytest.mark.asyncio
async def test_custom_model_create_preserves_model_card_fields(monkeypatch) -> None:
    captured: dict = {}

    def fake_add_custom_model(model_id: str, config: dict) -> None:
        captured["model_id"] = model_id
        captured["config"] = config

    monkeypatch.setattr(custom_routes, "add_custom_model", fake_add_custom_model)

    response = await custom_routes.create_custom_model(
        CustomModelCreate(**_custom_model_create_payload())
    )

    config = captured["config"]
    assert response.model_id == "custom-qwen35"
    assert config["capabilities"] == ["reasoning", "function_calling"]
    assert config["feature_config"] == {"request_parameters": {"omit": ["top_p"]}}
    assert config["tool_rendering"] == TOOL_RENDERING_SLIM_SCHEMA
    assert config["tool_call_format"] == TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS


@pytest.mark.asyncio
async def test_custom_model_update_preserves_model_card_fields(monkeypatch) -> None:
    stored_config = {
        **_custom_model_create_payload(),
        "location": "cloud",
        "provider": "custom",
    }
    updated: dict = {}

    monkeypatch.setattr(
        custom_routes,
        "get_custom_models",
        lambda: {"custom-qwen35": dict(stored_config)},
    )
    monkeypatch.setattr(
        custom_routes,
        "registry_update_custom_model",
        lambda model_id, config: updated.update({"model_id": model_id, "config": config}),
    )

    response = await custom_routes.update_custom_model_endpoint(
        "custom-qwen35",
        CustomModelUpdate(
            handler="anthropic_compatible",
            capabilities=["reasoning"],
            feature_config={"request_parameters": {"omit": ["temperature"]}},
            tool_rendering="full_schema",
            tool_call_format="json_tool_call",
        ),
    )

    assert response.model_id == "custom-qwen35"
    assert updated["config"]["handler"] == "anthropic_compatible"
    assert updated["config"]["capabilities"] == ["reasoning"]
    assert updated["config"]["feature_config"] == {
        "request_parameters": {"omit": ["temperature"]}
    }
    assert updated["config"]["tool_rendering"] == "full_schema"
    assert updated["config"]["tool_call_format"] == "json_tool_call"


@pytest.mark.asyncio
async def test_custom_model_update_rejects_local_to_remote_handler_conversion(monkeypatch) -> None:
    monkeypatch.setattr(
        custom_routes,
        "get_custom_models",
        lambda: {
            "local-model": {
                "handler": "llama_cpp",
                "location": "local",
                "provider": "custom",
                "display_name": "Local model",
            }
        },
    )

    with pytest.raises(HTTPException) as error:
        await custom_routes.update_custom_model_endpoint(
            "local-model",
            CustomModelUpdate(handler="openai_compatible"),
        )

    assert error.value.status_code == 400


def test_runtime_profile_reads_custom_endpoint_model_card(monkeypatch) -> None:
    config = {
        **_custom_model_create_payload(),
        "location": "cloud",
        "provider": "custom",
    }

    monkeypatch.setattr(
        "api.core.models.reasoning.model_runtime_profile.get_model",
        lambda model_id: config if model_id == "custom-qwen35" else None,
    )

    model = OpenAICompatibleModel(Path("/tmp"), {ModelCapability.REASONING})
    model.model_name = "custom-qwen35"
    model.model_identifier = "Qwen3.5-32B-Instruct"
    model.base_url = "https://qwen35.example/v1"
    model.max_context_length = 131072
    model.max_output_tokens = 8192

    profile = resolve_runtime_model_profile(model)

    assert profile.handler == "openai_compatible"
    assert profile.tool_rendering == TOOL_RENDERING_SLIM_SCHEMA
    assert profile.tool_call_format == TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS
    assert profile.capabilities == ["reasoning", "function_calling"]


@pytest.mark.asyncio
async def test_openai_compatible_adapter_parses_function_parameter_text_tool_calls():
    from api.services.agent_processing.lifecycle.execution_graph.openai_compatible_langchain_adapter import (
        OpenAICompatibleLangChainAdapter,
    )

    content_pieces = [
        "<tool_call>\n<function=record_result>\n",
        "<parameter=value>\nbasil-local-eval\n</parameter>\n",
        "</function>\n</tool_call>",
    ]

    async def _stream():
        for piece in content_pieces:
            yield {"choices": [{"delta": {"content": piece}}]}

    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=MagicMock(return_value=_stream()),
            )
        )
    )
    adapter = OpenAICompatibleLangChainAdapter(
        model_name="custom-qwen35",
        model_identifier="Qwen3.5-32B-Instruct",
        base_url="https://qwen35.example/v1",
        max_tokens=8192,
        tool_rendering=TOOL_RENDERING_SLIM_SCHEMA,
        tool_call_format=TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS,
    )
    adapter._client = client

    result = await adapter._agenerate([HumanMessage(content="record the value")])

    message = result.generations[0].message
    assert len(message.tool_calls) == 1
    assert message.tool_calls[0]["id"] == "call_0_record_result"
    assert message.tool_calls[0]["name"] == "record_result"
    assert message.tool_calls[0]["args"] == {"value": "basil-local-eval"}


def test_agent_executor_routes_openai_compatible_custom_model(monkeypatch) -> None:
    config = {
        **_custom_model_create_payload(),
        "location": "cloud",
        "provider": "custom",
    }
    monkeypatch.setattr(
        "api.core.models.reasoning.model_runtime_profile.get_model",
        lambda model_id: config if model_id == "custom-qwen35" else None,
    )

    model = OpenAICompatibleModel(Path("/tmp"), {ModelCapability.REASONING})
    model.model_name = "custom-qwen35"
    model.model_identifier = "Qwen3.5-32B-Instruct"
    model.base_url = "https://qwen35.example/v1"
    model.api_key = None
    model.temperature = 0.1
    model.max_context_length = 131072
    model.max_output_tokens = 8192
    model._async_client = MagicMock()

    coordinator = MagicMock()
    coordinator._llm_model = model

    adapter = create_langchain_llm(coordinator)

    assert adapter.model_name == "custom-qwen35"
    assert adapter.model_identifier == "Qwen3.5-32B-Instruct"
    assert adapter.base_url == "https://qwen35.example/v1"
