"""Exact-text edits for agent file-service tools.

``apply_text_edits`` is pure: it applies ordered replacements to a string and either returns every result or raises before anything is written. ``run_text_file_edit`` reads the file once, applies the edits in memory, and hands a single overwrite to the caller's write function, so protected-path refusal, managed file history, atomic replacement, verified receipts, and artifact publication are exactly those of ``write_text_file``. The digest of the bytes that were edited travels with that overwrite as ``expected_sha256``, so a file that changed in between is refused instead of silently reverted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Sequence

from api.services.agent_processing.shared.material_operation_receipts import (
    MaterialOperationContractError,
    MaterialOperationEnvelope,
    extract_material_operation_envelope,
)

MAX_EDITS_PER_CALL = 50

MAX_FILES_PER_CALL = 20

MAX_EDIT_FILE_BYTES = 2 * 1024 * 1024
"""Larger files are refused: an exact-text edit is for source and configuration files, and the whole file is held in memory while it is edited."""

WriteFunction = Callable[..., Awaitable[dict[str, Any]]]


class TextEditError(ValueError):
    """An edit request that cannot be applied; ``error_type`` is the stable machine-readable reason."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


@dataclass(frozen=True)
class TextEdit:
    """One exact replacement: ``old_text`` becomes ``new_text`` once, or everywhere when ``replace_all`` is set."""

    old_text: str
    new_text: str
    replace_all: bool = False


def failure_result(
    path: str,
    error_type: str,
    error: str,
    *,
    previous_sha256: str | None = None,
) -> dict[str, Any]:
    """The same failure shape ``LocalTextFileWriter`` returns before a write starts."""
    return {
        "success": False,
        "file_path": path,
        "operation": "modify",
        "mode": "overwrite",
        "error_type": error_type,
        "error": error,
        "previous_sha256": previous_sha256,
        "execution_success": False,
        "file_artifacts": [],
    }


def parse_text_edits(raw_edits: Any) -> list[TextEdit]:
    """Validate the raw edit list; nested pydantic models are accepted as well as plain mappings."""
    if not isinstance(raw_edits, (list, tuple)) or not raw_edits:
        raise TextEditError("no_edits", "edits must be a non-empty list of objects with old_text and new_text.")
    if len(raw_edits) > MAX_EDITS_PER_CALL:
        raise TextEditError(
            "too_many_edits",
            f"At most {MAX_EDITS_PER_CALL} edits are allowed in one call; split the change into several calls.",
        )
    parsed: list[TextEdit] = []
    for index, raw in enumerate(raw_edits):
        if not isinstance(raw, Mapping) and hasattr(raw, "model_dump"):
            raw = raw.model_dump()
        if not isinstance(raw, Mapping):
            raise TextEditError("invalid_edit", f"Edit {index} must be an object with old_text and new_text.")
        old_text = raw.get("old_text")
        new_text = raw.get("new_text")
        replace_all = raw.get("replace_all", False)
        if not isinstance(old_text, str) or not isinstance(new_text, str) or not isinstance(replace_all, bool):
            raise TextEditError(
                "invalid_edit",
                f"Edit {index} needs a string old_text, a string new_text, and an optional boolean replace_all.",
            )
        parsed.append(TextEdit(old_text=old_text, new_text=new_text, replace_all=replace_all))
    return parsed


def _mismatch_hint(text: str, old_text: str) -> str:
    """Name the most common reason an exact match fails, so the next attempt can be right."""
    if (
        "\n" in old_text
        and "\r\n" not in old_text
        and "\r\n" in text
        and text.count(old_text.replace("\n", "\r\n")) > 0
    ):
        return " (the file uses CRLF line endings, and this text matches when each newline is written as CRLF)"
    if " ".join(old_text.split()) in " ".join(text.split()):
        return " (the same words appear with different whitespace, so check indentation and line breaks)"
    return ""


def apply_text_edits(text: str, edits: Sequence[TextEdit]) -> tuple[str, list[dict[str, int]]]:
    """Apply the edits in order, each against the result of the one before, and return the new text plus per-edit counts.

    Every edit must match exactly once unless it sets ``replace_all``. Any failure raises ``TextEditError`` and the caller writes nothing, so a call either applies completely or not at all.
    """
    current = text
    applied: list[dict[str, int]] = []
    for index, edit in enumerate(edits):
        if edit.old_text == "":
            raise TextEditError("empty_old_text", f"Edit {index}: old_text must not be empty. Nothing was changed.")
        if edit.old_text == edit.new_text:
            raise TextEditError(
                "noop_edit",
                f"Edit {index}: old_text and new_text are identical, so nothing would change. Nothing was changed.",
            )
        count = current.count(edit.old_text)
        if count == 0:
            raise TextEditError(
                "old_text_not_found",
                f"Edit {index}: old_text was not found in the file{_mismatch_hint(current, edit.old_text)}. Nothing was changed.",
            )
        if count > 1 and not edit.replace_all:
            raise TextEditError(
                "old_text_ambiguous",
                f"Edit {index}: old_text matches {count} places. Include more surrounding lines so it matches exactly once, or set replace_all to true. Nothing was changed.",
            )
        if edit.replace_all:
            current = current.replace(edit.old_text, edit.new_text)
            applied.append({"index": index, "replacements": count})
        else:
            current = current.replace(edit.old_text, edit.new_text, 1)
            applied.append({"index": index, "replacements": 1})
    if current == text:
        raise TextEditError("noop_edit", "The edits cancel each other out, so the file would not change. Nothing was changed.")
    return current, applied


