"""Script inspection for interpreter commands, and the refusal to run a script that changed after approval."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from api.services.agent_processing.tools.direct_application_interactions.shell.shell_script_inspection import (
    MAX_SCRIPT_BYTES,
    SCRIPT_TOO_LARGE_NOTICE,
    SCRIPT_UNREADABLE_NOTICE,
    inspect_command_script,
    script_changed_since_inspection,
)
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_service import ShellService
from api.services.agent_processing.tools.safety.models import ExecutionApprovalOutcome


def test_a_readable_script_is_returned_with_its_text_path_and_hash(tmp_path: Path) -> None:
    script = tmp_path / "run.sh"
    script.write_text("echo hello\n", encoding="utf-8")

    inspection = inspect_command_script("bash", ["run.sh"], tmp_path)

    assert inspection is not None
    assert inspection.path == str(script.resolve())
    assert inspection.content == "echo hello\n"
    assert len(inspection.sha256) == 64
    assert inspection.notice is None
    assert script_changed_since_inspection(inspection) is False


def test_python_and_other_interpreters_with_flags_before_the_script_are_inspected(tmp_path: Path) -> None:
    script = tmp_path / "tool.py"
    script.write_text("print(1)\n", encoding="utf-8")

    assert inspect_command_script("/usr/bin/python3", ["-u", str(script)], tmp_path).content == "print(1)\n"
    assert inspect_command_script("python3.11", ["--", str(script)], tmp_path).content == "print(1)\n"


@pytest.mark.parametrize(
    ("command", "args"),
    [
        ("bash", ["-lc", "echo hi"]),
        ("sh", ["-c", "echo hi"]),
        ("python3", ["-c", "print(1)"]),
        ("python3", ["-m", "http.server"]),
        ("node", ["-e", "1"]),
        ("git", ["status"]),
        ("bash", []),
    ],
)
def test_inline_code_and_non_interpreters_have_no_script(command: str, args: list[str], tmp_path: Path) -> None:
    (tmp_path / "status").write_text("x", encoding="utf-8")

    assert inspect_command_script(command, args, tmp_path) is None


def test_a_missing_script_is_not_inspected(tmp_path: Path) -> None:
    assert inspect_command_script("bash", ["not-there.sh"], tmp_path) is None
    assert inspect_command_script("bash", [str(tmp_path)], tmp_path) is None


def test_a_binary_script_gets_a_notice_instead_of_text(tmp_path: Path) -> None:
    (tmp_path / "blob.sh").write_bytes(b"\xff\xfe\x00binary")
    (tmp_path / "nul.sh").write_text("echo hi\x00", encoding="utf-8")

    for name in ("blob.sh", "nul.sh"):
        inspection = inspect_command_script("bash", [name], tmp_path)
        assert inspection.content is None and inspection.sha256 is None
        assert inspection.notice == SCRIPT_UNREADABLE_NOTICE
        assert script_changed_since_inspection(inspection) is False


def test_an_oversized_script_gets_a_notice_instead_of_text(tmp_path: Path) -> None:
    (tmp_path / "big.sh").write_text("#" * (MAX_SCRIPT_BYTES + 1), encoding="utf-8")
    (tmp_path / "limit.sh").write_text("#" * MAX_SCRIPT_BYTES, encoding="utf-8")

    assert inspect_command_script("bash", ["big.sh"], tmp_path).notice == SCRIPT_TOO_LARGE_NOTICE
    assert inspect_command_script("bash", ["limit.sh"], tmp_path).content is not None


def test_a_modified_or_removed_script_is_detected(tmp_path: Path) -> None:
    script = tmp_path / "run.sh"
    script.write_text("echo one\n", encoding="utf-8")
    inspection = inspect_command_script("bash", ["run.sh"], tmp_path)

    script.write_text("echo two\n", encoding="utf-8")
    assert script_changed_since_inspection(inspection) is True

    script.write_text("echo one\n", encoding="utf-8")
    assert script_changed_since_inspection(inspection) is False

    script.unlink()
    assert script_changed_since_inspection(inspection) is True


class _RecordingApprovalService:
    def __init__(self, *, mutate: Path | None = None) -> None:
        self.contexts: list[dict] = []
        self._mutate = mutate

    async def request_approval_with_outcome(self, command, context=None):
        self.contexts.append(dict(context or {}))
        if self._mutate is not None:
            self._mutate.write_text("echo tampered\n", encoding="utf-8")
        return ExecutionApprovalOutcome(approved=True, reason="Approved by test fixture.")


def _service(tmp_path: Path, approval_service) -> ShellService:
    service = ShellService()
    service._home_root = tmp_path.resolve()
    service._approval_service = approval_service
    return service


@pytest.mark.asyncio
async def test_shell_service_sends_the_script_and_explanation_with_the_approval(tmp_path: Path) -> None:
    (tmp_path / "run.sh").write_text("echo approved\n", encoding="utf-8")
    approvals = _RecordingApprovalService()

    result = await _service(tmp_path, approvals).execute_command(
        "bash",
        ["run.sh"],
        cwd=str(tmp_path),
        purpose="Prints a greeting.",
        whitelist_advice={"recommend": False, "reason": "It is a script."},
    )

    context = approvals.contexts[0]
    assert context["script_content"] == "echo approved\n"
    assert context["script_path"] == str((tmp_path / "run.sh").resolve())
    assert len(context["script_sha256"]) == 64
    assert context["purpose"] == "Prints a greeting."
    assert context["whitelist_advice"] == {"recommend": False, "reason": "It is a script."}
    assert context["purpose_required"] is True
    assert result["success"] is True and result["stdout"] == "approved\n"


@pytest.mark.asyncio
async def test_shell_service_refuses_a_script_changed_after_approval(tmp_path: Path) -> None:
    script = tmp_path / "run.sh"
    script.write_text("echo approved\n", encoding="utf-8")
    approvals = _RecordingApprovalService(mutate=script)

    result = await _service(tmp_path, approvals).execute_command("bash", ["run.sh"], cwd=str(tmp_path), purpose="Greets.")

    assert result["success"] is False
    assert result["error_type"] == "script_changed_after_approval"
    assert "changed after it was shown for approval" in result["stderr"]
    assert "tampered" not in result["stdout"]


@pytest.mark.asyncio
async def test_inline_commands_carry_no_script_fields(tmp_path: Path) -> None:
    approvals = _RecordingApprovalService()

    await _service(tmp_path, approvals).execute_command("bash", ["-lc", "echo hi"], cwd=str(tmp_path), purpose="Greets.")

    assert "script_content" not in approvals.contexts[0]
    assert "script_path" not in approvals.contexts[0]


@pytest.mark.asyncio
async def test_an_explanation_request_is_returned_to_the_agent_without_counting_as_a_denial(tmp_path: Path) -> None:
    from api.services.agent_processing.tools.safety.explanation_gate import (
        EXPLANATION_REQUIRED_MESSAGE,
        EXPLANATION_REQUIRED_STATUS,
    )

    class _AskForExplanation:
        async def request_approval_with_outcome(self, command, context=None):
            return ExecutionApprovalOutcome(
                approved=False, status=EXPLANATION_REQUIRED_STATUS, reason=EXPLANATION_REQUIRED_MESSAGE
            )

    result = await _service(tmp_path, _AskForExplanation()).execute_command("git", ["status"], cwd=str(tmp_path))

    assert result["success"] is False
    assert result["error_type"] == EXPLANATION_REQUIRED_STATUS
    assert result["approval_denied"] is False
    assert result["stderr"] == EXPLANATION_REQUIRED_MESSAGE
