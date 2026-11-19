"""Put one artifact of a local server recipe in place: download and verify it, or check out a pinned commit and build it.

An artifact ends up at ``expects`` under the connection's install folder or the attempt fails. A hash that does not match what the person approved raises ``HashMismatch``, which the caller treats as final: it never falls back to another way of getting the same file. Every other failure raises ``AcquireError`` so the next listed method can be tried.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import re
import shutil
import uuid
from pathlib import Path
from typing import Awaitable, Callable, Optional, Union

from api.core.models.preferences import MCPArtifact, MCPBuildMethod, MCPDownloadMethod

from .local_server_archive import ArchiveError, extract_archive
from .local_server_commands import CommandResult, run_command
from .local_server_download import DownloadError, download_file
from .local_server_placeholders import DATA_DIR_PLACEHOLDER, INSTALL_DIR_PLACEHOLDER

Method = Union[MCPDownloadMethod, MCPBuildMethod]
Report = Callable[[str, str], None]
Downloader = Callable[..., Awaitable[str]]
Runner = Callable[..., Awaitable[CommandResult]]

PARTIAL_FOLDER = ".partial"
BUILD_FOLDER = ".build"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")
_GIT_TRANSPORT_OPTIONS = ("-c", "protocol.allow=never", "-c", "protocol.https.allow=always")
_GIT_TIMEOUT_SECONDS = 900.0


class AcquireError(Exception):
    """This way of getting the artifact did not work. The message is plain language for the person."""


class HashMismatch(AcquireError):
    """The file arrived but is not the file the person approved. Never worked around."""


def current_arch() -> str:
    return "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "amd64"


def _expected_hash(method: MCPDownloadMethod) -> Optional[str]:
    return method.sha256 or method.sha256_by_arch.get(current_arch())


def resolved_url(method: MCPDownloadMethod) -> str:
    return method.url.replace("{os}", "darwin").replace("{arch}", current_arch())


def method_fingerprint(method: Method) -> str:
    """A short identity for a method with this Mac's architecture filled in, so a changed recipe is prepared again."""
    if isinstance(method, MCPDownloadMethod):
        basis = {"kind": "download", "url": resolved_url(method), "sha256": _expected_hash(method), "archive": method.archive, "strip": method.strip_components}
    else:
        basis = {"kind": "build", "git_url": method.git_url, "commit": method.commit, "steps": [step.model_dump() for step in method.steps]}
    return hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()


def inside(path: Path, root: Path) -> bool:
    resolved = Path(os.path.realpath(path))
    base = Path(os.path.realpath(root))
    return resolved == base or base in resolved.parents


def _destination(install_dir: Path, artifact: MCPArtifact) -> Path:
    target = install_dir / artifact.expects
    if not inside(target.parent, install_dir):
        raise AcquireError(f"{artifact.name} would be placed outside its own folder.")
    return target


def _clear(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def clean_temporary_files(install_dir: Path) -> None:
    """Remove what an interrupted preparation left behind."""
    for name in (PARTIAL_FOLDER, BUILD_FOLDER):
        shutil.rmtree(install_dir / name, ignore_errors=True)


async def acquire_download(
    method: MCPDownloadMethod,
    artifact: MCPArtifact,
    install_dir: Path,
    *,
    download: Downloader = download_file,
    report: Report,
) -> None:
    expected = _expected_hash(method)
    if expected is None:
        raise AcquireError(f"This download has no hash for this Mac's {current_arch()} processor, so Basil will not fetch it.")
    target = _destination(install_dir, artifact)
    partial = install_dir / PARTIAL_FOLDER
    partial.mkdir(parents=True, exist_ok=True)
    os.chmod(partial, 0o700)
    saved = partial / f"{uuid.uuid4().hex}.download"
    staging = partial / f"{uuid.uuid4().hex}.unpacked"
    try:
        report("downloading", f"Downloading {artifact.name} from {resolved_url(method)}")
        try:
            digest = await download(resolved_url(method), saved)
        except DownloadError as exc:
            raise AcquireError(str(exc)) from exc
        report("verifying", f"Checking {artifact.name} against the approved hash")
        if digest.lower() != expected.lower():
            raise HashMismatch(f"The file for {artifact.name} is not the one you approved: its SHA-256 is {digest}, not {expected}. Basil deleted it and will not use it.")
        target.parent.mkdir(parents=True, exist_ok=True)
        if method.archive is None:
            _clear(target)
            os.replace(saved, target)
            os.chmod(target, 0o700 if method.executable else 0o600)
            return
        report("extracting", f"Unpacking {artifact.name}")
        try:
            await asyncio.to_thread(extract_archive, saved, method.archive, staging, strip_components=method.strip_components)
        except ArchiveError as exc:
            raise AcquireError(str(exc)) from exc
        for entry in staging.iterdir():
            place = target.parent / entry.name
            _clear(place)
            os.replace(entry, place)
    finally:
        _clear(saved)
        _clear(staging)


def _substituted(argv: list, install_dir: Path, data_dir: Path) -> list:
    return [item.replace(INSTALL_DIR_PLACEHOLDER, str(install_dir)).replace(DATA_DIR_PLACEHOLDER, str(data_dir)) for item in argv]


async def _git(source: Path, *arguments: str, run: Runner) -> CommandResult:
    return await run(["git", *_GIT_TRANSPORT_OPTIONS, *arguments], cwd=source, extra_env={"GIT_TERMINAL_PROMPT": "0"}, timeout=_GIT_TIMEOUT_SECONDS)


async def acquire_build(
    method: MCPBuildMethod,
    artifact: MCPArtifact,
    install_dir: Path,
    data_dir: Path,
    *,
    run: Runner = run_command,
    report: Report,
) -> None:
    target = _destination(install_dir, artifact)
    source = install_dir / BUILD_FOLDER / (_SAFE_NAME.sub("-", artifact.name).strip("-.") or "artifact") / "src"
    shutil.rmtree(source.parent, ignore_errors=True)
    source.mkdir(parents=True)
    try:
        report("building", f"Fetching the source for {artifact.name} at commit {method.commit[:12]}")
        for arguments in (("init", "-q"), ("fetch", "--depth", "1", "--no-tags", "--no-recurse-submodules", "-q", method.git_url, method.commit), ("checkout", "-q", "--detach", "FETCH_HEAD")):
            result = await _git(source, *arguments, run=run)
            if not result.ok:
                raise AcquireError(f"Fetching the source from {method.git_url} failed: {result.output}")
        head = await _git(source, "rev-parse", "HEAD", run=run)
        if not head.ok or head.output.strip() != method.commit:
            raise HashMismatch(f"The source fetched for {artifact.name} is not the commit you approved ({method.commit}). Basil deleted it and will not build it.")
        for number, step in enumerate(method.steps, start=1):
            folder = source / step.cwd if step.cwd else source
            if not inside(folder, source) or not folder.is_dir():
                raise AcquireError(f"Build step {number} names a folder that is not inside the source: {step.cwd}.")
            report("building", f"Building {artifact.name}: step {number} of {len(method.steps)}")
            result = await run(_substituted(step.argv, install_dir, data_dir), cwd=folder)
            if not result.ok:
                raise AcquireError(f"Build step {number} ({' '.join(step.argv[:3])}) failed with exit code {result.returncode}: {result.output}")
        if not target.exists() or not inside(target, install_dir):
            raise AcquireError(f"The build finished but did not produce {artifact.expects}.")
    finally:
        shutil.rmtree(install_dir / BUILD_FOLDER, ignore_errors=True)
