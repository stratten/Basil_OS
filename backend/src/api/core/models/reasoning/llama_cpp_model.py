from pathlib import Path
import gc
import os
import sys
import time
import threading
import logging
import asyncio
import re
import json
import weakref
from dataclasses import dataclass, replace
from typing import Callable, Set, Dict, Any, AsyncGenerator, Iterator, Optional, List, Tuple

from ...logging.api_logger import api_logger
from ...runtime.hardware_capability_service import HardwareCapabilityService
from ...runtime.llama_cpp_load_plan import build_llama_cpp_load_plan
from ...runtime.llama_cpp_memory_budget import CONTEXT_STEP, MEMORY_FLOOR_CONTEXT, read_model_memory_facts
from ..base_model import ModelMetadata, ModelState
from ..model_types import ModelCapability
from .base_reasoning import (
    DEFAULT_STREAMING_MAX_TOKENS,
    BaseReasoningModel,
    ReasoningTruncatedError,
    has_unterminated_reasoning,
    strip_inline_reasoning,
)
from .local_model_failure import (
    DecodeFailure,
    LocalModelDecodeError,
    LocalModelFailureKind,
    parse_decode_failure,
)
from .streaming_async_bridge import async_iter_sync_stream

# Mirrors the max_tokens default on generate_response, so the prompt and message
# entry points give a caller that names no budget the same room to answer.
DEFAULT_MAX_TOKENS = 1024
_LOCAL_RUNTIME_TRACE_ENV = "BASIL_LOCAL_RUNTIME_TRACE"

logger = api_logger.getChild("llama_cpp_model")

# Global model cache to keep models loaded between requests
_MODEL_CACHE = {}
_MODEL_EXECUTION_LOCKS: Dict[str, Any] = {}
# Context ceilings set after a native decode failed, keyed like _MODEL_CACHE. Every wrapper on the same GGUF plans its next load under the ceiling, so a reload never climbs back to the size that failed.
_CONTEXT_CEILINGS_BY_KEY: Dict[str, int] = {}


def _context_ceiling_for(cache_key: str) -> Optional[int]:
    with _MODEL_EXECUTION_LOCKS_GUARD:
        return _CONTEXT_CEILINGS_BY_KEY.get(cache_key)


def _set_context_ceiling(cache_key: str, ceiling: int) -> None:
    with _MODEL_EXECUTION_LOCKS_GUARD:
        _CONTEXT_CEILINGS_BY_KEY[cache_key] = ceiling
_MODEL_EXECUTION_LOCKS_GUARD = threading.Lock()


class LlamaCppTokenizerWrapper:
    """Exposes llama.cpp tokenization through the encode/decode interface base_reasoning expects."""

    exact_token_counts = True

    def __init__(self, llm: Any) -> None:
        self.llm = llm

    def encode(self, text: Any) -> List[int]:
        return self.llm.tokenize(text.encode() if isinstance(text, str) else text)

    def decode(self, tokens: Any) -> str:
        return self.llm.detokenize(tokens).decode()


def _get_model_execution_lock(model_path: Path) -> Any:
    """Return the shared native-execution lock for one canonical GGUF path."""
    cache_key = str(model_path.expanduser().resolve())
    with _MODEL_EXECUTION_LOCKS_GUARD:
        lock = _MODEL_EXECUTION_LOCKS.get(cache_key)
        if lock is None:
            lock = threading.RLock()
            _MODEL_EXECUTION_LOCKS[cache_key] = lock
        return lock


