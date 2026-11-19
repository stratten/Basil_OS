"""The agent's side of a local server recipe: the approval cards, starting a preparation, and reporting how it is going.

The recipe says what a program needs installed, how its files are fetched or built, and how its own status page is read. The agent supplies it, the person approves exactly what it will download and run on the card written here, and Basil does the rest. Nothing in this module names a particular program.
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from typing import Any, Dict, List, Optional

from api.core.models.preferences import MCPConnectionRecord, MCPInstallRecipe, MCPProbeSpec, MCPRequirement, MCPStdioSpec
from api.services.mcp_connectors.companion_supervisor import CompanionError, get_companion_supervisor
from api.services.mcp_connectors.local_server_prepare import (
    describe_method,
    get_local_server_preparer,
    requirement_install_command,
)

logger = logging.getLogger(__name__)

INSTALL_APPROVAL_SOURCE = "external_catalog_install_requirement"
# The execution-approvals table only accepts a fixed list of execution types, so these cards reuse the connection-setup type and are told apart by their source.
APPROVAL_EXECUTION_TYPE = "mcp_connection_setup"
MAX_STATUS_LOG_CHARS = 1500

RECIPE_SCHEMA = (
    "arguments.install is a recipe: {requirements: [{name, reason, check: [argv], install: [argv] (optional), for_method: any|download|build}], "
    "artifacts: [{name, expects: a path under {install_dir}, methods: [{kind: 'download', url: https address with optional {os} and {arch}, sha256 or sha256_by_arch {arm64, amd64}, archive: tar.gz|zip (optional), strip_components, executable} "
    "or {kind: 'build', git_url: https address, commit: the full 40-character hash, steps: [{argv: [...], cwd: relative folder (optional)}]}] in the order to try them}]}. "
    "Every command is an argv list, never a shell string, and an https address, a pinned hash or commit is required. "
    "In command, args, cwd and env write {install_dir} for the folder Basil keeps the files in, {data_dir} for the program's own data folder, {port} for the port Basil picks, and {run_secret} for a fresh token Basil generates on every run (a companion only). "
    "arguments.companion.probe tells Basil how to read the background program's own status page: {url: loopback address containing {port}, auth: none|bearer_run_secret|bearer_secret, secret_name, state_path: dotted path, "
    "states: {value: starting|ready|needs_action|failed}, message_path, action_kind: 'qr', action_path, expires_path}. "
    "arguments.replace is the connection_id of a local server to rewrite in place, for correcting a recipe that failed; its saved secrets are kept."
)


def _joined(argv: List[str]) -> str:
    return shlex.join(argv)


def _requirement_sentence(requirement: MCPRequirement) -> str:
    install = f"; with your separate approval it installs it by running {requirement_install_command(requirement)}" if requirement.install else "; it cannot install it, so you would install it yourself"
    return f"{requirement.name} ({requirement.reason}) is checked by running {_joined(requirement.check)}{install}"


def _probe_sentence(probe: MCPProbeSpec) -> str:
    authenticate = {"none": "without credentials", "bearer_run_secret": "with the token Basil generates for each run", "bearer_secret": f"with your saved secret {probe.secret_name}"}[probe.auth]
    shown = " Any code you must scan is shown only in Basil's Settings, in memory, and is never saved." if probe.action_path else ""
    return f"Basil reads the background program's own status page at {probe.url}, {authenticate}, to tell whether it is ready or waiting for you.{shown}"


def recipe_card_sentences(spec: MCPStdioSpec) -> List[str]:
    """What the recipe will do, one sentence per part, with every address, hash, commit and command written out in full."""
    sentences: List[str] = []
    recipe = spec.install
    if recipe is not None and recipe.requirements:
        sentences.append("Before anything else Basil checks for these programs: " + "; ".join(_requirement_sentence(item) for item in recipe.requirements) + ".")
    if recipe is not None:
        for artifact in recipe.artifacts:
            ways = " If that fails, it tries: ".join(describe_method(method) for method in artifact.methods)
            sentences.append(f"Basil puts {artifact.name} at {artifact.expects} inside its own folder for this server by: {ways}.")
        if any(method.kind == "build" for artifact in recipe.artifacts for method in artifact.methods):
            sentences.append("A build runs the listed commands on this Mac with your account's access, so approve it only if you trust that source and those commands. Basil checks out exactly the commit named and refuses anything else.")
        if any(method.kind == "download" for artifact in recipe.artifacts for method in artifact.methods):
            sentences.append("A download is used only if its SHA-256 matches the one listed. A file that does not match is deleted and never run.")
    if spec.companion is not None and spec.companion.probe is not None:
        sentences.append(_probe_sentence(spec.companion.probe))
    return sentences


def recipe_card_lines(spec: MCPStdioSpec) -> List[str]:
    """The same content as lines for the command area of the card."""
    lines: List[str] = []
    recipe = spec.install
    if recipe is not None:
        for requirement in recipe.requirements:
            lines.append(f"requirement: {requirement.name}: check {_joined(requirement.check)}; install {requirement_install_command(requirement) or '(you install it)'}")
        for artifact in recipe.artifacts:
            for number, method in enumerate(artifact.methods, start=1):
                lines.append(f"artifact {artifact.name} -> {artifact.expects}, option {number}: {describe_method(method)}")
    if spec.companion is not None and spec.companion.probe is not None:
        lines.append(f"status page: {spec.companion.probe.url}")
    return lines


def capture_runtime_context() -> Dict[str, Any]:
    """The agent's runtime context at this moment, so an approval asked later from a background task still reaches the right task."""
    try:
        from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context

        context = get_current_agent_context()
        return context if isinstance(context, dict) else {}
    except Exception as exc:
        logger.debug("Could not read agent runtime context for an approval: %s", exc)
        return {}


