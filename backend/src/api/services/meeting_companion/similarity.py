"""Pure text heuristics shared by the gate, the prefetcher and de-duplication."""

from __future__ import annotations

import re
from typing import List, Set

# Reused rather than re-implemented: the same set-overlap measure the skill de-duplication uses (two empty sets score 0.0, so empty text never counts as a duplicate).
from api.services.skills.skill_overlap import jaccard_similarity as jaccard  # noqa: F401

_WORD = re.compile(r"[A-Za-z0-9_]+(?:'[A-Za-z]+)?")

STOPWORDS = frozenset(
    {
        "the", "and", "for", "that", "this", "with", "from", "have", "has", "had", "are", "was", "were",
        "will", "would", "could", "should", "can", "not", "but", "you", "your", "our", "their", "they",
        "them", "then", "than", "there", "here", "what", "when", "where", "which", "who", "whom", "how",
        "why", "about", "into", "over", "also", "just", "like", "got", "get", "its", "it's", "i'm",
        "we're", "you're", "they're", "don't", "doesn't", "didn't", "can't", "won't", "yeah", "okay",
        "know", "think", "going", "gonna", "really", "very", "some", "any", "all", "out", "one", "two",
        "been", "being", "does", "did", "too", "now", "see", "say", "said", "make", "made", "need",
    }
)

BACKCHANNEL = frozenset(
    {
        "yeah", "yes", "yep", "yup", "right", "okay", "ok", "mm", "hmm", "uh", "um", "uhh", "mhm",
        "sure", "cool", "great", "thanks", "thank", "you", "alright", "no", "nope", "got", "it",
        "good", "fine", "exactly", "absolutely", "totally", "so", "well", "and", "i", "see",
    }
)

INTERROGATIVES = frozenset(
    {
        "what", "how", "why", "when", "where", "who", "which", "can", "could", "would", "do", "does",
        "did", "is", "are", "will", "should", "have", "has", "may",
    }
)


def normalize_text(text: str) -> str:
    """Collapse whitespace runs and trim."""
    return " ".join(text.split())


def tokens(text: str) -> List[str]:
    """Lower-cased word tokens."""
    return [match.group(0).lower() for match in _WORD.finditer(text)]


def content_tokens(text: str) -> Set[str]:
    """Distinct lower-cased tokens of three or more characters that are not stopwords."""
    return {token for token in tokens(text) if len(token) >= 3 and token not in STOPWORDS}


def is_backchannel(text: str) -> bool:
    """True for utterances too short or too filler-like to trigger the Companion."""
    words = tokens(text)
    if len(words) < 4:
        return True
    return all(word in BACKCHANNEL for word in words)


def looks_like_question(text: str) -> bool:
    """Heuristic question detection that also works when the recognizer omits the question mark."""
    stripped = normalize_text(text)
    words = tokens(stripped)
    if len(words) < 3 or is_backchannel(stripped):
        return False
    if stripped.endswith("?"):
        return True
    return len(words) >= 5 and words[0] in INTERROGATIVES