async def run_text_file_edit(
    *,
    writer: Any,
    write_text_file: WriteFunction,
    path: str,
    edits: Any,
    expected_sha256: str | None,
) -> dict[str, Any]:
    """Read, edit in memory, then overwrite once through ``write_text_file`` with the digest of what was read."""
    try:
        parsed = parse_text_edits(edits)
    except TextEditError as exc:
        return failure_result(path, exc.error_type, str(exc))

    snapshot = await writer.read_text_snapshot(path=path, max_bytes=MAX_EDIT_FILE_BYTES)
    if not snapshot.get("success"):
        return snapshot

    target = str(snapshot["file_path"])
    current_sha256 = str(snapshot["sha256"])
    if expected_sha256 is not None and expected_sha256 != current_sha256:
        return failure_result(
            target,
            "stale_target",
            "expected_sha256 does not match the current file content. Nothing was changed.",
            previous_sha256=current_sha256,
        )
    try:
        edited, applied = apply_text_edits(str(snapshot["text"]), parsed)
    except TextEditError as exc:
        return failure_result(target, exc.error_type, str(exc), previous_sha256=current_sha256)

    result = await write_text_file(path=target, content=edited, mode="overwrite", expected_sha256=current_sha256)
    if isinstance(result, dict) and result.get("success"):
        return {**result, "edits_applied": applied}
    return result


PathPrecheck = Callable[[str], "dict[str, Any] | None"]


def _parse_file_entries(raw_files: Any) -> list[tuple[str, list[TextEdit], str | None]]:
    """Validate the raw multi-file list into ``(path, edits, expected_sha256)`` entries."""
    if not isinstance(raw_files, (list, tuple)) or not raw_files:
        raise TextEditError("no_files", "files must be a non-empty list of objects with path and edits.")
    if len(raw_files) > MAX_FILES_PER_CALL:
        raise TextEditError(
            "too_many_files",
            f"At most {MAX_FILES_PER_CALL} files are allowed in one call; split the change into several calls.",
        )
    entries: list[tuple[str, list[TextEdit], str | None]] = []
    for index, raw in enumerate(raw_files):
        if not isinstance(raw, Mapping) and hasattr(raw, "model_dump"):
            raw = raw.model_dump()
        if not isinstance(raw, Mapping):
            raise TextEditError("invalid_file_entry", f"File {index} must be an object with path and edits.")
        path = raw.get("path")
        expected_sha256 = raw.get("expected_sha256")
        if not isinstance(path, str) or not path.strip() or not (expected_sha256 is None or isinstance(expected_sha256, str)):
            raise TextEditError(
                "invalid_file_entry",
                f"File {index} needs a string path and an optional string expected_sha256.",
            )
        try:
            edits = parse_text_edits(raw.get("edits"))
        except TextEditError as exc:
            raise TextEditError(exc.error_type, f"File {index} ({path}): {exc}") from exc
        entries.append((path, edits, expected_sha256))
    return entries


