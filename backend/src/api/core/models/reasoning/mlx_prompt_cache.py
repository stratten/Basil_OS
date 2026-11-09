"""A single-slot prompt cache for MLX text generation.

An agent run sends the same long prefix (system prompt, core tool schemas, earlier turns) with every model call, and without a cache MLX reads all of it again each time. This module keeps the attention state for the most recent long prompt so the next call only reads what changed.

Design rules:

* One slot, guarded by a non-blocking lock. A call that cannot take the slot, and a short unrelated call (a validator-style side call of a thousand tokens or so), run with a throwaway cache and never touch the slot.
* Models whose cache can be trimmed (plain attention layers) reuse the slot in place: the slot is trimmed back to the longest common prefix with the new prompt, then the changed tail is read.
* Models whose cache cannot be trimmed (hybrid and recurrent layers such as Qwen3.5 and Qwen3.6) cannot drop generated tokens afterwards, so the slot stores a checkpoint that stops a few tokens before the end of the prompt. Each call reads forward from the checkpoint, copies it, and generates on the copy, which leaves the checkpoint a clean prefix of the next prompt.
* Any exception discards the slot. A cancel keeps it, trimmed to what the cache actually holds.

``mlx_lm`` is imported lazily inside the default callables, so importing this module never loads Metal.
"""

from __future__ import annotations

import copy
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence

logger = logging.getLogger(__name__)

BYPASS_PROMPT_FRACTION = 0.25
BYPASS_SHARED_FRACTION = 0.5
CHECKPOINT_MARGIN_TOKENS = 32
MIN_CHECKPOINT_TOKENS = 256

PATH_DISABLED = "disabled"
PATH_BUSY = "bypass-busy"
PATH_SHORT = "bypass-short"
PATH_IN_PLACE = "in-place"
PATH_CHECKPOINT = "checkpoint"
PATH_FRESH = "fresh"


@dataclass
class PromptCacheStats:
    """What one generation call did with the prompt cache. The engine fills the timing fields as the call runs."""

    path: str
    prompt_tokens: int
    reused_tokens: int = 0
    prefill_tokens: int = 0
    first_token_seconds: Optional[float] = None
    prompt_tps: Optional[float] = None
    generation_tokens: int = 0
    generation_tps: Optional[float] = None

    def describe(self) -> str:
        return f"reused {self.reused_tokens} of {self.prompt_tokens} prompt tokens ({self.path})"


@dataclass
class CacheOperations:
    """Everything that touches MLX, so tests can substitute fakes."""

    make_cache: Callable[[Any], Any]
    can_trim: Callable[[Any], bool]
    trim: Callable[[Any, int], int]
    prefill: Callable[[Any, Sequence[int], Any], None]
    evaluate: Callable[[Any], None]
    offset: Callable[[Any], Optional[int]]
    copy_cache: Callable[[Any], Any]


def _default_make_cache(model: Any) -> Any:
    from mlx_lm.models.cache import make_prompt_cache

    return make_prompt_cache(model)


def _default_can_trim(cache: Any) -> bool:
    from mlx_lm.models.cache import can_trim_prompt_cache

    return bool(can_trim_prompt_cache(cache))


def _default_trim(cache: Any, count: int) -> int:
    from mlx_lm.models.cache import trim_prompt_cache

    return int(trim_prompt_cache(cache, count))


def _default_prefill(model: Any, ids: Sequence[int], cache: Any) -> None:
    """Read ``ids`` into ``cache`` without sampling. ``max_tokens=0`` feeds the whole prompt and generates nothing."""
    if not ids:
        return
    import mlx.core as mx
    from mlx_lm.generate import generate_step

    for _ in generate_step(mx.array(list(ids)), model, max_tokens=0, prompt_cache=cache):
        pass


def _default_evaluate(cache: Any) -> None:
    import mlx.core as mx

    mx.eval([layer.state for layer in cache])


def _default_offset(cache: Any) -> Optional[int]:
    """Tokens held by the cache, read from the first layer that reports an offset (attention layers do, recurrent layers do not)."""
    for layer in cache:
        value = getattr(layer, "offset", None)
        if isinstance(value, int):
            return value
    return None


