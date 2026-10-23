"""Bounded UTF-8 text-file mutation for agent file-service tools."""

from __future__ import annotations

import asyncio
import os
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

from api.services.agent_processing.shared.material_operation_receipts import (
    LedgerEntityReference,
    MaterialOperationEnvelope,
    MaterialOperationReceipt,
    extract_material_operation_envelope,
)
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_file_artifacts import (
    DeclaredFileOperation,
    prepare_file_operations,
    verify_file_operations,
)


TextWriteMode = Literal["create", "overwrite", "append"]

_ARTIFACT_ID_PREFIX = "file-"
_ARTIFACT_ID_DIGEST_LENGTH = 24


def select_direct_text_write_artifact(result: Any) -> dict[str, Any] | None:
    """Select one metadata-only artifact from a valid direct text-write receipt."""
    envelope = extract_material_operation_envelope(result)
    if envelope is None or len(envelope.receipts) != 1:
        return None

    receipt = envelope.receipts[0]
    if (
        receipt.entity.entity_type != "file"
        or receipt.entity.source_system != "filesystem"
        or receipt.entity.source_scope != {"host_scope": "local"}
        or receipt.verification_status not in {"verified", "failed"}
    ):
        return None

    path = receipt.entity.external_id
    target = Path(path)
    operation = receipt.requested_effect.get("operation")
    if not target.is_absolute() or operation not in {"create", "modify"}:
        return None

    evidence = receipt.evidence
    artifact_evidence = evidence.get("file_artifact")
    if receipt.verification_status == "verified":
        if (
            not isinstance(artifact_evidence, Mapping)
            or artifact_evidence.get("full_path") != path
            or artifact_evidence.get("operation") != operation
            or artifact_evidence.get("kind") != "file"
        ):
            return None
        bytes_written = evidence.get("bytes_written")
        digest = evidence.get("sha256")
        if (
            type(bytes_written) is not int
            or bytes_written < 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            return None
        lifecycle = "verified"
        verification = {
            "status": "verified",
            "summary": f"Verified {bytes_written} bytes; SHA-256 {digest}.",
        }
    else:
        lifecycle = "failed"
        verification = {
            "status": "failed",
            "summary": "Verification failed: postcondition_verification_failed.",
        }

    normalized_path = os.path.normpath(path)
    return {
        "artifact_id": (
            f"{_ARTIFACT_ID_PREFIX}"
            f"{sha256(normalized_path.encode('utf-8')).hexdigest()[:_ARTIFACT_ID_DIGEST_LENGTH]}"
        ),
        "display_name": target.name,
        "local_path": normalized_path,
        "artifact_kind": "file",
        "operation": operation,
        "lifecycle": lifecycle,
        "preview": {"capability": "unknown"},
        "verification": verification,
    }


class LocalTextFileWriter:
    """Perform one path-bounded UTF-8 text mutation with durable verification."""

    def __init__(self, allowed_roots: Iterable[Path]) -> None:
        self._allowed_roots = tuple(Path(root).expanduser().resolve() for root in allowed_roots)

    async def write_text_file(
        self,
        *,
        path: str,
        content: str,
        mode: TextWriteMode,
        expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._write_text_file,
            path=path,
            content=content,
            mode=mode,
            expected_sha256=expected_sha256,
        )

    def _write_text_file(
        self,
        *,
        path: str,
        content: str,
        mode: TextWriteMode,
        expected_sha256: str | None,
    ) -> dict[str, Any]:
        if mode not in {"create", "overwrite", "append"}:
            return self._failure(
                path=path,
                operation="unknown",
                error_type="invalid_mode",
                error="mode must be one of create, overwrite, or append.",
            )
        operation = "create" if mode == "create" else "modify"
        try:
            declarations = prepare_file_operations(
                [{"operation": operation, "path": path}],
                self._allowed_roots,
            )
        except ValueError as exc:
            return self._failure(
                path=path,
                operation=operation,
                error_type="invalid_path_or_mode",
                error=str(exc),
            )

        declaration = declarations[0]
        target = declaration.path
        if not target.parent.is_dir():
            return self._failure(
                path=str(target),
                operation=operation,
                mode=mode,
                error_type="parent_directory_missing",
                error=f"Parent directory does not exist: {target.parent}",
                declaration=declaration,
            )
        if declaration.path_before.exists and declaration.path_before.kind != "file":
            return self._failure(
                path=str(target),
                operation=operation,
                mode=mode,
                error_type="target_not_regular_file",
                error=f"Text write target must be a regular file: {target}",
                declaration=declaration,
            )
        if mode == "create" and expected_sha256 is not None:
            return self._failure(
                path=str(target),
                operation=operation,
                mode=mode,
                error_type="expected_sha256_not_supported_for_create",
                error="expected_sha256 is only valid for overwrite or append.",
                declaration=declaration,
            )

        previous_sha256 = declaration.path_before.fingerprint
        if expected_sha256 is not None and previous_sha256 != expected_sha256:
            return self._failure(
                path=str(target),
                operation=operation,
                mode=mode,
                error_type="stale_target",
                error="expected_sha256 does not match the current file content.",
                declaration=declaration,
                previous_sha256=previous_sha256,
            )

        encoded_content = content.encode("utf-8")
        try:
            if mode == "create":
                self._create_exclusively(target, encoded_content)
            elif mode == "overwrite":
                self._overwrite_atomically(target, encoded_content)
            else:
                self._append_and_sync(target, encoded_content)
        except OSError as exc:
            return self._failure(
                path=str(target),
                operation=operation,
                mode=mode,
                error_type="write_failed",
                error=f"Could not write text file: {exc}",
                declaration=declaration,
                previous_sha256=previous_sha256,
            )

        artifacts, verification_errors = verify_file_operations(declarations)
        if verification_errors:
            return self._failure(
                path=str(target),
                operation=operation,
                mode=mode,
                error_type="postcondition_verification_failed",
                error="; ".join(verification_errors),
                declaration=declaration,
                previous_sha256=previous_sha256,
                execution_state="succeeded",
                verification_status="failed",
                evidence={"file_artifact_errors": verification_errors},
            )

        current_sha256 = self._sha256(target)
        result = {
            "success": True,
            "file_path": str(target),
            "operation": operation,
            "mode": mode,
            "bytes_written": len(encoded_content),
            "previous_sha256": previous_sha256,
            "sha256": current_sha256,
            "file_artifacts": artifacts,
            "execution_success": True,
        }
        return self._attach_receipt(
            result,
            declaration=declaration,
            mode=mode,
            execution_state="succeeded",
            verification_status="verified",
            evidence={
                "file_artifact": artifacts[0],
                "previous_sha256": previous_sha256,
                "sha256": current_sha256,
                "bytes_written": len(encoded_content),
            },
        )

    @staticmethod
    def _create_exclusively(target: Path, content: bytes) -> None:
        with target.open("xb") as destination:
            destination.write(content)
            destination.flush()
            os.fsync(destination.fileno())

    @staticmethod
    def _overwrite_atomically(target: Path, content: bytes) -> None:
        temporary = target.with_name(f".{target.name}.basil-write-{os.getpid()}")
        try:
            with temporary.open("xb") as destination:
                destination.write(content)
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _append_and_sync(target: Path, content: bytes) -> None:
        with target.open("ab") as destination:
            destination.write(content)
            destination.flush()
            os.fsync(destination.fileno())

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _failure(
        self,
        *,
        path: str,
        operation: str,
        mode: str | None = None,
        error_type: str,
        error: str,
        declaration: DeclaredFileOperation | None = None,
        previous_sha256: str | None = None,
        execution_state: str = "not_started",
        verification_status: str = "not_applicable",
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = {
            "success": False,
            "file_path": path,
            "operation": operation,
            "mode": mode,
            "error_type": error_type,
            "error": error,
            "previous_sha256": previous_sha256,
            "execution_success": execution_state == "succeeded",
            "file_artifacts": [],
        }
        if declaration is None:
            return result
        return self._attach_receipt(
            result,
            declaration=declaration,
            mode=mode,
            execution_state=execution_state,
            verification_status=verification_status,
            evidence=evidence or {"error_type": error_type, "error": error},
            discrepancy={"error_type": error_type, "error": error},
        )

    @staticmethod
    def _attach_receipt(
        result: dict[str, Any],
        *,
        declaration: DeclaredFileOperation,
        mode: str | None,
        execution_state: str,
        verification_status: str,
        evidence: dict[str, Any],
        discrepancy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        receipt = MaterialOperationReceipt(
            entity=LedgerEntityReference(
                entity_type="file",
                source_system="filesystem",
                source_scope={"host_scope": "local"},
                external_id=str(declaration.path),
            ),
            requested_effect={
                "operation": declaration.operation,
                "mode": mode,
                "path": str(declaration.path),
            },
            execution_state=execution_state,
            observed_postcondition=(
                {"file_artifact": (result.get("file_artifacts") or [None])[0]}
                if verification_status == "verified"
                else {}
            ),
            verification_status=verification_status,
            evidence=evidence,
            discrepancy=discrepancy or {},
        )
        envelope = MaterialOperationEnvelope(receipts=(receipt,))
        return {**result, **envelope.to_tool_result_fields()}
