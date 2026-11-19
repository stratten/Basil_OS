"""Unpack a downloaded archive into a folder without letting it write anywhere else.

Every entry is checked by name before anything is written: no absolute paths, no ``..``, no backslashes, no devices or pipes, and a link is kept only when it points at something inside the folder. A zip archive may not contain links at all. Entry count and total size are capped so a small archive cannot fill the disk. File permissions keep the owner's read, write and execute bits and drop everything else.
"""

from __future__ import annotations

import os
import posixpath
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import IO, Optional, Tuple

MAX_ENTRIES = 20000
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
_COPY_CHUNK = 64 * 1024


class ArchiveError(Exception):
    """The archive is unsafe or damaged. The message is plain language for the person."""


def _clean_parts(name: str, strip: int) -> Optional[Tuple[str, ...]]:
    """The entry's path parts after dropping ``strip`` leading folders, or None for an entry that is only a stripped folder."""
    if not name or name.startswith("/") or "\\" in name or "\x00" in name:
        raise ArchiveError(f"The archive contains an unsafe path, '{name}'.")
    parts = [part for part in PurePosixPath(name).parts if part != "."]
    if any(part == ".." for part in parts):
        raise ArchiveError(f"The archive contains an entry that climbs out of its folder, '{name}'.")
    kept = parts[strip:]
    return tuple(kept) if kept else None


def _inside(path: Path, root: Path) -> bool:
    resolved = Path(os.path.realpath(path))
    base = Path(os.path.realpath(root))
    return resolved == base or base in resolved.parents


def _target(root: Path, parts: Tuple[str, ...], name: str) -> Path:
    target = root.joinpath(*parts)
    if not _inside(target.parent, root):
        raise ArchiveError(f"The archive tries to write outside its folder through '{name}'.")
    return target


def _safe_mode(mode: int, default: int) -> int:
    """Owner-only permissions, executable when the archive marked the file executable for its owner."""
    return 0o700 if (mode or default) & 0o100 else 0o600


def _link_is_contained(root: Path, parts: Tuple[str, ...], link_target: str, name: str) -> None:
    if link_target.startswith("/") or "\\" in link_target:
        raise ArchiveError(f"The archive contains a link to a path outside its folder, '{name}'.")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname("/".join(parts)), link_target))
    if resolved == ".." or resolved.startswith("../"):
        raise ArchiveError(f"The archive contains a link that leaves its folder, '{name}'.")


class _Budget:
    def __init__(self) -> None:
        self.entries = 0
        self.bytes = 0

    def entry(self) -> None:
        self.entries += 1
        if self.entries > MAX_ENTRIES:
            raise ArchiveError("The archive holds too many files.")

    def add(self, count: int) -> None:
        self.bytes += count
        if self.bytes > MAX_TOTAL_BYTES:
            raise ArchiveError("The archive unpacks to more than Basil allows.")


def _write_file(source: IO[bytes], target: Path, mode: int, budget: _Budget) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.exists():
        raise ArchiveError(f"The archive lists '{target.name}' twice.")
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        while True:
            chunk = source.read(_COPY_CHUNK)
            if not chunk:
                break
            budget.add(len(chunk))
            handle.write(chunk)
    os.chmod(target, mode)


def _verify_links(root: Path) -> None:
    """After unpacking, every link must really lead to something inside the folder, whatever chain of links it goes through."""
    for current, folders, files in os.walk(root):
        for name in [*folders, *files]:
            path = Path(current) / name
            if path.is_symlink() and not _inside(path, root):
                raise ArchiveError(f"The archive contains a link that leads outside its folder, '{path.relative_to(root)}'.")


def _extract_tar(archive: Path, destination: Path, strip: int) -> None:
    budget = _Budget()
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle:
                budget.entry()
                parts = _clean_parts(member.name, strip)
                if parts is None:
                    continue
                target = _target(destination, parts, member.name)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    os.chmod(target, 0o700)
                elif member.isreg():
                    source = bundle.extractfile(member)
                    if source is None:
                        raise ArchiveError(f"The archive entry '{member.name}' could not be read.")
                    _write_file(source, target, _safe_mode(member.mode, 0o644), budget)
                elif member.issym():
                    _link_is_contained(destination, parts, member.linkname, member.name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(member.linkname, target)
                elif member.islnk():
                    link_parts = _clean_parts(member.linkname, strip)
                    if link_parts is None:
                        raise ArchiveError(f"The archive contains a link to a missing file, '{member.name}'.")
                    origin = _target(destination, link_parts, member.name)
                    if not origin.is_file():
                        raise ArchiveError(f"The archive contains a link to a missing file, '{member.name}'.")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(origin, target)
                    os.chmod(target, _safe_mode(member.mode, 0o644))
                else:
                    raise ArchiveError(f"The archive contains an entry Basil will not unpack, '{member.name}'.")
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise ArchiveError(f"The archive could not be unpacked: {exc}") from exc


def _extract_zip(archive: Path, destination: Path, strip: int) -> None:
    budget = _Budget()
    try:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                budget.entry()
                parts = _clean_parts(info.filename, strip)
                if parts is None:
                    continue
                kind = stat.S_IFMT(info.external_attr >> 16)
                if kind == stat.S_IFLNK:
                    raise ArchiveError(f"The archive contains a link, '{info.filename}', which Basil does not unpack from a zip file.")
                if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ArchiveError(f"The archive contains an entry Basil will not unpack, '{info.filename}'.")
                target = _target(destination, parts, info.filename)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    os.chmod(target, 0o700)
                    continue
                with bundle.open(info) as source:
                    _write_file(source, target, _safe_mode(info.external_attr >> 16, 0o644), budget)
    except (zipfile.BadZipFile, EOFError, OSError) as exc:
        raise ArchiveError(f"The archive could not be unpacked: {exc}") from exc


def extract_archive(archive: Path, kind: str, destination: Path, *, strip_components: int = 0) -> None:
    """Unpack ``archive`` (``tar.gz`` or ``zip``) into ``destination``, which is created when missing. Raises ArchiveError."""
    destination.mkdir(parents=True, exist_ok=True)
    if kind == "tar.gz":
        _extract_tar(archive, destination, strip_components)
    elif kind == "zip":
        _extract_zip(archive, destination, strip_components)
    else:
        raise ArchiveError(f"Basil cannot unpack a {kind} archive.")
    _verify_links(destination)