def _default_copy(cache: Any) -> Any:
    return copy.deepcopy(cache)


DEFAULT_OPERATIONS = CacheOperations(
    make_cache=_default_make_cache,
    can_trim=_default_can_trim,
    trim=_default_trim,
    prefill=_default_prefill,
    evaluate=_default_evaluate,
    offset=_default_offset,
    copy_cache=_default_copy,
)


def common_prefix_length(left: Sequence[int], right: Sequence[int]) -> int:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return index


class PromptCacheLease:
    """What one generation call gets: the cache to pass to ``stream_generate`` and the tokens it still has to read."""

    def __init__(
        self,
        owner: Optional["MlxPromptCache"],
        cache: Any,
        feed_ids: List[int],
        prompt_ids: List[int],
        stats: PromptCacheStats,
        *,
        writes_slot: bool,
    ) -> None:
        self._owner = owner
        self.cache = cache
        self.feed_ids = feed_ids
        self._prompt_ids = prompt_ids
        self.stats = stats
        self._writes_slot = writes_slot
        self._finished = False

    def finish(self, generated_ids: Sequence[int], *, failed: bool) -> None:
        """Record what the cache now holds, or discard it after a failure, and free the slot. Safe to call twice."""
        if self._finished:
            return
        self._finished = True
        if self._owner is None:
            return
        self._owner._finish(self, generated_ids, failed=failed)


