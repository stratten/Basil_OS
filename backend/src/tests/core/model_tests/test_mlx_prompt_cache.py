"""The MLX prompt cache reuses the shared prefix of a long prompt, keeps short side calls from evicting it, and recovers from every failure."""

from types import SimpleNamespace

import pytest

from api.core.models.reasoning.mlx_engine import MlxChatEngine, _prompt_cache_enabled_by_environment
from api.core.models.reasoning.mlx_prompt_cache import MlxPromptCache

from .mlx_fakes import CachingStream, FakeCacheOperations, ScriptedStream, make_engine, response

SYSTEM = "S" * 400
# The fake template renders "<system>" + text + "<user>" + text + "<assistant>", one token per character, so this prompt is 8 + 400 + 6 + 2 + 11 tokens.
FIRST_PROMPT_TOKENS = 427


def build(*, trimmable=True, stream=None, **operation_options):
    operations = FakeCacheOperations(trimmable=trimmable, **operation_options)
    prompt_cache = MlxPromptCache(operations.operations())
    caching_stream = stream or CachingStream()
    harness = make_engine([], stream=caching_stream, prompt_cache=prompt_cache)
    return SimpleNamespace(operations=operations, prompt_cache=prompt_cache, stream=caching_stream, engine=harness.engine)


def chat(harness, user="q1", *, system=SYSTEM, stream=False):
    return harness.engine.create_chat_completion(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=8,
        stream=stream,
    )


# ---- trimmable models: the slot is reused in place ----------------------------


def test_the_first_call_reads_the_whole_prompt_into_a_new_slot():
    harness = build()

    chat(harness)

    stats = harness.engine.last_prompt_stats
    assert (stats.path, stats.prompt_tokens, stats.reused_tokens, stats.prefill_tokens) == ("fresh", FIRST_PROMPT_TOKENS, 0, FIRST_PROMPT_TOKENS)
    assert harness.stream.calls == [{"prompt_length": FIRST_PROMPT_TOKENS, "has_cache": True}]
    assert harness.prompt_cache.cached_token_count == FIRST_PROMPT_TOKENS + 3


def test_a_follow_up_with_the_same_prefix_reads_only_what_changed():
    harness = build()
    chat(harness, "q1")

    result = chat(harness, "q2")

    stats = harness.engine.last_prompt_stats
    shared = len("<system>") + len(SYSTEM) + len("<user>") + 1
    assert (stats.path, stats.reused_tokens, stats.prefill_tokens) == ("in-place", shared, FIRST_PROMPT_TOKENS - shared)
    assert harness.stream.calls[-1]["prompt_length"] == FIRST_PROMPT_TOKENS - shared
    assert harness.operations.trims == [FIRST_PROMPT_TOKENS + 3 - shared]
    assert result["usage"]["prompt_tokens"] == FIRST_PROMPT_TOKENS
    assert result["choices"][0]["message"]["content"] == "ABC"


def test_an_identical_prompt_still_leaves_one_token_to_read():
    harness = build()
    chat(harness, "q1")

    chat(harness, "q1")

    stats = harness.engine.last_prompt_stats
    assert stats.reused_tokens == FIRST_PROMPT_TOKENS - 1
    assert harness.stream.calls[-1]["prompt_length"] == 1


def test_a_short_unrelated_call_does_not_touch_the_main_slot():
    harness = build()
    chat(harness, "q1")
    held = harness.prompt_cache.cached_token_count

    chat(harness, "y", system="x")

    stats = harness.engine.last_prompt_stats
    assert stats.path == "bypass-short"
    assert harness.stream.calls[-1]["has_cache"] is False
    assert harness.prompt_cache.cached_token_count == held
    assert harness.operations.trims == []
    chat(harness, "q2")
    assert harness.engine.last_prompt_stats.path == "in-place"


def test_a_short_call_that_mostly_matches_the_cache_is_served_from_it():
    harness = build()
    chat(harness, "q1")

    chat(harness, "q1", system="S" * 20)

    assert harness.engine.last_prompt_stats.reused_tokens > 0
    assert harness.stream.calls[-1]["has_cache"] is True


