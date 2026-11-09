"""A narrow guard that keeps the working notes from recording tool outcomes the chain never produced.

The check is deliberately limited. It looks only at explicit tool references written the way the work ledger records them (a service-style name such as gmail_service.send_email or gmail_service_send_email) that sit in the same sentence as a word claiming an outcome (sent, completed, verified, and so on). It cannot judge free prose such as "I emailed the clinic", and it does not try to. A claim passes when the ledger holds any receipt for that service and method in this chain, whatever its result, because the note's job is to describe where things stand and a failed call is a legitimate thing to note.
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, List, Tuple

_TOOL_REFERENCE = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)*_service)[._]([a-z][a-z0-9_]*)\b")
_OUTCOME_WORD = re.compile(
    r"\b(sent|succeeded|completed|confirmed|verified|executed|created|submitted|booked|paid|deleted|cancel{1,2}ed|uploaded|deployed|delivered|worked|went through)\b",
    re.IGNORECASE,
)
_SENTENCE_BREAK = re.compile(r"\n+|(?<=[.!?])\s+")

ReceiptLookup = Callable[[str, str], Awaitable[bool]]


def claimed_tool_outcomes(text: str) -> List[Tuple[str, str]]:
    """The (service, method) pairs a text names together with an outcome word, in order and without repeats."""
    found: List[Tuple[str, str]] = []
    for sentence in _SENTENCE_BREAK.split(str(text or "")):
        if not _OUTCOME_WORD.search(sentence):
            continue
        for match in _TOOL_REFERENCE.finditer(sentence):
            pair = (match.group(1), match.group(2))
            if pair not in found:
                found.append(pair)
    return found


async def ungrounded_claims(text: str, has_receipt: ReceiptLookup) -> List[str]:
    """Claims in the text that the chain's ledger has no record of, as service.method strings."""
    missing: List[str] = []
    for service, method in claimed_tool_outcomes(text):
        if not await has_receipt(service, method):
            missing.append(f"{service}.{method}")
    return missing


def grounding_error(missing: List[str]) -> str:
    """The correction returned to the model when a note names outcomes the chain never produced."""
    named = ", ".join(missing)
    return (
        f"The notes mention an outcome for {named}, but this task has no record of that call. "
        "Notes describe where things stand, so write only what the tools actually reported. "
        "Run the call first, or reword the note to say it has not been done."
    )


async def receipt_exists(knowledge_service: Any, session_id: str, service: str, method: str) -> bool:
    """True when the chain's work ledger holds any receipt for this service and method."""
    receipts = await knowledge_service.agent_work_receipt_repository.get_receipts(
        session_id=session_id, service=service, method=method, limit=1,
    )
    return bool(receipts)
