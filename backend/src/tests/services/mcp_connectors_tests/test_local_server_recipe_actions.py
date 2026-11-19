"""The agent's recipe surface: the approval cards, preparing in the background, the status report, and replacing a server in place."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

from api.core.models.preferences import MCPConnectionRecord, Preferences
from api.core.preferences import preferences_io
from api.services.agent_processing.tools.external_services import external_catalog_tool
from api.services.agent_processing.tools.external_services.external_catalog import local_server_recipe_actions as actions
from api.services.agent_processing.tools.external_services.external_catalog.local_server_recipe_actions import local_server_status_action
from api.services.agent_processing.tools.external_services.external_catalog.local_server_register import (
    describe_local_server_approval,
    register_external_catalog_local_server as register,
)
from api.services.mcp_connectors.companion_probe import ProbeReading
from api.services.mcp_connectors.companion_supervisor import CompanionSnapshot, CompanionSupervisor, get_companion_supervisor, set_companion_supervisor
from api.services.mcp_connectors.local_server_commands import CommandResult
from api.services.mcp_connectors.local_server_prepare import LocalServerPreparer, set_local_server_preparer
from api.services.mcp_connectors.local_server_spec import build_local_server_spec

FIXTURE = str(Path(__file__).with_name("stdio_fixture_server.py"))
PROGRAM = (
    f"#!{sys.executable}\n"
    "import socket, sys, time\n"
    "s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
    "s.bind(('127.0.0.1', int(sys.argv[1]))); s.listen()\n"
    "while True: time.sleep(1)\n"
).encode()
PROGRAM_SHA = hashlib.sha256(PROGRAM).hexdigest()
URL = "https://example.test/releases/bridge"
EXIT_AT_ONCE = "raise SystemExit(3)\n"


class _RecordingApprovalService:
    instances: List["_RecordingApprovalService"] = []
    answers: List[bool] = []
    default = True

    def __init__(self, websocket_manager=None):
        self.requests: List[tuple] = []
        _RecordingApprovalService.instances.append(self)

    async def request_approval(self, command, context=None):
        self.requests.append((command, dict(context or {})))
        answer = _RecordingApprovalService.answers.pop(0) if _RecordingApprovalService.answers else _RecordingApprovalService.default
        return (answer, False, "exact")


class World:
    def __init__(self) -> None:
        self.installed = False
        self.commands: List[List[str]] = []

    async def run(self, argv, **kwargs: Any) -> CommandResult:
        self.commands.append(list(argv))
        if argv[0] == "xtool":
            return CommandResult(0 if self.installed else 127, "")
        if argv[0] == "xinstall":
            self.installed = True
        return CommandResult(0, "")

    async def download(self, url: str, destination: Path, **kwargs: Any) -> str:
        destination.write_bytes(PROGRAM)
        return PROGRAM_SHA


@pytest.fixture
def approvals(monkeypatch):
    _RecordingApprovalService.instances = []
    _RecordingApprovalService.answers = []
    _RecordingApprovalService.default = True
    monkeypatch.setattr("api.services.agent_processing.tools.safety.execution_approval_service.ExecutionApprovalService", _RecordingApprovalService)
    return _RecordingApprovalService


@pytest.fixture
def stored_preferences(monkeypatch) -> Dict[str, Preferences]:
    holder = {"value": Preferences()}
    monkeypatch.setattr(preferences_io, "load_preferences", lambda: holder["value"].model_copy(deep=True))
    monkeypatch.setattr(preferences_io, "save_preferences", lambda prefs: holder.__setitem__("value", prefs.model_copy(deep=True)))
    return holder


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def supervisor(tmp_path, world) -> Iterator[CompanionSupervisor]:
    instance = CompanionSupervisor(tmp_path / "local_servers", ready_timeout_seconds=15.0, no_port_grace_seconds=0.3, stop_grace_seconds=3.0)
    set_companion_supervisor(instance)
    set_local_server_preparer(LocalServerPreparer(run=world.run, download=world.download))
    yield instance
    set_local_server_preparer(None)
    set_companion_supervisor(None)


def _recipe() -> Dict[str, Any]:
    return {
        "requirements": [{"name": "Xtool", "reason": "The bridge needs it.", "check": ["xtool"], "install": ["xinstall", "xtool"], "for_method": "any"}],
        "artifacts": [{"name": "Bridge", "expects": "bin/bridge", "methods": [{"kind": "download", "url": URL, "sha256": PROGRAM_SHA}]}],
    }


def _arguments(**overrides: Any) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {
        "command": sys.executable,
        "args": [FIXTURE],
        "companion": {"command": "{install_dir}/bin/bridge", "args": ["{port}"]},
        "install": _recipe(),
    }
    arguments.update(overrides)
    return arguments


def _stored(holder: Dict[str, Preferences]) -> List[MCPConnectionRecord]:
    return holder["value"].connections.mcp_connections


def _requests(approvals) -> List[tuple]:
    return [request for instance in approvals.instances for request in instance.requests]


async def _eventually(predicate, timeout: float = 15.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the condition never became true")


@pytest.mark.asyncio
async def test_the_card_lists_every_address_hash_command_and_install_the_recipe_will_use(approvals, stored_preferences, supervisor):
    arguments = _arguments(
        install={
            **_recipe(),
            "artifacts": [
                {
                    "name": "Bridge",
                    "expects": "bin/bridge",
                    "methods": [
                        {"kind": "download", "url": URL, "sha256": PROGRAM_SHA},
                        {"kind": "build", "git_url": "https://example.test/org/bridge.git", "commit": "a" * 40, "steps": [{"argv": ["make", "{install_dir}/bin/bridge"], "cwd": "cmd"}]},
                    ],
                }
            ],
        },
        companion={
            "command": "{install_dir}/bin/bridge",
            "args": ["{port}"],
            "probe": {"url": "http://127.0.0.1:{port}/status", "auth": "none", "state_path": "state", "states": {"ok": "ready"}, "action_kind": "qr", "action_path": "qr"},
        },
    )

    await register(arguments, "Bridge")

    command, context = _requests(approvals)[0]
    purpose = context["purpose"]
    for fragment in (URL, PROGRAM_SHA, "https://example.test/org/bridge.git", "a" * 40, "make '{install_dir}/bin/bridge' in cmd", "xtool", "xinstall xtool", "your separate approval", "http://127.0.0.1:{port}/status", "never saved", "does not match"):
        assert fragment in purpose, fragment
    for fragment in (f"requirement: Xtool: check xtool; install xinstall xtool", f"option 1: Download {URL}", "option 2: Build from https://example.test/org/bridge.git at commit " + "a" * 40, "status page: http://127.0.0.1:{port}/status"):
        assert fragment in command, fragment
    assert context["require_explicit_approval"] is True


@pytest.mark.asyncio
async def test_a_recipe_that_is_not_ready_is_saved_prepared_in_the_background_and_asks_for_each_install(approvals, stored_preferences, supervisor, world):
    result = await register(_arguments(), "Bridge")

    assert result["ok"] is True and result["result"]["status"] == "preparing", result
    connection_id = result["result"]["connection_id"]
    assert "local_server_status" in result["result"]["message"]
    assert len(_stored(stored_preferences)) == 1

    await _eventually(lambda: any(source == actions.INSTALL_APPROVAL_SOURCE for source in (context["source"] for _command, context in _requests(approvals))))
    await _eventually(lambda: get_companion_supervisor().snapshot(connection_id).running)

    install_command, install_context = next(request for request in _requests(approvals) if request[1]["source"] == actions.INSTALL_APPROVAL_SOURCE)
    assert install_command.startswith('install-local-server-requirement "Bridge" "Xtool"') and "command: xinstall xtool" in install_command
    assert install_context["require_explicit_approval"] is True and install_context["execution_type"] == "mcp_connection_setup"
    assert ["xinstall", "xtool"] in world.commands
    report = (await local_server_status_action(connection_id))["result"]
    assert report["setup"]["ready"] is True and report["program"]["status"] == "running"
    assert "describe_server" in report["next_step"]


@pytest.mark.asyncio
async def test_a_denied_install_leaves_the_server_waiting_and_runs_nothing(approvals, stored_preferences, supervisor, world):
    approvals.answers = [True, False]

    result = await register(_arguments(), "Bridge")
    connection_id = result["result"]["connection_id"]
    await _eventually(lambda: _setup(connection_id)["phase"] == "needs_requirement")

    report = (await local_server_status_action(connection_id))["result"]
    assert report["setup"]["requirement"] == "Xtool" and "not approved" in report["setup"]["message"]
    assert ["xinstall", "xtool"] not in world.commands
    assert "Settings → Connections" in report["next_step"]
    assert not supervisor.snapshot(connection_id).running


def _setup(connection_id: str):
    record = next(item for item in _read_records() if item.id == connection_id)
    from api.services.mcp_connectors.local_server_paths import connection_folders
    from api.services.mcp_connectors.local_server_prepare import get_local_server_preparer

    status = get_local_server_preparer().status(connection_id, record.stdio.install, connection_folders(get_companion_supervisor().state_dir, connection_id))
    return {"phase": status.phase}


def _read_records() -> List[MCPConnectionRecord]:
    return preferences_io.load_preferences().connections.mcp_connections


@pytest.mark.asyncio
async def test_the_status_report_never_contains_the_scan_code_and_tells_the_agent_what_the_user_must_do(approvals, stored_preferences, supervisor, monkeypatch):
    registered = await register({"command": sys.executable, "args": [FIXTURE], "companion": {"command": sys.executable, "args": ["-c", "import time; time.sleep(30)"]}}, "Plain")
    connection_id = registered["result"]["connection_id"]
    waiting = CompanionSnapshot(status="running", port=1234, health=ProbeReading(phase="needs_action", message="Scan the code.", action_kind="qr", action_value="SECRET-QR-VALUE"))
    monkeypatch.setattr(supervisor, "snapshot", lambda _id: waiting)

    report = await local_server_status_action(connection_id)

    text = json.dumps(report)
    assert "SECRET-QR-VALUE" not in text
    result = report["result"]
    assert result["program"]["health_phase"] == "needs_action"
    assert "scan the code shown on this server's row" in result["next_step"] and "Scan the code." in result["next_step"]
    assert result["setup"] is None
    await supervisor.stop_all()


@pytest.mark.asyncio
async def test_the_status_action_reports_an_unknown_or_missing_connection_plainly(approvals, stored_preferences, supervisor):
    for connection_id in (None, "", "no-such-connection"):
        result = await local_server_status_action(connection_id)

        assert result["ok"] is False and result["error"]["kind"] == "invalid_arguments", connection_id


@pytest.mark.asyncio
async def test_replacing_a_server_rewrites_it_in_place_and_the_card_says_what_it_replaces(approvals, stored_preferences, supervisor):
    first = await register({"command": sys.executable, "args": [FIXTURE]}, "Original")
    connection_id = first["result"]["connection_id"]
    before = _stored(stored_preferences)[0]
    approvals.instances = []

    second = await register({"command": sys.executable, "args": [FIXTURE, "plain"], "replace": connection_id}, "Corrected", "New note")

    assert second["ok"] is True and second["result"]["status"] == "connected" and second["result"]["connection_id"] == connection_id, second
    stored = _stored(stored_preferences)
    assert len(stored) == 1 and stored[0].id == connection_id
    assert stored[0].friendly_name == "Corrected" and stored[0].description == "New note"
    assert stored[0].stdio.args == [FIXTURE, "plain"] and stored[0].registered_at == before.registered_at
    purpose = _requests(approvals)[0][1]["purpose"]
    assert purpose.startswith("This replaces the existing server Original") and "saved secret values are kept" in purpose
    assert "(replaces Original)" in _requests(approvals)[0][0]


@pytest.mark.asyncio
async def test_replacing_with_the_same_definition_is_allowed_but_adding_it_again_is_not(approvals, stored_preferences, supervisor):
    first = await register({"command": sys.executable, "args": [FIXTURE]}, "Original")
    connection_id = first["result"]["connection_id"]

    again = await register({"command": sys.executable, "args": [FIXTURE]}, "Copy")
    replaced = await register({"command": sys.executable, "args": [FIXTURE], "replace": connection_id}, "Same")

    assert again["result"]["status"] == "already_connected"
    assert replaced["result"]["status"] == "connected" and len(_stored(stored_preferences)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("replace", ["not-a-real-id", "", 5])
async def test_replacing_something_that_does_not_exist_is_refused_before_the_user_is_asked(replace, approvals, stored_preferences, supervisor):
    result = await register({"command": sys.executable, "args": [FIXTURE], "replace": replace}, "Name")

    assert result["ok"] is False and result["error"]["kind"] == "invalid_arguments"
    assert _requests(approvals) == [] and _stored(stored_preferences) == []


@pytest.mark.asyncio
async def test_a_replaced_server_that_does_not_start_is_kept_so_it_can_be_corrected_again(approvals, stored_preferences, supervisor):
    first = await register({"command": sys.executable, "args": [FIXTURE]}, "Original")
    connection_id = first["result"]["connection_id"]

    broken = await register(
        {"command": sys.executable, "args": [FIXTURE], "companion": {"command": sys.executable, "args": ["-c", EXIT_AT_ONCE, "{port}"]}, "replace": connection_id},
        "Original",
    )

    assert broken["ok"] is False and "was updated but did not start" in broken["error"]["message"]
    assert "arguments.replace" in broken["error"]["user_action_required"]
    stored = _stored(stored_preferences)
    assert len(stored) == 1 and stored[0].id == connection_id and stored[0].stdio.companion is not None


@pytest.mark.asyncio
async def test_a_recipe_the_backend_refuses_is_reported_before_the_user_is_asked_and_the_usage_teaches_the_format(approvals, stored_preferences, supervisor):
    bad = _recipe()
    bad["artifacts"][0]["methods"][0]["url"] = "http://plain.test/x"

    refused = await register(_arguments(install=bad), "Bridge")
    empty = await register({}, "Bridge")

    assert refused["ok"] is False and "https" in refused["error"]["message"]
    assert _requests(approvals) == [] and _stored(stored_preferences) == []
    usage = empty["error"]["message"]
    for fragment in ("arguments.install is a recipe", "sha256", "40-character", "{install_dir}", "{run_secret}", "companion.probe", "arguments.replace"):
        assert fragment in usage, fragment


@pytest.mark.asyncio
async def test_the_catalog_tool_dispatches_the_status_action_and_the_schema_teaches_it(monkeypatch):
    seen: Dict[str, Any] = {}

    async def fake(connection_id):
        seen["connection_id"] = connection_id
        return {"ok": True, "result": {"next_step": "ok"}}

    monkeypatch.setattr(external_catalog_tool, "_local_server_status", fake)
    raw = await external_catalog_tool._external_catalog_impl(action="local_server_status", connection_id="abc")

    assert json.loads(raw)["result"]["next_step"] == "ok" and seen == {"connection_id": "abc"}
    properties = external_catalog_tool.ExternalCatalogInput.model_json_schema()["properties"]
    assert "local_server_status" in properties["action"]["enum"] and "local_server_status" in properties["action"]["description"]
    assert "install" in properties["arguments"]["description"] and "replace" in properties["arguments"]["description"]


def test_the_card_for_a_replacement_names_the_old_command_and_a_plain_card_has_no_recipe_text():
    spec = build_local_server_spec(command=sys.executable, args=[FIXTURE], cwd=None, env={})
    old = MCPConnectionRecord(friendly_name="Old", server_url="basil-stdio://x", stdio=build_local_server_spec(command=sys.executable, args=[FIXTURE, "old"], cwd=None, env={}))

    plain = describe_local_server_approval("New", spec)
    replacing = describe_local_server_approval("New", spec, old)

    assert "replaces" not in plain and "separate approval" not in plain and "SHA-256" not in plain
    assert replacing.startswith("This replaces the existing server Old, which currently runs") and "old" in replacing


def test_a_long_basil_written_card_reaches_the_user_whole_while_an_agent_written_one_is_still_capped():
    from api.services.agent_processing.tools.safety.approval_presentation import approval_presentation_fields

    long_text = "x" * 5000 + " the-last-address"

    basil = approval_presentation_fields("cmd", "cmd", {"purpose": long_text, "purpose_source": "basil"})
    agent = approval_presentation_fields("cmd", "cmd", {"purpose": long_text})

    assert basil["purpose"].endswith("the-last-address")
    assert len(agent["purpose"]) == 1000
