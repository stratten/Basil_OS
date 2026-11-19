"""Preparing a local server: requirements, download or build, verification, resuming, and the gates in front of launch."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import stat
import sys
import tarfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

from api.core.models.preferences import MCPRequirement, Preferences
from api.core.preferences import preferences_io
from api.services.mcp_connectors import local_server_prepare
from api.services.mcp_connectors.companion_supervisor import CompanionSupervisor, set_companion_supervisor
from api.services.mcp_connectors.local_server_commands import CommandResult
from api.services.mcp_connectors.local_server_download import DownloadError
from api.services.mcp_connectors.local_server_launch import prepare_stdio_launch
from api.services.mcp_connectors.local_server_paths import ensure_connection_folders
from api.services.mcp_connectors.local_server_prepare import (
    NOT_PREPARED_MESSAGE,
    LocalServerPreparer,
    PrepareError,
    artifacts_ready,
)
from api.services.mcp_connectors.local_server_recipe import build_install_recipe
from api.services.mcp_connectors.local_server_registration import register_local_server_record

CONNECTION_ID = "0b2f3c9e-1d44-4e0a-9a53-5f1d2c7b8a10"
COMMIT = "a" * 40
BODY = b"#!/bin/sh\necho approved\n"
BODY_SHA = hashlib.sha256(BODY).hexdigest()
URL = "https://example.test/releases/tool"
REPO = "https://example.test/org/tool.git"


def _download_method(sha: str = BODY_SHA, **extra: Any) -> Dict[str, Any]:
    return {"kind": "download", "url": URL, "sha256": sha, **extra}


def _build_method(steps: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {"kind": "build", "git_url": REPO, "commit": COMMIT, "steps": steps if steps is not None else [{"argv": ["make", "{install_dir}/bin/tool"]}]}


def _recipe(methods: List[Dict[str, Any]], *, requirements: Optional[List[Dict[str, Any]]] = None, expects: str = "bin/tool"):
    return build_install_recipe({"requirements": requirements or [], "artifacts": [{"name": "Tool", "expects": expects, "methods": methods}]})


GO = {"name": "Go", "reason": "Needed to build.", "check": ["go", "version"], "install": ["brew", "install", "go"], "for_method": "build"}


class Fakes:
    """A scripted command runner and downloader that record what they were asked to do."""

    def __init__(self, tmp_path: Path) -> None:
        self.folders = ensure_connection_folders(tmp_path / "state", CONNECTION_ID)
        self.commands: List[Tuple[List[str], Dict[str, Any]]] = []
        self.downloads: List[str] = []
        self.met: Dict[str, bool] = {"go": False, "git": True}
        self.install_exit = 0
        self.build_exit = 0
        self.head = COMMIT
        self.download_body: Optional[bytes] = BODY
        self.download_error: Optional[Exception] = None
        self.hold: Optional[asyncio.Event] = None

    async def run(self, argv, **kwargs: Any) -> CommandResult:
        self.commands.append((list(argv), kwargs))
        program = argv[0]
        if program == "go":
            return CommandResult(0 if self.met["go"] else 127, "")
        if program == "git" and argv[1:2] == ["--version"]:
            return CommandResult(0 if self.met["git"] else 127, "")
        if program == "git" and "rev-parse" in argv:
            return CommandResult(0, self.head)
        if program == "brew":
            if self.install_exit == 0:
                self.met["go"] = True
            return CommandResult(self.install_exit, "installer output")
        if program == "make":
            if self.build_exit != 0:
                return CommandResult(self.build_exit, "compile error on line 3")
            target = Path(argv[1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(BODY)
            return CommandResult(0, "")
        return CommandResult(0, "")

    async def download(self, url: str, destination: Path, **kwargs: Any) -> str:
        self.downloads.append(url)
        if self.hold is not None:
            await self.hold.wait()
        if self.download_error is not None:
            raise self.download_error
        assert self.download_body is not None
        destination.write_bytes(self.download_body)
        return hashlib.sha256(self.download_body).hexdigest()

    def preparer(self) -> LocalServerPreparer:
        return LocalServerPreparer(run=self.run, download=self.download)

    def ran(self, program: str) -> List[List[str]]:
        return [argv for argv, _ in self.commands if argv[0] == program]


@pytest.fixture
def fakes(tmp_path) -> Fakes:
    return Fakes(tmp_path)


@pytest.mark.asyncio
async def test_a_download_is_verified_placed_executable_and_recorded(fakes):
    recipe = _recipe([_download_method()])

    status = await fakes.preparer().prepare(CONNECTION_ID, recipe, fakes.folders)

    target = fakes.folders.install / "bin" / "tool"
    assert status.phase == "ready"
    assert target.read_bytes() == BODY and stat.S_IMODE(target.stat().st_mode) == 0o700
    assert artifacts_ready(recipe, fakes.folders)
    record = fakes.folders.install.parent / "prepared.json"
    assert stat.S_IMODE(record.stat().st_mode) == 0o600 and "Tool" in json.loads(record.read_text())["done"]
    assert not (fakes.folders.install / ".partial" / "x").exists()
    assert fakes.commands == []


@pytest.mark.asyncio
async def test_a_second_run_skips_what_is_already_in_place_and_repairs_what_was_tampered_with(fakes):
    recipe = _recipe([_download_method()])
    preparer = fakes.preparer()
    await preparer.prepare(CONNECTION_ID, recipe, fakes.folders)
    await preparer.prepare(CONNECTION_ID, recipe, fakes.folders)
    assert len(fakes.downloads) == 1

    (fakes.folders.install / "bin" / "tool").write_bytes(b"tampered")
    assert not artifacts_ready(recipe, fakes.folders)
    await preparer.prepare(CONNECTION_ID, recipe, fakes.folders)

    assert len(fakes.downloads) == 2 and (fakes.folders.install / "bin" / "tool").read_bytes() == BODY


@pytest.mark.asyncio
async def test_a_changed_recipe_is_prepared_again(fakes):
    preparer = fakes.preparer()
    await preparer.prepare(CONNECTION_ID, _recipe([_download_method()]), fakes.folders)
    changed = _recipe([{"kind": "download", "url": URL + "-v2", "sha256": BODY_SHA}])

    assert not artifacts_ready(changed, fakes.folders)
    await preparer.prepare(CONNECTION_ID, changed, fakes.folders)

    assert fakes.downloads == [URL, URL + "-v2"]


@pytest.mark.asyncio
async def test_a_hash_that_does_not_match_is_final_and_does_not_fall_back_to_a_build(fakes):
    recipe = _recipe([_download_method(sha="b" * 64), _build_method()])

    status = await fakes.preparer().prepare(CONNECTION_ID, recipe, fakes.folders)

    assert status.phase == "failed" and "not the one you approved" in status.message
    assert BODY_SHA in status.message and "b" * 64 in status.message
    assert not (fakes.folders.install / "bin" / "tool").exists()
    assert fakes.commands == []
    assert not list((fakes.folders.install / ".partial").glob("*"))


@pytest.mark.asyncio
async def test_a_download_that_cannot_be_fetched_falls_back_to_the_next_method(fakes):
    fakes.download_error = DownloadError("The download failed: the server answered 404.")
    recipe = _recipe([_download_method(), _build_method()], requirements=[GO])
    fakes.met["go"] = True

    status = await fakes.preparer().prepare(CONNECTION_ID, recipe, fakes.folders)

    assert status.phase == "ready"
    assert (fakes.folders.install / "bin" / "tool").read_bytes() == BODY
    assert any("fetch" in argv for argv in fakes.ran("git"))
    assert not (fakes.folders.install / ".build").exists()


@pytest.mark.asyncio
async def test_every_method_failing_reports_each_reason(fakes):
    fakes.download_error = DownloadError("The download failed: the server answered 404.")
    fakes.build_exit = 2
    recipe = _recipe([_download_method(), _build_method()], requirements=[GO])
    fakes.met["go"] = True

    status = await fakes.preparer().prepare(CONNECTION_ID, recipe, fakes.folders)

    assert status.phase == "failed" and status.artifact == "Tool"
    assert "answered 404" in (status.detail or "") and "compile error on line 3" in (status.detail or "")
    assert not (fakes.folders.install / ".build").exists()


@pytest.mark.asyncio
async def test_a_build_uses_the_pinned_commit_and_refuses_a_different_one(fakes):
    recipe = _recipe([_build_method()])
    preparer = fakes.preparer()

    status = await preparer.prepare(CONNECTION_ID, recipe, fakes.folders)
    assert status.phase == "ready"
    fetches = [argv for argv in fakes.ran("git") if "fetch" in argv]
    assert fetches and fetches[0][-2:] == [REPO, COMMIT] and "protocol.allow=never" in fetches[0]
    assert all(kwargs.get("extra_env") == {"GIT_TERMINAL_PROMPT": "0"} for argv, kwargs in fakes.commands if argv[0] == "git" and "--version" not in argv)

    fakes.head = "c" * 40
    second = ensure_connection_folders(fakes.folders.install.parents[2], CONNECTION_ID + "-2")
    refused = await preparer.prepare(CONNECTION_ID + "-2", recipe, second)
    assert refused.phase == "failed" and "not the commit you approved" in refused.message


@pytest.mark.asyncio
async def test_a_build_step_that_produces_nothing_is_a_failure(fakes):
    recipe = _recipe([_build_method(steps=[{"argv": ["true"]}])])

    status = await fakes.preparer().prepare(CONNECTION_ID, recipe, fakes.folders)

    assert status.phase == "failed" and "did not produce bin/tool" in (status.detail or "")


@pytest.mark.asyncio
async def test_a_build_step_folder_cannot_leave_the_source(fakes, tmp_path):
    recipe = _recipe([_build_method(steps=[{"argv": ["true"], "cwd": "missing"}])])

    status = await fakes.preparer().prepare(CONNECTION_ID, recipe, fakes.folders)

    assert status.phase == "failed" and "not inside the source" in (status.detail or "")


@pytest.mark.asyncio
async def test_an_archive_download_is_unpacked_into_the_folder_of_the_expected_file(fakes):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo("release-1/tool")
        info.size = len(BODY)
        info.mode = 0o755
        bundle.addfile(info, io.BytesIO(BODY))
    fakes.download_body = buffer.getvalue()
    sha = hashlib.sha256(fakes.download_body).hexdigest()
    recipe = _recipe([_download_method(sha=sha, archive="tar.gz", strip_components=1)], expects="bin/tool")

    status = await fakes.preparer().prepare(CONNECTION_ID, recipe, fakes.folders)

    assert status.phase == "ready"
    assert (fakes.folders.install / "bin" / "tool").read_bytes() == BODY
    assert artifacts_ready(recipe, fakes.folders)


@pytest.mark.asyncio
async def test_an_archive_that_does_not_contain_the_expected_file_is_not_recorded(fakes):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo("other")
        info.size = 1
        bundle.addfile(info, io.BytesIO(b"x"))
    fakes.download_body = buffer.getvalue()
    sha = hashlib.sha256(fakes.download_body).hexdigest()
    recipe = _recipe([_download_method(sha=sha, archive="tar.gz")], expects="bin/tool")

    await fakes.preparer().prepare(CONNECTION_ID, recipe, fakes.folders)

    assert not artifacts_ready(recipe, fakes.folders)


@pytest.mark.asyncio
async def test_a_requirement_with_no_install_command_waits_for_the_person(fakes):
    requirement = {**GO, "install": None}
    recipe = _recipe([_build_method()], requirements=[requirement])

    status = await fakes.preparer().prepare(CONNECTION_ID, recipe, fakes.folders)

    assert (status.phase, status.requirement, status.can_install) == ("needs_requirement", "Go", False)
    assert "Needed to build." in status.message
    assert fakes.ran("make") == []


@pytest.mark.asyncio
async def test_a_requirement_that_can_be_installed_waits_for_approval_and_never_installs_without_it(fakes):
    recipe = _recipe([_build_method()], requirements=[GO])

    status = await fakes.preparer().prepare(CONNECTION_ID, recipe, fakes.folders)

    assert (status.phase, status.requirement, status.can_install) == ("needs_requirement", "Go", True)
    assert fakes.ran("brew") == []


@pytest.mark.asyncio
async def test_a_denied_install_is_not_run(fakes):
    recipe = _recipe([_build_method()], requirements=[GO])
    asked: List[MCPRequirement] = []

    async def deny(requirement: MCPRequirement) -> bool:
        asked.append(requirement)
        return False

    status = await fakes.preparer().prepare(CONNECTION_ID, recipe, fakes.folders, approve_install=deny)

    assert [item.name for item in asked] == ["Go"]
    assert status.phase == "needs_requirement" and "not approved" in status.message
    assert fakes.ran("brew") == []


@pytest.mark.asyncio
async def test_an_approved_install_runs_then_the_build_continues(fakes):
    recipe = _recipe([_build_method()], requirements=[GO])
    phases: List[str] = []
    preparer = fakes.preparer()

    async def approve(requirement: MCPRequirement) -> bool:
        phases.append(preparer.status(CONNECTION_ID, recipe, fakes.folders).phase)
        return True

    status = await preparer.prepare(CONNECTION_ID, recipe, fakes.folders, approve_install=approve)

    assert status.phase == "ready"
    assert fakes.ran("brew") == [["brew", "install", "go"]]
    assert fakes.commands[[argv for argv, _ in fakes.commands].index(["brew", "install", "go"])][1]["extra_env"]["NONINTERACTIVE"] == "1"
    assert (fakes.folders.install / "bin" / "tool").exists()


@pytest.mark.asyncio
async def test_a_failed_install_stops_with_its_output(fakes):
    fakes.install_exit = 1
    recipe = _recipe([_build_method()], requirements=[GO])

    async def approve(requirement: MCPRequirement) -> bool:
        return True

    status = await fakes.preparer().prepare(CONNECTION_ID, recipe, fakes.folders, approve_install=approve)

    assert status.phase == "failed" and "exit code 1" in status.message and status.detail == "installer output"


@pytest.mark.asyncio
async def test_an_install_that_finishes_but_is_still_not_found_waits_for_the_person(fakes):
    recipe = _recipe([_build_method()], requirements=[GO])

    async def approve(requirement: MCPRequirement) -> bool:
        return True

    original = fakes.run

    async def run(argv, **kwargs):
        result = await original(argv, **kwargs)
        if argv[0] == "brew":
            fakes.met["go"] = False
        return result

    preparer = LocalServerPreparer(run=run, download=fakes.download)
    status = await preparer.prepare(CONNECTION_ID, recipe, fakes.folders, approve_install=approve)

    assert status.phase == "needs_requirement" and "still cannot find it" in status.message


@pytest.mark.asyncio
async def test_a_build_only_requirement_is_not_checked_when_a_download_is_used(fakes):
    recipe = _recipe([_download_method(), _build_method()], requirements=[GO])

    status = await fakes.preparer().prepare(CONNECTION_ID, recipe, fakes.folders)

    assert status.phase == "ready" and fakes.commands == []


@pytest.mark.asyncio
async def test_git_is_checked_before_a_build_even_when_the_recipe_does_not_list_it(fakes):
    fakes.met["git"] = False

    status = await fakes.preparer().prepare(CONNECTION_ID, _recipe([_build_method()]), fakes.folders)

    assert (status.phase, status.requirement, status.can_install) == ("needs_requirement", "Git", True)


@pytest.mark.asyncio
async def test_a_requirement_for_any_method_is_checked_first(fakes):
    requirement = {"name": "Runtime", "reason": "The server runs on it.", "check": ["runtime", "--version"], "for_method": "any"}
    recipe = _recipe([_download_method()], requirements=[requirement])

    async def run(argv, **kwargs):
        return CommandResult(1, "")

    status = await LocalServerPreparer(run=run, download=fakes.download).prepare(CONNECTION_ID, recipe, fakes.folders)

    assert status.phase == "needs_requirement" and status.requirement == "Runtime" and fakes.downloads == []


@pytest.mark.asyncio
async def test_canceling_stops_the_work_and_the_next_run_clears_what_was_left(fakes):
    fakes.hold = asyncio.Event()
    recipe = _recipe([_download_method()])
    preparer = fakes.preparer()

    preparer.start(CONNECTION_ID, recipe, fakes.folders)
    for _ in range(100):
        if fakes.downloads:
            break
        await asyncio.sleep(0.01)
    assert preparer.status(CONNECTION_ID, recipe, fakes.folders).active

    canceled = await preparer.cancel(CONNECTION_ID)

    assert canceled.phase == "canceled" and not preparer.is_running(CONNECTION_ID)
    leftover = fakes.folders.install / ".partial" / "old.download"
    leftover.parent.mkdir(parents=True, exist_ok=True)
    leftover.write_bytes(b"half")
    fakes.hold = None
    status = await preparer.prepare(CONNECTION_ID, recipe, fakes.folders)
    assert status.phase == "ready" and not leftover.exists()


@pytest.mark.asyncio
async def test_starting_twice_reports_the_run_already_under_way(fakes):
    fakes.hold = asyncio.Event()
    recipe = _recipe([_download_method()])
    preparer = fakes.preparer()
    preparer.start(CONNECTION_ID, recipe, fakes.folders)
    preparer.start(CONNECTION_ID, recipe, fakes.folders)
    for _ in range(100):
        if fakes.downloads:
            break
        await asyncio.sleep(0.01)
    fakes.hold.set()
    await preparer.prepare(CONNECTION_ID, recipe, fakes.folders)

    assert fakes.downloads == [URL]


@pytest.mark.asyncio
async def test_an_unexpected_error_is_reported_as_failed_not_raised(fakes):
    fakes.download_error = RuntimeError("disk exploded")

    status = await fakes.preparer().prepare(CONNECTION_ID, _recipe([_download_method()]), fakes.folders)

    assert status.phase == "failed" and "disk exploded" in status.message


@pytest.mark.asyncio
async def test_a_download_with_no_hash_for_this_processor_is_not_fetched(fakes):
    other = "amd64" if local_server_prepare.current_arch() == "arm64" else "arm64"
    recipe = _recipe([{"kind": "download", "url": URL, "sha256_by_arch": {other: BODY_SHA}}])

    status = await fakes.preparer().prepare(CONNECTION_ID, recipe, fakes.folders)

    assert status.phase == "failed" and "no hash for this Mac" in (status.detail or "") and fakes.downloads == []


@pytest.mark.asyncio
async def test_installing_one_requirement_needs_its_approval_and_then_leaves_the_server_to_be_prepared(fakes):
    recipe = _recipe([_build_method()], requirements=[GO])
    preparer = fakes.preparer()

    async def deny(requirement: MCPRequirement) -> bool:
        return False

    async def approve(requirement: MCPRequirement) -> bool:
        return True

    denied = await preparer.install_requirement(CONNECTION_ID, recipe, "Go", approve_install=deny)
    assert denied.phase == "needs_requirement" and fakes.ran("brew") == []

    installed = await preparer.install_requirement(CONNECTION_ID, recipe, "Go", approve_install=approve)
    assert installed.phase == "idle" and "Go is installed" in installed.message and fakes.ran("brew") == [["brew", "install", "go"]]


@pytest.mark.asyncio
async def test_installing_a_requirement_that_does_not_exist_or_has_no_command_is_an_error(fakes):
    recipe = _recipe([_build_method()], requirements=[{**GO, "install": None}])

    async def approve(requirement: MCPRequirement) -> bool:
        return True

    with pytest.raises(PrepareError, match="no requirement named Nope"):
        await fakes.preparer().install_requirement(CONNECTION_ID, recipe, "Nope", approve_install=approve)
    with pytest.raises(PrepareError, match="no install command"):
        await fakes.preparer().install_requirement(CONNECTION_ID, recipe, "Go", approve_install=approve)


@pytest.mark.asyncio
async def test_installing_while_preparation_runs_is_refused(fakes):
    fakes.hold = asyncio.Event()
    recipe = _recipe([_download_method(), _build_method()], requirements=[GO])
    preparer = fakes.preparer()
    preparer.start(CONNECTION_ID, recipe, fakes.folders)

    async def approve(requirement: MCPRequirement) -> bool:
        return True

    with pytest.raises(PrepareError, match="already running"):
        await preparer.install_requirement(CONNECTION_ID, recipe, "Go", approve_install=approve)
    await preparer.cancel(CONNECTION_ID)


def test_status_is_ready_once_everything_is_in_place_even_after_a_restart(fakes):
    recipe = _recipe([_download_method()])
    assert fakes.preparer().status(CONNECTION_ID, recipe, fakes.folders).phase == "idle"

    asyncio.run(fakes.preparer().prepare(CONNECTION_ID, recipe, fakes.folders))

    assert fakes.preparer().status(CONNECTION_ID, recipe, fakes.folders).phase == "ready"
    assert fakes.preparer().status(CONNECTION_ID, None, fakes.folders).phase == "idle"


def test_a_recipe_with_nothing_to_put_in_place_is_always_ready(fakes):
    assert artifacts_ready(None, fakes.folders)
    assert artifacts_ready(build_install_recipe({"requirements": [{"name": "X", "reason": "r", "check": ["x"]}]}), fakes.folders)


@pytest.fixture
def stored_preferences(monkeypatch) -> Dict[str, Preferences]:
    holder = {"value": Preferences()}
    monkeypatch.setattr(preferences_io, "load_preferences", lambda: holder["value"].model_copy(deep=True))
    monkeypatch.setattr(preferences_io, "save_preferences", lambda prefs: holder.__setitem__("value", prefs.model_copy(deep=True)))
    return holder


@pytest.mark.asyncio
async def test_a_server_whose_files_are_not_prepared_does_not_start_or_launch_and_says_how_to_fix_it(tmp_path, stored_preferences):
    supervisor = CompanionSupervisor(tmp_path / "local_servers", ready_timeout_seconds=15.0, stop_grace_seconds=3.0)
    set_companion_supervisor(supervisor)
    install = {"artifacts": [{"name": "Tool", "expects": "bin/tool", "methods": [_download_method()]}]}
    record = register_local_server_record(
        friendly_name="Needs files",
        command=sys.executable,
        args=["-c", "pass"],
        companion={"command": "{install_dir}/bin/tool", "args": []},
        install=install,
    )
    try:
        snapshot = await supervisor.start(record.id)
        assert snapshot.status == "failed" and snapshot.last_error == NOT_PREPARED_MESSAGE

        prepared = await prepare_stdio_launch(record.stdio, record.id)
        assert prepared.parameters is None and prepared.error is not None
        assert NOT_PREPARED_MESSAGE in prepared.error["error"]["message"]
        assert "choose Prepare" in prepared.error["error"]["user_action_required"]
    finally:
        await supervisor.stop_all()
        set_companion_supervisor(None)
