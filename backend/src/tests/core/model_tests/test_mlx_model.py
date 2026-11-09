"""MlxModel loads, shares, unloads, and generates through the inherited llama.cpp machinery, with a fake MLX backend."""

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from api.core.models.base_model import ModelState
from api.core.models.model_types import ModelCapability
from api.core.models.reasoning import mlx_model
from api.core.models.reasoning.mlx_model import (
    MlxModel,
    evict_mlx_contexts_under,
    shutdown_cached_mlx_models,
)
from api.core.models.reasoning.model_runtime_profile import resolve_runtime_model_profile
from api.core.runtime import mlx_support
from api.services.agent_processing.lifecycle.execution_graph.llama_cpp_langchain_adapter import (
    create_langchain_llm_from_llama_cpp,
)

from .mlx_fakes import make_engine, response


@pytest.fixture
def mlx_state(monkeypatch):
    """Isolated engine cache, MLX reported available, and every engine built from fakes."""
    monkeypatch.setattr(mlx_model, "_MLX_ENGINE_CACHE", {})
    monkeypatch.setattr(mlx_model, "_MLX_WRAPPERS_BY_KEY", {})
    monkeypatch.setattr(mlx_model, "mlx_runtime_available", lambda: True)
    state = SimpleNamespace(
        built=[],
        responses=[response("Hi there", 2, finish_reason="stop", prompt_tokens=5)],
    )

    def build(model_path, context_window):
        harness = make_engine(
            state.responses,
            context_window=context_window,
            model_dir=model_path,
            load=False,
        )
        state.built.append(harness)
        return harness.engine

    monkeypatch.setattr(mlx_model, "_build_engine", build)
    return state


def _folder(parent: Path, name: str) -> Path:
    folder = parent / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _model(folder: Path, context_window=None) -> MlxModel:
    model = MlxModel(folder, {ModelCapability.REASONING})
    if context_window is not None:
        model.apply_registry_config({"context_window": context_window})
    return model


@pytest.mark.asyncio
async def test_load_builds_one_engine_and_uses_the_registry_context(tmp_path, mlx_state):
    folder = _folder(tmp_path, "qwen35-4b-mlx-4bit")
    model = _model(folder, context_window=8192)

    await model.load()

    assert model.state == ModelState.READY
    assert model.is_loaded
    assert model.n_ctx == 8192
    assert model.max_context_length == 8192
    assert len(mlx_state.built) == 1
    assert mlx_state.built[0].loaded == [str(folder)]


@pytest.mark.asyncio
async def test_a_second_wrapper_reuses_the_cached_engine(tmp_path, mlx_state):
    folder = _folder(tmp_path, "qwen35-4b-mlx-4bit")
    first, second = _model(folder, 4096), _model(folder, 4096)

    await first.load()
    await second.load()

    assert second.llm is first.llm
    assert len(mlx_state.built) == 1


@pytest.mark.asyncio
async def test_unload_closes_the_engine_once_marks_every_wrapper_and_allows_a_fresh_load(tmp_path, mlx_state):
    folder = _folder(tmp_path, "qwen35-4b-mlx-4bit")
    first, second = _model(folder, 4096), _model(folder, 4096)
    await first.load()
    await second.load()

    await first.unload()

    assert mlx_state.built[0].cleared == [True]
    assert first.llm is None and second.llm is None
    assert first.state == ModelState.UNLOADED and second.state == ModelState.UNLOADED
    assert mlx_model._MLX_ENGINE_CACHE == {}

    await first.unload()
    assert mlx_state.built[0].cleared == [True]

    await first.load()
    assert len(mlx_state.built) == 2
    assert first.is_loaded


@pytest.mark.asyncio
async def test_a_missing_folder_is_a_clear_error(tmp_path, mlx_state):
    model = _model(tmp_path / "not-there")
    with pytest.raises(RuntimeError, match="folder not found"):
        await model.load()
    assert model.state == ModelState.ERROR
    assert mlx_state.built == []


@pytest.mark.asyncio
async def test_an_unsupported_mac_is_a_clear_error(tmp_path, mlx_state, monkeypatch):
    monkeypatch.setattr(mlx_model, "mlx_runtime_available", lambda: False)
    model = _model(_folder(tmp_path, "qwen35-4b-mlx-4bit"))
    with pytest.raises(RuntimeError, match="Apple Silicon"):
        await model.load()
    assert model.state == ModelState.ERROR
    assert mlx_state.built == []


