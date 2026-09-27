"""
Load Qwen2.5-VL GGUF + mmproj for analyze_with_vision local fallback.

Mirrors scripts/test_local_vision_gguf.py — requires llama-cpp-python with
Qwen25VLChatHandler. Does not download weights.
"""

from __future__ import annotations

import logging
import asyncio
import gc
from pathlib import Path
from typing import Any, Optional, Set, Tuple

from api.core.models.models_registry import get_model
from api.core.models.base_model import ModelMetadata, ModelState
from api.core.models.model_types import ModelCapability
from api.core.models.reasoning.base_reasoning import BaseReasoningModel
from api.core.runtime.hardware_capability_service import HardwareCapabilityService
from api.core.runtime.llama_cpp_load_plan import build_llama_cpp_load_plan

logger = logging.getLogger(__name__)


class _LocalQwenVlLlamaWrapper(BaseReasoningModel):
    """Qwen2.5-VL adapter for both normal text generation and vision tooling."""

    def __init__(
        self,
        llama_instance: Any,
        model_path: Path,
        max_ctx: int,
        *,
        model_id: str,
        required_capabilities: Optional[Set[ModelCapability]] = None,
    ) -> None:
        capabilities = required_capabilities or {ModelCapability.REASONING, ModelCapability.VISION}
        super().__init__(model_path, capabilities)
        self.llm = llama_instance
        self.model_path = model_path
        self.model_id = model_id
        self.max_context_length = max_ctx
        self.max_tokens_to_sample = min(4096, max_ctx // 4)
        self.state = ModelState.READY

    async def load(self) -> None:
        if self.llm is None:
            raise RuntimeError("Qwen2.5-VL llama instance is not available")
        self.state = ModelState.READY

    async def unload(self) -> None:
        self.llm = None
        self._model = None
        self.state = ModelState.UNLOADED
        gc.collect()

    async def generate_response(
        self,
        prompt: str,
        context: Optional[dict[str, Any]] = None,
        max_tokens: int = 1024,
        temperature: float = 0.1,
        top_p: float = 0.95,
        top_k: int = 40,
        **_: Any,
    ) -> str:
        if self.state != ModelState.READY:
            await self.load()
        if self.llm is None:
            raise RuntimeError("Qwen2.5-VL model is not loaded")

        if context:
            context_str = "\n".join(f"{key}: {value}" for key, value in context.items())
            prompt = f"{context_str}\n\n{prompt}"

        output = await asyncio.to_thread(
            self.llm.create_chat_completion,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
        )
        return output["choices"][0]["message"]["content"].strip()

    def _generate(self, prompt: str, max_tokens: int) -> str:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.generate_response(prompt, max_tokens=max_tokens))
        finally:
            loop.close()

    async def _generate_async(self, prompt: str, max_tokens: int) -> str:
        return await self.generate_response(prompt, max_tokens=max_tokens)

    async def validate(self) -> bool:
        try:
            response = await self.generate_response("Reply with exactly: ok", max_tokens=8)
            return bool(response.strip())
        except Exception as exc:
            logger.warning("Qwen2.5-VL validation failed: %s", exc, exc_info=True)
            return False

    def validate_capabilities(self) -> bool:
        metadata = self.get_metadata()
        return all(capability in metadata.capabilities for capability in self.required_capabilities)

    def get_metadata(self) -> ModelMetadata:
        return ModelMetadata(
            name=self.model_id,
            version="1.0",
            source="llama.cpp",
            capabilities={ModelCapability.REASONING, ModelCapability.VISION},
            description="Qwen2.5-VL GGUF model with text and image reasoning support",
            parameters={
                "n_ctx": self.max_context_length,
                "quantization": "GGUF",
                "format": "GGUF",
            },
            requirements={"llama-cpp-python": "with Qwen25VLChatHandler support"},
            memory_requirements="16GB+",
            supports_gpu=True,
            context_window=self.max_context_length,
            max_output_tokens=self.max_tokens_to_sample,
        )


def load_local_qwen25_vl_wrapper(
    models_dir: Path,
    model_id: str,
    required_capabilities: Optional[Set[ModelCapability]] = None,
) -> Tuple[Optional[_LocalQwenVlLlamaWrapper], Optional[str]]:
    """
    Load llama.cpp Llama with Qwen25VLChatHandler.

    Returns:
        (wrapper, None) on success, or (None, error_message) on failure.
    """
    cfg = get_model(model_id.strip())
    if not cfg:
        return None, f"Unknown local vision model id: {model_id}"
    if cfg.get("handler") != "llama_cpp_vision":
        return None, "Registry entry is not a llama_cpp_vision model"

    main_name = cfg.get("main_model_file")
    mmproj_name = cfg.get("mmproj_file")
    if not main_name or not mmproj_name:
        return None, "Registry entry missing main_model_file or mmproj_file"

    main_path = models_dir / main_name
    mmproj_path = models_dir / mmproj_name
    if not main_path.is_file():
        return None, f"Main GGUF not found: {main_path}"
    if not mmproj_path.is_file():
        return None, f"mmproj GGUF not found: {mmproj_path}"

    try:
        from llama_cpp import Llama
        from llama_cpp.llama_chat_format import Qwen25VLChatHandler
    except ImportError as exc:
        return None, f"llama-cpp-python Qwen VL support not available: {exc}"

    hardware_profile = HardwareCapabilityService().get_profile()
    load_plan = build_llama_cpp_load_plan(
        hardware_profile=hardware_profile,
        registry_config=cfg,
        gguf_context_window=None,
        default_context_window=8192,
        min_context_window=2048,
        max_context_window=8192,
    )

    try:
        chat_handler = Qwen25VLChatHandler(
            clip_model_path=str(mmproj_path),
            verbose=False,
        )
        llama = Llama(**load_plan.to_llama_kwargs(main_path, chat_handler=chat_handler))
    except Exception as exc:
        logger.warning("Local Qwen2.5-VL load failed: %s", exc, exc_info=True)
        return None, str(exc)

    wrapper = _LocalQwenVlLlamaWrapper(
        llama,
        main_path,
        load_plan.n_ctx,
        model_id=model_id.strip(),
        required_capabilities=required_capabilities,
    )
    logger.info(
        "👁️ Local Qwen2.5-VL vision LLM loaded: %s (n_ctx=%s, n_gpu_layers=%s, n_threads=%s)",
        main_path.name,
        load_plan.n_ctx,
        load_plan.n_gpu_layers,
        load_plan.n_threads,
    )
    return wrapper, None


def create_local_qwen_vl_langchain_adapter(models_dir: Path, model_id: str) -> Any:
    """Return a ``LlamaCppLangChainAdapter`` for local Qwen VL, or raise."""
    from api.services.agent_processing.lifecycle.execution_graph.llama_cpp_langchain_adapter import (
        create_langchain_llm_from_llama_cpp,
    )

    wrapper, err = load_local_qwen25_vl_wrapper(models_dir, model_id)
    if wrapper is None or err:
        raise RuntimeError(err or "Failed to load local Qwen2.5-VL model")
    return create_langchain_llm_from_llama_cpp(wrapper)
