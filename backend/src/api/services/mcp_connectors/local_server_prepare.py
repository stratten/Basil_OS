"""Prepare a local server before it first runs: check what it needs installed, then put its files in place.

A recipe lists requirements (programs that must exist) and artifacts (files Basil downloads or builds). ``LocalServerPreparer`` walks them one at a time and reports a phase the Settings screen and the agent can read: checking, needs_requirement, installing, downloading, verifying, extracting, building, ready, failed or canceled.

Preparation can be repeated safely. A finished artifact is recorded with a fingerprint of the method that produced it, so a second run skips it, and a changed recipe is prepared again. Temporary files from an interrupted run are removed when the next one starts. Installing a requirement runs only after that step is approved: the caller passes the approval, and nothing here runs an install without it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shlex
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional, Tuple, Union

from api.core.models.preferences import MCPArtifact, MCPBuildMethod, MCPDownloadMethod, MCPInstallRecipe, MCPRequirement

from .local_server_acquire import (
    AcquireError,
    HashMismatch,
    acquire_build,
    acquire_download,
    clean_temporary_files,
    current_arch,
    method_fingerprint,
)
from .local_server_commands import CHECK_TIMEOUT_SECONDS, CommandResult, run_command
from .local_server_download import download_file
from .local_server_paths import ConnectionFolders

logger = logging.getLogger(__name__)

INSTALL_TIMEOUT_SECONDS = 1800.0
RECORD_FILE = "prepared.json"

ApproveInstall = Callable[[MCPRequirement], Awaitable[bool]]

NOT_PREPARED_MESSAGE = "This server's files have not been prepared yet. Open Settings → Connections, find this server, and choose Prepare."

PHASE_IDLE = "idle"
PHASE_CHECKING = "checking"
PHASE_NEEDS_REQUIREMENT = "needs_requirement"
PHASE_INSTALLING = "installing"
PHASE_READY = "ready"
PHASE_FAILED = "failed"
PHASE_CANCELED = "canceled"
ACTIVE_PHASES = frozenset({PHASE_CHECKING, PHASE_INSTALLING, "downloading", "verifying", "extracting", "building"})

# Fetching source needs git, and on a Mac without the developer tools the git on the path is a stub that opens an installer window instead of running.
GIT_REQUIREMENT = MCPRequirement(
    name="Git",
    reason="Basil needs Git to fetch the source code it will build.",
    check=["git", "--version"],
    install=["xcode-select", "--install"],
    for_method="build",
)


@dataclass
class PrepareStatus:
    phase: str = PHASE_IDLE
    message: str = ""
    artifact: Optional[str] = None
    requirement: Optional[str] = None
    can_install: bool = False
    detail: Optional[str] = None
    updated_at: float = field(default_factory=time.time)

    @property
    def active(self) -> bool:
        return self.phase in ACTIVE_PHASES


class PrepareError(Exception):
    """A request about preparation that cannot be carried out. The message is plain language."""


class _Stop(Exception):
    """Preparation cannot go on. Carries the status to leave behind."""

    def __init__(self, status: PrepareStatus) -> None:
        super().__init__(status.message)
        self.status = status


def _record_path(folders: ConnectionFolders) -> Path:
    return folders.install.parent / RECORD_FILE


def _read_record(folders: ConnectionFolders) -> Dict[str, str]:
    try:
        data = json.loads(_record_path(folders).read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    done = data.get("done") if isinstance(data, dict) else None
    return {str(key): str(value) for key, value in done.items()} if isinstance(done, dict) else {}


def _write_record(folders: ConnectionFolders, done: Dict[str, str]) -> None:
    path = _record_path(folders)
    temporary = path.with_name(f"{RECORD_FILE}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump({"done": done}, handle)
    os.replace(temporary, path)


_hash_cache: Dict[Tuple[str, int, int], str] = {}


def _file_hash(path: Path) -> str:
    """The SHA-256 of a file. A file that has not changed since it was last read is not read again, because the Settings screen asks often."""
    info = path.stat()
    key = (str(path), info.st_mtime_ns, info.st_size)
    cached = _hash_cache.get(key)
    if cached is not None:
        return cached
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    if len(_hash_cache) > 64:
        _hash_cache.clear()
    _hash_cache[key] = digest.hexdigest()
    return _hash_cache[key]


def artifact_is_ready(artifact: MCPArtifact, folders: ConnectionFolders, done: Optional[Dict[str, str]] = None) -> bool:
    """True when the artifact is in place and was produced by one of the methods the recipe lists now."""
    target = folders.install / artifact.expects
    if not target.exists():
        return False
    recorded = (_read_record(folders) if done is None else done).get(artifact.name)
    chosen = next((method for method in artifact.methods if method_fingerprint(method) == recorded), None)
    if chosen is None:
        return False
    if isinstance(chosen, MCPDownloadMethod) and chosen.archive is None and target.is_file():
        expected = chosen.sha256 or chosen.sha256_by_arch.get(current_arch())
        return expected is not None and _file_hash(target) == expected.lower()
    return True


def artifacts_ready(recipe: Optional[MCPInstallRecipe], folders: ConnectionFolders) -> bool:
    """True when the recipe has nothing left to put in place."""
    if recipe is None or not recipe.artifacts:
        return True
    done = _read_record(folders)
    return all(artifact_is_ready(artifact, folders, done) for artifact in recipe.artifacts)


def requirement_install_command(requirement: MCPRequirement) -> Optional[str]:
    """The install command exactly as it is shown to the person and compared when they approve it."""
    return shlex.join(requirement.install) if requirement.install else None


def find_requirement(recipe: MCPInstallRecipe, name: str) -> Optional[MCPRequirement]:
    """A requirement of the recipe by name, including the Git requirement that every build needs."""
    return next((item for item in [*recipe.requirements, GIT_REQUIREMENT] if item.name == name), None)


class LocalServerPreparer:
    """Runs preparations and keeps the latest status of each connection in memory."""

    def __init__(
        self,
        *,
        run: Callable[..., Awaitable[CommandResult]] = run_command,
        download: Callable[..., Awaitable[str]] = download_file,
    ) -> None:
        self._run = run
        self._download = download
        self._status: Dict[str, PrepareStatus] = {}
        self._tasks: Dict[str, "asyncio.Task[None]"] = {}

    def status(self, connection_id: str, recipe: Optional[MCPInstallRecipe], folders: ConnectionFolders) -> PrepareStatus:
        """The latest status. With nothing recorded this run, ready when every artifact is in place and idle otherwise."""
        known = self._status.get(connection_id)
        if known is not None:
            return known
        if recipe is not None and recipe.artifacts and artifacts_ready(recipe, folders):
            return PrepareStatus(phase=PHASE_READY, message="Everything this server needs is in place.")
        return PrepareStatus()

    def is_running(self, connection_id: str) -> bool:
        task = self._tasks.get(connection_id)
        return task is not None and not task.done()

    def start(self, connection_id: str, recipe: MCPInstallRecipe, folders: ConnectionFolders, *, approve_install: Optional[ApproveInstall] = None) -> PrepareStatus:
        """Begin preparing in the background, or report the preparation already under way."""
        if self.is_running(connection_id):
            return self._status[connection_id]
        self._set(connection_id, PHASE_CHECKING, "Checking what this server needs.")
        self._tasks[connection_id] = asyncio.create_task(self._guarded(connection_id, self._run_recipe(connection_id, recipe, folders, approve_install)))
        return self._status[connection_id]

    async def prepare(self, connection_id: str, recipe: MCPInstallRecipe, folders: ConnectionFolders, *, approve_install: Optional[ApproveInstall] = None) -> PrepareStatus:
        """Prepare and wait for the outcome."""
        self.start(connection_id, recipe, folders, approve_install=approve_install)
        task = self._tasks[connection_id]
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled() or task.done():
                return self._status[connection_id]
            raise
        return self._status[connection_id]

    async def wait(self, connection_id: str) -> PrepareStatus:
        """Wait for the preparation under way, if any, and return the status it left."""
        task = self._tasks.get(connection_id)
        if task is not None and not task.done():
            await asyncio.gather(task, return_exceptions=True)
        return self._status.get(connection_id) or PrepareStatus()

    async def cancel(self, connection_id: str) -> PrepareStatus:
        task = self._tasks.get(connection_id)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return self._status.get(connection_id) or PrepareStatus()

    def _installable(self, connection_id: str, recipe: MCPInstallRecipe, name: str) -> MCPRequirement:
        if self.is_running(connection_id):
            raise PrepareError("Preparation is already running for this server. Wait for it to finish or cancel it first.")
        requirement = find_requirement(recipe, name)
        if requirement is None:
            raise PrepareError(f"This server's recipe has no requirement named {name}.")
        if not requirement.install:
            raise PrepareError(f"{name} has no install command in the recipe, so install it yourself.")
        return requirement

    async def _install_one(self, connection_id: str, requirement: MCPRequirement, approve_install: ApproveInstall) -> None:
        await self._ensure_requirement(connection_id, requirement, approve_install)
        self._set(connection_id, PHASE_IDLE, f"{requirement.name} is installed. Prepare the server to continue.")

    async def install_requirement(self, connection_id: str, recipe: MCPInstallRecipe, name: str, *, approve_install: ApproveInstall) -> PrepareStatus:
        """Install one named requirement after ``approve_install`` says yes, wait, and report whether it is now met."""
        requirement = self._installable(connection_id, recipe, name)
        await self._guarded(connection_id, self._install_one(connection_id, requirement, approve_install))
        return self._status[connection_id]

    def start_install_requirement(self, connection_id: str, recipe: MCPInstallRecipe, name: str, *, approve_install: ApproveInstall) -> PrepareStatus:
        """Begin installing one named requirement in the background, since an install can take minutes."""
        requirement = self._installable(connection_id, recipe, name)
        self._set(connection_id, PHASE_CHECKING, f"Checking for {requirement.name}.", requirement=requirement.name)
        self._tasks[connection_id] = asyncio.create_task(self._guarded(connection_id, self._install_one(connection_id, requirement, approve_install)))
        return self._status[connection_id]

    def forget(self, connection_id: str) -> None:
        self._status.pop(connection_id, None)
        task = self._tasks.pop(connection_id, None)
        if task is not None and not task.done():
            task.cancel()

    def _set(self, connection_id: str, phase: str, message: str, **fields: object) -> None:
        self._status[connection_id] = PrepareStatus(phase=phase, message=message, **fields)  # type: ignore[arg-type]

    async def _guarded(self, connection_id: str, work: Awaitable[None]) -> None:
        """Run ``work`` and turn however it ends into a status, so a background run never raises."""
        try:
            await work
        except _Stop as stop:
            self._status[connection_id] = stop.status
        except asyncio.CancelledError:
            self._set(connection_id, PHASE_CANCELED, "Preparation was canceled.")
            raise
        except Exception as exc:
            logger.exception("Preparing local server %s failed", connection_id)
            self._set(connection_id, PHASE_FAILED, f"Preparation stopped unexpectedly: {exc}")

    async def _run_recipe(self, connection_id: str, recipe: MCPInstallRecipe, folders: ConnectionFolders, approve_install: Optional[ApproveInstall]) -> None:
        clean_temporary_files(folders.install)
        met: set = set()
        for requirement in recipe.requirements:
            if requirement.for_method == "any":
                await self._ensure_requirement(connection_id, requirement, approve_install, met=met)
        for artifact in recipe.artifacts:
            if artifact_is_ready(artifact, folders):
                continue
            await self._acquire(connection_id, recipe, artifact, folders, approve_install, met)
        self._set(connection_id, PHASE_READY, "Everything this server needs is in place.")

    def _applicable(self, recipe: MCPInstallRecipe, kind: str) -> List[MCPRequirement]:
        found = [item for item in recipe.requirements if item.for_method == kind]
        if kind == "build" and not any(item.name == GIT_REQUIREMENT.name for item in recipe.requirements):
            found.insert(0, GIT_REQUIREMENT)
        return found

    async def _acquire(self, connection_id: str, recipe: MCPInstallRecipe, artifact: MCPArtifact, folders: ConnectionFolders, approve_install: Optional[ApproveInstall], met: set) -> None:
        failures: List[str] = []
        blocked: Optional[PrepareStatus] = None
        for method in artifact.methods:
            kind = "download" if isinstance(method, MCPDownloadMethod) else "build"
            try:
                for requirement in self._applicable(recipe, kind):
                    await self._ensure_requirement(connection_id, requirement, approve_install, met=met)
                await self._attempt(connection_id, method, artifact, folders)
            except _Stop as stop:
                if stop.status.phase != PHASE_NEEDS_REQUIREMENT:
                    raise
                blocked = stop.status
                failures.append(stop.status.message)
                continue
            except HashMismatch as exc:
                raise _Stop(PrepareStatus(phase=PHASE_FAILED, message=str(exc), artifact=artifact.name)) from exc
            except AcquireError as exc:
                failures.append(str(exc))
                continue
            done = _read_record(folders)
            done[artifact.name] = method_fingerprint(method)
            _write_record(folders, done)
            return
        if blocked is not None:
            raise _Stop(PrepareStatus(phase=PHASE_NEEDS_REQUIREMENT, message=blocked.message, artifact=artifact.name, requirement=blocked.requirement, can_install=blocked.can_install, detail=" | ".join(failures)))
        raise _Stop(PrepareStatus(phase=PHASE_FAILED, message=f"Basil could not get {artifact.name}.", artifact=artifact.name, detail=" | ".join(failures)))

    async def _attempt(self, connection_id: str, method, artifact: MCPArtifact, folders: ConnectionFolders) -> None:
        def report(phase: str, message: str) -> None:
            self._set(connection_id, phase, message, artifact=artifact.name)

        folders.install.mkdir(parents=True, exist_ok=True)
        folders.data.mkdir(parents=True, exist_ok=True)
        if isinstance(method, MCPDownloadMethod):
            await acquire_download(method, artifact, folders.install, download=self._download, report=report)
        else:
            await acquire_build(method, artifact, folders.install, folders.data, run=self._run, report=report)

    async def _is_met(self, requirement: MCPRequirement) -> bool:
        result = await self._run(requirement.check, timeout=CHECK_TIMEOUT_SECONDS)
        return result.ok

    async def _ensure_requirement(self, connection_id: str, requirement: MCPRequirement, approve_install: Optional[ApproveInstall], *, met: Optional[set] = None) -> None:
        """Return when the requirement is met. Raises _Stop when it is not and cannot be met without the person."""
        if met is not None and requirement.name in met:
            return
        self._set(connection_id, PHASE_CHECKING, f"Checking for {requirement.name}.", requirement=requirement.name)
        if await self._is_met(requirement):
            if met is not None:
                met.add(requirement.name)
            return
        can_install = bool(requirement.install)
        needs = PrepareStatus(
            phase=PHASE_NEEDS_REQUIREMENT,
            message=f"{requirement.name} is needed. {requirement.reason}",
            requirement=requirement.name,
            can_install=can_install,
        )
        if not can_install or approve_install is None:
            raise _Stop(needs)
        if not await approve_install(requirement):
            needs.message = f"{requirement.name} is needed, and installing it was not approved. {requirement.reason}"
            raise _Stop(needs)
        self._set(connection_id, PHASE_INSTALLING, f"Installing {requirement.name}.", requirement=requirement.name)
        result = await self._run(requirement.install, timeout=INSTALL_TIMEOUT_SECONDS, extra_env={"HOMEBREW_NO_AUTO_UPDATE": "1", "NONINTERACTIVE": "1"})
        if not result.ok:
            raise _Stop(PrepareStatus(phase=PHASE_FAILED, message=f"Installing {requirement.name} failed with exit code {result.returncode}.", requirement=requirement.name, detail=result.output))
        if not await self._is_met(requirement):
            needs.message = f"{requirement.name} was installed but Basil still cannot find it. If an installer window opened, let it finish, then prepare the server again."
            raise _Stop(needs)
        if met is not None:
            met.add(requirement.name)


def describe_method(method: Union[MCPDownloadMethod, MCPBuildMethod]) -> str:
    """One plain-language line naming every address, hash, commit and command a method uses, for the approval card and the Settings row. Nothing is shortened."""
    if isinstance(method, MCPDownloadMethod):
        hashes = method.sha256 or ", ".join(f"{arch}: {value}" for arch, value in sorted(method.sha256_by_arch.items()))
        packed = f", unpacked as {method.archive}" if method.archive else ""
        return f"Download {method.url} (SHA-256 {hashes}{packed})"
    steps = "; ".join(shlex.join(step.argv) + (f" in {step.cwd}" if step.cwd else "") for step in method.steps) or "no build commands"
    return f"Build from {method.git_url} at commit {method.commit}, running: {steps}"


_preparer: Optional[LocalServerPreparer] = None


def get_local_server_preparer() -> LocalServerPreparer:
    global _preparer
    if _preparer is None:
        _preparer = LocalServerPreparer()
    return _preparer


def set_local_server_preparer(preparer: Optional[LocalServerPreparer]) -> None:
    global _preparer
    _preparer = preparer
