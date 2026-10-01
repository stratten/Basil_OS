"""Build the single final-narrative prompt shared by every memory source.

One prompt and one output contract makes the narrative consistent across sources. Source adapters decide when an event is terminal before it reaches the model; the model describes that final event and never controls its lifecycle.

The contract covers length as well as shape. MAX_NARRATIVE_CHARS is stated to the model here and enforced by the synthesizer on the reply, because entries are meant to stay succinct; detail beyond that is read from the source record.
"""

from __future__ import annotations

import json
from typing import Any, Dict

# The gathered context can be large (an agent task's result_data especially);
# cap what reaches the model so a single row cannot blow the context window.
CONTEXT_MAX_CHARS = 6000

# The stored-narrative length contract. It lives here, beside the instruction
# that states it, and the synthesizer imports it to validate against; keeping one
# constant means a model can never be rejected against a limit it was not told.
# (The reverse direction would be an import cycle: synthesizer imports prompt.)
MAX_NARRATIVE_CHARS = 600

# Each hint names the subject of the summary, not the machinery that captured it.
# "a voice/audio transcription" invited narrating that transcription succeeded,
# which cost roughly a third of every summary and, across a stream dominated by
# dictation, would have made "capture worked" the loudest recurring signal.
_KIND_HINTS = {
    "agent_task": (
        "an autonomous agent task run, possibly multi-step; summarize what the "
        "agent did and what it produced"
    ),
    "transcription": (
        "something you said out loud; summarize what you said, not that audio was "
        "captured or converted to text"
    ),
    "assistant_output": (
        "an assistant response to your request; summarize what the response "
        "actually said or concluded"
    ),
    "scheduled_run": (
        "a scheduled agent task execution; summarize what it did and what it "
        "produced"
    ),
    "conversation_turn": (
        "one user message and its completed, failed, or canceled assistant response; "
        "summarize the exchange and its terminal outcome"
    ),
    "screen_block": (
        "a block of on-screen activity captured over a span of time; summarize "
        "what you were working on"
    ),
    "meeting": (
        "a recorded meeting or call; summarize what it was about and its "
        "substantive outcome, drawing on the transcript and any analysis "
        "provided"
    ),
}


def _bounded_json(value: Any) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, default=str, indent=2)
    except (TypeError, ValueError):
        encoded = str(value)
    if len(encoded) <= CONTEXT_MAX_CHARS:
        return encoded
    return encoded[:CONTEXT_MAX_CHARS] + "\n... [truncated]"


def build_prompt(entry: Dict[str, Any], context: Dict[str, Any]) -> str:
    kind = str(entry.get("source_kind") or "event")
    hint = _KIND_HINTS.get(kind, "an application event")
    header = {
        "type": kind,
        "title": entry.get("title"),
        "occurred_at": entry.get("occurred_at"),
        "status": entry.get("source_status"),
        "outcome": entry.get("outcome"),
        "card_summary": entry.get("summary"),
        "metadata": entry.get("payload"),
    }
    return (
        "You summarize a single item from a personal activity log. This item is "
        f"{hint}.\n\n"
        "Write a concise, faithful narrative of the substance recorded here. "
        "Describe what happened or what the record expresses - such as a request, "
        "question, decision, or stated intent. State what was produced or concluded "
        "only when the source material supports it. Do not claim that a requested "
        "action was completed merely because it was requested, and do not describe "
        "how the item was captured or processed. Address the user "
        f'as "you". Two to four sentences, under {MAX_NARRATIVE_CHARS} characters '
        "in total. Do not try to be comprehensive: anything needing more detail than this is read "
        "from the source record instead.\n\n"
        "This is a terminal memory event. Describe its actual outcome faithfully, "
        "including a failure or cancellation when recorded, but do not decide "
        "whether it remains open.\n\n"
        "Provide your answer as a JSON object with exactly this structure:\n"
        "{\n"
        f'  "narrative": "Two to four sentences, under {MAX_NARRATIVE_CHARS} '
        'characters, of the substantive event or intent recorded"\n'
        "}\n\n"
        "IMPORTANT GUIDELINES:\n"
        '1. Address the user as "you" and describe the substantive event or intent; distinguish a request from its outcome\n'
        f"2. Keep the narrative under {MAX_NARRATIVE_CHARS} characters; a longer one is rejected\n"
        "3. Never mention how the item was captured or processed: no tool or model "
        "names, no durations, no character counts, and not whether it succeeded or "
        "failed. All of that is recorded separately. Write only what happened\n"
        "4. Do not invent detail that is not present in the source material\n"
        "5. Do not include reasoning, planning, or commentary outside the JSON object\n"
        "6. Do not use markdown code blocks or backticks - return raw JSON only\n"
        "7. Return exactly one JSON object; do not emit a second one\n"
        "8. Return valid JSON that can be parsed programmatically\n\n"
        "ITEM HEADER:\n"
        f"{_bounded_json(header)}\n\n"
        "SOURCE MATERIAL:\n"
        f"{_bounded_json(context)}\n"
    )
