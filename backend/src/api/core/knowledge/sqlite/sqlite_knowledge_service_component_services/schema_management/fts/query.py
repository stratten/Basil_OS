"""Shared FTS5 query helpers.

Extracted from the agent-task search path so the meeting transcript search
repository can reuse identical tokenization, MATCH-query formatting, and LIKE
fallback escaping. `AgentTaskQueries` keeps its own private copies (left
untouched to avoid risk to a working path); these are the canonical versions.
"""

import re
from typing import List


def search_tokens(query: str) -> List[str]:
    """Lowercased word tokens from a free-text query (punctuation stripped)."""
    return [token.lower() for token in re.findall(r"[\w]+", query or "")]


def format_fts_match_query(query: str) -> str:
    """Build an FTS5 MATCH expression: prefix-match every token, AND-joined.

    Returns an empty string when the query has no usable tokens, so callers can
    fall back to a substring search instead of issuing an invalid MATCH.
    """
    tokens = search_tokens(query)
    return " AND ".join(f'"{token}"*' for token in tokens)


def escape_like_token(token: str) -> str:
    """Escape a token for a `LIKE ? ESCAPE '\\'` substring fallback."""
    return token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
