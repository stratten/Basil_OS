"""Unpacking archives safely: traversal, links, devices, size caps and permissions."""

from __future__ import annotations

import io
import os
import stat
import tarfile
import zipfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import pytest

from api.services.mcp_connectors import local_server_archive
from api.services.mcp_connectors.local_server_archive import ArchiveError, extract_archive

Entry = Tuple[str, Optional[bytes], dict]


def _tar(path: Path, entries: List[Callable[[tarfile.TarFile], None]]) -> Path:
    with tarfile.open(path, "w:gz") as bundle:
        for add in entries:
            add(bundle)
    return path


def _file(name: str, data: bytes = b"data", mode: int = 0o644) -> Callable[[tarfile.TarFile], None]:
    def add(bundle: tarfile.TarFile) -> None:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        info.mode = mode
        bundle.addfile(info, io.BytesIO(data))

    return add


def _folder(name: str) -> Callable[[tarfile.TarFile], None]:
    def add(bundle: tarfile.TarFile) -> None:
        info = tarfile.TarInfo(name)
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        bundle.addfile(info)

    return add


def _special(name: str, kind: bytes, target: str = "") -> Callable[[tarfile.TarFile], None]:
    def add(bundle: tarfile.TarFile) -> None:
        info = tarfile.TarInfo(name)
        info.type = kind
        info.linkname = target
        bundle.addfile(info)

    return add


def test_a_tar_is_unpacked_with_stripped_folders_and_owner_only_permissions(tmp_path):
    archive = _tar(
        tmp_path / "a.tar.gz",
        [_folder("pkg-1.0"), _folder("pkg-1.0/bin"), _file("pkg-1.0/bin/tool", b"#!/bin/sh\n", 0o4755), _file("pkg-1.0/README", b"hi", 0o666)],
    )

    extract_archive(archive, "tar.gz", tmp_path / "out", strip_components=1)

    tool = tmp_path / "out" / "bin" / "tool"
    assert tool.read_bytes() == b"#!/bin/sh\n"
    assert stat.S_IMODE(tool.stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "out" / "README").stat().st_mode) == 0o600
    assert not (tmp_path / "out" / "pkg-1.0").exists()


@pytest.mark.parametrize("name", ["../escape", "a/../../escape", "/etc/escape", "a\\b", "ok/../../x"])
def test_a_path_that_climbs_out_or_is_absolute_is_refused_before_anything_is_written(tmp_path, name):
    archive = _tar(tmp_path / "a.tar.gz", [_file("fine", b"x"), _file(name, b"bad")])

    with pytest.raises(ArchiveError, match="unsafe path|climbs out"):
        extract_archive(archive, "tar.gz", tmp_path / "out")

    assert not (tmp_path / "escape").exists() and not Path("/etc/escape").exists()


def test_a_link_to_an_absolute_path_or_out_of_the_folder_is_refused(tmp_path):
    for number, target in enumerate(("/etc/passwd", "../../outside", "a/../../outside")):
        archive = _tar(tmp_path / f"l{number}.tar.gz", [_special("link", tarfile.SYMTYPE, target)])
        with pytest.raises(ArchiveError, match="link"):
            extract_archive(archive, "tar.gz", tmp_path / f"out{number}")


def test_a_chain_of_links_that_leads_outside_is_caught_after_unpacking(tmp_path):
    archive = _tar(
        tmp_path / "a.tar.gz",
        [_special("here", tarfile.SYMTYPE, "."), _special("up", tarfile.SYMTYPE, "here/..")],
    )

    with pytest.raises(ArchiveError, match="leads outside"):
        extract_archive(archive, "tar.gz", tmp_path / "out")


