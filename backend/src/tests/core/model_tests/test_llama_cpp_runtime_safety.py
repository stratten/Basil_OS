from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from api.services.agent_processing.lifecycle.execution_graph.llama_cpp_langchain_adapter import (
    create_langchain_llm_from_llama_cpp,
)


_RUNTIME_VALIDATION_ENV = "RUN_LOCAL_MODEL_RUNTIME_VALIDATION"
_RUNTIME_MODEL_PATH_ENV = "BASIL_LOCAL_MODEL_RUNTIME_PATH"
_DEFAULT_MODEL_RELATIVE_PATH = Path(".basil/models/qwen3-8b-instruct-q4km.gguf")


class _ConcurrentFakeLlama:
    def __init__(self) -> None:
        self._counter_lock = threading.Lock()
        self.active_calls = 0
        self.maximum_active_calls = 0

    def create_chat_completion(self, **_kwargs):
        with self._counter_lock:
            self.active_calls += 1
            self.maximum_active_calls = max(self.maximum_active_calls, self.active_calls)
        try:
            time.sleep(0.05)
            yield {"choices": [{"delta": {"content": "ok"}}]}
        finally:
            with self._counter_lock:
                self.active_calls -= 1

    def n_ctx(self) -> int:
        return 128


def _adapter_for_fake_llama(fake_llama: _ConcurrentFakeLlama):
    model = SimpleNamespace(
        llm=fake_llama,
        model_path=Path("test-qwen.gguf"),
        max_context_length=128,
        max_tokens_to_sample=8,
        native_execution_lock=threading.RLock(),
    )
    return create_langchain_llm_from_llama_cpp(model)


@pytest.mark.asyncio
async def test_bound_adapters_serialize_shared_native_context() -> None:
    fake_llama = _ConcurrentFakeLlama()
    root_adapter = _adapter_for_fake_llama(fake_llama)
    bound_adapter = root_adapter.bind_tools([])

    first, second = await asyncio.gather(
        root_adapter._agenerate([HumanMessage(content="first")]),
        bound_adapter._agenerate([HumanMessage(content="second")]),
    )

    assert first.generations[0].message.content == "ok"
    assert second.generations[0].message.content == "ok"
    assert fake_llama.maximum_active_calls == 1


def _model_path() -> Path:
    configured = os.getenv(_RUNTIME_MODEL_PATH_ENV)
    if configured:
        return Path(configured).expanduser()
    original_home = Path(os.environ.get("BASIL_TEST_ORIGINAL_HOME", Path.home()))
    return original_home / _DEFAULT_MODEL_RELATIVE_PATH


def _runtime_script(model_path: Path, backend: str) -> str:
    return f'''import asyncio
from dataclasses import replace
import json
from pathlib import Path

from langchain_core.messages import HumanMessage
from api.core.models.model_types import ModelCapability
from api.core.models.reasoning.llama_cpp_model import LlamaCppModel
from api.services.agent_processing.lifecycle.execution_graph.llama_cpp_langchain_adapter import create_langchain_llm_from_llama_cpp


async def main() -> None:
    model = LlamaCppModel(Path({str(model_path)!r}), {{ModelCapability.REASONING}})
    if {backend!r} == "cpu":
        model.hardware_profile = replace(
            model.hardware_profile,
            gpu_available=False,
            gpu_backend=None,
            recommended_gpu_layers=0,
        )
    model.max_tokens_to_sample = 16
    await model.load()
    adapter = create_langchain_llm_from_llama_cpp(model)
    bound_adapter = adapter.bind_tools([])
    results = await asyncio.gather(
        adapter._agenerate([HumanMessage(content="Reply with exactly: local")]),
        bound_adapter._agenerate([HumanMessage(content="Reply with exactly: local")]),
    )
    contents = [result.generations[0].message.content for result in results]
    assert all(content.strip() for content in contents)
    print(json.dumps({{"backend": {backend!r}, "contents": contents}}))


asyncio.run(main())
'''


@pytest.mark.integration
@pytest.mark.parametrize("backend", ["cpu", "metal"])
def test_real_local_model_serializes_concurrent_adapter_requests(backend: str) -> None:
    if os.getenv(_RUNTIME_VALIDATION_ENV) != "1":
        pytest.skip(f"Set {_RUNTIME_VALIDATION_ENV}=1 to run the real GGUF runtime check.")

    model_path = _model_path()
    if not model_path.is_file():
        pytest.skip(f"The local GGUF fixture is not installed at {model_path}.")

    source_root = Path(__file__).parents[3]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(source_root)
    completed = subprocess.run(
        [sys.executable, "-c", _runtime_script(model_path, backend)],
        cwd=source_root.parent,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result_line = next(
        line for line in reversed(completed.stdout.splitlines()) if line.startswith("{")
    )
    result = json.loads(result_line)
    assert result["backend"] == backend
    assert len(result["contents"]) == 2
