"""Performs Gmail inbox archive and move receipts through Mail's own commands.

The receipt script marks a message ``ui_required`` when Mail reports its mailbox as something other than INBOX, which is how a Gmail account presents an inbox message. Mail's scripted ``move`` cannot remove the Inbox label there, so this module runs ``gmail_inbox_ui_script`` for those receipts and then lets ``post_move_verification`` confirm the result by RFC message id.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from api.services.agent_processing.shared.material_operation_receipts import (
    MaterialOperationEnvelope,
    MaterialOperationReceipt,
)

from .gmail_inbox_ui_script import RESULT_PREFIX, ROW_SCAN_LIMIT, build_gmail_inbox_ui_script
from .post_move_verification import GMAIL_LABEL_REASON

logger = logging.getLogger(__name__)

ScriptRunner = Callable[[str], Awaitable[Tuple[bool, Any, str]]]

ApprovalRequester = Callable[[Dict[str, Any]], Awaitable[Tuple[bool, str]]]
"""Asks the user to approve Mail's windows being taken over. Receives the summary built by ``_approval_summary`` and returns (approved, reason when not approved)."""

NO_APPROVAL_CHANNEL_REASON = "Archiving or moving a Gmail message drives Mail's visible windows and menus, which needs the user's approval, and no approval channel is available, so nothing was changed"

STATUS_REASONS: Dict[str, str] = {
    "row_not_found": f"Mail's inbox window has no conversation with this subject in its first {ROW_SCAN_LIMIT} rows, so nothing was changed",
    "archive_unavailable": "Mail's Archive command is not available for this conversation (for example because it includes sent items), so nothing was changed",
    "move_unavailable": "Mail's Move to command is not available for this conversation, so nothing was changed",
    "target_menu_item_not_found": "Mail's Move to menu has no entry for the destination mailbox under the destination account, so nothing was changed",
    "accessibility_denied": "Mail can only archive or move a Gmail inbox message through its menus, which needs Accessibility permission for the app that runs the backend, and macOS has not granted it",
    "ui_unavailable": "Mail's inbox window could not be opened for automation, so nothing was changed",
    "ui_error": "Mail's menu automation failed, so nothing was changed",
}


def _requires_ui(receipt: MaterialOperationReceipt) -> bool:
    return receipt.execution_state == "attempted" and receipt.evidence.get("ui_required") is True


def _rebuilt(receipt: MaterialOperationReceipt, **changes: Any) -> MaterialOperationReceipt:
    return MaterialOperationReceipt(
        entity=receipt.entity,
        requested_effect=receipt.requested_effect,
        execution_state=changes.get("execution_state", receipt.execution_state),
        observed_postcondition=changes.get("observed_postcondition", receipt.observed_postcondition),
        verification_status=changes.get("verification_status", receipt.verification_status),
        evidence=changes.get("evidence", receipt.evidence),
        discrepancy=changes.get("discrepancy", receipt.discrepancy),
    )


def _blocked(receipt: MaterialOperationReceipt, reason: str, extra: Optional[Dict[str, Any]] = None) -> MaterialOperationReceipt:
    evidence = dict(receipt.evidence)
    evidence["blocked_before_mutation"] = True
    discrepancy = {"reason": reason}
    discrepancy.update(extra or {})
    return _rebuilt(
        receipt,
        execution_state="not_started",
        verification_status="not_applicable",
        evidence=evidence,
        discrepancy=discrepancy,
    )


def _invoked(receipt: MaterialOperationReceipt, row: int) -> MaterialOperationReceipt:
    evidence = dict(receipt.evidence)
    evidence["performed_by"] = "mail_ui_menu"
    evidence["ui_row"] = row
    return _rebuilt(receipt, evidence=evidence)


def parse_ui_results(output: Any) -> Dict[str, Dict[str, Any]]:
    """Parse the UI script output into one result per conversation subject."""
    text = output if isinstance(output, str) else json.dumps(output, default=str)
    marker = text.find(RESULT_PREFIX)
    if marker < 0:
        raise ValueError("Mail UI script output did not contain RESULT_JSON.")
    payload = json.loads(text[marker + len(RESULT_PREFIX):].strip())
    results = {str(item["core_subject"]): item for item in payload.get("results", [])}
    results["__cleanup_notes__"] = {"detail": str(payload.get("cleanup_notes") or "")}
    return results


def _unrequested_siblings(receipt: MaterialOperationReceipt, requested_rfc_ids: set[str]) -> List[str]:
    siblings = receipt.evidence.get("sibling_rfc_ids") or []
    return [str(rfc) for rfc in siblings if str(rfc) not in requested_rfc_ids]


def _approval_summary(
    receipts: List[MaterialOperationReceipt],
    operation: str,
    runnable: Dict[Tuple[str, str, str], List[int]],
) -> Dict[str, Any]:
    """What the approval card must tell the user before Mail's windows are taken over."""
    indexes = [index for group in runnable.values() for index in group]
    subjects = sorted({str(receipts[index].evidence["subject_core"]) for index in indexes})
    accounts = sorted({account for account, _target, _target_account in runnable})
    targets = sorted({target for _account, target, _target_account in runnable if target})
    return {
        "operation": operation,
        "message_count": len(indexes),
        "accounts": accounts,
        "subjects": subjects,
        "target_mailboxes": targets,
    }


