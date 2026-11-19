"""Oversized tool results are saved under the task chain's workspace, read back by the same chain, and swept after the retention period."""

import os
import time

import pytest

from api.core.config import api_settings
from api.services.agent_processing.shared.agent_runtime_context import reset_current_agent_context, set_current_agent_context
from api.services.agent_processing.tools.internal_basil_tools.stored_result import store


@pytest.fixture
def chain(monkeypatch, tmp_path):
    monkeypatch.setattr(api_settings.settings, "STORAGE_DIR", tmp_path)
    token = set_current_agent_context({"root_task_id": "chain-1", "agent_task_id": "turn-2"})
    yield tmp_path
    reset_current_agent_context(token)


def _directory(root):
    return root / "agent_task_workspaces" / "chain-1" / ".tool_results"


def test_a_saved_result_reads_back_exactly_including_special_characters(chain):
    text = '{"quote": "\\"", "snow": "\u2603", "line": "a\\nb"}\n' + "x" * 1000

    saved = store.save_result(text)

    assert saved["result_id"].startswith("r-")
    assert saved["size_chars"] == len(text)
    assert saved["file"] == f".tool_results/{saved['result_id']}.txt"
    assert saved["path"].endswith(saved["file"])
    assert store.load_result(saved["result_id"]) == text
    assert (_directory(chain) / f"{saved['result_id']}.txt").is_file()
    assert not list(_directory(chain).glob("*.partial"))


def test_a_later_turn_of_the_same_chain_reads_the_result(chain):
    saved = store.save_result("hello")
    token = set_current_agent_context({"root_task_id": "chain-1", "agent_task_id": "turn-3"})
    try:
        assert store.load_result(saved["result_id"]) == "hello"
    finally:
        reset_current_agent_context(token)


def test_another_chain_cannot_read_it(chain):
    saved = store.save_result("private")
    token = set_current_agent_context({"root_task_id": "chain-other"})
    try:
        assert store.load_result(saved["result_id"]) is None
    finally:
        reset_current_agent_context(token)


@pytest.mark.parametrize("bad", ["", "r-zzzz", "../x", "r-12345678", "r-1a2b3c4d.txt", "/etc/passwd", None, 5])
def test_malformed_and_unknown_ids_return_none(chain, bad):
    assert store.load_result(bad) is None


def test_there_is_nothing_to_save_to_outside_an_agent_run(monkeypatch, tmp_path):
    monkeypatch.setattr(api_settings.settings, "STORAGE_DIR", tmp_path)

    assert store.save_result("x") is None
    assert store.load_result("r-12345678") is None
    assert not (tmp_path / "agent_task_workspaces").exists()


def test_a_failed_write_returns_none_and_leaves_no_partial_file(chain, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(store.os, "replace", refuse)

    assert store.save_result("x") is None
    assert not list(_directory(chain).glob("*"))


def test_the_sweep_removes_only_expired_results_and_then_the_empty_folder(chain):
    old = store.save_result("old")
    new = store.save_result("new")
    scratch = chain / "agent_task_workspaces" / "chain-1" / "scratch.py"
    scratch.write_text("keep me")
    ancient = time.time() - 40 * 86400
    os.utime(_directory(chain) / f"{old['result_id']}.txt", (ancient, ancient))

    assert store.sweep_expired() == 1
    assert store.load_result(old["result_id"]) is None
    assert store.load_result(new["result_id"]) == "new"

    assert store.sweep_expired(now=time.time() + 30 * 86400) == 1
    assert not _directory(chain).exists()
    assert scratch.read_text() == "keep me"


def test_the_sweep_does_nothing_when_no_workspace_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(api_settings.settings, "STORAGE_DIR", tmp_path)

    assert store.sweep_expired() == 0
