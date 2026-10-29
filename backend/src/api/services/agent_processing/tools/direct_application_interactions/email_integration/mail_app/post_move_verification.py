"""Settle-window verification of Mail move and delete receipts by RFC message id.

Mail's integer ``id`` is neither unique nor stable across mailboxes, and a move on an Exchange account settles asynchronously. The mutation pass therefore reports ``attempted`` receipts that carry the RFC ``message id``, account, source mailbox, and target mailbox. This module re-checks those mailboxes by RFC message id and upgrades each receipt to verified, unverified, or failed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Dict, Optional, Sequence, Tuple

from api.services.agent_processing.shared.material_operation_receipts import (
    MaterialOperationEnvelope,
    MaterialOperationReceipt,
)

logger = logging.getLogger(__name__)

SETTLE_DELAYS_SECONDS: Tuple[float, ...] = (0.0, 3.0, 3.0, 6.0)
"""Sleep before each poll, so checks happen at roughly 0, 3, 6, and 12 seconds."""

GMAIL_LABEL_REASON = (
    "still present in source after settle window. Mail kept the message in the inbox while adding the destination label, "
    "which is what a scripted move does on a Gmail account, so the message has not left the inbox"
)

RESULT_PREFIX = "RESULT_JSON:"
COUNT_NOT_CHECKED = -2
COUNT_SCAN_SKIPPED = -3
"""The destination mailbox was too large to scan; ``operation_receipt_scripts.TARGET_SCAN_LIMIT`` bounds the scan."""

ScriptRunner = Callable[[str], Awaitable[Tuple[bool, Any, str]]]
Sleeper = Callable[[float], Awaitable[None]]


def parse_location_counts(output: Any) -> Dict[int, Dict[str, Any]]:
    """Parse ``verify_locations_script`` output into counts keyed by check index."""
    text = output if isinstance(output, str) else json.dumps(output, default=str)
    marker = text.find(RESULT_PREFIX)
    if marker < 0:
        raise ValueError("Mail verification output did not contain RESULT_JSON.")
    payload = json.loads(text[marker + len(RESULT_PREFIX):].strip())
    counts: Dict[int, Dict[str, Any]] = {}
    for item in payload.get("checks", []):
        counts[int(item["check_index"])] = {
            "source_count": int(item["source_count"]),
            "target_count": int(item["target_count"]),
            "error": str(item.get("lookup_error") or ""),
        }
    return counts


def _is_attempted_move_or_delete(receipt: MaterialOperationReceipt) -> bool:
    return (
        receipt.execution_state == "attempted"
        and bool(str(receipt.evidence.get("rfc_message_id") or "").strip())
    )


def _is_resolved(operation: str, counts: Dict[str, Any]) -> bool:
    if counts.get("error"):
        return False
    source_gone = counts["source_count"] == 0
    if operation in ("delete", "archive"):
        return source_gone
    return source_gone and (counts["target_count"] >= 1 or counts["target_count"] == COUNT_SCAN_SKIPPED)


def _rebuilt(
    receipt: MaterialOperationReceipt,
    *,
    execution_state: str,
    verification_status: str,
    observed_postcondition: Dict[str, Any],
    discrepancy: Dict[str, Any],
    polls: int,
) -> MaterialOperationReceipt:
    evidence = dict(receipt.evidence)
    evidence["verification_method"] = "rfc_message_id_scan"
    evidence["verification_polls"] = polls
    return MaterialOperationReceipt(
        entity=receipt.entity,
        requested_effect=receipt.requested_effect,
        execution_state=execution_state,
        observed_postcondition=observed_postcondition,
        verification_status=verification_status,
        evidence=evidence,
        discrepancy=discrepancy,
    )


def classify_receipt(
    receipt: MaterialOperationReceipt,
    counts: Optional[Dict[str, Any]],
    *,
    polls: int,
) -> MaterialOperationReceipt:
    """Return the final receipt for one attempted move or delete after the last poll."""
    operation = str(receipt.requested_effect.get("operation") or "")
    if counts is None or counts.get("error"):
        reason = "verification could not be completed"
        if counts and counts.get("error"):
            reason = f"verification lookup failed: {counts['error']}"
        return _rebuilt(
            receipt,
            execution_state="attempted",
            verification_status="unverified",
            observed_postcondition={},
            discrepancy={"reason": reason},
            polls=polls,
        )
    source_count = counts["source_count"]
    target_count = counts["target_count"]
    observed = {
        "source_mailbox": receipt.evidence.get("source_mailbox"),
        "source_count": source_count,
        "source_absent": source_count == 0,
    }
    if operation == "move":
        observed["destination_mailbox"] = receipt.evidence.get("target_mailbox")
        if target_count == COUNT_SCAN_SKIPPED:
            observed["target_scan_skipped"] = True
        else:
            observed["target_count"] = target_count
    if _is_resolved(operation, counts):
        return _rebuilt(
            receipt,
            execution_state="succeeded",
            verification_status="verified",
            observed_postcondition=observed,
            discrepancy={},
            polls=polls,
        )
    if operation == "move" and source_count >= 1 and target_count == COUNT_SCAN_SKIPPED:
        return _rebuilt(
            receipt,
            execution_state="attempted",
            verification_status="unverified",
            observed_postcondition=observed,
            discrepancy={
                "reason": "still present in source after settle window and the destination mailbox is too large to scan",
                "source_count": source_count,
            },
            polls=polls,
        )
    if operation == "move" and source_count >= 1 and target_count >= 1:
        return _rebuilt(
            receipt,
            execution_state="succeeded",
            verification_status="unverified",
            observed_postcondition=observed,
            discrepancy={
                "reason": GMAIL_LABEL_REASON,
                "source_count": source_count,
                "target_count": target_count,
            },
            polls=polls,
        )
    if operation == "move" and source_count == 0 and target_count == 0:
        reason = "message found in neither source nor target mailbox"
    elif operation == "move":
        reason = "message still in source and absent from target mailbox"
    else:
        reason = "message still present in source after settle window"
    return _rebuilt(
        receipt,
        execution_state="failed",
        verification_status="failed",
        observed_postcondition=observed,
        discrepancy={
            "reason": reason,
            "source_count": source_count,
            "target_count": target_count,
        },
        polls=polls,
    )


async def settle_attempted_receipts(
    envelope: MaterialOperationEnvelope,
    *,
    build_script: Callable[[list[dict[str, str]]], str],
    run_script: ScriptRunner,
    delays: Sequence[float] = SETTLE_DELAYS_SECONDS,
    sleep: Sleeper = asyncio.sleep,
) -> MaterialOperationEnvelope:
    """Poll Mail by RFC message id until every attempted receipt resolves or the window ends."""
    receipts = list(envelope.receipts)
    pending = [index for index, receipt in enumerate(receipts) if _is_attempted_move_or_delete(receipt)]
    if not pending:
        return envelope

    latest: Dict[int, Optional[Dict[str, Any]]] = {index: None for index in pending}
    resolved: set[int] = set()
    polls = 0
    for delay in delays:
        unresolved = [index for index in pending if index not in resolved]
        if not unresolved:
            break
        if delay > 0:
            await sleep(delay)
        polls += 1
        checks = [
            {
                "rfc_message_id": str(receipts[index].evidence.get("rfc_message_id")),
                "account": str(receipts[index].evidence.get("account") or ""),
                "target_account": str(receipts[index].evidence.get("target_account") or ""),
                "source_mailbox": str(receipts[index].evidence.get("source_mailbox") or ""),
                "target_mailbox": str(receipts[index].evidence.get("target_mailbox") or ""),
            }
            for index in unresolved
        ]
        try:
            success, data, error = await run_script(build_script(checks))
            if not success:
                raise RuntimeError(error or "Mail verification script failed.")
            counts_by_check = parse_location_counts(data)
        except Exception as exc:  # noqa: BLE001 - one failed poll must not abort the settle window
            logger.warning("Mail verification poll %d failed: %s", polls, exc)
            for index in unresolved:
                latest[index] = {"source_count": -1, "target_count": -1, "error": str(exc)}
            continue
        for position, index in enumerate(unresolved):
            counts = counts_by_check.get(position)
            if counts is None:
                latest[index] = {"source_count": -1, "target_count": -1, "error": "no verification result returned"}
                continue
            latest[index] = counts
            operation = str(receipts[index].requested_effect.get("operation") or "")
            if _is_resolved(operation, counts):
                resolved.add(index)

    for index in pending:
        receipts[index] = classify_receipt(receipts[index], latest[index], polls=polls)
    return MaterialOperationEnvelope(receipts=tuple(receipts))
