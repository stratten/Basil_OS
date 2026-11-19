"""End-to-end proof of the shell file_operations -> verified file_artifacts pipeline.

These tests exercise the exact mechanism the agent system prompt's MATERIAL OUTCOME
VERIFICATION section (system_prompts.py) directs the agent to use, wiring the real
production functions together the way a live shell_service.execute_command call does:

    prepare_file_operations -> (command runs) -> verify_file_operations
        -> shell result carries file_artifacts
        -> extract_files_from_steps turns artifacts into result_payload.files (the
           clickable card)
        -> attach_shell_material_operation_receipts turns the same declarations into
           a shared material-operation envelope
        -> build_material_outcome_brief turns that envelope into the claim
           constraint fed to the writer/finalizer

Three scenarios are covered:
    1. Normal flow: a declared create that actually happens is verified, produces a
       card, and is safe to claim as done.
    2. Negative: a declared create that does NOT happen (verification fails) produces
       no card and forbids the "done" claim.
    3. Adversarial (the reported bug): a file is genuinely created on disk but
       file_operations was never declared for it. This proves that omission is
       invisible to every downstream mechanism -- no artifact, no card, no receipt,
       nothing to constrain the claim -- which is exactly why the fix in this task
       is a prompt-level completion requirement rather than a code-level detector.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from api.services.agent_processing.lifecycle.finalization.file_result_extraction import (
    extract_files_from_steps,
)
from api.services.agent_processing.shared.material_outcome_brief import (
    build_material_outcome_brief,
)
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_execution_result import (
    build_shell_result,
)
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_file_artifacts import (
    prepare_file_operations,
    verify_file_operations,
)
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_material_operation_receipts import (
    attach_shell_material_operation_receipts,
)


def _step_from_shell_result(shell_result: dict) -> dict:
    """Match the shape a LangChain tool step contributes to `steps` at finalization."""
    return {"result": shell_result}


def test_declared_and_verified_write_produces_card_and_allows_done_claim(tmp_path: Path):
    """Normal flow: declare file_operations, the write actually happens, verify succeeds."""
    target = tmp_path / "SOW - ABA Initial Setup (Redacted).docx"

    declarations = prepare_file_operations(
        [{"operation": "create", "path": str(target)}],
        [tmp_path],
    )

    # Simulate the command the shell tool would have run.
    target.write_bytes(b"redacted docx bytes")

    artifacts, errors = verify_file_operations(declarations)
    assert errors == []
    assert artifacts == [
        {
            "name": target.name,
            "full_path": str(target),
            "operation": "create",
            "kind": "file",
            "sha256": hashlib.sha256(b"redacted docx bytes").hexdigest(),
        }
    ]

    shell_result = build_shell_result(
        success=True,
        stdout="",
        stderr="",
        exit_code=0,
        duration_ms=12,
        cwd=str(tmp_path),
        command_echo="python3 redact.py",
        file_artifacts=artifacts,
    )
    shell_result = attach_shell_material_operation_receipts(shell_result, declarations)

    # 1) Card: the finalizer's file extraction must surface the verified artifact.
    files = extract_files_from_steps([_step_from_shell_result(shell_result)])
    assert files == [
        {"name": target.name, "full_path": str(target), "operation": "create", "kind": "file"}
    ]

    # 2) Claim grounding: a verified receipt permits stating the change as done.
    brief = build_material_outcome_brief([_step_from_shell_result(shell_result)])
    assert brief is not None
    assert "Verified changes you may state as done" in brief
    assert "not confirmed" not in brief


def test_declared_but_unrealized_write_produces_no_card_and_forbids_done_claim(tmp_path: Path):
    """Negative: file_operations declares a create, but the command never wrote the file."""
    target = tmp_path / "never_written.docx"

    declarations = prepare_file_operations(
        [{"operation": "create", "path": str(target)}],
        [tmp_path],
    )

    # The command "succeeds" (e.g. a script exits 0) but does not create the file.
    artifacts, errors = verify_file_operations(declarations)
    assert artifacts == []
    assert errors == [f"Created file is missing: {target}"]

    shell_result = build_shell_result(
        success=True,
        stdout="",
        stderr="",
        exit_code=0,
        duration_ms=8,
        cwd=str(tmp_path),
        command_echo="python3 redact.py",
        file_artifacts=artifacts,
        file_artifact_errors=errors,
    )
    shell_result = attach_shell_material_operation_receipts(shell_result, declarations)

    # 1) No card: nothing verified, so no file entry is surfaced.
    files = extract_files_from_steps([_step_from_shell_result(shell_result)])
    assert files == []

    # 2) Claim grounding: the receipt is failed (matching error), not "done".
    brief = build_material_outcome_brief([_step_from_shell_result(shell_result)])
    assert brief is not None
    assert "Changes that failed" in brief
    assert "Verified changes you may state as done" not in brief


def test_write_without_declared_file_operations_is_invisible_to_verification(tmp_path: Path):
    """Adversarial (the reported bug): a real write with no file_operations declared.

    This reproduces the exact defect: the agent ran a script that wrote a real file,
    but declared no file_operations for it. No artifact, no receipt, and therefore
    nothing constrains the agent's prose claim -- proving the omission is a
    behavioral gap the prompt must close, not something the pipeline can detect for
    the agent after the fact.
    """
    target = tmp_path / "SOW - ABA Initial Setup (Redacted).docx"
    target.write_bytes(b"redacted docx bytes")  # genuinely created

    shell_result = build_shell_result(
        success=True,
        stdout="",
        stderr="",
        exit_code=0,
        duration_ms=10,
        cwd=str(tmp_path),
        command_echo="python3 redact.py",
    )
    # No declarations at all: mirrors the reported task's actual tool call.
    shell_result = attach_shell_material_operation_receipts(shell_result, declarations=[])

    files = extract_files_from_steps([_step_from_shell_result(shell_result)])
    assert files == []
    assert "material_operation" not in shell_result

    brief = build_material_outcome_brief([_step_from_shell_result(shell_result)])
    assert brief is None
