"""Normalize structured tool outputs into durable work-ledger records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

from .ledger_json import sanitize_ledger_email_record, to_ledger_json_value

_BODY_KEYS = frozenset({"body", "content", "html_body", "text", "raw"})
_IDENTITY_KEYS = ("external_id", "id", "message_id", "email_id", "thread_id", "path", "url")
_ITEM_COLLECTION_KEYS = ("items", "results", "emails", "messages", "records", "data")


@dataclass(frozen=True)
class CapturedLedgerRecord:
    """One durable entity inferred from a structured tool result."""

    external_id: str
    entity_type: str
    source_system: str
    metadata: Dict[str, Any]
    verification_status: str = "not_applicable"
    evidence: Dict[str, Any] | None = None


def normalize_tool_result(value: Any) -> Any:
    """Return the structured result payload without serializing or truncating it."""
    if isinstance(value, (dict, list)):
        return value
    return getattr(value, "result", value)


def capture_scope(payload: Any) -> Dict[str, Any]:
    """Extract source coverage metadata from nested service envelopes."""
    coverage = getattr(payload, "coverage_metadata", None)
    if isinstance(coverage, dict):
        return {"coverage": to_ledger_json_value(coverage)}
    for value in walk_values(payload):
        if not isinstance(value, dict):
            continue
        coverage = value.get("coverage_metadata")
        if isinstance(coverage, dict):
            return {"coverage": to_ledger_json_value(coverage)}
    return {}


def capture_records(payload: Any, *, source_system: str) -> List[CapturedLedgerRecord]:
    """Capture email/discovery entities, verified files, and browser targets.

    ``source_system`` must be the caller's own known service identity (for
    example ``"email_service"``); it is never guessed from payload content.
    Every record captured through this best-effort, key-sniffing path is
    scoped to that source_system so two different services can never collide
    on the same bare external_id (Foundation Remediation).
    """
    records: List[CapturedLedgerRecord] = []
    seen: set[str] = set()

    def add(
        external_id: Any,
        metadata: Dict[str, Any],
        *,
        entity_type: str,
        verification_status: str = "not_applicable",
        evidence: Dict[str, Any] | None = None,
    ) -> None:
        if external_id is None:
            return
        normalized_id = str(external_id)
        if normalized_id in seen:
            return
        seen.add(normalized_id)
        records.append(CapturedLedgerRecord(
            external_id=normalized_id,
            entity_type=entity_type,
            source_system=source_system,
            metadata=metadata,
            verification_status=verification_status,
            evidence=evidence,
        ))

    coverage = getattr(payload, "coverage_metadata", None)
    if coverage is not None:
        for email in payload:
            metadata = sanitize_ledger_email_record(email)
            external_id = metadata.get("id") or metadata.get("message_id")
            add(external_id, metadata, entity_type="email")

    for item in _iter_item_records(payload):
        external_id = next((item.get(key) for key in _IDENTITY_KEYS if item.get(key) is not None), None)
        add(
            external_id,
            {
                key: to_ledger_json_value(value)
                for key, value in item.items()
                if key not in _BODY_KEYS
            },
            entity_type="discovered_item",
        )

    for value in walk_values(payload):
        if not isinstance(value, dict):
            continue
        target = value.get("browser_automation_target")
        if isinstance(target, dict):
            browser_id = ":".join(str(target.get(key, "")) for key in ("browser", "window_index", "tab_index"))
            add(
                f"browser:{browser_id}",
                {"kind": "browser_target", **target},
                entity_type="browser_target",
                evidence={"browser_automation_target": target},
            )
        artifacts = value.get("file_artifacts")
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    continue
                path = artifact.get("full_path") or artifact.get("path")
                add(
                    f"file:{path}" if path else None,
                    {"kind": "file_artifact", **artifact},
                    entity_type="file",
                    verification_status="verified",
                    evidence={"file_artifact": artifact},
                )
        for key in ("discovery_receipt", "discovery_receipts"):
            receipts = value.get(key)
            if isinstance(receipts, dict):
                receipts = [receipts]
            if not isinstance(receipts, list):
                continue
            for receipt in receipts:
                if not isinstance(receipt, dict):
                    continue
                receipt_id = next((receipt.get(key) for key in _IDENTITY_KEYS if receipt.get(key) is not None), None)
                add(
                    f"discovery:{receipt_id}" if receipt_id is not None else None,
                    {"kind": "discovery_receipt", **receipt},
                    entity_type="discovery_receipt",
                    evidence={"discovery_receipt": receipt},
                )
    return records


def walk_values(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for nested in value.values():
            yield from walk_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_values(nested)


def _iter_item_records(payload: Any) -> Iterable[Dict[str, Any]]:
    for value in walk_values(payload):
        if not isinstance(value, dict):
            continue
        for key in _ITEM_COLLECTION_KEYS:
            candidate = value.get(key)
            if isinstance(candidate, list):
                yield from (item for item in candidate if isinstance(item, dict))
