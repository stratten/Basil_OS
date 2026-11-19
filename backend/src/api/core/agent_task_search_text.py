"""The one builder for the text indexed to search a conversation chain.

Both the write path (``agent_tasks/mutations/root_summary.py``) and the schema migration backfill call this, so they cannot disagree about what is indexed. It imports nothing from the knowledge packages, so either side can import it without a cycle.

A follow-up task's ``accumulated_artifacts`` carries ``chain_agentTasks``, a copy of every earlier turn in its chain (its text, its full result, and its operation). Indexing every copy made a chain's entry grow with the square of its length, and some reached hundreds of megabytes. Almost every copy repeats text that is already indexed from that turn's own row, but not all: when a turn's own stored result was later replaced, the copy is the only surviving record of what it produced. So a copied field is left out only when its text is already inside that turn's own indexed text, and is kept, once, when it is not.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, List, Optional

from api.core.json_helpers import json_loads_or_empty as safe_json_loads

SEARCH_COLUMNS = (
    "title", "original_prompt", "transcribed_prompt",
    "app_name", "window_title", "screen_text",
    "result_preview", "result_data", "accumulated_artifacts",
    "execution_timeline",
)
JSON_COLUMNS = frozenset({"result_data", "accumulated_artifacts", "execution_timeline"})
CHAIN_COPY_KEY = "chain_agentTasks"
CHAIN_COPY_FIELDS = ("text", "result", "operation")


def render_search_value(value: Any) -> Optional[str]:
    """The text a value contributes to the document, or None when it contributes nothing."""
    if value is None:
        return None
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def append_search_value(parts: List[str], value: Any) -> None:
    rendered = render_search_value(value)
    if rendered is not None:
        parts.append(rendered)


def build_search_document(rows: List[sqlite3.Row]) -> str:
    """Build the search text for a chain from its rows, ordered oldest first."""
    parts: List[str] = []
    own_text_by_task_id: dict[Any, str] = {}
    seen_copies: set[tuple[Any, str, int]] = set()

    for row in rows:
        row_parts: List[str] = []
        chain_copies: Any = None
        for key in SEARCH_COLUMNS:
            if key not in row.keys():
                continue
            value = row[key]
            if key in JSON_COLUMNS:
                value = safe_json_loads(value)
            if key == "accumulated_artifacts" and isinstance(value, dict) and CHAIN_COPY_KEY in value:
                chain_copies = value[CHAIN_COPY_KEY]
                value = {name: item for name, item in value.items() if name != CHAIN_COPY_KEY}
            append_search_value(row_parts, value)

        parts.extend(row_parts)
        own_text_by_task_id[row["id"] if "id" in row.keys() else None] = "\n".join(row_parts)

        if not isinstance(chain_copies, list):
            continue
        for item in chain_copies:
            if not isinstance(item, dict):
                continue
            task_id = item.get("id")
            own_text = own_text_by_task_id.get(task_id, "")
            for field in CHAIN_COPY_FIELDS:
                rendered = render_search_value(item.get(field))
                if rendered is None:
                    continue
                fingerprint = (task_id, field, hash(rendered))
                if fingerprint in seen_copies:
                    continue
                seen_copies.add(fingerprint)
                if rendered not in own_text:
                    parts.append(rendered)

    return "\n".join(parts)