def shutdown_cached_llama_cpp_models() -> None:
    """Close cached native contexts before interpreter teardown."""
    with _MODEL_EXECUTION_LOCKS_GUARD:
        cached_models = list(_MODEL_CACHE.items())
        _MODEL_CACHE.clear()

    for cache_key, llm in cached_models:
        with _MODEL_EXECUTION_LOCKS_GUARD:
            lock = _MODEL_EXECUTION_LOCKS.get(cache_key)
        if lock is None:
            lock = threading.RLock()
        with lock:
            close = getattr(llm, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except Exception:
                logger.warning(
                    "Failed to close cached llama.cpp model: %s",
                    cache_key,
                    exc_info=True,
                )


# Wrappers that share one native context, keyed like _MODEL_CACHE. Unloading
# the context marks every one of them unloaded so none keeps a closed handle.
_WRAPPERS_BY_CACHE_KEY: Dict[str, "weakref.WeakSet[Any]"] = {}


def _execution_lock_for_key(cache_key: str) -> Any:
    """Return the native-execution lock for a cache key, creating it if needed."""
    with _MODEL_EXECUTION_LOCKS_GUARD:
        lock = _MODEL_EXECUTION_LOCKS.get(cache_key)
        if lock is None:
            lock = threading.RLock()
            _MODEL_EXECUTION_LOCKS[cache_key] = lock
        return lock


def _register_wrapper(cache_key: str, wrapper: Any) -> None:
    with _MODEL_EXECUTION_LOCKS_GUARD:
        _WRAPPERS_BY_CACHE_KEY.setdefault(cache_key, weakref.WeakSet()).add(wrapper)


def _evict_native_context(cache_key: str) -> bool:
    """Close one cached native context and remove it from the cache.

    Waits for any generation in progress on the same GGUF (they hold the same
    lock), so a context is never closed under a running call. Returns True if a
    context was cached.
    """
    with _execution_lock_for_key(cache_key):
        with _MODEL_EXECUTION_LOCKS_GUARD:
            llm = _MODEL_CACHE.pop(cache_key, None)
            wrappers = list(_WRAPPERS_BY_CACHE_KEY.pop(cache_key, ()))
        for wrapper in wrappers:
            wrapper._mark_unloaded()
        if llm is None:
            return False
        close = getattr(llm, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                logger.warning(
                    "Failed to close llama.cpp context: %s", cache_key, exc_info=True
                )
        return True


def evict_llama_cpp_contexts_under(root: Path) -> List[str]:
    """Close every cached native context whose GGUF lives at or under ``root``.

    Used before a model's files are deleted. Returns the evicted cache keys.
    """
    resolved_root = Path(root).expanduser().resolve()
    with _MODEL_EXECUTION_LOCKS_GUARD:
        candidates = list(_MODEL_CACHE.keys())
    evicted: List[str] = []
    for cache_key in candidates:
        key_path = Path(cache_key)
        if key_path == resolved_root or resolved_root in key_path.parents:
            if _evict_native_context(cache_key):
                evicted.append(cache_key)
    if evicted:
        gc.collect()
    return evicted


@dataclass(frozen=True)
class LocalCompletionTelemetry:
    """Scalar completion metadata for one local llama.cpp chat completion."""

    requested_output_tokens: int
    finish_reason: str
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_tokens: Optional[int]
    completion_token_source: str
    raw_completion_tokens: Optional[int]
    visible_completion_tokens: Optional[int]
    lock_wait_ms: int
    native_duration_ms: int
    completed_at_monotonic_ms: int


@dataclass(frozen=True)
class _NativeChatCompletionResult:
    """Unmodified llama.cpp chat completion plus native timing metadata."""

    response: Dict[str, Any]
    lock_wait_ms: int
    native_duration_ms: int


def _emit_runtime_trace(event: str, **fields: Any) -> None:
    """Emit opt-in, prompt-free timing data for local native completions."""
    if os.getenv(_LOCAL_RUNTIME_TRACE_ENV) != "1":
        return
    logger.warning(
        "LOCAL_RUNTIME_TRACE %s",
        json.dumps(
            {"event": event, "monotonic_seconds": time.monotonic(), **fields},
            sort_keys=True,
        ),
    )


class LlamaCppModel(BaseReasoningModel):
    """Implementation of a reasoning model using llama.cpp with GGUF models."""
    
    # Default context window - will be overridden by GGUF metadata if available
    DEFAULT_CONTEXT_WINDOW = 32768  # 32K default, reasonable for most modern models

    # Reasoning markers for the GGUF families this adapter loads (Qwen, DeepSeek-R1
    # and friends). Other adapters use different conventions, and cloud models
    # return reasoning in a separate field, so this knowledge stays local.
    _THINK_OPEN = "<think>"
    _THINK_CLOSE = "</think>"

    def __init__(self, model_path: Path, required_capabilities: Set[ModelCapability]):
        """Initialize the llama.cpp model."""
        super().__init__(model_path, required_capabilities)
        self.model_path = model_path
        self.llm = None
        self._native_execution_lock = _get_model_execution_lock(self.model_path)
        self.device = "metal" if sys.platform == "darwin" and "arm" in os.uname().machine else "cpu"
        
        # Context/output limits — set from registry config via apply_registry_config(),
        # otherwise fall back to GGUF metadata, then DEFAULT_CONTEXT_WINDOW.
        self.n_ctx = self.DEFAULT_CONTEXT_WINDOW
        self.max_context_length = self.DEFAULT_CONTEXT_WINDOW
        self.max_tokens_to_sample: Optional[int] = None
        self._registry_config: Optional[Dict[str, Any]] = None
        self._local_generation: Dict[str, Any] = {}
        self._reasoning_mode = "tagged"
        
        # Shared hardware profile used by llama.cpp load planning.
        self.hardware_profile = HardwareCapabilityService().get_profile()
        
        # Log GPU capabilities
        print(f"[LlamaCpp] GPU acceleration enabled with {self.hardware_profile.gpu_backend}")
        print(f"[LlamaCpp] Memory optimizations: {self.hardware_profile.memory_optimizations}")

    def apply_registry_config(self, config: Dict[str, Any]) -> None:
        """Apply registry context, capability ceiling, and local-generation policy."""
        self._registry_config = config
        if config.get("context_window"):
            self.n_ctx = int(config["context_window"])
            self.max_context_length = int(config["context_window"])
            logger.info(f"[LlamaCpp] Registry config: context_window={self.n_ctx}")
        if config.get("max_output_tokens"):
            self.max_tokens_to_sample = int(config["max_output_tokens"])
            logger.info(f"[LlamaCpp] Registry config: max_output_tokens={self.max_tokens_to_sample}")
        local_generation = config.get("local_generation")
        if isinstance(local_generation, dict):
            self._local_generation = dict(local_generation)
            reasoning_mode = local_generation.get("reasoning_mode")
            if reasoning_mode in {"tagged", "none"}:
                self._reasoning_mode = reasoning_mode

    def _sampling_kwargs(
        self,
        *,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
    ) -> Dict[str, Any]:
        sampling = getattr(self, "_local_generation", {}).get("sampling")
        sampling = sampling if isinstance(sampling, dict) else {}
        result: Dict[str, Any] = {
            "temperature": temperature if temperature is not None else sampling.get("temperature", 0.1),
            "top_p": top_p if top_p is not None else sampling.get("top_p", 0.95),
            "top_k": top_k if top_k is not None else sampling.get("top_k", 40),
            "repeat_penalty": sampling.get("repeat_penalty", 1.15),
        }
        min_p = sampling.get("min_p")
        if isinstance(min_p, (int, float)):
            result["min_p"] = float(min_p)
        return result

    # Minimum plausible context window — anything below this from GGUF parsing
    # is almost certainly a type indicator or index, not the real value.
    _MIN_PLAUSIBLE_CONTEXT = 512

    def _get_context_window_from_gguf(self) -> int:
        """Read the context window size from GGUF metadata.
        
        Returns the model's trained context length, or DEFAULT_CONTEXT_WINDOW if not found.
        """
        try:
            from gguf import GGUFReader
            
            reader = GGUFReader(str(self.model_path))
            
            # Look for context length in metadata.
            # GGUF fields have a `data` attribute (numpy array of the actual value)
            # and a `parts` list whose first element is the raw type tag —
            # always use `data` when available to avoid grabbing a type indicator.
            for field in reader.fields.values():
                field_name = field.name.lower() if hasattr(field, 'name') else str(field).lower()
                if 'context_length' in field_name or 'n_ctx' in field_name:
                    # Preferred: use the .data attribute (the actual value array)
                    if hasattr(field, 'data') and field.data is not None:
                        try:
                            if hasattr(field.data, 'tolist'):
                                values = field.data.tolist()
                            else:
                                values = list(field.data)
                            if values and isinstance(values[0], (int, float)):
                                context_length = int(values[0])
                                if context_length >= self._MIN_PLAUSIBLE_CONTEXT:
                                    logger.info(f"[LlamaCpp] Found context_length in GGUF metadata (data): {context_length}")
                                    return context_length
                                else:
                                    logger.warning(
                                        f"[LlamaCpp] GGUF context_length={context_length} is implausibly small, ignoring"
                                    )
                        except Exception as e:
                            logger.warning(f"[LlamaCpp] Error reading field.data: {e}")

                    # Fallback: use parts, but skip the first element (type tag)
                    if hasattr(field, 'parts') and len(field.parts) > 1:
                        for part in field.parts[1:]:
                            if hasattr(part, 'tolist'):
                                values = part.tolist()
                                if values and isinstance(values[0], (int, float)):
                                    context_length = int(values[0])
                                    if context_length >= self._MIN_PLAUSIBLE_CONTEXT:
                                        logger.info(f"[LlamaCpp] Found context_length in GGUF metadata (parts): {context_length}")
                                        return context_length
                                    else:
                                        logger.warning(
                                            f"[LlamaCpp] GGUF context_length={context_length} from parts is implausibly small, ignoring"
                                        )
            
            # Model-specific fallbacks
            model_name = self.model_path.name.lower()
            if 'qwen' in model_name:
                logger.info("[LlamaCpp] Qwen model detected, using 32K context window")
                return 32768
            elif 'llama' in model_name:
                logger.info("[LlamaCpp] Llama model detected, using 8K context window")
                return 8192
            
            logger.info(f"[LlamaCpp] No context_length found in GGUF, using default: {self.DEFAULT_CONTEXT_WINDOW}")
            return self.DEFAULT_CONTEXT_WINDOW
            
        except ImportError:
            logger.warning("[LlamaCpp] gguf library not available, using default context window")
            return self.DEFAULT_CONTEXT_WINDOW
        except Exception as e:
            logger.warning(f"[LlamaCpp] Failed to read GGUF metadata: {e}, using default context window")
            return self.DEFAULT_CONTEXT_WINDOW

    def _read_gguf_metadata_context_or_none(self) -> Optional[int]:
        """Return the trained context length from GGUF metadata, or None when unknown.

        Unlike ``_get_context_window_from_gguf`` this does not apply
        model-name heuristics or the DEFAULT_CONTEXT_WINDOW fallback, so it
        is safe for validation use where we must distinguish "trained value
        is X" from "we don't know". Used to compare a registry-requested
        ``context_window`` against the model's actual trained ceiling.
        """
        try:
            from gguf import GGUFReader
        except ImportError:
            return None

        try:
            reader = GGUFReader(str(self.model_path))
            for field in reader.fields.values():
                field_name = (
                    field.name.lower() if hasattr(field, "name") else str(field).lower()
                )
                if "context_length" not in field_name and "n_ctx" not in field_name:
                    continue

                # Preferred: use the .data attribute (the actual value array).
                if hasattr(field, "data") and field.data is not None:
                    try:
                        if hasattr(field.data, "tolist"):
                            values = field.data.tolist()
                        else:
                            values = list(field.data)
                        if values and isinstance(values[0], (int, float)):
                            context_length = int(values[0])
                            if context_length >= self._MIN_PLAUSIBLE_CONTEXT:
                                return context_length
                    except Exception:
                        pass

                # Fallback: parts[1:] skips the type tag at index 0.
                if hasattr(field, "parts") and len(field.parts) > 1:
                    for part in field.parts[1:]:
                        if hasattr(part, "tolist"):
                            try:
                                values = part.tolist()
                            except Exception:
                                continue
                            if values and isinstance(values[0], (int, float)):
                                context_length = int(values[0])
                                if context_length >= self._MIN_PLAUSIBLE_CONTEXT:
                                    return context_length
            return None
        except Exception:
            return None

    @staticmethod
    def _coerce_positive_int(value: Any) -> Optional[int]:
        """Return ``value`` as a positive int when possible, else None.

        Used to gate optional registry fields like ``n_batch``/``n_ubatch``
        so we never pass zero, negative, or malformed values into llama.cpp.
        """
        try:
            coerced = int(value)
        except (TypeError, ValueError):
            return None
        return coerced if coerced > 0 else None

    def _is_chatml_prompt(self, prompt: str) -> bool:
        """Return True if the prompt appears to use ChatML formatting."""
        return "<|im_start|>" in prompt and "<|im_end|>" in prompt

    def _parse_chatml_prompt(self, prompt: str) -> Tuple[List[Dict[str, str]], bool]:
        """Parse ChatML prompt into llama.cpp chat messages.

        Returns a tuple of (messages, has_generation_prompt).
        """
        messages: List[Dict[str, str]] = []
        has_generation_prompt = False

        pattern = r"<\|im_start\|>([^\n]+)\n(.*?)<\|im_end\|>"
        position = 0
        for match in re.finditer(pattern, prompt, re.DOTALL):
            role = match.group(1).strip().lower()
            content = match.group(2)
            messages.append({
                "role": role if role in {"system", "user", "assistant"} else "user",
                "content": content.strip()
            })
            position = match.end()

        tail = prompt[position:].strip()
        if tail.startswith("<|im_start|>assistant"):
            has_generation_prompt = True

        return messages, has_generation_prompt

    def _has_unterminated_thinking(self, text: str) -> bool:
        """True when reasoning opened and never closed, i.e. output was cut off."""
        return has_unterminated_reasoning(text, self._THINK_OPEN, self._THINK_CLOSE)

    def _strip_think_sections(self, text: str) -> str:
        """Remove <think> blocks and residual chat markers from the response."""
        text = strip_inline_reasoning(text, self._THINK_OPEN, self._THINK_CLOSE)
        text = text.replace("<|im_end|>", "").replace("<|im_start|>", "")
        return text.strip()
    
    @property
    def native_execution_lock(self) -> Any:
        lock = getattr(self, "_native_execution_lock", None)
        if lock is None:
            model_path = getattr(self, "model_path", None)
            lock = (
                _get_model_execution_lock(model_path)
                if isinstance(model_path, Path)
                else threading.RLock()
            )
            self._native_execution_lock = lock
        return lock

    def _plan_native_load(self) -> Any:
        """Resolve the load plan: registry and GGUF context, the memory ceiling, and any ceiling a failed decode set."""
        # Use registry-configured context window if available,
        # otherwise fall back to GGUF metadata parsing.
        trained_context = self._read_gguf_metadata_context_or_none()
        if self._registry_config and self._registry_config.get("context_window"):
            context_window = self._registry_config["context_window"]
            if trained_context is not None and context_window > trained_context:
                logger.warning(
                    f"[LlamaCpp] Registry context_window={context_window} exceeds GGUF "
                    f"trained context={trained_context}; loading at requested value but "
                    f"model behavior beyond {trained_context} tokens may be unreliable"
                )
            elif trained_context is not None:
                logger.info(
                    f"[LlamaCpp] Using registry context window: {context_window} tokens "
                    f"(GGUF trained context={trained_context})"
                )
            else:
                logger.info(
                    f"[LlamaCpp] Using registry context window: {context_window} tokens "
                    f"(GGUF trained context unavailable for validation)"
                )
        else:
            context_window = self._get_context_window_from_gguf()
            if trained_context is None and context_window != self.DEFAULT_CONTEXT_WINDOW:
                trained_context = context_window
            logger.info(f"[LlamaCpp] Using GGUF-derived context window: {context_window} tokens")

        registry_cfg = self._registry_config or {}
        memory_facts = read_model_memory_facts(self.model_path)
        load_plan = build_llama_cpp_load_plan(
            hardware_profile=self.hardware_profile,
            registry_config=registry_cfg,
            gguf_context_window=trained_context or context_window,
            default_context_window=self.DEFAULT_CONTEXT_WINDOW,
            max_context_window=_context_ceiling_for(str(self.model_path.resolve())),
            model_bytes=memory_facts.model_bytes,
            kv_bytes_per_token=memory_facts.kv_bytes_per_token,
        )
        logger.info(
            "[LlamaCpp] Final load settings: "
            f"n_ctx={load_plan.n_ctx}, n_gpu_layers={load_plan.n_gpu_layers}, "
            f"n_threads={load_plan.n_threads}, n_batch={load_plan.n_batch}, "
            f"n_ubatch={load_plan.n_ubatch}, fallback_reasons={load_plan.fallback_reasons}"
        )
        return load_plan

    def _open_native_context(self, cache_key: str, load_plan: Any) -> Any:
        """Create the native llama.cpp context for a plan, or reuse the cached one. Blocking; callers off the event loop only."""
        from llama_cpp import Llama

        llama_kwargs = load_plan.to_llama_kwargs(self.model_path)
        with self.native_execution_lock:
            cached = _MODEL_CACHE.get(cache_key)
            if cached is not None:
                return cached
            loaded = Llama(**llama_kwargs)
            if load_plan.prompt_cache_bytes > 0:
                from llama_cpp.llama_cache import LlamaRAMCache

                loaded.set_cache(LlamaRAMCache(capacity_bytes=load_plan.prompt_cache_bytes))
                logger.info(
                    "[LlamaCpp] Prompt-state cache enabled: capacity=%.1f GiB",
                    load_plan.prompt_cache_bytes / (1 << 30),
                )
            _MODEL_CACHE[cache_key] = loaded
            return loaded

    async def load(self) -> None:
        """Load the llama.cpp model."""
        if self.state == ModelState.READY:
            logger.info("Llama.cpp model already loaded")
            return
        # Check if model is in cache
        cache_key = str(self.model_path.resolve())
        with self.native_execution_lock:
            cached_model = _MODEL_CACHE.get(cache_key)
        if cached_model is not None:
            logger.info(f"Using cached Llama.cpp model for {self.model_path}")
            self.llm = cached_model
            self.tokenizer = LlamaCppTokenizerWrapper(cached_model)
            _register_wrapper(cache_key, self)
            native_context = getattr(cached_model, "n_ctx", None)
            if callable(native_context):
                self.n_ctx = native_context()
                self.max_context_length = self.n_ctx
            self.state = ModelState.READY
            return

        logger.info(f"Loading Llama.cpp model from {self.model_path}")
        self.state = ModelState.LOADING
        
        try:
            # Import here to avoid dependency issues if llama_cpp is not installed
            from llama_cpp import Llama
            
            load_plan = self._plan_native_load()
            context_window = load_plan.n_ctx
            self.llm = await asyncio.to_thread(self._open_native_context, cache_key, load_plan)

            # llama.cpp picks this from the GGUF's tokenizer.chat_template and
            # silently falls back to a guessed llama-2 format when a model has
            # none, which would mis-format every prompt. Log it so that is visible.
            logger.info(
                f"[LlamaCpp] Chat format resolved from GGUF: "
                f"{getattr(self.llm, 'chat_format', None)}"
            )
            
            # Store context window for base_reasoning.py to use
            self.n_ctx = context_window
            self.max_context_length = context_window
            
            logger.info(f"Successfully loaded Llama.cpp model with {context_window} token context")
            
            self.tokenizer = LlamaCppTokenizerWrapper(self.llm)
            _register_wrapper(cache_key, self)
            logger.info("Created llama.cpp tokenizer wrapper")
            
            logger.info(f"Cached Llama.cpp model for future use")
            
            self.state = ModelState.READY
            
        except Exception as e:
            logger.error(f"Failed to load Llama.cpp model: {e}")
            self.state = ModelState.ERROR
            raise RuntimeError(f"Failed to load Llama.cpp model: {e}")

    def _mark_unloaded(self) -> None:
        """Drop this wrapper's handle on the native context."""
        self.llm = None
        self.tokenizer = None
        self.state = ModelState.UNLOADED

    async def unload(self) -> None:
        """Close the native context and release its memory.

        The context is shared by every wrapper on the same GGUF, so all of them
        are marked unloaded. A later ``load()`` builds a fresh context.
        """
        cache_key = str(self.model_path.resolve())
        # Off the event loop: this waits for any generation still running.
        await asyncio.to_thread(_evict_native_context, cache_key)
        self._mark_unloaded()
        gc.collect()
        logger.info("[LlamaCpp] Unloaded %s", self.model_path.name)

    def _decode_error(self, failure: DecodeFailure, retried_context: Optional[int]) -> LocalModelDecodeError:
        """Build the typed failure for a native decode that could not be recovered."""
        return LocalModelDecodeError(
            code=failure.code,
            kind=failure.kind,
            model_name=self.model_path.name,
            n_ctx=self.n_ctx,
            retried_at_context=retried_context,
        )

    def _reload_after_memory_failure(self, failure: DecodeFailure) -> Optional[int]:
        """Reload the native context at half the size after a memory failure and return the new context, or None.

        Only a fatal compute failure is retried, because a prompt that does not fit (code 1) needs a larger context, not a smaller one.
        The reload runs under the native-execution lock, which is re-entrant, so callers that already hold it (the wrapper's own calls) and callers that do not (the agent adapter) are both safe.
        The ceiling is recorded per GGUF so every wrapper on it plans later loads under the size that worked.
        """
        if failure.kind is not LocalModelFailureKind.MEMORY:
            return None
        with self.native_execution_lock:
            return self._reload_at_half_context(failure)

    def _reload_at_half_context(self, failure: DecodeFailure) -> Optional[int]:
        target = (self.n_ctx // 2) // CONTEXT_STEP * CONTEXT_STEP
        if target < MEMORY_FLOOR_CONTEXT:
            return None
        cache_key = str(self.model_path.resolve())
        logger.warning(
            "[LlamaCpp] llama_decode returned %s at n_ctx=%s; reloading %s at n_ctx<=%s",
            failure.code, self.n_ctx, self.model_path.name, target,
        )
        try:
            _set_context_ceiling(cache_key, target)
            _evict_native_context(cache_key)
            load_plan = self._plan_native_load()
            llm = self._open_native_context(cache_key, load_plan)
        except Exception:
            logger.exception("[LlamaCpp] Reload at a smaller context failed for %s", self.model_path.name)
            return None
        self.llm = llm
        self.tokenizer = LlamaCppTokenizerWrapper(llm)
        _register_wrapper(cache_key, self)
        self.n_ctx = load_plan.n_ctx
        self.max_context_length = load_plan.n_ctx
        self.state = ModelState.READY
        return load_plan.n_ctx

    def _create_completion(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        if self.llm is None:
            raise RuntimeError("Llama.cpp model is not loaded")
        with self.native_execution_lock:
            # An unload may have run while this call waited for the lock.
            llm = self.llm
            if llm is None:
                raise RuntimeError("Llama.cpp model is not loaded")
            return llm.create_completion(*args, **kwargs)

    def _create_chat_completion(self, **kwargs: Any) -> _NativeChatCompletionResult:
        if self.llm is None:
            raise RuntimeError("Llama.cpp model is not loaded")
        requested_at = time.perf_counter()
        _emit_runtime_trace(
            "native_chat_completion_waiting_for_lock",
            model_path=str(getattr(self, "model_path", "")),
            max_tokens=kwargs.get("max_tokens"),
            message_count=len(kwargs.get("messages") or []),
        )
        with self.native_execution_lock:
            lock_acquired_at = time.perf_counter()
            lock_wait_ms = int((lock_acquired_at - requested_at) * 1000)
            _emit_runtime_trace(
                "native_chat_completion_started",
                model_path=str(getattr(self, "model_path", "")),
                lock_wait_seconds=lock_acquired_at - requested_at,
                max_tokens=kwargs.get("max_tokens"),
                message_count=len(kwargs.get("messages") or []),
            )
            llm = self.llm
            if llm is None:
                raise RuntimeError("Llama.cpp model is not loaded")
            try:
                response = llm.create_chat_completion(**kwargs)
            except Exception as exc:
                _emit_runtime_trace(
                    "native_chat_completion_raised",
                    model_path=str(getattr(self, "model_path", "")),
                    native_duration_seconds=time.perf_counter() - lock_acquired_at,
                    error_type=type(exc).__name__,
                )
                failure = parse_decode_failure(exc)
                if failure is None:
                    raise
                retried_context = self._reload_after_memory_failure(failure)
                if retried_context is not None and self.llm is not None:
                    try:
                        response = self.llm.create_chat_completion(**kwargs)
                    except Exception as second_exc:
                        failure = parse_decode_failure(second_exc)
                        if failure is None:
                            raise
                        raise self._decode_error(failure, retried_context) from second_exc
                else:
                    raise self._decode_error(failure, retried_context) from exc
            native_duration_ms = int((time.perf_counter() - lock_acquired_at) * 1000)
            _emit_runtime_trace(
                "native_chat_completion_returned",
                model_path=str(getattr(self, "model_path", "")),
                native_duration_seconds=native_duration_ms / 1000.0,
                finish_reason=(
                    response.get("choices", [{}])[0].get("finish_reason")
                    if isinstance(response, dict)
                    else None
                ),
            )
            return _NativeChatCompletionResult(
                response=response,
                lock_wait_ms=lock_wait_ms,
                native_duration_ms=native_duration_ms,
            )

    def _stream_chat_completion(self, **kwargs: Any) -> Iterator[Dict[str, Any]]:
        """Iterate one native chat stream while exclusively owning its GGUF context."""
        if self.llm is None:
            raise RuntimeError("Llama.cpp model is not loaded")
        requested_at = time.monotonic()
        _emit_runtime_trace(
            "native_chat_stream_waiting_for_lock",
            model_path=str(getattr(self, "model_path", "")),
            max_tokens=kwargs.get("max_tokens"),
            message_count=len(kwargs.get("messages") or []),
        )
        with self.native_execution_lock:
            stream_started_at = time.monotonic()
            chunk_count = 0
            _emit_runtime_trace(
                "native_chat_stream_started",
                model_path=str(getattr(self, "model_path", "")),
                lock_wait_seconds=stream_started_at - requested_at,
                max_tokens=kwargs.get("max_tokens"),
                message_count=len(kwargs.get("messages") or []),
            )
            llm = self.llm
            if llm is None:
                raise RuntimeError("Llama.cpp model is not loaded")
            try:
                for chunk in llm.create_chat_completion(stream=True, **kwargs):
                    chunk_count += 1
                    if chunk_count == 1:
                        _emit_runtime_trace(
                            "native_chat_stream_first_chunk",
                            model_path=str(getattr(self, "model_path", "")),
                            first_chunk_seconds=time.monotonic() - stream_started_at,
                        )
                    yield chunk
            except Exception as exc:
                _emit_runtime_trace(
                    "native_chat_stream_raised",
                    model_path=str(getattr(self, "model_path", "")),
                    native_duration_seconds=time.monotonic() - stream_started_at,
                    chunk_count=chunk_count,
                    error_type=type(exc).__name__,
                )
                failure = parse_decode_failure(exc)
                if failure is None:
                    raise
                # A stream that already produced text cannot be replayed from the start, so only a failure before the first chunk is retried.
                retried_context = self._reload_after_memory_failure(failure) if chunk_count == 0 else None
                if retried_context is None or self.llm is None:
                    raise self._decode_error(failure, retried_context) from exc
                try:
                    for chunk in self.llm.create_chat_completion(stream=True, **kwargs):
                        chunk_count += 1
                        yield chunk
                except Exception as second_exc:
                    failure = parse_decode_failure(second_exc)
                    if failure is None:
                        raise
                    raise self._decode_error(failure, retried_context) from second_exc
            _emit_runtime_trace(
                "native_chat_stream_completed",
                model_path=str(getattr(self, "model_path", "")),
                native_duration_seconds=time.monotonic() - stream_started_at,
                chunk_count=chunk_count,
            )

    def _count_completion_tokens(self, text: str) -> Optional[int]:
        """Return tokenizer token count for ``text``, or None when unavailable."""
        if self.llm is None or not isinstance(text, str):
            return None
        try:
            return len(self.llm.tokenize(text.encode("utf-8")))
        except Exception:
            return None

    def _read_usage_tokens(self, output: Dict[str, Any]) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        usage = output.get("usage") if isinstance(output, dict) else None
        if not isinstance(usage, dict):
            return None, None, None

        def _coerce(value: Any) -> Optional[int]:
            if isinstance(value, (int, float)):
                coerced = int(value)
                return coerced if coerced >= 0 else None
            return None

        return (
            _coerce(usage.get("prompt_tokens")),
            _coerce(usage.get("completion_tokens")),
            _coerce(usage.get("total_tokens")),
        )

    def _build_completion_telemetry(
        self,
        *,
        requested_output_tokens: int,
        finish_reason: str,
        raw_content: str,
        visible_content: Optional[str],
        lock_wait_ms: int,
        native_duration_ms: int,
        usage_output: Dict[str, Any],
    ) -> LocalCompletionTelemetry:
        prompt_tokens, completion_tokens, total_tokens = self._read_usage_tokens(usage_output)
        raw_completion_tokens = completion_tokens
        completion_token_source = "usage"
        if raw_completion_tokens is None:
            # A partial usage object is not reliable enough to combine with a
            # tokenizer-only completion count. Preserve only the count we can
            # derive from the raw completion, as promised by this contract.
            prompt_tokens = None
            total_tokens = None
            raw_completion_tokens = self._count_completion_tokens(raw_content)
            completion_token_source = (
                "tokenizer_fallback" if raw_completion_tokens is not None else "unavailable"
            )
        visible_completion_tokens = (
            self._count_completion_tokens(visible_content)
            if visible_content is not None
            else None
        )
        return LocalCompletionTelemetry(
            requested_output_tokens=requested_output_tokens,
            finish_reason=finish_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            completion_token_source=completion_token_source,
            raw_completion_tokens=raw_completion_tokens,
            visible_completion_tokens=visible_completion_tokens,
            lock_wait_ms=lock_wait_ms,
            native_duration_ms=native_duration_ms,
            completed_at_monotonic_ms=int(time.monotonic() * 1000),
        )

    def _invoke_telemetry_callback(
        self,
        callback: Optional[Callable[[LocalCompletionTelemetry], None]],
        telemetry: LocalCompletionTelemetry,
    ) -> None:
        if callback is None:
            return
        callback(telemetry)

    async def generate_response(
        self, prompt: str, context: Dict[str, Any] = None, max_tokens: int = 1024, 
        temperature: float = 0.1, top_p: float = 0.95, top_k: int = 40, timeout: int = 30,
        preserve_thinking: bool = False,
        *,
        telemetry_callback: Optional[Callable[[LocalCompletionTelemetry], None]] = None,
    ) -> str:
        """Generate a response from the llama.cpp model.
        
        Args:
            prompt: The input prompt
            context: Optional context dictionary
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            top_p: Nucleus sampling parameter
            top_k: Top-k sampling parameter
            timeout: Generation timeout
            preserve_thinking: If True, preserve <think> tags in output (for conversation streaming)
        """
        if self.state != ModelState.READY:
            await self.load()
        
        # Process context if provided
        if context:
            context_str = "\n".join(f"{k}: {v}" for k, v in context.items())
            full_prompt = f"{context_str}\n\n{prompt}"
        else:
            full_prompt = prompt
        
        logger.info(f"Generating response for prompt (length: {len(full_prompt)} chars)")
        logger.info(f"Prompt preview: {full_prompt[:20]}...")
        
        start_time = time.time()
        try:
            # An unparseable ChatML prompt falls through to the completion API
            # rather than raising, which is what the warning has always claimed.
            # A plain prompt is one user turn, so it goes through the model's own
            # chat template rather than raw text continuation. Without a generation
            # prompt the model is never told to begin an assistant turn and can
            # answer with an immediate EOS; local_qwen_vl_loader and
            # signal_triage_agent both hand-roll this same wrapping to avoid that.
            use_chat_completion = True
            messages: List[Dict[str, str]] = [{"role": "user", "content": full_prompt}]
            if self._is_chatml_prompt(full_prompt):
                parsed, has_generation_prompt = self._parse_chatml_prompt(full_prompt)
                if parsed and has_generation_prompt:
                    messages = parsed
                else:
                    # Hand-written ChatML we cannot parse: as message content the
                    # markers would reach the model verbatim, so continue it as text.
                    use_chat_completion = False
                    logger.warning("ChatML prompt detected but could not parse messages; falling back to completion API")

            if use_chat_completion:
                response, finish_reason, completion_telemetry = await self._run_chat_completion(
                    messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                )
            else:
                output = await asyncio.to_thread(
                    self._create_completion,
                    full_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    repeat_penalty=1.15,
                )

                response = output["choices"][0]["text"]
                finish_reason = output["choices"][0].get("finish_reason", "unknown")
                completion_telemetry = self._build_completion_telemetry(
                    requested_output_tokens=max_tokens,
                    finish_reason=finish_reason,
                    raw_content=response,
                    visible_content=None,
                    lock_wait_ms=0,
                    native_duration_ms=0,
                    usage_output=output,
                )

            logger.info(f"Generation finish_reason: {finish_reason}")
            if finish_reason == "stop":
                logger.info(f"Stopped due to stop token. Last 100 chars: {response[-100:]}")

        except Exception:
            logger.exception("Error generating response")
            raise
        
        generation_time = time.time() - start_time
        logger.info(f"Generated response (length: {len(response)} chars)")
        logger.info(f"Response preview: {response[:30]}...")
        logger.info(f"Generation completed in {generation_time:.2f} seconds")

        try:
            finalized = self._finalize_response(
                response, finish_reason, max_tokens, preserve_thinking
            )
        except Exception:
            self._invoke_telemetry_callback(
                telemetry_callback,
                replace(
                    completion_telemetry,
                    visible_completion_tokens=None,
                ),
            )
            raise

        visible_content = finalized if not preserve_thinking else response
        self._invoke_telemetry_callback(
            telemetry_callback,
            replace(
                completion_telemetry,
                visible_completion_tokens=self._count_completion_tokens(visible_content),
            ),
        )
        return finalized

    async def _run_chat_completion(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: int,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
    ) -> Tuple[str, str, LocalCompletionTelemetry]:
        """Call llama.cpp's chat API with registry-selected sampling."""
        native_result = await asyncio.to_thread(
            self._create_chat_completion,
            messages=messages,
            max_tokens=max_tokens,
            **self._sampling_kwargs(
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
            ),
        )
        choice = native_result.response["choices"][0]
        raw_content = choice["message"]["content"]
        finish_reason = choice.get("finish_reason", "unknown")
        telemetry = self._build_completion_telemetry(
            requested_output_tokens=max_tokens,
            finish_reason=finish_reason,
            raw_content=raw_content,
            visible_content=None,
            lock_wait_ms=native_result.lock_wait_ms,
            native_duration_ms=native_result.native_duration_ms,
            usage_output=native_result.response,
        )
        return raw_content, finish_reason, telemetry

    def _finalize_response(
        self,
        response: str,
        finish_reason: str,
        max_tokens: int,
        preserve_thinking: bool,
    ) -> str:
        """Post-processing shared by the prompt and message entry points."""
        if preserve_thinking:
            return response
        response = response.replace("<|im_end|>", "").replace("<|im_start|>", "").strip()
        if getattr(self, "_reasoning_mode", "tagged") == "none":
            return response
        if self._has_unterminated_thinking(response):
            raise ReasoningTruncatedError(
                f"Generation stopped ({finish_reason}) inside the model's reasoning "
                f"block after {len(response)} chars without emitting an answer; "
                f"max_tokens={max_tokens} is below what this model needs to reason "
                "and then answer"
            )
        return self._strip_think_sections(response)

    async def generate_from_messages(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: Optional[int] = None,
        preserve_thinking: bool = False,
    ) -> str:
        """Generate from messages, letting llama.cpp apply the GGUF's template.

        The inherited default renders messages to a string that this adapter
        would immediately parse back into messages, and that string was built
        from hardcoded Qwen markers regardless of which model was loaded.
        """
        if self.state != ModelState.READY:
            await self.load()
        budget = max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS
        response, finish_reason, _telemetry = await self._run_chat_completion(
            messages, max_tokens=budget
        )
        logger.info(f"Generation finish_reason: {finish_reason}")
        return self._finalize_response(
            response, finish_reason, budget, preserve_thinking
        )

    async def _generate_from_messages_streaming(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """Yield llama.cpp chat deltas as native generation produces them."""
        if self.state != ModelState.READY:
            await self.load()
        budget = max_tokens if max_tokens is not None else DEFAULT_STREAMING_MAX_TOKENS
        async for chunk in async_iter_sync_stream(
            lambda: self._stream_chat_completion(
                messages=messages,
                max_tokens=budget,
                **self._sampling_kwargs(),
            ),
            thread_name="llama-cpp-chat-stream",
        ):
            choices = chunk.get("choices") if isinstance(chunk, dict) else None
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            text = delta.get("content")
            if isinstance(text, str) and text:
                yield text

    def _generate(self, prompt: str, max_tokens: int = 1024) -> str:
        """Synchronous method for generating text (required by abstract base class)."""
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.generate_response(prompt, max_tokens=max_tokens))
        finally:
            loop.close()

    async def _generate_async(self, prompt: str, max_tokens: int = 1024) -> str:
        """Asynchronous method for generating text (required by abstract base class)."""
        return await self.generate_response(prompt, max_tokens=max_tokens)

    async def validate(self) -> bool:
        """Validate that the model is working correctly."""
        if self.state != ModelState.READY:
            logger.info("Loading model for validation...")
            await self.load()
        
        try:
            # Simple validation prompt
            prompt = "Hello, can you help me solve this math problem: what is 12 + 15?"
            logger.info("Running validation with test prompt")
            
            response = await self.generate_response(prompt, max_tokens=50)
            
            # Check if we got some kind of meaningful response
            if response and len(response) > 10:
                logger.info("Model validation successful")
                return True
            else:
                logger.info("Model validation failed: response too short")
                return False
        except Exception as e:
            logger.error(f"Model validation failed: {e}")
            return False

    def get_metadata(self) -> ModelMetadata:
        """Get metadata about the model."""
        # Use actual context window if available, otherwise use default
        context_length = getattr(self, 'n_ctx', self.DEFAULT_CONTEXT_WINDOW)
        
        return ModelMetadata(
            name=self.model_path.stem if self.model_path else "GGUF Model",
            description=f"GGUF model using llama.cpp with {context_length} token context",
            version="1.0",
            source="llama.cpp",
            capabilities={ModelCapability.REASONING},
            parameters={
                "n_ctx": context_length,
                "quantization": "GGUF",
                "format": "GGUF"
            },
            requirements={
                "llama-cpp-python": ">=0.2.0"
            },
            memory_requirements="8GB",
            supports_gpu=True,
            context_length=context_length
        ) 