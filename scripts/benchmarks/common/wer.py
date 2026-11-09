"""Word error rate with a small edit-distance implementation (jiwer is not installed).

Normalization: lowercase, curly quotes to straight, hyphens and underscores to spaces, drop every character that is not a letter, digit, apostrophe, or space, collapse whitespace.
"""
from __future__ import annotations

import re
from typing import List, Sequence, Tuple


def normalize(text: str) -> List[str]:
    text = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    text = re.sub(r"[-_]", " ", text)
    text = re.sub(r"[^a-z0-9' ]", " ", text)
    return text.split()


def edit_distance(ref: Sequence[str], hyp: Sequence[str]) -> int:
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, start=1):
        current = [i]
        for j, h in enumerate(hyp, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (0 if r == h else 1)))
        previous = current
    return previous[-1]


def word_errors(reference: str, hypothesis: str) -> Tuple[int, int]:
    """Return (word errors, reference word count) for one utterance."""
    ref, hyp = normalize(reference), normalize(hypothesis)
    return edit_distance(ref, hyp), len(ref)


def corpus_wer(pairs: Sequence[Tuple[str, str]]) -> float:
    errors = words = 0
    for reference, hypothesis in pairs:
        e, n = word_errors(reference, hypothesis)
        errors += e
        words += n
    return errors / words if words else float("nan")


def term_recall(terms: Sequence[str], hypothesis: str) -> Tuple[int, int]:
    """Count target terms present in the hypothesis after normalization (multi-word terms must appear as a contiguous phrase)."""
    hyp = " ".join(normalize(hypothesis))
    found = sum(1 for term in terms if " ".join(normalize(term)) in hyp)
    return found, len(terms)


if __name__ == "__main__":
    assert word_errors("the cat sat", "the cat sat") == (0, 3)
    assert word_errors("the cat sat", "a cat sat down") == (2, 3)
    assert normalize("Don't stop-me, now!") == ["don't", "stop", "me", "now"]
    assert term_recall(["Kubernetes", "llama cpp"], "we run kubernetes and llama.cpp") == (2, 2)
    print("wer self-test passed")
