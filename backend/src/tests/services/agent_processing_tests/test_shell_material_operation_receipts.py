"""Independent non-AppleScript producer tests for shell material receipts."""

from pathlib import Path

from api.services.agent_processing.tools.direct_application_interactions.shell.shell_file_artifacts import (
    prepare_file_operations,
)
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_material_operation_receipts import (
    attach_shell_material_operation_receipts,
)


def test_verified_file_operation_emits_shared_material_envelope(tmp_path: Path):
    destination = tmp_path / "created.txt"
    declaration = prepare_file_operations(
        [{"operation": "create", "path": str(destination)}],
        [tmp_path],
    )
    destination.write_text("created")

    result = attach_shell_material_operation_receipts(
        {
            "success": True,
            "execution_success": True,
            "file_artifacts": [
                {
                    "full_path": str(destination),
                    "operation": "create",
                    "kind": "file",
                }
            ],
        },
        declaration,
    )

    receipt = result["material_operation"]["receipts"][0]
    assert receipt["entity"]["source_system"] == "filesystem"
    assert receipt["verification_status"] == "verified"
    assert receipt["observed_postcondition"]["file_artifact"]["full_path"] == str(destination)


def test_denied_file_operation_is_not_claimed_as_executed(tmp_path: Path):
    declaration = prepare_file_operations(
        [{"operation": "create", "path": str(tmp_path / "denied.txt")}],
        [tmp_path],
    )

    result = attach_shell_material_operation_receipts(
        {"success": False, "approval_denied": True, "stderr": "Denied"},
        declaration,
    )

    receipt = result["material_operation"]["receipts"][0]
    assert receipt["execution_state"] == "not_started"
    assert receipt["verification_status"] == "not_applicable"