def test_a_busy_slot_sends_the_second_call_through_a_throwaway_cache():
    harness = build()
    first = chat(harness, "q1", stream=True)
    next(first)

    chat(harness, "q2")

    assert harness.engine.last_prompt_stats.path == "bypass-busy"
    assert harness.stream.calls[-1]["has_cache"] is False
    first.close()
    chat(harness, "q3")
    assert harness.engine.last_prompt_stats.path == "in-place"


def test_canceling_keeps_the_cache_trimmed_to_what_it_holds():
    harness = build()
    stream = chat(harness, "q1", stream=True)
    next(stream)
    next(stream)

    stream.close()

    assert harness.prompt_cache.cached_token_count == FIRST_PROMPT_TOKENS + 1
    chat(harness, "q2")
    assert harness.engine.last_prompt_stats.path == "in-place"


def test_a_failure_discards_the_cache_and_the_next_call_starts_clean():
    harness = build(stream=CachingStream(fail_after=1))

    with pytest.raises(RuntimeError, match="generation failed"):
        chat(harness, "q1")

    assert harness.prompt_cache.cached_token_count == 0
    harness.stream.fail_after = None
    chat(harness, "q2")
    assert harness.engine.last_prompt_stats.path == "fresh"
    assert len(harness.operations.made) == 2


def test_a_cache_that_cannot_be_trimmed_back_starts_from_an_empty_cache():
    harness = build(trim_works=False)
    chat(harness, "q1")

    chat(harness, "q2")

    stats = harness.engine.last_prompt_stats
    assert (stats.path, stats.reused_tokens) == ("fresh", 0)
    assert harness.stream.calls[-1]["prompt_length"] == FIRST_PROMPT_TOKENS
    assert len(harness.operations.made) == 2


def test_closing_the_engine_releases_the_slot():
    harness = build()
    chat(harness)

    harness.engine.close()

    assert harness.prompt_cache.cached_token_count == 0
    assert harness.engine.last_prompt_stats is None


# ---- models whose cache cannot be trimmed: a prefix checkpoint ----------------


def test_a_hybrid_model_checkpoints_the_prompt_short_of_the_end_and_generates_on_a_copy():
    harness = build(trimmable=False)

    chat(harness, "q1")

    stats = harness.engine.last_prompt_stats
    checkpoint = FIRST_PROMPT_TOKENS - 32
    assert (stats.path, stats.reused_tokens, stats.prefill_tokens) == ("fresh", 0, FIRST_PROMPT_TOKENS)
    assert harness.operations.prefills == [checkpoint]
    assert harness.operations.copies == 1
    assert harness.stream.calls == [{"prompt_length": 32, "has_cache": True}]
    assert harness.prompt_cache.cached_token_count == checkpoint
    assert harness.stream.caches[0] is not harness.operations.made[0]


def test_a_hybrid_follow_up_reads_forward_from_the_checkpoint():
    harness = build(trimmable=False)
    chat(harness, "q1")

    chat(harness, "q2" + "x" * 15)

    stats = harness.engine.last_prompt_stats
    checkpoint = FIRST_PROMPT_TOKENS - 32
    assert (stats.path, stats.reused_tokens) == ("checkpoint", checkpoint)
    assert harness.operations.prefills == [checkpoint, 15]
    assert stats.prefill_tokens == 15 + 32
    assert harness.prompt_cache.cached_token_count == checkpoint + 15
    assert len(harness.operations.made) == 1


def test_a_hybrid_prompt_that_diverges_inside_the_checkpoint_starts_over():
    harness = build(trimmable=False)
    chat(harness, "q1")

    chat(harness, "q1", system="S" * 100 + "T" * 300)

    stats = harness.engine.last_prompt_stats
    assert (stats.path, stats.reused_tokens) == ("fresh", 0)
    assert len(harness.operations.made) == 2


def test_a_hybrid_short_prompt_gets_no_checkpoint():
    harness = build(trimmable=False)

    chat(harness, "y", system="x")

    assert harness.engine.last_prompt_stats.path == "bypass-short"
    assert harness.stream.calls[-1]["has_cache"] is False
    assert harness.prompt_cache.cached_token_count == 0


