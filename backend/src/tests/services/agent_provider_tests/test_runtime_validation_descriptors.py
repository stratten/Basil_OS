"""Safety and coverage checks for attended ACP runtime validation descriptors."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from api.services.agent_providers.testing.runtime_validation_descriptors import (
    RUNTIME_VALIDATION_DESCRIPTORS,
    RuntimeValidationDescriptorError,
    get_runtime_validation_descriptor,
    validate_runtime_validation_root,
)
from api.services.agent_providers.testing.runtime_validation_runner import (
    create_runtime_validation_session,
    prepare_runtime_validation,
)


def test_runtime_validation_matrix_covers_native_and_adapter_paths() -> None:
    assert set(RUNTIME_VALIDATION_DESCRIPTORS) == {
        "opencode",
        "gemini-cli",
        "claude-agent-acp",
        "codex-acp",
    }
    assert {
        descriptor.support_path
        for descriptor in RUNTIME_VALIDATION_DESCRIPTORS.values()
    } == {"native", "adapter"}
    for descriptor in RUNTIME_VALIDATION_DESCRIPTORS.values():
        assert descriptor.expected_transport == "stdio"
        assert descriptor.launch_argv
        assert descriptor.version_argv
        assert descriptor.credential_owner


def test_runtime_validation_descriptor_rejects_unknown_executables() -> None:
    with pytest.raises(RuntimeValidationDescriptorError, match="Unknown ACP runtime"):
        get_runtime_validation_descriptor("unreviewed-wrapper")


def test_codex_descriptor_contains_no_credential_value_or_authentication_configuration() -> None:
    descriptor = get_runtime_validation_descriptor("codex-acp")

    assert all(
        "CODEX_API_KEY" not in argument and "OPENAI_API_KEY" not in argument
        for argument in (*descriptor.launch_argv, *descriptor.version_argv)
    )
    assert "authentication_method_id" not in descriptor.__dataclass_fields__


def test_runtime_validation_root_accepts_only_a_dedicated_private_tmp_child() -> None:
    root = validate_runtime_validation_root(Path("/private/tmp/basil-acp-validation-test"))

    assert root == Path("/private/tmp/basil-acp-validation-test")

    with pytest.raises(RuntimeValidationDescriptorError, match="dedicated child"):
        validate_runtime_validation_root(Path("/private/tmp"))
    with pytest.raises(RuntimeValidationDescriptorError, match="beneath /private/tmp"):
        validate_runtime_validation_root(Path.home() / "workspace")


def test_runtime_preflight_requires_exact_opt_in_and_reports_missing_executables() -> None:
    preflight = prepare_runtime_validation(
        descriptor_identifier="gemini-cli",
        session_root=Path("/private/tmp/basil-acp-validation-gemini"),
        environment={
            "BASIL_ACP_RUNTIME_VALIDATION": "1",
            "BASIL_ACP_RUNTIME_DESCRIPTOR": "gemini-cli",
        },
        executable_resolver=lambda executable: None,
    )

    assert preflight.descriptor.identifier == "gemini-cli"
    assert preflight.executable_available is False

    with pytest.raises(RuntimeValidationDescriptorError, match="BASIL_ACP_RUNTIME_VALIDATION"):
        prepare_runtime_validation(
            descriptor_identifier="opencode",
            session_root=Path("/private/tmp/basil-acp-validation-opencode"),
            environment={"BASIL_ACP_RUNTIME_DESCRIPTOR": "opencode"},
        )


def test_runtime_validation_session_owns_and_removes_only_its_dedicated_root() -> None:
    root = Path("/private/tmp") / f"basil-acp-validation-session-{uuid.uuid4().hex}"
    preflight = prepare_runtime_validation(
        descriptor_identifier="opencode",
        session_root=root,
        environment={
            "BASIL_ACP_RUNTIME_VALIDATION": "1",
            "BASIL_ACP_RUNTIME_DESCRIPTOR": "opencode",
        },
        executable_resolver=lambda executable: "/usr/bin/false",
    )

    session = create_runtime_validation_session(preflight)

    assert session.workspace_root.is_dir()
    assert session.database_path.parent == root
    session.close()
    assert not root.exists()
