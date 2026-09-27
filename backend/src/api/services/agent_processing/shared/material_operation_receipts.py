"""Shared, adapter-neutral receipts for material operations."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional


MATERIAL_OPERATION_ENVELOPE_KEY = "material_operation"
MATERIAL_OPERATION_CONTRACT_VERSION = 1
EXECUTION_STATES = frozenset({"not_started", "attempted", "succeeded", "failed"})
VERIFICATION_STATUSES = frozenset(
    {"not_applicable", "verified", "unverified", "failed"}
)


class MaterialOperationContractError(ValueError):
    """Raised when an adapter supplies an invalid material-operation envelope."""


def _require_non_empty_string(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise MaterialOperationContractError(f"{field_name} is required.")
    return normalized


def _require_object(value: Any, field_name: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MaterialOperationContractError(f"{field_name} must be an object.")
    try:
        return json.loads(json.dumps(dict(value), ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise MaterialOperationContractError(
            f"{field_name} must contain JSON-compatible values."
        ) from exc


def canonical_source_scope(value: Any) -> Dict[str, Any]:
    """Normalize source scope into the deterministic identity representation."""
    return _require_object(value if value is not None else {}, "source_scope")


@dataclass(frozen=True)
class LedgerEntityReference:
    """Source-safe external identity for one durable ledger entity."""

    entity_type: str
    source_system: str
    source_scope: Dict[str, Any]
    external_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "entity_type",
            _require_non_empty_string(self.entity_type, "entity_type"),
        )
        object.__setattr__(
            self,
            "source_system",
            _require_non_empty_string(self.source_system, "source_system"),
        )
        object.__setattr__(
            self,
            "source_scope",
            canonical_source_scope(self.source_scope),
        )
        object.__setattr__(
            self,
            "external_id",
            _require_non_empty_string(self.external_id, "external_id"),
        )

    @property
    def source_scope_json(self) -> str:
        return json.dumps(self.source_scope, ensure_ascii=False, sort_keys=True)

    @property
    def identity_key(self) -> tuple[str, str, str, str]:
        return (
            self.entity_type,
            self.source_system,
            self.source_scope_json,
            self.external_id,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "source_system": self.source_system,
            "source_scope": self.source_scope,
            "external_id": self.external_id,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "LedgerEntityReference":
        if not isinstance(value, Mapping):
            raise MaterialOperationContractError("entity must be an object.")
        return cls(
            entity_type=value.get("entity_type"),
            source_system=value.get("source_system"),
            source_scope=value.get("source_scope"),
            external_id=value.get("external_id"),
        )


@dataclass(frozen=True)
class MaterialOperationReceipt:
    """Execution and verification evidence for one material entity transition."""

    entity: LedgerEntityReference
    requested_effect: Dict[str, Any]
    execution_state: str
    observed_postcondition: Dict[str, Any]
    verification_status: str
    evidence: Dict[str, Any]
    discrepancy: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.entity, LedgerEntityReference):
            raise MaterialOperationContractError("entity must be a LedgerEntityReference.")
        object.__setattr__(
            self,
            "requested_effect",
            _require_object(self.requested_effect, "requested_effect"),
        )
        execution_state = _require_non_empty_string(
            self.execution_state,
            "execution_state",
        ).lower()
        if execution_state not in EXECUTION_STATES:
            raise MaterialOperationContractError(
                f"Unsupported execution_state: {execution_state}."
            )
        object.__setattr__(self, "execution_state", execution_state)
        object.__setattr__(
            self,
            "observed_postcondition",
            _require_object(
                self.observed_postcondition,
                "observed_postcondition",
            ),
        )
        verification_status = _require_non_empty_string(
            self.verification_status,
            "verification_status",
        ).lower()
        if verification_status not in VERIFICATION_STATUSES:
            raise MaterialOperationContractError(
                f"Unsupported verification_status: {verification_status}."
            )
        object.__setattr__(self, "verification_status", verification_status)
        object.__setattr__(self, "evidence", _require_object(self.evidence, "evidence"))
        object.__setattr__(
            self,
            "discrepancy",
            _require_object(self.discrepancy, "discrepancy"),
        )
        if verification_status == "verified":
            if execution_state != "succeeded":
                raise MaterialOperationContractError(
                    "Verified receipts require execution_state=succeeded."
                )
            if not self.observed_postcondition or not self.evidence:
                raise MaterialOperationContractError(
                    "Verified receipts require observed_postcondition and evidence."
                )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity": self.entity.to_dict(),
            "requested_effect": self.requested_effect,
            "execution_state": self.execution_state,
            "observed_postcondition": self.observed_postcondition,
            "verification_status": self.verification_status,
            "evidence": self.evidence,
            "discrepancy": self.discrepancy,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "MaterialOperationReceipt":
        if not isinstance(value, Mapping):
            raise MaterialOperationContractError("receipt must be an object.")
        return cls(
            entity=LedgerEntityReference.from_dict(value.get("entity")),
            requested_effect=value.get("requested_effect"),
            execution_state=value.get("execution_state"),
            observed_postcondition=value.get("observed_postcondition"),
            verification_status=value.get("verification_status"),
            evidence=value.get("evidence"),
            discrepancy=value.get("discrepancy") or {},
        )


@dataclass(frozen=True)
class MaterialOperationEnvelope:
    """A complete material operation reported by an adapter."""

    receipts: tuple[MaterialOperationReceipt, ...]
    contract_version: int = MATERIAL_OPERATION_CONTRACT_VERSION
    material_write: bool = True

    def __post_init__(self) -> None:
        if self.contract_version != MATERIAL_OPERATION_CONTRACT_VERSION:
            raise MaterialOperationContractError(
                f"Unsupported material operation contract version: {self.contract_version}."
            )
        if self.material_write is not True:
            raise MaterialOperationContractError(
                "Material operation envelopes require material_write=true."
            )
        if not self.receipts:
            raise MaterialOperationContractError(
                "Material operation envelopes require at least one receipt."
            )
        keys = set()
        for receipt in self.receipts:
            if not isinstance(receipt, MaterialOperationReceipt):
                raise MaterialOperationContractError(
                    "receipts must contain MaterialOperationReceipt values."
                )
            if receipt.entity.identity_key in keys:
                raise MaterialOperationContractError(
                    "Material operation envelopes cannot contain duplicate entity references."
                )
            keys.add(receipt.entity.identity_key)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "material_write": True,
            "receipts": [receipt.to_dict() for receipt in self.receipts],
        }

    def to_tool_result_fields(self) -> Dict[str, Any]:
        """Project aggregate status for existing tool and finalizer consumers."""
        verification_statuses = {
            receipt.verification_status for receipt in self.receipts
        }
        if verification_statuses == {"verified"}:
            aggregate_status = "verified"
        elif "failed" in verification_statuses:
            aggregate_status = "failed"
        else:
            aggregate_status = "unverified"
        return {
            MATERIAL_OPERATION_ENVELOPE_KEY: self.to_dict(),
            "outcome_verification_status": aggregate_status,
            "needs_outcome_review": aggregate_status != "verified",
            "outcome_review": {
                "material_write": True,
                "verification_status": aggregate_status,
                "summary": (
                    f"{len(self.receipts)} material-operation receipt(s): "
                    f"{aggregate_status}."
                ),
                "evidence": {
                    "receipt_count": len(self.receipts),
                },
                "expected": {},
                "actual": {},
                "discrepancies": [
                    receipt.discrepancy
                    for receipt in self.receipts
                    if receipt.discrepancy
                ],
            },
        }

    @classmethod
    def from_dict(cls, value: Any) -> "MaterialOperationEnvelope":
        if not isinstance(value, Mapping):
            raise MaterialOperationContractError(
                "material_operation must be an object."
            )
        receipts = value.get("receipts")
        if not isinstance(receipts, list):
            raise MaterialOperationContractError(
                "material_operation.receipts must be a list."
            )
        return cls(
            contract_version=value.get("contract_version"),
            material_write=value.get("material_write"),
            receipts=tuple(MaterialOperationReceipt.from_dict(item) for item in receipts),
        )


def extract_material_operation_envelope(value: Any) -> Optional[MaterialOperationEnvelope]:
    """Extract an explicit shared envelope without interpreting arbitrary output."""
    if not isinstance(value, Mapping):
        return None
    candidate = value.get(MATERIAL_OPERATION_ENVELOPE_KEY)
    return (
        MaterialOperationEnvelope.from_dict(candidate)
        if candidate is not None
        else None
    )


def receipt_summaries(
    receipts: Iterable[MaterialOperationReceipt],
) -> list[Dict[str, Any]]:
    """Return compact body-free summaries for continuation handoff rendering."""
    return [
        {
            "entity": receipt.entity.to_dict(),
            "execution_state": receipt.execution_state,
            "verification_status": receipt.verification_status,
            "requested_effect": receipt.requested_effect,
            "discrepancy": receipt.discrepancy,
        }
        for receipt in receipts
    ]