def test_nothing_can_be_written_through_a_link_to_a_folder_outside(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    archive = _tar(tmp_path / "a.tar.gz", [_special("door", tarfile.SYMTYPE, "inside"), _file("door/file", b"x")])
    (tmp_path / "out").mkdir()
    os.symlink(outside, tmp_path / "out" / "inside")

    with pytest.raises(ArchiveError):
        extract_archive(archive, "tar.gz", tmp_path / "out")

    assert list(outside.iterdir()) == []


def test_a_link_that_stays_inside_is_kept(tmp_path):
    archive = _tar(tmp_path / "a.tar.gz", [_file("lib/real", b"x"), _special("bin-link", tarfile.SYMTYPE, "lib/real")])

    extract_archive(archive, "tar.gz", tmp_path / "out")

    assert (tmp_path / "out" / "bin-link").is_symlink() and (tmp_path / "out" / "bin-link").read_bytes() == b"x"


def test_a_hard_link_to_a_missing_file_and_a_device_are_refused(tmp_path):
    missing = _tar(tmp_path / "m.tar.gz", [_special("copy", tarfile.LNKTYPE, "nothing")])
    with pytest.raises(ArchiveError, match="missing file"):
        extract_archive(missing, "tar.gz", tmp_path / "out1")

    device = _tar(tmp_path / "d.tar.gz", [_special("dev", tarfile.CHRTYPE)])
    with pytest.raises(ArchiveError, match="will not unpack"):
        extract_archive(device, "tar.gz", tmp_path / "out2")


def test_a_file_listed_twice_is_refused(tmp_path):
    archive = _tar(tmp_path / "a.tar.gz", [_file("same", b"1"), _file("same", b"2")])

    with pytest.raises(ArchiveError, match="twice"):
        extract_archive(archive, "tar.gz", tmp_path / "out")


def test_entry_and_size_caps_stop_an_archive_that_would_fill_the_disk(tmp_path, monkeypatch):
    many = _tar(tmp_path / "many.tar.gz", [_file(f"f{number}") for number in range(5)])
    monkeypatch.setattr(local_server_archive, "MAX_ENTRIES", 3)
    with pytest.raises(ArchiveError, match="too many files"):
        extract_archive(many, "tar.gz", tmp_path / "out1")

    monkeypatch.setattr(local_server_archive, "MAX_ENTRIES", 100)
    monkeypatch.setattr(local_server_archive, "MAX_TOTAL_BYTES", 10)
    big = _tar(tmp_path / "big.tar.gz", [_file("big", b"x" * 100)])
    with pytest.raises(ArchiveError, match="more than Basil allows"):
        extract_archive(big, "tar.gz", tmp_path / "out2")


def test_damaged_and_wrong_kind_archives_are_reported_plainly(tmp_path):
    broken = tmp_path / "broken.tar.gz"
    broken.write_bytes(b"not an archive")
    with pytest.raises(ArchiveError, match="could not be unpacked"):
        extract_archive(broken, "tar.gz", tmp_path / "out1")
    with pytest.raises(ArchiveError, match="could not be unpacked"):
        extract_archive(broken, "zip", tmp_path / "out2")
    with pytest.raises(ArchiveError, match="cannot unpack a rar"):
        extract_archive(broken, "rar", tmp_path / "out3")


def _zip(path: Path, *entries: Tuple[str, bytes, int]) -> Path:
    with zipfile.ZipFile(path, "w") as bundle:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            bundle.writestr(info, data)
    return path


def test_a_zip_is_unpacked_with_stripped_folders(tmp_path):
    archive = _zip(tmp_path / "a.zip", ("pkg/bin/tool", b"x", stat.S_IFREG | 0o755), ("pkg/README", b"y", stat.S_IFREG | 0o644), ("pkg/", b"", stat.S_IFDIR | 0o755))

    extract_archive(archive, "zip", tmp_path / "out", strip_components=1)

    assert stat.S_IMODE((tmp_path / "out" / "bin" / "tool").stat().st_mode) == 0o700
    assert (tmp_path / "out" / "README").read_bytes() == b"y"


@pytest.mark.parametrize("name", ["../escape", "/abs", "a\\b"])
def test_a_zip_path_that_escapes_is_refused(tmp_path, name):
    archive = _zip(tmp_path / "a.zip", (name, b"x", stat.S_IFREG | 0o644))

    with pytest.raises(ArchiveError):
        extract_archive(archive, "zip", tmp_path / "out")


def test_a_zip_with_a_link_or_device_is_refused(tmp_path):
    link = _zip(tmp_path / "l.zip", ("link", b"/etc/passwd", stat.S_IFLNK | 0o777))
    with pytest.raises(ArchiveError, match="contains a link"):
        extract_archive(link, "zip", tmp_path / "out1")

    device = _zip(tmp_path / "d.zip", ("dev", b"", stat.S_IFCHR | 0o644))
    with pytest.raises(ArchiveError, match="will not unpack"):
        extract_archive(device, "zip", tmp_path / "out2")
