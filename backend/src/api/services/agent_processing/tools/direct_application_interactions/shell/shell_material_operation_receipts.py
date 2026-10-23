"""Translate declared shell filesystem transitions into shared receipts."""

from __future__ import annotations

from typing import Any, Dict, Sequence

from api.services.agent_processing.shared.material_operation_receipts import (
    LedgerEntityReference,
    MaterialOperationEnvelope,
    MaterialOperationReceipt,
)

from .shell_file_artifacts import DeclaredFileOperation


def attach_shell_material_operation_receipts(
    result: Dict[str, Any],
    declarations: Sequence[DeclaredFileOperation],
) -> Dict[str, Any]:
    """Attach one shared receipt for every declared filesystem operation."""
    if not declarations:
        return result
    artifacts = {
        artifact.get("full_path"): artifact
        for artifact in result.get("file_artifacts") or []
        if isinstance(artifact, dict)
    }
    errors = [str(error) for error in result.get("file_artifact_errors") or []]
    execution_succeeded = bool(result.get("execution_success", result.get("success")))
    approval_denied = bool(
        result.get("approval_denied") or result.get("approval_blocked")
    ) or (
        (result.get("approval_decision") or {}).get("status") == "denied"
    )
    receipts = []
    for declaration in declarations:
        path = str(declaration.path)
        artifact = artifacts.get(path)
        matching_errors = [error for error in errors if path in error]
        if approval_denied or not execution_succeeded:
            execution_state = "not_started" if approval_denied else "attempted"
            verification_status = "not_applicable" if approval_denied else "unverified"
            observed_postcondition = {}
            evidence = {
                "execution_success": execution_succeeded,
                "approval_blocked": approval_denied,
            }
            discrepancy = {"error": result.get("stderr")} if result.get("stderr") else {}
        elif artifact:
            execution_state = "succeeded"
            verification_status = "verified"
            observed_postcondition = {"file_artifact": artifact}
            evidence = {"file_artifact": artifact}
            discrepancy = {}
        else:
            execution_state = "succeeded"
            verification_status = "failed" if matching_errors else "unverified"
            observed_postcondition = {}
            evidence = {"file_artifact_errors": matching_errors}
            discrepancy = {"errors": matching_errors} if matching_errors else {}
        receipts.append(
            MaterialOperationReceipt(
                entity=LedgerEntityReference(
                    entity_type="file",
                    source_system="filesystem",
                    source_scope={"host_scope": "local"},
                    external_id=path,
                ),
                requested_effect={
                    "operation": declaration.operation,
                    "path": path,
                    **(
                        {"source_path": str(declaration.source_path)}
                        if declaration.source_path
                        else {}
                    ),
                },
                execution_state=execution_state,
                observed_postcondition=observed_postcondition,
                verification_status=verification_status,
                evidence=evidence,
                discrepancy=discrepancy,
            )
        )
    envelope = MaterialOperationEnvelope(receipts=tuple(receipts))
    return {**result, **envelope.to_tool_result_fields()}