async def apply_gmail_inbox_ui(
    envelope: MaterialOperationEnvelope,
    operation: str,
    *,
    escape: Callable[[str], str],
    run_script: ScriptRunner,
    request_approval: Optional[ApprovalRequester] = None,
) -> MaterialOperationEnvelope:
    """Archive or move every ``ui_required`` receipt through Mail's menus and return the updated envelope.

    The menus take over the user's screen, so nothing runs until ``request_approval`` approves the receipts that would actually run. A missing requester, a denial, or a failed request leaves every one of them ``not_started`` with the reason.
    """
    receipts = list(envelope.receipts)
    pending = [index for index, receipt in enumerate(receipts) if _requires_ui(receipt)]
    if not pending:
        return envelope

    requested = {str(receipt.evidence.get("rfc_message_id") or "") for receipt in receipts}
    runnable: Dict[Tuple[str, str, str], List[int]] = {}
    for index in pending:
        receipt = receipts[index]
        core = str(receipt.evidence.get("subject_core") or "")
        if not core:
            receipts[index] = _blocked(receipt, "the message has no subject, so Mail's inbox row cannot be identified safely")
            continue
        extra = _unrequested_siblings(receipt, requested)
        if extra:
            receipts[index] = _blocked(
                receipt,
                "Mail archives and moves a whole conversation, and this message's conversation also holds inbox messages that were not requested; include every message of the conversation or leave this one alone",
                {"unrequested_conversation_rfc_message_ids": extra},
            )
            continue
        key = (
            str(receipt.evidence.get("account") or ""),
            str(receipt.evidence.get("target_mailbox") or "") if operation == "move" else "",
            str(receipt.evidence.get("target_account") or "") if operation == "move" else "",
        )
        runnable.setdefault(key, []).append(index)

    if runnable:
        approved, denial = await _request_ui_approval(request_approval, _approval_summary(receipts, operation, runnable))
        if not approved:
            for group in runnable.values():
                for index in group:
                    receipts[index] = _blocked(receipts[index], denial, {"approval": "not_granted"})
            return MaterialOperationEnvelope(receipts=tuple(receipts))

    for (account, target_mailbox, target_account), indexes in runnable.items():
        cores = sorted({str(receipts[index].evidence["subject_core"]) for index in indexes})
        script = build_gmail_inbox_ui_script(
            escape=escape,
            account_name=account,
            operation=operation,
            target_name=target_mailbox,
            target_account_name=target_account,
            core_subjects=cores,
        )
        try:
            success, data, error = await run_script(script)
            if not success:
                raise RuntimeError(error or "Mail UI script failed.")
            results = parse_ui_results(data)
        except Exception as exc:  # noqa: BLE001 - Mail may have acted before the failure, so verification decides the outcome
            logger.warning("Mail UI organization could not be confirmed: %s", exc)
            for index in indexes:
                evidence = dict(receipts[index].evidence)
                evidence["ui_script_error"] = str(exc)
                receipts[index] = _rebuilt(receipts[index], evidence=evidence)
            continue
        for index in indexes:
            receipt = receipts[index]
            result = results.get(str(receipt.evidence["subject_core"]), {})
            status = str(result.get("status") or "ui_error")
            if status == "invoked":
                receipts[index] = _invoked(receipt, int(result.get("row") or 0))
                continue
            reason = STATUS_REASONS.get(status, STATUS_REASONS["ui_error"])
            detail = str(result.get("detail") or "")
            receipts[index] = _blocked(receipt, f"{reason}: {detail}" if detail else reason, {"ui_status": status})
    return MaterialOperationEnvelope(receipts=tuple(receipts))


async def _request_ui_approval(request_approval: Optional[ApprovalRequester], summary: Dict[str, Any]) -> Tuple[bool, str]:
    """Fail closed: only an explicit approval from the requester lets the menus run."""
    if request_approval is None:
        return False, NO_APPROVAL_CHANNEL_REASON
    try:
        approved, reason = await request_approval(summary)
    except Exception as exc:  # noqa: BLE001 - an approval that could not be asked is not an approval
        logger.warning("Mail UI approval request failed: %s", exc)
        return False, f"{NO_APPROVAL_CHANNEL_REASON}: {exc}"
    return (True, "") if approved else (False, reason or NO_APPROVAL_CHANNEL_REASON)


def prepare_archive_fallback(envelope: MaterialOperationEnvelope) -> Tuple[MaterialOperationEnvelope, bool]:
    """Re-open moves that Mail ignored because the message already carried the destination label.

    Mail's Move to command does nothing when the destination label is already on the message, so the message stays in the inbox even though it is already filed where the caller asked. Archiving then removes the inbox label and leaves the destination label, which is exactly the requested outcome. Returns the envelope with those receipts attempted again, and whether any were re-opened.
    """
    receipts = list(envelope.receipts)
    reopened = False
    for index, receipt in enumerate(receipts):
        if not _needs_archive_fallback(receipt):
            continue
        evidence = dict(receipt.evidence)
        evidence["archive_fallback"] = True
        receipts[index] = _rebuilt(
            receipt,
            execution_state="attempted",
            verification_status="unverified",
            observed_postcondition={},
            discrepancy={},
            evidence=evidence,
        )
        reopened = True
    return MaterialOperationEnvelope(receipts=tuple(receipts)), reopened


def _needs_archive_fallback(receipt: MaterialOperationReceipt) -> bool:
    return (
        receipt.requested_effect.get("operation") == "move"
        and receipt.evidence.get("performed_by") == "mail_ui_menu"
        and not receipt.evidence.get("archive_fallback")
        and receipt.execution_state == "succeeded"
        and receipt.verification_status == "unverified"
        and receipt.discrepancy.get("reason") == GMAIL_LABEL_REASON
    )
