"""Explicit-gate preflight for attended ACP runtime validation."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .runtime_validation_descriptors import (
    AcpRuntimeValidationDescriptor,
    RuntimeValidationDescriptorError,
    get_runtime_validation_descriptor,
    validate_runtime_validation_root,
)


RUNTIME_VALIDATION_OPT_IN_ENV = "BASIL_ACP_RUNTIME_VALIDATION"
RUNTIME_VALIDATION_DESCRIPTOR_ENV = "BASIL_ACP_RUNTIME_DESCRIPTOR"


@dataclass(frozen=True)
class RuntimeValidationPreflight:
    """Sanitized readiness state before an attended provider process launch."""

    descriptor: AcpRuntimeValidationDescriptor
    session_root: Path
    executable_path: Path | None

    @property
    def executable_available(self) -> bool:
        return self.executable_path is not None


@dataclass
class RuntimeValidationSession:
    """Own the disposable files for one attended provider validation."""

    preflight: RuntimeValidationPreflight
    workspace_root: Path
    database_path: Path
    _closed: bool = False

    def close(self) -> None:
        """Remove only the validated dedicated session root."""

        if self._closed:
            return
        root = validate_runtime_validation_root(self.preflight.session_root)
        if not root.exists():
            self._closed = True
            return
        if root.is_symlink():
            raise RuntimeValidationDescriptorError(
                "Runtime validation session root must not be a symlink."
            )
        shutil.rmtree(root)
        self._closed = True


def prepare_runtime_validation(
    *,
    descriptor_identifier: str,
    session_root: Path,
    environment: dict[str, str] | None = None,
    executable_resolver: Callable[[str], str | None] = shutil.which,
) -> RuntimeValidationPreflight:
    """Validate an exact user-approved descriptor without launching its executable."""

    selected_environment = environment if environment is not None else os.environ
    if selected_environment.get(RUNTIME_VALIDATION_OPT_IN_ENV) != "1":
        raise RuntimeValidationDescriptorError(
            f"{RUNTIME_VALIDATION_OPT_IN_ENV}=1 is required before runtime validation."
        )
    if selected_environment.get(RUNTIME_VALIDATION_DESCRIPTOR_ENV) != descriptor_identifier:
        raise RuntimeValidationDescriptorError(
            f"{RUNTIME_VALIDATION_DESCRIPTOR_ENV} must name the selected descriptor."
        )

    descriptor = get_runtime_validation_descriptor(descriptor_identifier)
    validated_root = validate_runtime_validation_root(session_root)
    executable = executable_resolver(descriptor.launch_argv[0])
    return RuntimeValidationPreflight(
        descriptor=descriptor,
        session_root=validated_root,
        executable_path=Path(executable).resolve() if executable else None,
    )


def create_runtime_validation_session(
    preflight: RuntimeValidationPreflight,
) -> RuntimeValidationSession:
    """Create the disposable workspace and database paths without launching a runtime."""

    root = validate_runtime_validation_root(preflight.session_root)
    if root.exists():
        raise RuntimeValidationDescriptorError(
            "Runtime validation session root already exists; choose a new dedicated path."
        )
    workspace_root = root / "workspace"
    workspace_root.mkdir(parents=True)
    return RuntimeValidationSession(
        preflight=preflight,
        workspace_root=workspace_root,
        database_path=root / "provider-validation.db",
    )


__all__ = [
    "RUNTIME_VALIDATION_DESCRIPTOR_ENV",
    "RUNTIME_VALIDATION_OPT_IN_ENV",
    "RuntimeValidationPreflight",
    "RuntimeValidationSession",
    "create_runtime_validation_session",
    "prepare_runtime_validation",
]
