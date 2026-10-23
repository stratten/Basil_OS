"""Tests for the live-path repetition/non-speech degeneration guard.

Covers the exact loop shapes seen in the live transcript (unigram, cycle,
bracketed non-speech markers), cross-commit accumulation, prefix/suffix
preservation, and negative cases proving legible speech is never dropped.
"""

from api.services.whisper_live_core.repetition_degeneration_guard import (
    LENIENT_POLICY,
    STRICT_POLICY,
    RepetitionDegenerationTracker,
    repetition_policy_for_source,
    trim_degenerate_repetition,
)


class FakeToken:
    """Minimal stand-in for an ASR word token exposing ``text`` / ``is_silence``."""

    def __init__(self, text: str, silence: bool = False):
        self.text = text
        self._silence = silence

    def is_silence(self) -> bool:
        return self._silence

    def __repr__(self) -> str:  # aids test failure output
        return f"FakeToken({self.text!r})"


def _texts(tokens):
    return [t.text for t in tokens]


def _trim(tokens, policy=LENIENT_POLICY, carry=None):
    return trim_degenerate_repetition(tokens, carry=carry, policy=policy)


# ---- source policy selection ----

def test_policy_microphone_and_unknown_are_strict() -> None:
    assert repetition_policy_for_source("Microphone") is STRICT_POLICY
    assert repetition_policy_for_source("microphone") is STRICT_POLICY
    assert repetition_policy_for_source("unknown") is STRICT_POLICY
    assert repetition_policy_for_source("") is STRICT_POLICY
    assert repetition_policy_for_source(None) is STRICT_POLICY


def test_policy_named_system_sources_are_lenient() -> None:
    assert repetition_policy_for_source("System Audio (All Apps)") is LENIENT_POLICY
    assert repetition_policy_for_source("Zoom") is LENIENT_POLICY


# ---- unigram loop (the "no, no, no, ..." shape) ----

def test_unigram_loop_collapsed_to_single_copy() -> None:
    tokens = [FakeToken(" no,") for _ in range(40)]
    kept, _ = _trim(tokens)
    assert _texts(kept) == [" no,"]


def test_unigram_loop_preserves_prefix_and_suffix() -> None:
    # Mirrors the [17:59] log line: real speech, a long loop, then real speech.
    tokens = (
        [FakeToken("We"), FakeToken("on"), FakeToken("a"), FakeToken("club.")]
        + [FakeToken(" no,") for _ in range(60)]
        + [FakeToken("Bye."), FakeToken("Okay")]
    )
    kept, _ = _trim(tokens)
    assert _texts(kept) == ["We", "on", "a", "club.", " no,", "Bye.", "Okay"]


def test_its_loop_collapsed() -> None:
    # The [13:11]-[13:30] "it's it's it's ..." shape within one commit.
    tokens = [FakeToken("it's") for _ in range(30)]
    kept, _ = _trim(tokens)
    assert _texts(kept) == ["it's"]


# ---- cycle loop (the "the blue, the blue, ..." shape) ----

def test_two_word_cycle_collapsed_to_single_cycle() -> None:
    tokens = []
    for _ in range(25):
        tokens.append(FakeToken("the"))
        tokens.append(FakeToken("blue,"))
    kept, _ = _trim(tokens)
    assert _texts(kept) == ["the", "blue,"]


def test_two_word_cycle_keeps_following_real_speech() -> None:
    tokens = []
    for _ in range(25):
        tokens.append(FakeToken("the"))
        tokens.append(FakeToken("blue,"))
    tokens += [FakeToken("that"), FakeToken("the"), FakeToken("terms")]
    kept, _ = _trim(tokens)
    assert _texts(kept) == ["the", "blue,", "that", "the", "terms"]


# ---- bracketed non-speech marker runs ----

def test_marker_run_dropped_entirely() -> None:
    tokens = [FakeToken("[Music]") for _ in range(6)]
    kept, _ = _trim(tokens)
    assert kept == []


def test_paren_marker_run_dropped() -> None:
    tokens = [FakeToken("(upbeat music)") for _ in range(5)]
    kept, _ = _trim(tokens)
    assert kept == []


def test_single_marker_is_preserved() -> None:
    tokens = [FakeToken("Thanks"), FakeToken("for"), FakeToken("joining"), FakeToken("[MUSIC PLAYING]")]
    kept, _ = _trim(tokens)
    assert _texts(kept) == ["Thanks", "for", "joining", "[MUSIC PLAYING]"]


# ---- cross-commit accumulation ----

def test_loop_spanning_two_commits_is_suppressed_in_second() -> None:
    tracker = RepetitionDegenerationTracker(LENIENT_POLICY)
    # First commit: a few "no" (below threshold) -> emitted as-is.
    first = tracker.filter([FakeToken(" no,") for _ in range(4)])
    assert len(first) == 4
    # Second commit: the loop continues; combined run is well over threshold,
    # so the continuation is fully dropped (we already showed the lead-in).
    second = tracker.filter([FakeToken(" no,") for _ in range(30)])
    assert second == []


def test_cross_commit_resets_after_real_speech() -> None:
    tracker = RepetitionDegenerationTracker(LENIENT_POLICY)
    tracker.filter([FakeToken(" no,") for _ in range(30)])
    # New, unrelated speech must pass untouched once the loop ends.
    out = tracker.filter([FakeToken("don't"), FakeToken("see"), FakeToken("that")])
    assert _texts(out) == ["don't", "see", "that"]


def test_tracker_reset_clears_carry() -> None:
    tracker = RepetitionDegenerationTracker(LENIENT_POLICY)
    tracker.filter([FakeToken(" no,") for _ in range(30)])
    tracker.reset()
    # After reset the next short run starts fresh (3 copies kept, below threshold).
    out = tracker.filter([FakeToken(" no,") for _ in range(3)])
    assert len(out) == 3


# ---- negative cases (no recall cost) ----

def test_natural_triple_repeat_is_kept() -> None:
    # "No, no, no" said by a human is normal speech, not a loop.
    tokens = [FakeToken("No,"), FakeToken("no,"), FakeToken("no,")]
    kept, _ = _trim(tokens)
    assert _texts(kept) == ["No,", "no,", "no,"]


def test_normal_sentence_untouched() -> None:
    tokens = [FakeToken(w) for w in ["I", "do", "have", "to", "drop", "it"]]
    kept, _ = _trim(tokens)
    assert _texts(kept) == ["I", "do", "have", "to", "drop", "it"]


def test_microphone_policy_tolerates_more_repeats() -> None:
    # 7 repeats: dropped under the lenient (system) policy, kept under strict.
    tokens = [FakeToken("yeah") for _ in range(7)]
    lenient_kept, _ = _trim(tokens, policy=LENIENT_POLICY)
    strict_kept, _ = _trim(tokens, policy=STRICT_POLICY)
    assert _texts(lenient_kept) == ["yeah"]
    assert len(strict_kept) == 7


def test_silence_tokens_preserved_and_break_runs() -> None:
    silence = FakeToken("", silence=True)
    tokens = [FakeToken("ok"), silence, FakeToken("ok")]
    kept, _ = _trim(tokens)
    assert kept == tokens


def test_empty_tokens_noop() -> None:
    kept, carry = _trim([])
    assert kept == []
    assert carry == {"unit": (), "count": 0}
