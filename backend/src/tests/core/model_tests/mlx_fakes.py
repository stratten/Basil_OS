"""Fakes that let MlxChatEngine run without MLX or any model files."""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Optional, Sequence

from api.core.models.reasoning.mlx_engine import MlxChatEngine
from api.core.models.reasoning.mlx_prompt_cache import CacheOperations, MlxPromptCache


class FakeTokenizer:
    """One token per character. With add_special_tokens=True every token is offset by 1000 so the flag is observable."""

    def __init__(self) -> None:
        self.template_calls: List[Dict[str, Any]] = []

    def encode(self, text: str, add_special_tokens: bool = True) -> List[int]:
        offset = 1000 if add_special_tokens else 0
        return [ord(char) + offset for char in text]

    def decode(self, tokens: Sequence[int]) -> str:
        return "".join(chr(token - 1000 if token >= 1000 else token) for token in tokens)

    def apply_chat_template(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        add_generation_prompt: bool = True,
        tokenize: bool = False,
    ) -> str:
        self.template_calls.append(
            {
                "messages": messages,
                "tools": tools,
                "add_generation_prompt": add_generation_prompt,
                "tokenize": tokenize,
            }
        )
        body = "".join(f"<{message['role']}>{message.get('content') or ''}" for message in messages)
        return body + ("<assistant>" if add_generation_prompt else "")


def response(
    text: str,
    generation_tokens: Optional[int],
    *,
    finish_reason: Optional[str] = None,
    prompt_tokens: int = 0,
    token: Optional[int] = None,
) -> SimpleNamespace:
    """Shaped like mlx_lm.GenerationResponse for the fields the engine reads."""
    return SimpleNamespace(
        text=text,
        token=token,
        generation_tokens=generation_tokens,
        prompt_tokens=prompt_tokens,
        finish_reason=finish_reason,
    )


class FakeLayer:
    def __init__(self) -> None:
        self.offset = 0


class FakeCache:
    """One attention layer that only counts tokens, standing in for a list of mlx_lm cache layers."""

    def __init__(self, trimmable: bool) -> None:
        self.trimmable = trimmable
        self.layers = [FakeLayer()]

    def __iter__(self):
        return iter(self.layers)

    @property
    def offset(self) -> int:
        return self.layers[0].offset


class FakeCacheOperations:
    """Implements the CacheOperations seam with plain counters and records what the cache did."""

    def __init__(self, *, trimmable: bool = True, trim_works: bool = True, make_fails: bool = False, prefill_fails: bool = False) -> None:
        self.trimmable = trimmable
        self.trim_works = trim_works
        self.make_fails = make_fails
        self.prefill_fails = prefill_fails
        self.made: List[FakeCache] = []
        self.trims: List[int] = []
        self.prefills: List[int] = []
        self.copies = 0
        self.evaluations = 0

    def _make(self, model: Any) -> FakeCache:
        if self.make_fails:
            raise RuntimeError("this model has no prompt cache")
        cache = FakeCache(self.trimmable)
        self.made.append(cache)
        return cache

    def _trim(self, cache: FakeCache, count: int) -> int:
        self.trims.append(count)
        if not self.trim_works:
            return 0
        cache.layers[0].offset -= count
        return count

    def _prefill(self, model: Any, ids: Sequence[int], cache: FakeCache) -> None:
        if self.prefill_fails:
            raise RuntimeError("prefill failed")
        self.prefills.append(len(ids))
        cache.layers[0].offset += len(ids)

    def _evaluate(self, cache: FakeCache) -> None:
        self.evaluations += 1

    def _copy(self, cache: FakeCache) -> FakeCache:
        self.copies += 1
        return copy.deepcopy(cache)

    def operations(self) -> CacheOperations:
        return CacheOperations(
            make_cache=self._make,
            can_trim=lambda cache: cache.trimmable,
            trim=self._trim,
            prefill=self._prefill,
            evaluate=self._evaluate,
            offset=lambda cache: cache.offset,
            copy_cache=self._copy,
        )


class CachingStream:
    """Stands in for mlx_lm.stream_generate with a prompt cache: feeds the cache the way mlx_lm does and records each call.

    Like mlx_lm, every generated token is fed to the cache before it is yielded, and the closing response repeats the last token.
    """

    def __init__(self, tokens: Sequence[int] = (65, 66, 67), *, fail_after: Optional[int] = None) -> None:
        self.tokens = list(tokens)
        self.fail_after = fail_after
        self.calls: List[Dict[str, Any]] = []
        self.caches: List[Any] = []

    def __call__(self, model: Any, tokenizer: Any, **kwargs: Any) -> Iterator[SimpleNamespace]:
        self.calls.append({"prompt_length": len(kwargs["prompt"]), "has_cache": "prompt_cache" in kwargs})
        self.caches.append(kwargs.get("prompt_cache"))
        return self._iterate(kwargs["prompt"], kwargs.get("prompt_cache"))

    def _iterate(self, prompt: Sequence[int], cache: Any) -> Iterator[SimpleNamespace]:
        if cache is not None:
            cache.layers[0].offset += len(prompt)
        for index, token in enumerate(self.tokens):
            if self.fail_after is not None and index >= self.fail_after:
                raise RuntimeError("generation failed")
            if cache is not None:
                cache.layers[0].offset += 1
            yield response(chr(token), index + 1, token=token, prompt_tokens=len(prompt))
        yield response("", len(self.tokens), token=self.tokens[-1], finish_reason="length", prompt_tokens=len(prompt))


class ScriptedStream:
    """Stands in for mlx_lm.stream_generate: records its keyword arguments and hands out a closable iterator."""

    def __init__(self, responses: Sequence[SimpleNamespace]) -> None:
        self.responses = list(responses)
        self.calls: List[Dict[str, Any]] = []
        self.consumed = 0
        self.closed = False

    def __call__(self, model: Any, tokenizer: Any, **kwargs: Any) -> Iterator[SimpleNamespace]:
        self.calls.append(kwargs)
        return self._iterate()

    def _iterate(self) -> Iterator[SimpleNamespace]:
        try:
            for item in self.responses:
                self.consumed += 1
                yield item
        finally:
            self.closed = True


def make_engine(
    responses: Sequence[SimpleNamespace],
    *,
    context_window: int = 4096,
    model_dir: Any = "qwen35-4b-mlx-4bit",
    load: bool = True,
    stream: Any = None,
    prompt_cache: Optional[MlxPromptCache] = None,
) -> SimpleNamespace:
    """Build an engine whose every dependency is a recording fake. The prompt cache is off unless a test passes one."""
    tokenizer = FakeTokenizer()
    stream = stream if stream is not None else ScriptedStream(responses)
    samplers: List[Dict[str, Any]] = []
    processors: List[Dict[str, Any]] = []
    cleared: List[bool] = []
    loaded: List[str] = []

    def loader(path: str):
        loaded.append(path)
        return object(), tokenizer

    engine = MlxChatEngine(
        model_dir,
        context_window,
        loader=loader,
        stream_generate=stream,
        sampler_factory=lambda **kwargs: samplers.append(kwargs) or "sampler",
        logits_processor_factory=lambda **kwargs: processors.append(kwargs) or ["processor"],
        cache_clearer=lambda: cleared.append(True),
        prompt_cache=prompt_cache or MlxPromptCache(FakeCacheOperations().operations(), enabled=False),
    )
    if load:
        engine.load()
    return SimpleNamespace(
        engine=engine,
        tokenizer=tokenizer,
        stream=stream,
        samplers=samplers,
        processors=processors,
        cleared=cleared,
        loaded=loaded,
    )