async def ask_user_approval(command: str, fields: Dict[str, Any], runtime_context: Optional[Dict[str, Any]] = None) -> bool:
    """Show the execution approval card for ``command`` and return whether the person approved. Any failure to ask counts as a denial."""
    try:
        from api.services.agent_processing.tools.safety.execution_approval_service import ExecutionApprovalService
    except Exception as exc:
        logger.warning("ExecutionApprovalService unavailable; approval denied (%s)", exc)
        return False
    context = capture_runtime_context() if runtime_context is None else runtime_context
    approval_context: Dict[str, Any] = {"execution_type": APPROVAL_EXECUTION_TYPE, "require_explicit_approval": True, "purpose_source": "basil", **fields}
    if context.get("agent_task_id"):
        approval_context["agent_task_id"] = context["agent_task_id"]
    service = ExecutionApprovalService(websocket_manager=context.get("websocket_manager"))
    try:
        approved, _remember, _pattern_type = await service.request_approval(command, context=approval_context)
        return bool(approved)
    except Exception as exc:
        logger.warning("Approval flow raised; treating as denied: %s", exc)
        return False


def requirement_approver(server_name: str, runtime_context: Dict[str, Any]):
    """An approver for the preparer: one card per requirement install, which no remembered pattern or auto-approval can skip."""

    async def approve(requirement: MCPRequirement) -> bool:
        command = requirement_install_command(requirement) or ""
        block = "\n".join([f'install-local-server-requirement "{server_name}" "{requirement.name}"', f"command: {command}", f"reason: {requirement.reason}"])
        purpose = (
            f"Install {requirement.name} so the local server {server_name} can be set up. Basil will run: {command}. {requirement.reason} "
            "This changes software on your Mac and runs with your account's full access, so approve it only if you trust the command."
        )
        return await ask_user_approval(
            block,
            {
                "source": INSTALL_APPROVAL_SOURCE,
                "purpose": purpose,
                "description": "Installing software needs your explicit approval every time",
                "friendly_name": server_name,
            },
            runtime_context,
        )

    return approve


_background_tasks: set = set()


async def _start_when_prepared(connection_id: str) -> None:
    """When a preparation ends with everything in place, start the background program so any step that needs the person appears. Never raises."""
    try:
        status = await get_local_server_preparer().wait(connection_id)
        if status.phase == "ready" and get_companion_supervisor().snapshot(connection_id).status != "running":
            await get_companion_supervisor().start(connection_id)
    except CompanionError as exc:
        logger.info("Local server %s was prepared but its background program did not start: %s", connection_id, exc)
    except Exception:
        logger.exception("Starting local server %s after preparing it failed", connection_id)


def start_preparation(record: MCPConnectionRecord) -> None:
    """Begin preparing in the background, asking for each requirement install on its own card, then start the background program."""
    recipe = record.stdio.install if record.stdio is not None else None
    if recipe is None:
        return
    supervisor = get_companion_supervisor()
    get_local_server_preparer().start(record.id, recipe, supervisor.folders(record.id), approve_install=requirement_approver(record.friendly_name, capture_runtime_context()))
    if record.stdio is not None and record.stdio.companion is not None:
        follow_up = asyncio.create_task(_start_when_prepared(record.id))
        _background_tasks.add(follow_up)
        follow_up.add_done_callback(_background_tasks.discard)


