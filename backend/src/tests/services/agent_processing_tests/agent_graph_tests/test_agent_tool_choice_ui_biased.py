import uuid
from pathlib import Path
import subprocess

import pytest

from api.services.agent_processing.lifecycle.runtime.workflow_coordinator import WorkflowCoordinator
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_service import ShellService
from api.services.agent_processing.tools.safety.approval_override import (
    ApprovalOverride,
    clear_override,
    register_override,
)


def _cleanup_textedit_artifact(out_path: Path) -> None:
    escaped_name = out_path.name.replace('"', '\\"')
    cleanup_script = f'''
if application "TextEdit" is running then
    tell application "TextEdit"
        if exists document "{escaped_name}" then
            close document "{escaped_name}" saving no
        end if
    end tell
end if
'''
    subprocess.run(
        ["osascript", "-e", cleanup_script],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    out_path.unlink(missing_ok=True)


@pytest.mark.e2e
@pytest.mark.manual
@pytest.mark.asyncio
async def test_agent_tool_choice_ui_biased_textedit(request: pytest.FixtureRequest):
    """
    UI-biased instruction that mentions TextEdit and saving a document, to observe
    whether the agent selects AppleScript tools vs Shell for file creation.

    Validates:
    - final_envelope present/successful
    - created file appears in result_payload.files
    - file exists and contains the expected content (substring match)
    - records which tool(s) were used (AppleScript vs Shell)
    """

    shell_service = ShellService()
    repo_root = getattr(shell_service, "_repo_root")
    assert repo_root and Path(repo_root).is_dir(), "repo_root should be detected"

    out_dir = Path(repo_root) / "tmp_ui_choice"
    out_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"uibias_{uuid.uuid4().hex[:8]}.txt"
    out_path = (out_dir / file_name).resolve()
    request.addfinalizer(lambda: _cleanup_textedit_artifact(out_path))

    # UI-biased instruction referencing TextEdit explicitly
    user_instruction = (
        "Open TextEdit and create a new document. Type exactly 'hello ui'. "
        "Save it to '" + str(out_path) + "' and confirm it was saved. Then finalize."
    )

    coordinator = WorkflowCoordinator(websocket_manager=None)
    agent_task_id = str(uuid.uuid4())
    register_override(agent_task_id, ApprovalOverride(approval_mode="always_approve"))

    try:
        result = await coordinator.execute_complete_workflow(
            user_agent_task=user_instruction,
            context={"active_app": "TextEdit"},
            agent_task_id=agent_task_id,
        )
    finally:
        clear_override(agent_task_id)

    final_env = getattr(result, "final_envelope", None)
    assert isinstance(final_env, dict), "final_envelope should be present and a dict"
    assert final_env.get("success") is True, f"final_envelope should indicate success: {final_env}"

    rp = final_env.get("result_payload") or {}
    files = rp.get("files") or []
    file_paths = {str(Path(f.get("full_path", "")).resolve()) for f in files if isinstance(f, dict)}
    # Relaxed: allow additional files (e.g., cleaned-up artifacts) as long as our target is included
    assert str(out_path) in file_paths, (
        f"final_envelope files should include created file path: {out_path} vs {file_paths}"
    )

    # File must exist; content should include our expected text
    assert out_path.exists(), f"File should exist: {out_path}"
    text = out_path.read_text(encoding="utf-8", errors="ignore")
    assert "hello ui" in text, f"File content should include 'hello ui', got: {text!r}"

    # Detect which tools were used
    used_tools = set()
    try:
        for exec_item in (getattr(result, "execution_results", []) or []):
            steps = exec_item.get("intermediate_steps") or []
            for step in steps:
                try:
                    action = step[0]
                    tool_name = getattr(action, "tool", None)
                    if tool_name:
                        used_tools.add(tool_name)
                except Exception:
                    continue
    except Exception:
        pass

    # Record whether AppleScript was used; do not hard-fail if Shell was chosen
    expected_any = {
        "applescript_service_execute_applescript",
        "applescript_service_generate_and_execute_applescript",
        "shell_service_execute_command",
    }
    assert used_tools & expected_any, f"Expected one of {expected_any}, saw tools={used_tools}"

    # Prefer AppleScript for UI-biased flows; surface as warning via assert message if not
    if not ({"applescript_service_execute_applescript", "applescript_service_generate_and_execute_applescript"} & used_tools):
        # This will not fail the test, but provides a helpful assertion context on mismatch
        # Developers can examine logs to decide whether to tighten prompt guidance
        pytest.skip(f"UI-biased request did not use AppleScript tools; used tools={used_tools}")