@pytest.mark.asyncio
async def test_an_engine_that_fails_to_load_leaves_no_cache_entry(tmp_path, mlx_state, monkeypatch):
    class ExplodingEngine:
        def load(self):
            raise OSError("bad weights")

    monkeypatch.setattr(mlx_model, "_build_engine", lambda model_path, context_window: ExplodingEngine())
    model = _model(_folder(tmp_path, "qwen35-4b-mlx-4bit"), 4096)

    with pytest.raises(RuntimeError, match="Failed to load MLX model: bad weights"):
        await model.load()

    assert model.state == ModelState.ERROR
    assert mlx_model._MLX_ENGINE_CACHE == {}


@pytest.mark.asyncio
async def test_evicting_under_a_root_closes_only_engines_inside_it(tmp_path, mlx_state):
    root = tmp_path / "models"
    inside_a, inside_b = _folder(root, "a-mlx-4bit"), _folder(root, "b-mlx-4bit")
    outside = _folder(tmp_path, "c-mlx-4bit")
    models = [_model(path, 4096) for path in (inside_a, inside_b, outside)]
    for model in models:
        await model.load()

    evicted = evict_mlx_contexts_under(root)

    assert sorted(evicted) == sorted([str(inside_a.resolve()), str(inside_b.resolve())])
    assert models[0].llm is None and models[1].llm is None
    assert models[2].llm is not None
    assert list(mlx_model._MLX_ENGINE_CACHE) == [str(outside.resolve())]


@pytest.mark.asyncio
async def test_shutdown_closes_every_cached_engine(tmp_path, mlx_state):
    models = [_model(_folder(tmp_path, name), 4096) for name in ("a-mlx-4bit", "b-mlx-4bit")]
    for model in models:
        await model.load()

    shutdown_cached_mlx_models()

    assert [harness.cleared for harness in mlx_state.built] == [[True], [True]]
    assert mlx_model._MLX_ENGINE_CACHE == {}
    assert all(model.llm is None for model in models)


@pytest.mark.asyncio
async def test_metadata_names_the_engine_and_the_folder(tmp_path, mlx_state):
    model = _model(_folder(tmp_path, "qwen35-4b-mlx-4bit"), 4096)
    await model.load()
    metadata = model.get_metadata()
    assert metadata.source == "mlx"
    assert metadata.name == "qwen35-4b-mlx-4bit"
    assert metadata.context_window == 4096


@pytest.mark.asyncio
async def test_generate_response_runs_through_the_inherited_machinery(tmp_path, mlx_state):
    model = _model(_folder(tmp_path, "qwen35-4b-mlx-4bit"), 8192)
    await model.load()

    assert await model.generate_response("hello", max_tokens=32) == "Hi there"


@pytest.mark.asyncio
async def test_usage_from_the_engine_reaches_the_telemetry_callback(tmp_path, mlx_state):
    model = _model(_folder(tmp_path, "qwen35-4b-mlx-4bit"), 8192)
    await model.load()
    captured = []

    await model.generate_response("hello", max_tokens=32, telemetry_callback=captured.append)

    assert len(captured) == 1
    assert captured[0].requested_output_tokens == 32
    assert captured[0].finish_reason == "stop"
    assert captured[0].prompt_tokens == 5
    assert captured[0].completion_tokens == 2
    assert captured[0].completion_token_source == "usage"


@pytest.mark.asyncio
async def test_the_adapter_parses_text_tool_calls_from_an_mlx_engine(monkeypatch):
    # The profile lookup walks the registry accessors, which hide MLX entries where MLX cannot run, so the test states that MLX can run.
    monkeypatch.setattr(mlx_support, "mlx_runtime_available", lambda: True)
    tool_text = "<tool_call>\n<function=lookup>\n<parameter=city>\nParis\n</parameter>\n</function>\n</tool_call>"
    harness = make_engine([response(tool_text, 20, finish_reason="stop")], context_window=8192)

    @tool
    def lookup(city: str) -> str:
        """Look up a city."""
        return city

    model = SimpleNamespace(
        llm=harness.engine,
        model_path=Path("qwen35-4b-mlx-4bit"),
        max_context_length=8192,
        max_tokens_to_sample=256,
        native_execution_lock=threading.RLock(),
    )
    profile = resolve_runtime_model_profile(model)
    assert profile.handler == "mlx"
    assert profile.tool_call_format == "function_parameter_tags"

    adapter = create_langchain_llm_from_llama_cpp(model, profile=profile, purpose="agent_execution")
    result = await adapter.bind_tools([lookup])._agenerate([HumanMessage(content="Weather in Paris?")])

    message = result.generations[0].message
    assert [call["name"] for call in message.tool_calls] == ["lookup"]
    assert message.tool_calls[0]["args"] == {"city": "Paris"}