def _next_step(setup: Optional[Dict[str, Any]], program: Optional[Dict[str, Any]]) -> str:
    if setup is not None and not setup["ready"]:
        phase = setup["phase"]
        if setup["active"]:
            return "Basil is still working on it. Check again shortly."
        if phase == "needs_requirement":
            return f"Setup is waiting on {setup['requirement']}. Tell the user to open Settings → Connections and choose Install or Prepare on this server, or to install it themselves."
        if phase == "failed":
            return "Setup failed. Read detail with the user, correct the recipe, and call register_local_server again with arguments.replace set to this connection_id."
        return "The files are not in place yet. Tell the user to open Settings → Connections and choose Prepare on this server."
    if program is not None:
        if program["needs_you"]:
            return program["needs_you"]
        if program["status"] == "needs_secrets":
            return "Tell the user to type the missing secret values in Settings → Connections."
        if program["status"] == "failed":
            return "The background program stopped. Read last_error and log_tail with the user, then correct the recipe or ask them to start it in Settings → Connections."
        if program["health_phase"] == "failed":
            return "The background program reports a problem. Read health_message with the user."
        if program["health_phase"] == "starting" or program["status"] == "starting":
            return "The background program is still starting. Check again shortly."
        if program["status"] == "stopped":
            return "The background program is not running. Tell the user to start it in Settings → Connections."
    return "Everything is in place. Confirm with action='describe_server' to read the tools."


def local_server_status(record: MCPConnectionRecord) -> Dict[str, Any]:
    """How a local server's setup and background program are doing, for the agent. The scan code itself is never included."""
    spec = record.stdio
    assert spec is not None
    supervisor = get_companion_supervisor()
    setup: Optional[Dict[str, Any]] = None
    recipe: Optional[MCPInstallRecipe] = spec.install
    if recipe is not None:
        from api.services.mcp_connectors.local_server_paths import connection_folders
        from api.services.mcp_connectors.local_server_prepare import artifact_is_ready

        folders = connection_folders(supervisor.state_dir, record.id)
        status = get_local_server_preparer().status(record.id, recipe, folders)
        artifacts = [{"name": artifact.name, "ready": artifact_is_ready(artifact, folders)} for artifact in recipe.artifacts]
        setup = {
            "phase": status.phase,
            "message": status.message,
            "active": status.active,
            "ready": all(item["ready"] for item in artifacts),
            "requirement": status.requirement,
            "can_install": status.can_install,
            "detail": status.detail,
            "artifacts": artifacts,
        }
    program: Optional[Dict[str, Any]] = None
    log_tail = ""
    if spec.companion is not None:
        snapshot = supervisor.snapshot(record.id)
        health = snapshot.health
        needs_you = ""
        if health is not None and health.phase == "needs_action":
            needs_you = "The user has to act in Settings → Connections" + (" and scan the code shown on this server's row with their phone." if health.action_kind == "qr" else ".") + (f" {health.message}" if health.message else "")
        program = {
            "status": snapshot.status,
            "last_error": snapshot.last_error,
            "restart_count": snapshot.restart_count,
            "health_phase": health.phase if health is not None else None,
            "health_message": health.message if health is not None else None,
            "needs_you": needs_you,
        }
        log_tail = supervisor.log_tail(record.id)[-MAX_STATUS_LOG_CHARS:]
    return {
        "ok": True,
        "result": {
            "connection_id": record.id,
            "service": record.friendly_name,
            "setup": setup,
            "program": program,
            "log_tail": log_tail,
            "next_step": _next_step(setup, program),
        },
    }


async def local_server_status_action(connection_id: Optional[str]) -> Dict[str, Any]:
    """The ``local_server_status`` action: find the local server by id and report on it."""
    from api.core.preferences.preferences_io import load_preferences

    from .envelopes import make_external_catalog_invalid_arguments

    if not connection_id:
        return make_external_catalog_invalid_arguments("local_server_status requires connection_id. Use action='list_servers' to find it.")
    for record in load_preferences().connections.mcp_connections:
        if record.id == connection_id and record.stdio is not None:
            return local_server_status(record)
    return make_external_catalog_invalid_arguments("That connection_id is not a local server that is set up. Use action='list_servers' to find the right one.")
