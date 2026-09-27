import uuid
from pathlib import Path

import pytest

from api.services.agent_processing.lifecycle.runtime.workflow_coordinator import WorkflowCoordinator
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_service import ShellService
from api.services.agent_processing.tools.safety.approval_override import (
    ApprovalOverride,
    clear_override,
    register_override,
)


@pytest.mark.e2e
@pytest.mark.manual
@pytest.mark.asyncio
async def test_agent_tool_choice_ambiguous_creation(request: pytest.FixtureRequest):
    """
    Ambiguous instruction to allow the agent to choose AppleScript vs Shell.

    Validates:
    - Agent produces a final_envelope with the created file
    - File exists on disk with expected content
    - Tool choice is detectable from the finalizer's intermediate-step summaries (shell or applescript)
    """

    shell_service = ShellService()
    repo_root = getattr(shell_service, "_repo_root")
    assert repo_root and Path(repo_root).is_dir(), "repo_root should be detected"

    # Allowlisted location to avoid permission/CWD issues; avoids hard-coding Desktop
    out_dir = Path(repo_root) / "tmp_tool_choice"
    out_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"ambiguous_{uuid.uuid4().hex[:8]}.txt"
    out_path = (out_dir / file_name).resolve()
    request.addfinalizer(lambda: out_path.unlink(missing_ok=True))

    # Ambiguous, preference-neutral instruction
    user_instruction = (
        "Create a new text file at '"
        + str(out_path)
        + "' containing the exact text 'hello ambiguous'. "
          "Choose the most reliable approach on macOS. If interacting with an app helps, you may do so; "
          "otherwise a shell command is fine. Then finalize."
    )

    coordinator = WorkflowCoordinator(websocket_manager=None)

    # Global settings are commonly WHITELIST_ONLY + WAIT_FOREVER: a shell/AppleScript
    # command outside the whitelist would otherwise wait forever for an interactive
    # approval that never arrives (websocket_manager=None here, nobody to click
    # approve). execute_complete_workflow only threads agent_task_id into the
    # approval-check context when one is given (see WorkflowCoordinator's
    # `if agent_task_id: context["agent_task_id"] = agent_task_id`), so a per-run
    # override registered against a real agent_task_id is required to make this
    # test run unattended, mirroring test_scripting_floor_e2e.py.
    agent_task_id = str(uuid.uuid4())
    register_override(agent_task_id, ApprovalOverride(approval_mode="always_approve"))
    try:
        # Execute with dynamic agent + tools. execute_complete_workflow is the only
        # supported execution mode (legacy graph/tools-execution toggles were removed);
        # its user-facing arg is user_agent_task, not user_instruction.
        result = await coordinator.execute_complete_workflow(
            user_agent_task=user_instruction,
            context={"active_app": "Terminal"},
            agent_task_id=agent_task_id,
        )
    finally:
        clear_override(agent_task_id)

    # final_envelope must be present/successful and include our file
    final_env = getattr(result, "final_envelope", None)
    assert isinstance(final_env, dict), "final_envelope should be present and a dict"
    assert final_env.get("success") is True, f"final_envelope should indicate success: {final_env}"

    rp = final_env.get("result_payload") or {}
    files = rp.get("files") or []
    file_paths = {str(Path(f.get("full_path", "")).resolve()) for f in files if isinstance(f, dict)}
    assert str(out_path) in file_paths, (
        f"final_envelope files should include created file path: {out_path} vs {file_paths}"
    )

    # File must exist with expected content
    assert out_path.exists(), f"File should exist: {out_path}"
    assert out_path.read_text(encoding="utf-8").strip() == "hello ambiguous"

    # Detect actual tool usage from the finalizer's own intermediate-step summaries.
    # tool_execution_results[0]["intermediate_steps"] holds compact, JSON-safe trace
    # records built by finalization.execution_result_processing._summarize_intermediate_steps (each a plain
    # dict with a "tool" key) -- NOT the raw LangChain (AgentAction, observation)
    # tuples the previous version of this test assumed. Reading step[0].tool off a
    # plain dict silently returns None, which is why used_tools always came back empty.
    used_tools = set()
    for exec_item in (getattr(result, "execution_results", None) or []):
        if not isinstance(exec_item, dict):
            continue
        for step_summary in (exec_item.get("intermediate_steps") or []):
            if isinstance(step_summary, dict):
                tool_name = step_summary.get("tool")
                if tool_name:
                    used_tools.add(tool_name)

    # At least one of our expected tools should be present
    expected = {
        "shell_service_execute_command",
        "applescript_service_execute_applescript",
        "applescript_service_generate_and_execute_applescript",
    }
    assert used_tools & expected, f"Expected one of {expected}, saw tools={used_tools}"