def test_a_hybrid_generation_failure_leaves_the_checkpoint_intact():
    harness = build(trimmable=False, stream=CachingStream(fail_after=0))
    with pytest.raises(RuntimeError, match="generation failed"):
        chat(harness, "q1")

    assert harness.prompt_cache.cached_token_count == FIRST_PROMPT_TOKENS - 32
    harness.stream.fail_after = None
    chat(harness, "q2")
    assert harness.engine.last_prompt_stats.path == "checkpoint"


# ---- failures of the cache itself ------------------------------------------------


def test_a_failed_prefill_discards_the_slot_and_releases_the_lock():
    harness = build(trimmable=False, prefill_fails=True)

    with pytest.raises(RuntimeError, match="prefill failed"):
        chat(harness, "q1")

    assert harness.prompt_cache.cached_token_count == 0
    harness.operations.prefill_fails = False
    chat(harness, "q1")
    assert harness.engine.last_prompt_stats.path == "fresh"


def test_a_model_without_a_prompt_cache_runs_uncached_and_stops_trying():
    harness = build(make_fails=True)

    chat(harness, "q1")
    chat(harness, "q2")

    assert harness.engine.last_prompt_stats.path == "disabled"
    assert [call["has_cache"] for call in harness.stream.calls] == [False, False]
    assert harness.operations.made == []


def test_a_disabled_cache_never_builds_a_slot():
    operations = FakeCacheOperations()
    harness = make_engine([], stream=CachingStream(), prompt_cache=MlxPromptCache(operations.operations(), enabled=False))

    chat(SimpleNamespace(engine=harness.engine))

    assert harness.engine.last_prompt_stats.path == "disabled"
    assert operations.made == []


@pytest.mark.parametrize("value", ["0", "false", "OFF", " no "])
def test_the_environment_variable_can_turn_the_cache_off(monkeypatch, value):
    monkeypatch.setenv("BASIL_MLX_PROMPT_CACHE", value)
    assert _prompt_cache_enabled_by_environment() is False


@pytest.mark.parametrize("value", [None, "1", "true", "anything"])
def test_the_cache_is_on_by_default(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("BASIL_MLX_PROMPT_CACHE", raising=False)
    else:
        monkeypatch.setenv("BASIL_MLX_PROMPT_CACHE", value)
    assert _prompt_cache_enabled_by_environment(total_ram_gb=32) is True


@pytest.mark.parametrize(("total_ram_gb", "expected"), [(8, False), (15, False), (16, True), (24, True), (96, True), (None, True)])
def test_the_cache_is_off_below_the_memory_floor_when_the_environment_is_silent(monkeypatch, total_ram_gb, expected):
    monkeypatch.delenv("BASIL_MLX_PROMPT_CACHE", raising=False)
    monkeypatch.setattr("api.core.models.preference_models.defaults._detected_total_ram_gb", lambda: total_ram_gb)

    assert _prompt_cache_enabled_by_environment() is expected


def test_an_explicit_environment_value_beats_the_memory_floor(monkeypatch):
    monkeypatch.setenv("BASIL_MLX_PROMPT_CACHE", "1")
    assert _prompt_cache_enabled_by_environment(total_ram_gb=8) is True
    monkeypatch.setenv("BASIL_MLX_PROMPT_CACHE", "0")
    assert _prompt_cache_enabled_by_environment(total_ram_gb=96) is False


# ---- streaming timing ---------------------------------------------------------------


def test_the_role_chunk_is_sent_only_after_the_prompt_has_been_read():
    stream = ScriptedStream([response("Hi", 1), response("", 1, finish_reason="stop")])
    engine: MlxChatEngine = make_engine([], stream=stream).engine

    chunks = engine.create_chat_completion(messages=[{"role": "user", "content": "hi"}], stream=True)
    assert stream.consumed == 0

    role_chunk = next(chunks)

    assert role_chunk["choices"][0]["delta"] == {"role": "assistant"}
    assert stream.consumed >= 1
    assert [chunk["choices"][0]["delta"].get("content") for chunk in chunks][0] == "Hi"
