"""The local-server spec: placeholders, secret names, background-program rules, and what registration stores."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest

from api.core.models.preferences import MCPConnectionRecord, MCPStdioSpec, Preferences
from api.core.preferences import preferences_io
from api.services.mcp_connectors.local_server_placeholders import (
    PlaceholderError,
    contains_path_placeholder,
    contains_port_placeholder,
    contains_run_secret_placeholder,
    substitute_placeholders,
    substitute_port,
)
from api.services.mcp_connectors.local_server_registration import (
    DuplicateLocalServerError,
    find_existing_local_server,
    register_local_server_record,
)
from api.services.mcp_connectors.local_server_spec import build_local_server_spec
from api.services.mcp_connectors.stdio_transport import StdioSpecError, build_parameters

FIXTURE = str(Path(__file__).with_name("stdio_fixture_server.py"))
BACKGROUND: Dict[str, Any] = {"command": sys.executable, "args": ["-c", "import time; time.sleep(60)"]}


@pytest.fixture
def stored_preferences(monkeypatch) -> Dict[str, Preferences]:
    holder = {"value": Preferences()}
    monkeypatch.setattr(preferences_io, "load_preferences", lambda: holder["value"].model_copy(deep=True))
    monkeypatch.setattr(preferences_io, "save_preferences", lambda prefs: holder.__setitem__("value", prefs.model_copy(deep=True)))
    return holder


def _spec(**overrides: Any) -> MCPStdioSpec:
    fields: Dict[str, Any] = {"command": sys.executable, "args": [FIXTURE], "cwd": None, "env": {}}
    fields.update(overrides)
    return build_local_server_spec(**fields)


def test_substitute_port_replaces_every_occurrence_and_leaves_other_text_alone():
    assert substitute_port("--port={port} --also={port}", 4321) == "--port=4321 --also=4321"
    assert substitute_port("no placeholder", None) == "no placeholder"


def test_substitute_port_without_a_port_says_the_background_program_is_not_running():
    with pytest.raises(PlaceholderError, match="not running"):
        substitute_port("--port={port}", None)


def test_placeholder_detection_helpers():
    assert contains_port_placeholder(["a", "b={port}"]) is True
    assert contains_port_placeholder(["a", "b"]) is False
    assert contains_run_secret_placeholder(["x", "--token={run_secret}"]) is True
    assert contains_run_secret_placeholder(["x"]) is False
    assert contains_path_placeholder(["{install_dir}/bin/x"]) is True
    assert contains_path_placeholder(["--data={data_dir}"]) is True
    assert contains_path_placeholder(["plain"]) is False


def test_substitute_placeholders_fills_all_four_and_names_the_one_with_nothing_to_fill_it():
    value = "{install_dir}/bin --port={port} --token={run_secret} --store={data_dir}"

    assert substitute_placeholders(value, port=9, run_secret="tok", data_dir="/d", install_dir="/i") == "/i/bin --port=9 --token=tok --store=/d"
    for missing, message in (("port", "port"), ("run_secret", "token"), ("data_dir", "data folder"), ("install_dir", "install folder")):
        values = {"port": 9, "run_secret": "tok", "data_dir": "/d", "install_dir": "/i"}
        del values[missing]
        with pytest.raises(PlaceholderError, match=message):
            substitute_placeholders(value, **values)


def test_build_parameters_fills_the_port_in_arguments_and_environment_and_adds_secrets_last():
    spec = MCPStdioSpec(command=sys.executable, args=[FIXTURE, "--port={port}"], env={"BRIDGE_URL": "http://127.0.0.1:{port}", "SAME": "plain"})

    parameters = build_parameters(spec, port=4321, extra_env={"SAME": "secret", "TOKEN": "abc"})

    assert parameters.args == [FIXTURE, "--port=4321"]
    assert parameters.env["BRIDGE_URL"] == "http://127.0.0.1:4321"
    assert parameters.env["SAME"] == "secret"
    assert parameters.env["TOKEN"] == "abc"


def test_build_parameters_refuses_a_port_placeholder_when_no_port_is_known():
    spec = MCPStdioSpec(command=sys.executable, args=["--port={port}"])

    with pytest.raises(StdioSpecError, match="not running"):
        build_parameters(spec)


def test_a_valid_spec_keeps_secret_names_and_defaults_the_companion_to_none():
    spec = _spec(secret_env=[" API_KEY ", "OTHER_TOKEN"])

    assert spec.secret_env == ["API_KEY", "OTHER_TOKEN"]
    assert spec.companion is None


@pytest.mark.parametrize("bad", [["1BAD"], ["A=B"], [""], ["has space"], ["x" * 65], ["A", "A"], [5], "TOKEN", {"A": "b"}])
def test_invalid_secret_names_are_refused(bad):
    with pytest.raises(StdioSpecError):
        _spec(secret_env=bad)


def test_more_than_sixteen_secrets_are_refused():
    with pytest.raises(StdioSpecError, match="at most 16"):
        _spec(secret_env=[f"SECRET_{index}" for index in range(17)])


def test_a_name_cannot_be_both_a_plain_variable_and_a_secret():
    with pytest.raises(StdioSpecError, match="both as a plain environment variable and as a secret"):
        _spec(env={"TOKEN": "x"}, secret_env=["TOKEN"])


@pytest.mark.parametrize(
    "overrides",
    [
        {"args": [FIXTURE, "--token={run_secret}"]},
        {"env": {"TOKEN": "{run_secret}"}},
    ],
)
def test_the_run_secret_placeholder_needs_a_background_program_to_share_it_with(overrides):
    with pytest.raises(StdioSpecError, match="no background program"):
        _spec(**overrides)


def test_the_run_secret_placeholder_is_accepted_when_a_background_program_is_given_it():
    spec = _spec(env={"TOKEN": "{run_secret}"}, companion={**BACKGROUND, "env": {"TOKEN": "{run_secret}"}})

    assert spec.env == {"TOKEN": "{run_secret}"}
    assert spec.companion is not None and spec.companion.env == {"TOKEN": "{run_secret}"}


def test_the_folder_placeholders_do_not_need_the_files_to_exist_yet():
    spec = _spec(command="{install_dir}/bin/not-yet-built", args=["--store={data_dir}"], cwd="{install_dir}")

    assert spec.command == "{install_dir}/bin/not-yet-built"


def test_build_parameters_fills_the_run_secret_and_folders():
    spec = MCPStdioSpec(command=sys.executable, args=[FIXTURE, "--store={data_dir}"], env={"TOKEN": "{run_secret}"})

    parameters = build_parameters(spec, run_secret="abc123", data_dir="/some/data")

    assert parameters.args == [FIXTURE, "--store=/some/data"]
    assert parameters.env["TOKEN"] == "abc123"


def test_port_placeholder_needs_a_companion_that_is_also_given_the_port():
    with pytest.raises(StdioSpecError, match="no background program"):
        _spec(args=[FIXTURE, "--port={port}"])
    with pytest.raises(StdioSpecError, match="no background program"):
        _spec(args=[FIXTURE, "--port={port}"], companion=BACKGROUND)

    spec = _spec(args=[FIXTURE, "--port={port}"], companion={**BACKGROUND, "args": ["-c", "pass", "{port}"]})
    assert spec.companion is not None


def test_a_fixed_port_and_the_port_placeholder_are_mutually_exclusive():
    with pytest.raises(StdioSpecError, match="either fixed_port"):
        _spec(companion={**BACKGROUND, "args": ["-c", "pass", "{port}"], "fixed_port": 8080})


@pytest.mark.parametrize("port", [0, 65536, -1, True, "80", 80.5])
def test_a_bad_fixed_port_is_refused(port):
    with pytest.raises(StdioSpecError, match="fixed_port"):
        _spec(companion={**BACKGROUND, "fixed_port": port})


def test_a_companion_with_unknown_keys_or_the_wrong_shape_is_refused():
    with pytest.raises(StdioSpecError, match="does not take shell"):
        _spec(companion={**BACKGROUND, "shell": "rm -rf /"})
    with pytest.raises(StdioSpecError, match="must be an object"):
        _spec(companion="go run .")
    with pytest.raises(StdioSpecError, match="start_with_basil"):
        _spec(companion={**BACKGROUND, "start_with_basil": "yes"})
    with pytest.raises(StdioSpecError, match="needs a command"):
        _spec(companion={"args": ["x"]})


def test_a_companion_whose_program_does_not_exist_is_refused():
    with pytest.raises(StdioSpecError, match="could not find a program"):
        _spec(companion={"command": "definitely-not-a-real-program-xyz"})


def test_a_valid_companion_defaults_to_starting_with_basil_and_keeps_its_secret_names():
    spec = _spec(companion={**BACKGROUND, "secret_env": ["BRIDGE_TOKEN"], "env": {"MODE": "x"}})

    assert spec.companion is not None
    assert spec.companion.start_with_basil is True
    assert spec.companion.secret_env == ["BRIDGE_TOKEN"]
    assert spec.companion.fixed_port is None


def test_a_companion_secret_cannot_clash_with_its_own_plain_environment():
    with pytest.raises(StdioSpecError, match="both as a plain environment variable and as a secret"):
        _spec(companion={**BACKGROUND, "env": {"BRIDGE_TOKEN": "x"}, "secret_env": ["BRIDGE_TOKEN"]})


def test_a_record_round_trips_and_an_older_record_loads_with_empty_defaults():
    spec = _spec(secret_env=["API_KEY"], companion={**BACKGROUND, "secret_env": ["BRIDGE_TOKEN"], "fixed_port": 9000})
    record = MCPConnectionRecord(friendly_name="X", server_url="basil-stdio://x", stdio=spec)

    restored = MCPConnectionRecord.model_validate(record.model_dump())
    assert restored.stdio is not None and restored.stdio.companion is not None
    assert restored.stdio.secret_env == ["API_KEY"]
    assert restored.stdio.companion.fixed_port == 9000

    legacy = MCPStdioSpec.model_validate({"command": "uv", "args": ["run"], "cwd": None, "env": {}, "source_url": None})
    assert legacy.secret_env == [] and legacy.companion is None


def test_registration_stores_the_companion_and_secret_names(stored_preferences):
    record = register_local_server_record(
        friendly_name="Bridge",
        command=sys.executable,
        args=[FIXTURE],
        secret_env=["API_KEY"],
        companion={**BACKGROUND, "start_with_basil": False},
    )

    stored = stored_preferences["value"].connections.mcp_connections[0]
    assert stored.id == record.id
    assert stored.stdio is not None and stored.stdio.secret_env == ["API_KEY"]
    assert stored.stdio.companion is not None and stored.stdio.companion.start_with_basil is False


def test_registration_honors_a_caller_chosen_id_and_refuses_a_bad_or_used_one(stored_preferences):
    chosen = str(uuid.uuid4())

    record = register_local_server_record(friendly_name="One", command=sys.executable, args=[FIXTURE], connection_id=chosen)
    assert record.id == chosen
    assert record.server_url == f"basil-stdio://{chosen}"

    with pytest.raises(StdioSpecError, match="not valid"):
        register_local_server_record(friendly_name="Two", command=sys.executable, args=[FIXTURE, "a"], connection_id="not-a-uuid")
    with pytest.raises(StdioSpecError, match="already in use"):
        register_local_server_record(friendly_name="Three", command=sys.executable, args=[FIXTURE, "b"], connection_id=chosen)
    assert len(stored_preferences["value"].connections.mcp_connections) == 1


def test_find_existing_local_server_matches_on_command_arguments_and_folder(stored_preferences):
    record = register_local_server_record(friendly_name="One", command=sys.executable, args=[FIXTURE])

    assert find_existing_local_server(_spec()) is not None
    assert find_existing_local_server(_spec()).id == record.id  # type: ignore[union-attr]
    assert find_existing_local_server(_spec(args=[FIXTURE, "different"])) is None
    with pytest.raises(DuplicateLocalServerError):
        register_local_server_record(friendly_name="Again", command=sys.executable, args=[FIXTURE])


def test_nothing_is_stored_when_the_companion_is_invalid(stored_preferences):
    with pytest.raises(StdioSpecError):
        register_local_server_record(friendly_name="Bad", command=sys.executable, args=[FIXTURE], companion={"command": "definitely-not-a-real-program-xyz"})

    assert stored_preferences["value"].connections.mcp_connections == []
