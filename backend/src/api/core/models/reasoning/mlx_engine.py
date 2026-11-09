"""An MLX text engine that offers the slice of llama-cpp-python's API that Basil's local model code calls.

``mlx_lm`` is imported lazily inside the default callables, so importing this module never loads Metal. Tests inject fake callables through the constructor.
"""

from __future__ import annotations

import gc
import itertools
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple, Union

from api.core.models.reasoning.mlx_prompt_cache import MlxPromptCache, PromptCacheStats

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 1024
PROMPT_CACHE_ENVIRONMENT_VARIABLE = "BASIL_MLX_PROMPT_CACHE"
PROMPT_CACHE_MIN_RAM_GB = 16
"""The prompt cache keeps one snapshot of the latest long prompt plus a working copy while generating, on top of the weights. A Mac with less memory than this runs with the cache off."""
CHAT_FORMAT_NAME = "mlx-chat-template"

LoadCallable = Callable[[str], Tuple[Any, Any]]
StreamCallable = Callable[..., Iterator[Any]]
FactoryCallable = Callable[..., Any]
Piece = Tuple[str, Optional[str]]


def _load_with_mlx_lm(model_dir: str) -> Tuple[Any, Any]:
    from mlx_lm import load

    model, tokenizer = load(model_dir)
    return model, tokenizer


def _stream_with_mlx_lm(*args: Any, **kwargs: Any) -> Iterator[Any]:
    from mlx_lm import stream_generate

    return stream_generate(*args, **kwargs)


def _make_sampler(**kwargs: Any) -> Any:
    from mlx_lm.sample_utils import make_sampler

    return make_sampler(**kwargs)


def _make_logits_processors(**kwargs: Any) -> Any:
    from mlx_lm.sample_utils import make_logits_processors

    return make_logits_processors(**kwargs)


def _clear_mlx_cache() -> None:
    import mlx.core as mx

    clear = getattr(mx, "clear_cache", None)
    if callable(clear):
        clear()


def _prompt_cache_enabled_by_environment(total_ram_gb: Optional[int] = None) -> bool:
    """Whether the prompt cache is on.

    ``BASIL_MLX_PROMPT_CACHE`` decides when it is set: 0, false, off, or no turn the cache off and any other value turns it on.
    When it is not set, the cache is on from ``PROMPT_CACHE_MIN_RAM_GB`` of memory upward, and off below that. An unreadable memory size leaves it on.
    ``total_ram_gb`` defaults to this machine's memory.
    """
    configured = os.environ.get(PROMPT_CACHE_ENVIRONMENT_VARIABLE, "").strip().lower()
    if configured:
        return configured not in {"0", "false", "off", "no"}
    if total_ram_gb is None:
        from api.core.models.preference_models.defaults import _detected_total_ram_gb

        total_ram_gb = _detected_total_ram_gb()
    return total_ram_gb is None or total_ram_gb >= PROMPT_CACHE_MIN_RAM_GB


def _normalize_stops(stop: Union[None, str, Sequence[str]]) -> List[str]:
    if not stop:
        return []
    if isinstance(stop, str):
        return [stop]
    return [item for item in stop if item]


def _find_stop(pending: str, stops: Sequence[str]) -> Optional[int]:
    hits = [index for index in (pending.find(stop) for stop in stops) if index >= 0]
    return min(hits) if hits else None


def _held_back_length(pending: str, stops: Sequence[str]) -> int:
    """Length of the longest tail of ``pending`` that could still become a stop string."""
    longest = 0
    for stop in stops:
        for size in range(min(len(stop) - 1, len(pending)), longest, -1):
            if pending.endswith(stop[:size]):
                longest = size
                break
    return longest


