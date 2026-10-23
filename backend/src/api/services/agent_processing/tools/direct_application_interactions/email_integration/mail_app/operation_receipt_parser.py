"""Strict parser for per-message Mail.app material-operation receipts."""

from __future__ import annotations

import json
from typing import Any

from api.services.agent_processing.shared.material_operation_receipts import (
    MaterialOperationContractError,
    MaterialOperationEnvelope,
)

from ..email_models import EmailOperation


class MailOperationReceiptParseError(ValueError):
    """Raised when Mail.app does not account for every requested message."""


def parse_mail_operation_receipts(
    output: str,
    operation: EmailOperation,
) -> MaterialOperationEnvelope:
    """Parse validated JSON emitted by a Mail receipt AppleScript."""
    payload_text = _extract_result_json(output)
    try:
        payload: Any = json.loads(payload_text)
    except (TypeError, ValueError) as exc:
        raise MailOperationReceiptParseError(
            "Mail operation receipt output is not valid JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise MailOperationReceiptParseError(
            "Mail operation receipt output must be a JSON object."
        )
    try:
        envelope = MaterialOperationEnvelope.from_dict(
            payload.get("material_operation", payload)
        )
    except MaterialOperationContractError as exc:
        raise MailOperationReceiptParseError(str(exc)) from exc
    expected_ids = set(operation.email_ids)
    actual_ids = [receipt.entity.external_id for receipt in envelope.receipts]
    if len(actual_ids) != len(set(actual_ids)):
        raise MailOperationReceiptParseError("Mail emitted duplicate message receipts.")
    if set(actual_ids) != expected_ids:
        missing = sorted(expected_ids - set(actual_ids))
        unexpected = sorted(set(actual_ids) - expected_ids)
        raise MailOperationReceiptParseError(
            f"Mail receipt targets do not match request; missing={missing}, "
            f"unexpected={unexpected}."
        )
    for receipt in envelope.receipts:
        if receipt.entity.entity_type != "email":
            raise MailOperationReceiptParseError(
                "Mail receipt entities must have entity_type=email."
            )
        if receipt.entity.source_system != "mail_app":
            raise MailOperationReceiptParseError(
                "Mail receipt entities must have source_system=mail_app."
            )
    return envelope


def _extract_result_json(output: str) -> str:
    for line in (output or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("RESULT_JSON:"):
            return stripped.removeprefix("RESULT_JSON:").strip()
    return (output or "").strip()
