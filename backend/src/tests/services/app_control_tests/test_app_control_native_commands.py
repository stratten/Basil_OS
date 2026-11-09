"""The native command channel: a closed verb list, validated parameters, a request/response bridge, and a host-only result route."""

import asyncio
import json
import re
from pathlib import Path

import pytest

from api.services.app_control import native_command_bridge as bridge
from api.services.app_control.native_commands import SETTINGS_TABS, VERBS, NativeCommandError, validate_native_command

SWIFT_HANDLER = Path(__file__).resolve().parents[5] / "client/Sources/Services/WebSocket/WebSocketService+NativeCommand.swift"
SWIFT_SETTINGS_SHELL = Path(__file__).resolve().parents[5] / "web-components/SettingsWebComponents/src/app/SettingsShell.tsx"


def test_only_listed_verbs_with_listed_parameters_are_accepted():
    assert validate_native_command("open_settings", None) == ("open_settings", {})
    assert validate_native_command("open_settings", {"tab": "appearance"}) == ("open_settings", {"tab": "appearance"})
    for verb, params in [("rm", {}), ("open_settings", {"tab": "../../etc"}), ("open_settings", {"tab": 5}), ("open_settings", {"url": "x"})]:
        with pytest.raises(NativeCommandError):
            validate_native_command(verb, params)


def test_the_python_and_swift_verb_lists_and_tab_lists_agree():
    swift = SWIFT_HANDLER.read_text()
    assert set(VERBS) == set(re.findall(r'case "([a-z_]+)":', swift.split("// verbs:begin", 1)[1].split("// verbs:end", 1)[0]))
    swift_tabs = set(re.findall(r'"([a-z-]+)"', swift.split("// tabs:begin", 1)[1].split("// tabs:end", 1)[0]))
    assert swift_tabs == set(SETTINGS_TABS)
    shell_tabs = set(re.findall(r"\{ id: '([a-z-]+)', label: '[^']+', migrated: true", SWIFT_SETTINGS_SHELL.read_text()))
    assert shell_tabs == set(SETTINGS_TABS), "The Settings screen's tabs changed; update SETTINGS_TABS and the Mac app's list."


class _Connection:
    def __init__(self, on_send=None):
        self.sent = []
        self._on_send = on_send

    async def send_json(self, payload):
        self.sent.append(payload)
        if self._on_send:
            self._on_send(payload)


@pytest.fixture
def connections(monkeypatch):
    live = []
    monkeypatch.setattr(bridge, "active_connections", live)
    return live


@pytest.mark.asyncio
async def test_success_is_reported_only_after_the_app_says_so(connections):
    connections.append(_Connection(lambda payload: asyncio.get_running_loop().call_soon(bridge.deliver_native_command_result, {"request_id": payload["request_id"], "success": True})))
    result = await bridge.send_native_command("open_settings", {"tab": "models"})
    assert result == {"ok": True, "verb": "open_settings", "params": {"tab": "models"}}
    assert connections[0].sent[0]["event_type"] == "native_command" and connections[0].sent[0]["verb"] == "open_settings"
    assert bridge.pending_native_commands == {}


@pytest.mark.asyncio
async def test_a_refusal_from_the_app_is_reported_as_a_failure(connections):
    connections.append(_Connection(lambda payload: asyncio.get_running_loop().call_soon(bridge.deliver_native_command_result, {"request_id": payload["request_id"], "success": False, "error": "no window"})))
    result = await bridge.send_native_command("open_settings")
    assert result == {"ok": False, "error": "no window"}


@pytest.mark.asyncio
async def test_no_connection_a_failed_send_a_timeout_and_a_bad_verb_are_all_failures_and_leave_nothing_pending(connections):
    assert (await bridge.send_native_command("open_settings"))["ok"] is False
    connections.append(_Connection())
    timed_out = await bridge.send_native_command("open_settings", timeout=0.05)
    assert timed_out["ok"] is False and "not known" in timed_out["error"]
    assert (await bridge.send_native_command("shutdown"))["ok"] is False
    assert len(connections[0].sent) == 1  # the bad verb never reached the app
    assert bridge.pending_native_commands == {}


def test_a_result_for_an_unknown_or_finished_request_is_refused():
    assert bridge.deliver_native_command_result({"request_id": "nope", "success": True}) is False
    assert bridge.deliver_native_command_result({"success": True}) is False


@pytest.mark.asyncio
async def test_the_tool_opens_settings_through_the_bridge_and_names_the_tab(monkeypatch):
    from api.services.agent_processing.tools.internal_basil_tools import app_settings_tool

    calls = []

    async def fake_send(verb, params=None):
        calls.append((verb, params))
        return {"ok": True, "verb": verb, "params": params}

    monkeypatch.setattr(app_settings_tool, "send_native_command", fake_send)
    shown = json.loads(await app_settings_tool._app_settings_impl(action="show_in_settings", tab="appearance"))
    assert shown["ok"] and shown["tab_label"] == "Appearance & Format"
    await app_settings_tool._app_settings_impl(action="show_in_settings")
    assert calls == [("open_settings", {"tab": "appearance"}), ("open_settings", {})]


def test_the_result_route_requires_the_host_credential():
    from api.routes.app_control_routes import router
    from api.core.security.backend_request_guard import require_host_credential

    route = next(route for route in router.routes if route.path.endswith("/native-command/result"))
    assert any(dependency.dependency is require_host_credential for dependency in route.dependencies)


def test_the_overview_counts_every_entry_once_and_explains_the_limits(engine):
    from api.services.app_control.entries import get_default_registry

    overview = engine.overview()
    registry = get_default_registry()
    totals = sum(section["free"] + section["needs_approval"] + section["only_the_user"] for section in overview["settings_sections"])
    assert totals == len(registry.all())
    appearance = next(section for section in overview["settings_sections"] if section["section"] == "appearance")
    assert appearance["free"] >= 8 and appearance["needs_approval"] >= 1
    assert "open_settings" in overview["native_commands"]
    assert any("Schedules" in line for line in overview["other_abilities"])
    assert "credentials" in overview["only_the_user_can"]


def test_every_deferred_domain_has_a_plain_language_label():
    from api.services.app_control.overview import DOMAIN_LABELS
    from api.services.app_control.route_classification import DEFERRED_BASELINE, ROUTE_RULES

    assert set(DOMAIN_LABELS) >= set(DEFERRED_BASELINE)
    assert {rule.domain for rule in ROUTE_RULES if rule.disposition == "deferred"} <= set(DOMAIN_LABELS)


@pytest.mark.asyncio
async def test_the_tool_serves_the_overview(monkeypatch):
    from api.services.agent_processing.tools.internal_basil_tools import app_settings_tool

    result = json.loads(await app_settings_tool._app_settings_impl(action="overview"))
    assert result["ok"] and result["settings_sections"]
