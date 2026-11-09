"""Writing a reviewed profile with a backup, and restoring it."""

from types import SimpleNamespace

import pytest

from api.services.memory.context_import.profile_store import (
    ProfileTooLargeError,
    UnknownProfileBackupError,
    restore_profile,
    write_profile,
)

CAPS = {"essentials.md": 100, "user.md": 200}


class FakeMemory:
    def __init__(self, essentials="- old essentials", user="- old user", fail_on=None):
        self.files = {"essentials.md": essentials, "user.md": user}
        self.fail_on = fail_on

    def read_memory_file(self, name):
        return SimpleNamespace(content=self.files[name])

    def replace_memory_file(self, name, content):
        if name == self.fail_on and content.startswith("- new"):
            raise RuntimeError("disk full")
        self.files[name] = content


def test_changed_files_are_written_and_restore_puts_them_back(tmp_path):
    memory = FakeMemory()
    backups = tmp_path / "backups"

    result = write_profile(memory, backups, label="me.md", new_contents={"essentials.md": "- new essentials", "user.md": "- new user"}, caps=CAPS)

    assert result["files_updated"] == ["essentials.md", "user.md"]
    assert memory.files == {"essentials.md": "- new essentials", "user.md": "- new user"}
    restored = restore_profile(memory, backups, result["backup_id"])
    assert restored["files_restored"] == ["essentials.md", "user.md"]
    assert memory.files == {"essentials.md": "- old essentials", "user.md": "- old user"}


def test_only_files_that_differ_are_written_and_backed_up(tmp_path):
    memory = FakeMemory()

    result = write_profile(memory, tmp_path / "backups", label="x", new_contents={"essentials.md": "- new essentials", "user.md": "- old user"}, caps=CAPS)

    assert result["files_updated"] == ["essentials.md"]
    restore_profile(memory, tmp_path / "backups", result["backup_id"])
    assert memory.files["essentials.md"] == "- old essentials"


def test_blank_text_leaves_a_file_alone_and_no_change_means_no_backup(tmp_path):
    memory = FakeMemory()

    result = write_profile(memory, tmp_path / "backups", label="x", new_contents={"essentials.md": "  ", "user.md": "- old user"}, caps=CAPS)

    assert result == {"backup_id": None, "files_updated": [], "label": "x"}
    assert not (tmp_path / "backups").exists()
    assert memory.files == {"essentials.md": "- old essentials", "user.md": "- old user"}


def test_an_over_limit_text_is_refused_before_anything_is_written(tmp_path):
    memory = FakeMemory()

    with pytest.raises(ProfileTooLargeError, match="essentials.md"):
        write_profile(memory, tmp_path / "backups", label="x", new_contents={"essentials.md": "- " + "x" * 150, "user.md": "- new user"}, caps=CAPS)

    assert memory.files == {"essentials.md": "- old essentials", "user.md": "- old user"}
    assert not (tmp_path / "backups").exists()


def test_a_failure_part_way_puts_the_earlier_file_back(tmp_path):
    memory = FakeMemory(fail_on="user.md")

    with pytest.raises(RuntimeError, match="disk full"):
        write_profile(memory, tmp_path / "backups", label="x", new_contents={"essentials.md": "- new essentials", "user.md": "- new user"}, caps=CAPS)

    assert memory.files == {"essentials.md": "- old essentials", "user.md": "- old user"}


@pytest.mark.parametrize("backup_id", ["../escape", "profile-xyz", "", "profile-000000000000"])
def test_an_invalid_or_missing_backup_id_is_a_clear_error(tmp_path, backup_id):
    with pytest.raises(UnknownProfileBackupError):
        restore_profile(FakeMemory(), tmp_path, backup_id)


def test_a_backup_can_be_restored_only_once(tmp_path):
    memory = FakeMemory()
    result = write_profile(memory, tmp_path / "backups", label="x", new_contents={"essentials.md": "- new essentials"}, caps=CAPS)
    restore_profile(memory, tmp_path / "backups", result["backup_id"])

    with pytest.raises(UnknownProfileBackupError):
        restore_profile(memory, tmp_path / "backups", result["backup_id"])
