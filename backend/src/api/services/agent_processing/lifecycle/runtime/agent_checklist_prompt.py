"""The bounded per-turn checklist block that is pushed into the model's prompt.

The checklist is state, so the model is shown it every turn instead of being trusted to pull it. The block has a hard size cap that scales with the model's prompt budget, so a long list or a long notes document can never crowd out a small model's window.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

CHARS_PER_TOKEN = 3
CHECKLIST_BUDGET_SHARE = 0.03
NOTES_BUDGET_SHARE = 0.02
CHECKLIST_MIN_CHARS = 600
CHECKLIST_MAX_CHARS = 3000
CHECKLIST_DEFAULT_CHARS = 1500
NOTES_INLINE_MAX_CHARS = 1500
COMPACT_MAX_CHARS = 500
COMPACT_ITEM_COUNT = 3
TITLE_CLIP_CHARS = 80
COMPACT_TITLE_CLIP_CHARS = 60
WAITING_CLIP_CHARS = 60
SHORT_ID_CHARS = 8
LEDGER_HINT_MIN_ITEMS = 3

_STATUS_PRIORITY = {"waiting_user": 0, "in_progress": 1, "pending": 2, "waiting_external": 3}
_CARRIED_NOTES_LABEL = "carried from the previous run, verify before relying on it"


def short_id(item_id: str) -> str:
    return str(item_id)[:SHORT_ID_CHARS]


def build_ledger_hint() -> str:
    """One line for a task whose checklist is empty although the coverage ledger already holds discovered records."""
    return (
        "CHECKLIST (empty). The coverage ledger already holds records found earlier in this chain, "
        "but the user sees only the checklist. Add one checklist item for the outcome each record needs (handled, decided, or followed up), "
        "with a reference to its thread or record, all in one call with items, and keep each item open until that outcome has really happened."
    )


def build_mid_run_cue() -> str:
    """Sent once, after a tool result, when the run has found a set of records and the checklist is still empty."""
    return (
        "CHECKLIST CHECK: your tools have returned a set of records, and this task's checklist is still empty. "
        "The user follows what still needs to happen only through the checklist. If these records each need an outcome (handled, decided, or followed up), "
        "call checklist add now with one item per record for that outcome, naming its thread or record, all in one call with items. Use a single batch item only if the set is larger than about 10. "
        "An item is an outcome, never your own action, and stays open until the outcome has really happened; a proposal or draft leaves it waiting_user. If this request needs no such tracking, carry on and do not mention this message."
    )


def build_empty_checklist_review() -> str:
    """Sent at most once, in place of a final answer, when the run found records but never created a checklist item."""
    return (
        "CHECKLIST CHECK (asked once, before your final answer): this run found a set of records but the checklist has no items, "
        "and the user sees only the checklist. If your answer covers several records, call checklist add now with one item per record for the outcome it needs "
        "(one batch item only if the set is larger than about 10, all in one call with items), set each to its true status (done only if the outcome already happened, waiting_user with waiting_on for a proposal or decision that needs the user, pending or in_progress if the next step is yours, or dropped), "
        "and then give your final answer again. If no tracking applies to this request, give the same final answer again. Do not mention this check in your answer."
    )


def _clip(text: Any, limit: int) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _budget_chars(prompt_budget_tokens: Optional[int], share: float) -> Optional[int]:
    if not prompt_budget_tokens:
        return None
    return int(prompt_budget_tokens * CHARS_PER_TOKEN * share)


def _counts_line(counts: Dict[str, int]) -> str:
    parts = [f"{counts['done']} of {counts['total']} done"]
    if counts.get("waiting_user"):
        parts.append(f"{counts['waiting_user']} waiting on the user")
    if counts.get("waiting_external"):
        parts.append(f"{counts['waiting_external']} waiting on others")
    return ", ".join(parts)


def _item_line(item: Dict[str, Any], title_limit: int) -> str:
    line = f"- [{item['status']}] {_clip(item['title'], title_limit)} (id {short_id(item['id'])})"
    if item.get("required"):
        line += " required"
    if item["status"] in ("waiting_user", "waiting_external") and item.get("waiting_on"):
        line += f", waiting on: {_clip(item['waiting_on'], WAITING_CLIP_CHARS)}"
    if item.get("last_actor") == "user":
        line += " (edited by the user)"
    return line


def _ranked_open_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    open_items = [item for item in items if item["status"] in _STATUS_PRIORITY and not item.get("archived_at")]
    return sorted(open_items, key=lambda item: (_STATUS_PRIORITY[item["status"]], item.get("sort_order", 0)))


def _notes_line(notes: Dict[str, Any], prompt_budget_tokens: Optional[int]) -> str:
    content = str(notes.get("content") or "")
    if not content:
        return ""
    allowed = _budget_chars(prompt_budget_tokens, NOTES_BUDGET_SHARE)
    inline_limit = NOTES_INLINE_MAX_CHARS if allowed is None else min(NOTES_INLINE_MAX_CHARS, allowed)
    label = "NOTES"
    if notes.get("carried_from_task_id") and notes.get("updated_by") == "system":
        label += f" ({_CARRIED_NOTES_LABEL})"
    elif notes.get("updated_by") == "user":
        label += " (last edited by the user)"
    if len(content) <= inline_limit:
        return f"{label}:\n{content}"
    return f"{label}: {len(content)} characters, too long to show here. Read them with checklist_notes (action read) when you need them."


def build_checklist_prompt_section(
    items: List[Dict[str, Any]],
    counts: Dict[str, int],
    notes: Dict[str, Any],
    *,
    prompt_budget_tokens: Optional[int],
    closed: bool = False,
) -> str:
    """Return the checklist block for this turn, or an empty string when the task has no checklist or notes yet."""
    has_notes = bool(str(notes.get("content") or ""))
    if counts.get("total", 0) == 0 and not has_notes:
        return ""
    share = _budget_chars(prompt_budget_tokens, CHECKLIST_BUDGET_SHARE)
    if share is not None and share < CHECKLIST_MIN_CHARS:
        return _compact_section(items, counts, notes, closed=closed)
    limit = CHECKLIST_DEFAULT_CHARS if share is None else min(CHECKLIST_MAX_CHARS, share)
    status = "closed by the user" if closed else _counts_line(counts)
    header = f"CHECKLIST (this task's durable list: {status}). Keep it current with the checklist tool; use checklist list for the rest."
    lines = [header]
    used = len(header)
    ranked = _ranked_open_items(items)
    shown = 0
    for item in ranked:
        line = _item_line(item, TITLE_CLIP_CHARS)
        if used + len(line) + 1 > limit:
            break
        lines.append(line)
        used += len(line) + 1
        shown += 1
    if len(ranked) > shown:
        lines.append(f"- and {len(ranked) - shown} more open items")
    notes_text = _notes_line(notes, prompt_budget_tokens)
    return "\n".join([*lines, notes_text] if notes_text else lines)


def _compact_section(items: List[Dict[str, Any]], counts: Dict[str, int], notes: Dict[str, Any], *, closed: bool) -> str:
    """Counts plus the top few items, for windows too small to afford the full block."""
    status = "closed by the user" if closed else _counts_line(counts)
    lines = [f"CHECKLIST ({status}). Use checklist list for details."]
    ranked = _ranked_open_items(items)
    for item in ranked[:COMPACT_ITEM_COUNT]:
        lines.append(f"- [{item['status']}] {_clip(item['title'], COMPACT_TITLE_CLIP_CHARS)} (id {short_id(item['id'])})")
    if len(ranked) > COMPACT_ITEM_COUNT:
        lines.append(f"- and {len(ranked) - COMPACT_ITEM_COUNT} more open items")
    if str(notes.get("content") or ""):
        lines.append("NOTES exist; read them with checklist_notes (action read).")
    text = "\n".join(lines)
    return text if len(text) <= COMPACT_MAX_CHARS else text[: COMPACT_MAX_CHARS - 1].rstrip() + "…"
