"""Which turns of one Agent Task chain a search query matches (read-only)."""

import re
import sqlite3
from dataclasses import dataclass
from typing import List, Optional

from .mutations.root_summary import build_search_document


@dataclass(frozen=True)
class TurnSearchMatches:
    """The query words and the ids of the turns that contain them, in chain order."""

    tokens: List[str]
    matched_turn_ids: List[str]


def query_tokens(query: Optional[str]) -> List[str]:
    """The lowercase words of a query, split the same way the sidebar search splits them."""
    return [token.lower() for token in re.findall(r"[\w]+", query or "")]


def find_matching_turns(conn: sqlite3.Connection, root_task_id: str, query: Optional[str]) -> Optional[TurnSearchMatches]:
    """Find the turns of a chain that hold the query words, or None when the chain does not exist.

    Each turn is indexed with the same document builder as the chain-wide search index, so a turn matches exactly what
    made the chain match. A turn needs every word; when no single turn has them all (the words are spread across turns),
    the turns holding the most words are returned instead so the reader still lands on the likeliest place.
    """
    tokens = query_tokens(query)
    rows = conn.execute(
        """
        SELECT *
        FROM agent_tasks
        WHERE COALESCE(root_task_id, id) = ?
        ORDER BY chain_sequence_number ASC, timestamp ASC, id ASC
        """,
        (root_task_id,),
    ).fetchall()
    if not any(row["id"] == root_task_id for row in rows):
        return None
    if not tokens:
        return TurnSearchMatches(tokens=[], matched_turn_ids=[])

    word_counts = []
    for row in rows:
        document = build_search_document([row]).lower()
        word_counts.append(sum(1 for token in tokens if token in document))
    best = max(word_counts)
    if best == 0:
        return TurnSearchMatches(tokens=tokens, matched_turn_ids=[])
    target = len(tokens) if best == len(tokens) else best
    matched = [row["id"] for row, count in zip(rows, word_counts) if count == target]
    return TurnSearchMatches(tokens=tokens, matched_turn_ids=matched)