def _files_failure(error_type: str, error: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    """Failure shape for a multi-file call; ``results`` holds one status entry per file when known."""
    return {
        "success": False,
        "operation": "modify",
        "mode": "overwrite",
        "error_type": error_type,
        "error": error,
        "files_total": len(results),
        "files_applied": sum(1 for item in results if item.get("status") == "applied"),
        "results": results,
        "execution_success": False,
        "file_artifacts": [],
    }


async def run_text_files_edit(
    *,
    writer: Any,
    write_text_file: WriteFunction,
    precheck: PathPrecheck,
    files: Any,
) -> dict[str, Any]:
    """Edit several files: validate every file in memory first, then overwrite them one at a time.

    Nothing is written unless every file validates. Each write goes through ``write_text_file`` with the digest that was read, so each file keeps its own atomic replacement, managed history, and verified receipt. The receipts of every attempted write are merged into one material-operation envelope, which the artifact publisher already turns into one artifact per verified file. A disk failure part-way cannot be rolled back across files, so it is reported as ``partial_failure`` with a status for every file.
    """
    try:
        entries = _parse_file_entries(files)
    except TextEditError as exc:
        return _files_failure(exc.error_type, str(exc), [])

    results: list[dict[str, Any]] = []
    prepared: list[tuple[int, str, str, str, list[dict[str, int]]]] = []
    failure_messages: list[str] = []
    first_error_type: str | None = None
    seen_targets: set[str] = set()
    for index, (path, edits, expected_sha256) in enumerate(entries):
        failure = precheck(path)
        snapshot: dict[str, Any] = {}
        if failure is None:
            snapshot = await writer.read_text_snapshot(path=path, max_bytes=MAX_EDIT_FILE_BYTES)
            if not snapshot.get("success"):
                failure = snapshot
        edited = ""
        applied: list[dict[str, int]] = []
        target = path
        digest = ""
        if failure is None:
            target = str(snapshot["file_path"])
            digest = str(snapshot["sha256"])
            if target in seen_targets:
                failure = failure_result(target, "duplicate_path", "This path appears more than once in files; combine its edits into one entry.")
            elif expected_sha256 is not None and expected_sha256 != digest:
                failure = failure_result(
                    target,
                    "stale_target",
                    "expected_sha256 does not match the current file content.",
                    previous_sha256=digest,
                )
            else:
                seen_targets.add(target)
                try:
                    edited, applied = apply_text_edits(str(snapshot["text"]), edits)
                except TextEditError as exc:
                    failure = failure_result(target, exc.error_type, str(exc), previous_sha256=digest)
        if failure is not None:
            if first_error_type is None:
                first_error_type = str(failure.get("error_type"))
            failure_messages.append(f"File {index} ({failure.get('file_path', path)}): {failure.get('error')}")
            results.append(
                {
                    "index": index,
                    "file_path": failure.get("file_path", path),
                    "status": "failed",
                    "error_type": failure.get("error_type"),
                    "error": failure.get("error"),
                    "previous_sha256": failure.get("previous_sha256"),
                }
            )
            continue
        prepared.append((index, target, edited, digest, applied))
        results.append({"index": index, "file_path": target, "status": "validated"})

    if failure_messages:
        for item in results:
            if item["status"] == "validated":
                item["status"] = "not_written"
        return _files_failure(
            first_error_type or "edit_failed",
            " ".join(failure_messages) + " Nothing was written to any file.",
            results,
        )

    receipts: list[Any] = []
    file_artifacts: list[Any] = []
    write_failure: dict[str, Any] | None = None
    for position, (index, target, edited, digest, applied) in enumerate(prepared):
        write_result = await write_text_file(path=target, content=edited, mode="overwrite", expected_sha256=digest)
        try:
            envelope = extract_material_operation_envelope(write_result)
        except MaterialOperationContractError:
            envelope = None
        if envelope is not None:
            receipts.extend(envelope.receipts)
        if isinstance(write_result, dict) and write_result.get("success"):
            results[index] = {
                "index": index,
                "file_path": target,
                "status": "applied",
                "edits_applied": applied,
                "bytes_written": write_result.get("bytes_written"),
                "previous_sha256": write_result.get("previous_sha256"),
                "sha256": write_result.get("sha256"),
            }
            file_artifacts.extend(write_result.get("file_artifacts") or [])
            continue
        write_failure = write_result if isinstance(write_result, dict) else {"error_type": "write_failed", "error": "The write did not return a result."}
        results[index] = {
            "index": index,
            "file_path": target,
            "status": "write_failed",
            "error_type": write_failure.get("error_type"),
            "error": write_failure.get("error"),
        }
        for later_index, *_ in prepared[position + 1:]:
            results[later_index]["status"] = "not_attempted"
        break

    applied_count = sum(1 for item in results if item["status"] == "applied")
    combined: dict[str, Any] = {
        "success": write_failure is None,
        "operation": "modify",
        "mode": "overwrite",
        "files_total": len(entries),
        "files_applied": applied_count,
        "results": results,
        "execution_success": write_failure is None,
        "file_artifacts": file_artifacts,
    }
    if receipts:
        combined.update(MaterialOperationEnvelope(receipts=tuple(receipts)).to_tool_result_fields())
    if write_failure is not None:
        reason = f"{write_failure.get('error_type')}: {write_failure.get('error')}"
        if applied_count:
            combined["error_type"] = "partial_failure"
            combined["error"] = (
                f"Wrote {applied_count} of {len(entries)} files before a write failed ({reason}). "
                "The files marked applied were changed and the rest were not written; re-read the changed files before retrying."
            )
        else:
            combined["error_type"] = write_failure.get("error_type") or "write_failed"
            combined["error"] = f"{write_failure.get('error')} Nothing was written to any file."
    return combined