class MlxPromptCache:
    """One slot of attention state for the most recent long prompt."""

    def __init__(self, operations: CacheOperations = DEFAULT_OPERATIONS, *, enabled: bool = True) -> None:
        self._ops = operations
        self._enabled = bool(enabled)
        self._lock = threading.Lock()
        self._cache: Any = None
        self._tokens: List[int] = []
        self._trimmable: Optional[bool] = None
        self._fallback_logged = False

    # ---- public surface -----------------------------------------------------

    def acquire(self, model: Any, prompt_ids: List[int]) -> PromptCacheLease:
        if not self._enabled:
            return self._throwaway(prompt_ids, PATH_DISABLED)
        if not self._lock.acquire(blocking=False):
            return self._throwaway(prompt_ids, PATH_BUSY)
        try:
            lease = self._acquire_locked(model, prompt_ids)
        except _CacheUnavailable as exc:
            self._discard()
            self._lock.release()
            self._enabled = False
            logger.warning("[MlxPromptCache] Prompt caching is not available for this model, continuing without it: %s", exc)
            return self._throwaway(prompt_ids, PATH_DISABLED)
        except BaseException:
            self._discard()
            self._lock.release()
            raise
        if lease is None:
            self._lock.release()
            return self._throwaway(prompt_ids, PATH_SHORT)
        return lease

    def clear(self) -> None:
        """Drop the slot, for example when the engine closes. Waits for a call that is mid-generation only by the caller's own ordering."""
        self._discard()

    @property
    def cached_token_count(self) -> int:
        return len(self._tokens) if self._cache is not None else 0

    # ---- acquisition ----------------------------------------------------------

    def _throwaway(self, prompt_ids: List[int], path: str) -> PromptCacheLease:
        stats = PromptCacheStats(path=path, prompt_tokens=len(prompt_ids), prefill_tokens=len(prompt_ids))
        return PromptCacheLease(None, None, list(prompt_ids), prompt_ids, stats, writes_slot=False)

    def _acquire_locked(self, model: Any, prompt_ids: List[int]) -> Optional[PromptCacheLease]:
        if self._cache is None:
            self._open_slot(model)
        shared = common_prefix_length(self._tokens, prompt_ids)
        if self._should_bypass(len(self._tokens), len(prompt_ids), shared):
            return None
        if self._trimmable:
            return self._acquire_in_place(model, prompt_ids, shared)
        return self._acquire_checkpoint(model, prompt_ids, shared)

    def _open_slot(self, model: Any) -> None:
        try:
            cache = self._ops.make_cache(model)
            trimmable = bool(self._ops.can_trim(cache))
        except Exception as exc:
            raise _CacheUnavailable(str(exc)) from exc
        self._cache = cache
        self._tokens = []
        self._trimmable = trimmable
        if not trimmable and not self._fallback_logged:
            self._fallback_logged = True
            logger.info("[MlxPromptCache] This model's cache cannot be trimmed, so it keeps a prefix checkpoint instead of the whole conversation")

    @staticmethod
    def _should_bypass(cached_length: int, prompt_length: int, shared: int) -> bool:
        if cached_length <= 0:
            return False
        return prompt_length < cached_length * BYPASS_PROMPT_FRACTION and shared < prompt_length * BYPASS_SHARED_FRACTION

    def _acquire_in_place(self, model: Any, prompt_ids: List[int], shared: int) -> PromptCacheLease:
        reuse = min(shared, len(prompt_ids) - 1)
        excess = len(self._tokens) - reuse
        if excess > 0:
            if int(self._ops.trim(self._cache, excess)) == excess:
                self._tokens = self._tokens[:reuse]
            else:
                logger.warning("[MlxPromptCache] Trimming the cache failed, starting from an empty cache")
                self._cache = self._ops.make_cache(model)
                self._tokens = []
                reuse = 0
        feed = list(prompt_ids[reuse:])
        stats = PromptCacheStats(
            path=PATH_IN_PLACE if reuse else PATH_FRESH,
            prompt_tokens=len(prompt_ids),
            reused_tokens=reuse,
            prefill_tokens=len(feed),
        )
        return PromptCacheLease(self, self._cache, feed, prompt_ids, stats, writes_slot=True)

    def _acquire_checkpoint(self, model: Any, prompt_ids: List[int], shared: int) -> Optional[PromptCacheLease]:
        target = len(prompt_ids) - CHECKPOINT_MARGIN_TOKENS
        if target < MIN_CHECKPOINT_TOKENS:
            return None
        held = len(self._tokens)
        if held and (shared != held or held > target):
            self._cache = self._ops.make_cache(model)
            self._tokens = []
            held = 0
        reused = held
        cache = self._cache
        self._cache = None
        try:
            self._ops.prefill(model, prompt_ids[held:target], cache)
            self._ops.evaluate(cache)
        except BaseException:
            self._tokens = []
            raise
        self._cache = cache
        self._tokens = list(prompt_ids[:target])
        working = self._ops.copy_cache(cache)
        feed = list(prompt_ids[target:])
        stats = PromptCacheStats(
            path=PATH_CHECKPOINT if reused else PATH_FRESH,
            prompt_tokens=len(prompt_ids),
            reused_tokens=reused,
            prefill_tokens=(target - reused) + len(feed),
        )
        return PromptCacheLease(self, working, feed, prompt_ids, stats, writes_slot=False)

    # ---- completion -------------------------------------------------------------

    def _finish(self, lease: PromptCacheLease, generated_ids: Sequence[int], *, failed: bool) -> None:
        try:
            if lease._writes_slot:
                self._commit_in_place(lease, generated_ids, failed=failed)
        finally:
            self._lock.release()

    def _commit_in_place(self, lease: PromptCacheLease, generated_ids: Sequence[int], *, failed: bool) -> None:
        if failed:
            self._discard()
            return
        try:
            known = list(lease._prompt_ids) + [int(token) for token in generated_ids]
            held = self._ops.offset(self._cache)
            if held is None:
                self._discard()
                return
            if held > len(known):
                if int(self._ops.trim(self._cache, held - len(known))) != held - len(known):
                    self._discard()
                    return
                held = len(known)
            self._ops.evaluate(self._cache)
            self._tokens = known[:held]
        except Exception:
            logger.debug("[MlxPromptCache] Could not record the cache state, discarding it", exc_info=True)
            self._discard()

    def _discard(self) -> None:
        self._cache = None
        self._tokens = []


class _CacheUnavailable(RuntimeError):
    """Raised when the model cannot build a prompt cache, so caching is switched off and the call runs uncached."""
