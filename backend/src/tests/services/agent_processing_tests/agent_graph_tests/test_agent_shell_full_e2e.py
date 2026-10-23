import os
from pathlib import Path
import subprocess
import sys

import pytest

from api.services.agent_processing.tools.direct_application_interactions.shell.shell_service import ShellService


_LOCAL_RUNTIME_VALIDATION_ENV = "RUN_LOCAL_AGENT_SHELL_E2E"
_LOCAL_MODEL_ID = "Qwen-qwen3-8b-instruct-q4km"
_LOCAL_MODEL_RELATIVE_PATH = Path(".basil/models/qwen3-8b-instruct-q4km.gguf")
_WORKFLOW_TIMEOUT_SECONDS = 90
_CHILD_PROCESS_TIMEOUT_SECONDS = 120


def _local_model_path() -> Path:
    original_home = Path(os.environ.get("BASIL_TEST_ORIGINAL_HOME", Path.home()))
    return original_home / _LOCAL_MODEL_RELATIVE_PATH


def _workflow_script(out_path: Path) -> str:
    return f'''import asyncio
import faulthandler
import json
from pathlib import Path
import sys
import threading
import time
import traceback
import uuid

from api.services.agent_processing.lifecycle.runtime.workflow_coordinator import WorkflowCoordinator
from api.services.agent_processing.tools.safety.approval_override import (
    ApprovalOverride,
    clear_override,
    register_override,
)
from api.core.models.reasoning.llama_cpp_model import shutdown_cached_llama_cpp_models


def trace(event: str, include_thread_stacks: bool = False) -> None:
    thread_stacks = {{}}
    if include_thread_stacks:
        frames = sys._current_frames()
        thread_stacks = {{
            thread.name: traceback.format_stack(frames[thread.ident])
            for thread in threading.enumerate()
            if thread.ident in frames
        }}
    print(
        "LOCAL_RUNTIME_TRACE "
        + json.dumps(
            {{
                "event": event,
                "monotonic_seconds": time.monotonic(),
                "threads": [
                    {{"name": thread.name, "daemon": thread.daemon, "alive": thread.is_alive()}}
                    for thread in threading.enumerate()
                ],
                "thread_stacks": thread_stacks,
            }}
        ),
        flush=True,
    )


async def main() -> None:
    agent_task_id = str(uuid.uuid4())
    register_override(agent_task_id, ApprovalOverride(approval_mode="always_approve"))
    try:
        trace("e2e_workflow_invocation_started")
        result = await WorkflowCoordinator(websocket_manager=None).execute_complete_workflow(
            user_agent_task=(
                "Using a shell command, create a text file at {str(out_path)!r} "
                "containing the exact text 'hello e2e'. Use bash -lc with absolute "
                "POSIX paths. Do not use AppleScript. Then finalize."
            ),
            context={{
                "active_app": "Terminal",
                "model_id": {_LOCAL_MODEL_ID!r},
                "workflow_wallclock_limit_seconds": {_WORKFLOW_TIMEOUT_SECONDS},
                "finalization_reserve_seconds": 15,
            }},
            agent_task_id=agent_task_id,
        )
        trace("e2e_workflow_returned")
        final_envelope = getattr(result, "final_envelope", None)
        assert isinstance(final_envelope, dict), "final_envelope should be present and a dict"
        assert final_envelope.get("success") is True, final_envelope
        result_payload = final_envelope.get("result_payload") or {{}}
        files = result_payload.get("files") or []
        file_paths = {{str(Path(item.get("full_path", "")).resolve()) for item in files if isinstance(item, dict)}}
        assert {str(out_path)!r} in file_paths, file_paths
        assert Path({str(out_path)!r}).read_text(encoding="utf-8").strip() == "hello e2e"
        trace("e2e_assertions_passed")
        print(json.dumps({{"agent_task_id": agent_task_id, "model_id": {_LOCAL_MODEL_ID!r}}}))
    finally:
        clear_override(agent_task_id)
        trace("e2e_override_cleared")


faulthandler.dump_traceback_later(105, file=sys.stderr)
try:
    asyncio.run(main())
finally:
    faulthandler.cancel_dump_traceback_later()
    shutdown_cached_llama_cpp_models()
trace("e2e_event_loop_closed", include_thread_stacks=True)
'''


@pytest.mark.e2e
def test_full_agent_shell_execution_end_to_end():
    """Run the pinned local-GGUF shell workflow in an isolated, bounded process."""
    if os.getenv(_LOCAL_RUNTIME_VALIDATION_ENV) != "1":
        pytest.skip(f"Set {_LOCAL_RUNTIME_VALIDATION_ENV}=1 to run the local shell workflow.")

    model_path = _local_model_path()
    if not model_path.is_file():
        pytest.skip(f"The local GGUF fixture is not installed at {model_path}.")

    shell_service = ShellService()
    repo_root = getattr(shell_service, "_repo_root")
    assert repo_root and Path(repo_root).is_dir(), "repo_root should be detected"

    out_dir = Path(repo_root) / "tmp_shell_e2e"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = (out_dir / "local-shell-e2e.txt").resolve()
    source_root = Path(__file__).parents[4]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(source_root)
    environment["BASIL_MODELS_DIR"] = str(model_path.parent)
    environment["BASIL_LOCAL_RUNTIME_TRACE"] = "1"

    failure_message = None
    try:
        completed = subprocess.run(
            [sys.executable, "-c", _workflow_script(out_path)],
            cwd=source_root.parent,
            env=environment,
            capture_output=True,
            text=True,
            timeout=_CHILD_PROCESS_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            failure_message = completed.stdout + completed.stderr
    except subprocess.TimeoutExpired as exc:
        child_output = "\n".join(
            part.decode() if isinstance(part, bytes) else part
            for part in (exc.stdout, exc.stderr)
            if part
        )
        trace_lines = [
            line for line in child_output.splitlines()
            if "LOCAL_RUNTIME_TRACE" in line
        ]
        failure_message = (
            f"Local shell workflow exceeded {_CHILD_PROCESS_TIMEOUT_SECONDS} seconds.\n"
            f"Runtime trace:\n{chr(10).join(trace_lines)}\n"
            f"Child output tail:\n{child_output[-4000:]}"
        )
    finally:
        out_path.unlink(missing_ok=True)
    if failure_message:
        pytest.fail(failure_message, pytrace=False)


