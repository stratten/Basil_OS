"""Data-only descriptors for explicitly attended ACP runtime validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class RuntimeValidationDescriptorError(ValueError):
    """Raised when a requested attended runtime-validation target is unsafe."""


@dataclass(frozen=True)
class AcpRuntimeValidationDescriptor:
    """Describe one runtime without storing credentials or launch-time environment values."""

    identifier: str
    display_name: str
    support_path: str
    launch_argv: tuple[str, ...]
    version_argv: tuple[str, ...]
    credential_owner: str
    expected_transport: str = "stdio"
    expected_capabilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.support_path not in {"native", "adapter"}:
            raise RuntimeValidationDescriptorError(
                f"{self.identifier!r} has unsupported path {self.support_path!r}"
            )
        if not self.launch_argv or not self.version_argv:
            raise RuntimeValidationDescriptorError(
                f"{self.identifier!r} requires launch and version commands"
            )
        if self.expected_transport != "stdio":
            raise RuntimeValidationDescriptorError(
                f"{self.identifier!r} must use stdio for first certification"
            )
        if not self.credential_owner.strip():
            raise RuntimeValidationDescriptorError(
                f"{self.identifier!r} must name its credential owner"
            )


RUNTIME_VALIDATION_DESCRIPTORS: dict[str, AcpRuntimeValidationDescriptor] = {
    "opencode": AcpRuntimeValidationDescriptor(
        identifier="opencode",
        display_name="OpenCode",
        support_path="native",
        launch_argv=("opencode", "acp", "--pure"),
        version_argv=("opencode", "--version"),
        credential_owner="OpenCode",
        expected_capabilities=frozenset({"loadSession"}),
    ),
    "gemini-cli": AcpRuntimeValidationDescriptor(
        identifier="gemini-cli",
        display_name="Gemini CLI",
        support_path="native",
        launch_argv=("gemini", "--acp"),
        version_argv=("gemini", "--version"),
        credential_owner="Gemini CLI",
    ),
    "claude-agent-acp": AcpRuntimeValidationDescriptor(
        identifier="claude-agent-acp",
        display_name="Claude Code through claude-agent-acp",
        support_path="adapter",
        launch_argv=("claude-agent-acp",),
        version_argv=("claude-agent-acp", "--version"),
        credential_owner="Claude Code and claude-agent-acp",
    ),
    "codex-acp": AcpRuntimeValidationDescriptor(
        identifier="codex-acp",
        display_name="Codex through codex-acp",
        support_path="adapter",
        launch_argv=("codex-acp",),
        version_argv=("codex-acp", "--version"),
        credential_owner="Codex and codex-acp",
    ),
}


def get_runtime_validation_descriptor(identifier: str) -> AcpRuntimeValidationDescriptor:
    """Return one known descriptor, rejecting unknown provider executables."""

    try:
        return RUNTIME_VALIDATION_DESCRIPTORS[identifier]
    except KeyError as error:
        raise RuntimeValidationDescriptorError(
            f"Unknown ACP runtime validation descriptor: {identifier!r}"
        ) from error


def validate_runtime_validation_root(root: Path) -> Path:
    """Require a caller-owned temporary root before any runtime process may launch."""

    resolved_root = root.expanduser().resolve()
    temporary_root = Path("/private/tmp").resolve()
    if not resolved_root.is_relative_to(temporary_root):
        raise RuntimeValidationDescriptorError(
            "Runtime validation roots must remain beneath /private/tmp."
        )
    if resolved_root == temporary_root:
        raise RuntimeValidationDescriptorError(
            "Runtime validation root must be a dedicated child of /private/tmp."
        )
    return resolved_root


__all__ = [
    "AcpRuntimeValidationDescriptor",
    "RUNTIME_VALIDATION_DESCRIPTORS",
    "RuntimeValidationDescriptorError",
    "get_runtime_validation_descriptor",
    "validate_runtime_validation_root",
]
