"""Validation and post-execution verification for declared shell file artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence


_SUPPORTED_OPERATIONS = frozenset({"create", "modify", "copy", "move", "rename", "delete", "record"})
_SOURCE_OPERATIONS = frozenset({"copy", "move", "rename"})


@dataclass(frozen=True)
class FileSystemState:
    exists: bool
    kind: Optional[str]
    fingerprint: Optional[str]


@dataclass(frozen=True)
class DeclaredFileOperation:
    operation: str
    path: Path
    source_path: Optional[Path]
    path_before: FileSystemState
    source_before: Optional[FileSystemState]
    recorded_operation: Optional[str] = None


def prepare_file_operations(
    declarations: Optional[Sequence[Mapping[str, Any]]],
    allowed_roots: Iterable[Path],
    *,
    recorded_after: Optional[float] = None,
) -> list[DeclaredFileOperation]:
    """Validate declarations and capture their state immediately before execution.

    ``record`` registers a file an earlier command already produced; it requires ``recorded_after`` (the run's wall-clock start) and a regular file changed since then.
    """
    normalized_roots = tuple(_normalize_allowed_root(root) for root in allowed_roots)
    prepared: list[DeclaredFileOperation] = []
    seen: set[tuple[str, str, str]] = set()

    for declaration in declarations or []:
        if not isinstance(declaration, Mapping) and hasattr(declaration, "model_dump"):
            declaration = declaration.model_dump()
        if not isinstance(declaration, Mapping):
            raise ValueError("Each file operation must be an object.")

        operation = str(declaration.get("operation") or "").strip().lower()
        if operation not in _SUPPORTED_OPERATIONS:
            raise ValueError(f"Unsupported file operation: {operation or '(missing)'}")

        path = _normalize_declared_path(declaration.get("path"), normalized_roots)
        source_path = None
        if operation in _SOURCE_OPERATIONS:
            source_path = _normalize_declared_path(
                declaration.get("source_path"),
                normalized_roots,
                label="source_path",
            )

        key = (operation, str(path), str(source_path or ""))
        if key in seen:
            raise ValueError(f"Duplicate file operation declaration: {operation} {path}")
        seen.add(key)

        path_before = _capture_state(path)
        source_before = _capture_state(source_path) if source_path else None
        _validate_preconditions(operation, path_before, source_before, path, source_path)
        recorded_operation = (
            _recorded_operation(path, path_before, recorded_after) if operation == "record" else None
        )
        prepared.append(
            DeclaredFileOperation(
                operation=operation,
                path=path,
                source_path=source_path,
                path_before=path_before,
                source_before=source_before,
                recorded_operation=recorded_operation,
            )
        )

    return prepared


def verify_file_operations(
    prepared_operations: Sequence[DeclaredFileOperation],
) -> tuple[list[dict[str, str]], list[str]]:
    """Return verified finalizer artifacts and errors for failed declarations."""
    artifacts: list[dict[str, str]] = []
    errors: list[str] = []

    for declaration in prepared_operations:
        path_after = _capture_state(declaration.path)
        source_after = _capture_state(declaration.source_path) if declaration.source_path else None
        error = _verify_transition(declaration, path_after, source_after)
        if error:
            errors.append(error)
            continue

        artifacts.append(
            {
                "name": declaration.path.name,
                "full_path": str(declaration.path),
                "operation": declaration.recorded_operation or declaration.operation,
                "kind": path_after.kind or declaration.path_before.kind or "",
                **(
                    {"sha256": path_after.fingerprint}
                    if path_after.kind == "file" and path_after.fingerprint
                    else {}
                ),
                **(
                    {"source_path": str(declaration.source_path)}
                    if declaration.source_path
                    else {}
                ),
            }
        )

    return artifacts, errors


def serialize_file_operation_declarations(
    prepared_operations: Sequence[DeclaredFileOperation],
    *,
    verification_status: str,
) -> list[dict[str, str]]:
    """Expose declared operations without claiming that any ran successfully."""
    declarations: list[dict[str, str]] = []
    for declaration in prepared_operations:
        entry = {
            "operation": declaration.operation,
            "path": str(declaration.path),
            "verification_status": verification_status,
        }
        if declaration.source_path:
            entry["source_path"] = str(declaration.source_path)
        declarations.append(entry)
    return declarations


def _normalize_allowed_root(root: Path) -> Path:
    return Path(root).expanduser().resolve()


def _normalize_declared_path(
    value: Any,
    allowed_roots: Sequence[Path],
    *,
    label: str = "path",
) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"File operation {label} is required.")

    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise ValueError(f"File operation {label} must be an absolute path.")
    if _contains_symlink(candidate):
        raise ValueError(f"File operation {label} cannot traverse a symbolic link.")

    resolved = candidate.resolve(strict=False)
    if not any(_is_descendant(resolved, root) for root in allowed_roots):
        roots = ", ".join(str(root) for root in allowed_roots)
        raise ValueError(f"File operation {label} is outside allowed roots: {roots}")
    return resolved


def _contains_symlink(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.exists() and current.is_symlink():
            return True
    return False


def _is_descendant(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _capture_state(path: Optional[Path]) -> FileSystemState:
    if path is None or not path.exists():
        return FileSystemState(exists=False, kind=None, fingerprint=None)
    if path.is_symlink():
        return FileSystemState(exists=True, kind="symlink", fingerprint=None)
    if path.is_file():
        return FileSystemState(exists=True, kind="file", fingerprint=_file_digest(path))
    if path.is_dir():
        stat = path.stat()
        return FileSystemState(
            exists=True,
            kind="directory",
            fingerprint=f"{stat.st_dev}:{stat.st_ino}:{stat.st_mtime_ns}",
        )
    return FileSystemState(exists=True, kind="other", fingerprint=None)


def _file_digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_preconditions(
    operation: str,
    path_before: FileSystemState,
    source_before: Optional[FileSystemState],
    path: Path,
    source_path: Optional[Path],
) -> None:
    if operation == "create" and path_before.exists:
        raise ValueError(f"Create destination already exists: {path}")
    if operation in {"modify", "delete"} and not path_before.exists:
        raise ValueError(f"{operation.title()} target does not exist: {path}")
    if operation == "record" and path_before.kind != "file":
        raise ValueError(f"Record target is not an existing regular file: {path}")
    if operation in _SOURCE_OPERATIONS:
        if source_before is None or not source_before.exists:
            raise ValueError(f"{operation.title()} source does not exist: {source_path}")
        if path_before.exists:
            raise ValueError(f"{operation.title()} destination already exists: {path}")
        if source_path == path:
            raise ValueError(f"{operation.title()} source and destination must differ.")


def _recorded_operation(
    path: Path,
    path_before: FileSystemState,
    recorded_after: Optional[float],
) -> str:
    if recorded_after is None:
        raise ValueError(f"Record requires an active agent task run: {path}")
    stat = path.stat()
    if stat.st_mtime < recorded_after:
        raise ValueError(f"Record target was not created or modified during this task: {path}")
    birth_time = getattr(stat, "st_birthtime", None)
    return "create" if birth_time is not None and birth_time >= recorded_after else "modify"


def _verify_transition(
    declaration: DeclaredFileOperation,
    path_after: FileSystemState,
    source_after: Optional[FileSystemState],
) -> Optional[str]:
    operation = declaration.operation
    if path_after.kind in {"symlink", "other"}:
        return f"{operation.title()} target has unsupported type at {declaration.path}"
    if operation == "create":
        return None if path_after.exists else f"Created file is missing: {declaration.path}"
    if operation == "modify":
        if not path_after.exists:
            return f"Modified file is missing: {declaration.path}"
        if path_after.fingerprint == declaration.path_before.fingerprint:
            return f"Declared file was not modified: {declaration.path}"
        return None
    if operation == "delete":
        return None if not path_after.exists else f"Deleted file still exists: {declaration.path}"
    if operation == "record":
        return None if path_after.kind == "file" else f"Recorded file is missing: {declaration.path}"

    if source_after is None or source_after.exists:
        return f"{operation.title()} source still exists: {declaration.source_path}"
    if not path_after.exists:
        return f"{operation.title()} destination is missing: {declaration.path}"
    if declaration.source_before and path_after.kind != declaration.source_before.kind:
        return f"{operation.title()} destination type changed: {declaration.path}"
    if (
        declaration.source_before
        and declaration.source_before.kind == "file"
        and path_after.fingerprint != declaration.source_before.fingerprint
    ):
        return f"{operation.title()} destination content differs: {declaration.path}"
    return None
