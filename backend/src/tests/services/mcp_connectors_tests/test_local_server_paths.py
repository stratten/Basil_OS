"""The per-connection install and data folders."""

from __future__ import annotations

import pytest

from api.services.mcp_connectors.local_server_paths import (
    connection_folders,
    ensure_connection_folders,
    is_safe_connection_id,
    remove_connection_folders,
)

CONNECTION_ID = "0b2f3c9e-1d44-4e0a-9a53-5f1d2c7b8a10"


@pytest.mark.parametrize("bad", ["", "..", "../x", "a/b", "a\\b", "x" * 65, "has space", "~root", "/abs"])
def test_ids_that_could_leave_the_state_folder_are_refused(tmp_path, bad):
    assert not is_safe_connection_id(bad)
    with pytest.raises(ValueError):
        connection_folders(tmp_path, bad)
    with pytest.raises(ValueError):
        ensure_connection_folders(tmp_path, bad)


def test_looking_up_the_folders_creates_nothing(tmp_path):
    folders = connection_folders(tmp_path, CONNECTION_ID)

    assert folders.install == tmp_path / "connections" / CONNECTION_ID / "install"
    assert folders.data == tmp_path / "connections" / CONNECTION_ID / "data"
    assert not (tmp_path / "connections").exists()


def test_the_folders_are_created_private_and_creating_them_again_keeps_their_contents(tmp_path):
    folders = ensure_connection_folders(tmp_path, CONNECTION_ID)
    (folders.data / "session.db").write_text("keep")

    again = ensure_connection_folders(tmp_path, CONNECTION_ID)

    assert again == folders
    assert (folders.data / "session.db").read_text() == "keep"
    for folder in (folders.install.parent, folders.install, folders.data):
        assert oct(folder.stat().st_mode & 0o777) == "0o700"


def test_removing_a_connection_deletes_its_folders_only(tmp_path):
    ensure_connection_folders(tmp_path, CONNECTION_ID)
    other = ensure_connection_folders(tmp_path, "other-connection")

    remove_connection_folders(tmp_path, CONNECTION_ID)

    assert not (tmp_path / "connections" / CONNECTION_ID).exists()
    assert other.install.exists()


def test_removing_a_missing_connection_or_an_invalid_id_does_nothing(tmp_path):
    remove_connection_folders(tmp_path, CONNECTION_ID)
    remove_connection_folders(tmp_path, "../..")

    assert tmp_path.exists()