class MlxChatEngine:
    """Loads an MLX checkpoint folder and answers like ``llama_cpp.Llama`` for the calls Basil makes."""

    chat_format = CHAT_FORMAT_NAME

    def __init__(
        self,
        model_dir: Union[str, Path],
        context_window: int,
        *,
        loader: LoadCallable = _load_with_mlx_lm,
        stream_generate: StreamCallable = _stream_with_mlx_lm,
        sampler_factory: FactoryCallable = _make_sampler,
        logits_processor_factory: FactoryCallable = _make_logits_processors,
        cache_clearer: Callable[[], None] = _clear_mlx_cache,
        prompt_cache: Optional[MlxPromptCache] = None,
    ) -> None:
        self.model_dir = Path(model_dir)
        self._context_window = int(context_window)
        self._loader = loader
        self._stream_generate = stream_generate
        self._make_sampler = sampler_factory
        self._make_logits_processors = logits_processor_factory
        self._clear_cache = cache_clearer
        self._model: Any = None
        self._tokenizer: Any = None
        self._prompt_cache = prompt_cache or MlxPromptCache(enabled=_prompt_cache_enabled_by_environment())
        self.last_prompt_stats: Optional[PromptCacheStats] = None

    # ---- lifecycle -------------------------------------------------------

    def load(self) -> None:
        self._model, self._tokenizer = self._loader(str(self.model_dir))

    def close(self) -> None:
        self._prompt_cache.clear()
        self.last_prompt_stats = None
        self._model = None
        self._tokenizer = None
        gc.collect()
        try:
            self._clear_cache()
        except Exception:
            logger.debug("Could not clear the MLX cache after closing %s", self.model_dir, exc_info=True)

    def n_ctx(self) -> int:
        return self._context_window

    def _require_loaded(self) -> None:
        if self._model is None or self._tokenizer is None:
            raise RuntimeError("MLX model is not loaded")

    # ---- tokenizer surface ----------------------------------------------

    def tokenize(self, text: bytes, add_bos: bool = True, special: bool = False) -> List[int]:
        self._require_loaded()
        decoded = text.decode("utf-8", errors="ignore")
        return [int(token) for token in self._tokenizer.encode(decoded, add_special_tokens=bool(add_bos))]

    def detokenize(self, tokens: Sequence[int], **_unused: Any) -> bytes:
        self._require_loaded()
        return self._tokenizer.decode([int(token) for token in tokens]).encode("utf-8")

    # ---- generation -------------------------------------------------------

    def _render_chat_prompt(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]]) -> str:
        return self._tokenizer.apply_chat_template(
            messages,
            tools=tools or None,
            add_generation_prompt=True,
            tokenize=False,
        )

    def _encode_prompt(self, prompt_text: str) -> List[int]:
        return [int(token) for token in self._tokenizer.encode(prompt_text, add_special_tokens=False)]

    def _check_context(self, prompt_tokens: int) -> None:
        if prompt_tokens >= self._context_window:
            raise ValueError(
                f"Requested tokens ({prompt_tokens}) exceed context window of {self._context_window}"
            )

    def _generate(
        self,
        prompt_ids: List[int],
        *,
        max_tokens: Optional[int],
        temperature: Optional[float],
        top_p: Optional[float],
        top_k: Optional[int],
        min_p: Optional[float],
        repeat_penalty: Optional[float],
        stop: Union[None, str, Sequence[str]],
        usage: Dict[str, int],
    ) -> Iterator[Piece]:
        """Yield ``(text, None)`` pieces, then one final ``("", finish_reason)``."""
        sampler = self._make_sampler(
            temp=float(temperature or 0.0),
            top_p=float(top_p if top_p is not None else 1.0),
            min_p=float(min_p or 0.0),
            top_k=int(top_k or 0),
        )
        processors = None
        if repeat_penalty and float(repeat_penalty) != 1.0:
            processors = self._make_logits_processors(repetition_penalty=float(repeat_penalty))
        stops = _normalize_stops(stop)
        budget = int(max_tokens) if max_tokens and int(max_tokens) > 0 else DEFAULT_MAX_TOKENS

        started_at = time.monotonic()
        lease = self._prompt_cache.acquire(self._model, list(prompt_ids))
        stats = lease.stats
        self.last_prompt_stats = stats
        stream_kwargs: Dict[str, Any] = {
            "prompt": list(lease.feed_ids),
            "max_tokens": budget,
            "sampler": sampler,
            "logits_processors": processors,
        }
        if lease.cache is not None:
            stream_kwargs["prompt_cache"] = lease.cache
        generated_ids: List[int] = []
        failed = False
        pending = ""
        finish: Optional[str] = None
        stopped = False
        responses: Any = None
        try:
            responses = self._stream_generate(self._model, self._tokenizer, **stream_kwargs)
            for response in responses:
                if stats.first_token_seconds is None:
                    stats.first_token_seconds = time.monotonic() - started_at
                token = getattr(response, "token", None)
                if isinstance(token, int):
                    generated_ids.append(token)
                generated = getattr(response, "generation_tokens", None)
                usage["completion_tokens"] = int(generated) if generated else usage["completion_tokens"] + 1
                stats.generation_tokens = usage["completion_tokens"]
                stats.prompt_tps = getattr(response, "prompt_tps", None) or stats.prompt_tps
                stats.generation_tps = getattr(response, "generation_tps", None) or stats.generation_tps
                reported_prompt = getattr(response, "prompt_tokens", None)
                if reported_prompt and len(lease.feed_ids) == len(prompt_ids):
                    usage["prompt_tokens"] = int(reported_prompt)
                piece = getattr(response, "text", "") or ""
                reason = getattr(response, "finish_reason", None)
                if reason:
                    finish = str(reason)
                if not stops:
                    if piece:
                        yield piece, None
                    continue
                pending += piece
                cut = _find_stop(pending, stops)
                if cut is not None:
                    if cut > 0:
                        yield pending[:cut], None
                    pending = ""
                    finish = "stop"
                    stopped = True
                    break
                hold = _held_back_length(pending, stops)
                ready = pending[: len(pending) - hold]
                pending = pending[len(pending) - hold :]
                if ready:
                    yield ready, None
            if pending and not stopped:
                yield pending, None
        except GeneratorExit:
            raise
        except BaseException:
            failed = True
            raise
        finally:
            close_responses = getattr(responses, "close", None)
            if callable(close_responses):
                close_responses()
            lease.finish(generated_ids, failed=failed)
        final = finish or ("length" if usage["completion_tokens"] >= budget else "stop")
        yield "", final

    def create_chat_completion(
        self,
        *,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Any = None,
        stream: bool = False,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = 0.0,
        top_p: Optional[float] = 1.0,
        top_k: Optional[int] = 0,
        min_p: Optional[float] = None,
        repeat_penalty: Optional[float] = 1.0,
        stop: Union[None, str, Sequence[str]] = None,
        **_unsupported: Any,
    ) -> Union[Dict[str, Any], Iterator[Dict[str, Any]]]:
        """Chat completion with OpenAI-style output. ``response_format`` and other llama-only options are accepted and ignored."""
        self._require_loaded()
        prompt_ids = self._encode_prompt(self._render_chat_prompt(messages, tools))
        self._check_context(len(prompt_ids))
        usage = {"prompt_tokens": len(prompt_ids), "completion_tokens": 0}
        pieces = self._generate(
            prompt_ids,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            min_p=min_p,
            repeat_penalty=repeat_penalty,
            stop=stop,
            usage=usage,
        )
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        if stream:
            return self._stream_chunks(pieces, completion_id, created)
        parts: List[str] = []
        finish = "stop"
        for text, reason in pieces:
            parts.append(text)
            if reason is not None:
                finish = reason
        return {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": self.model_dir.name,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "".join(parts)},
                    "finish_reason": finish,
                }
            ],
            "usage": {
                "prompt_tokens": usage["prompt_tokens"],
                "completion_tokens": usage["completion_tokens"],
                "total_tokens": usage["prompt_tokens"] + usage["completion_tokens"],
            },
        }

    def _stream_chunks(self, pieces: Iterator[Piece], completion_id: str, created: int) -> Iterator[Dict[str, Any]]:
        def chunk(delta: Dict[str, Any], finish_reason: Optional[str]) -> Dict[str, Any]:
            return {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": self.model_dir.name,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
            }

        try:
            # Pull the first piece before announcing the assistant role: the pull blocks while the prompt is read, so the role chunk marks the real first token and callers that time it see the true prompt-reading time.
            first = next(pieces, None)
            yield chunk({"role": "assistant"}, None)
            for text, reason in itertools.chain([] if first is None else [first], pieces):
                if text:
                    yield chunk({"content": text}, None)
                if reason is not None:
                    yield chunk({}, reason)
        finally:
            pieces.close()

    def create_completion(
        self,
        prompt: str,
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = 0.0,
        top_p: Optional[float] = 1.0,
        top_k: Optional[int] = 0,
        min_p: Optional[float] = None,
        repeat_penalty: Optional[float] = 1.0,
        stop: Union[None, str, Sequence[str]] = None,
        **_unsupported: Any,
    ) -> Dict[str, Any]:
        """Raw text continuation, non-streaming only (the one form Basil calls)."""
        self._require_loaded()
        prompt_ids = self._encode_prompt(prompt)
        self._check_context(len(prompt_ids))
        usage = {"prompt_tokens": len(prompt_ids), "completion_tokens": 0}
        parts: List[str] = []
        finish = "stop"
        for text, reason in self._generate(
            prompt_ids,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            min_p=min_p,
            repeat_penalty=repeat_penalty,
            stop=stop,
            usage=usage,
        ):
            parts.append(text)
            if reason is not None:
                finish = reason
        return {
            "id": f"cmpl-{uuid.uuid4().hex}",
            "object": "text_completion",
            "created": int(time.time()),
            "model": self.model_dir.name,
            "choices": [{"index": 0, "text": "".join(parts), "finish_reason": finish}],
            "usage": {
                "prompt_tokens": usage["prompt_tokens"],
                "completion_tokens": usage["completion_tokens"],
                "total_tokens": usage["prompt_tokens"] + usage["completion_tokens"],
            },
        }
