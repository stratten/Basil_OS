import pytest

from api.services.agent_processing.tools.safety.task_auto_approve import (
    MAX_TRACKED_TASKS,
    clear_all_task_auto_approve,
    is_task_auto_approve_enabled,
    set_task_auto_approve,
)


@pytest.fixture(autouse=True)
def _clean_switches():
    clear_all_task_auto_approve()
    yield
    clear_all_task_auto_approve()


def test_a_task_starts_with_the_switch_off():
    assert is_task_auto_approve_enabled("task-1") is False


def test_turning_the_switch_on_and_off_affects_only_that_task():
    assert set_task_auto_approve("task-1", True) is True

    assert is_task_auto_approve_enabled("task-1") is True
    assert is_task_auto_approve_enabled("task-2") is False

    assert set_task_auto_approve("task-1", False) is True
    assert is_task_auto_approve_enabled("task-1") is False


def test_turning_off_a_switch_that_was_never_on_is_harmless():
    assert set_task_auto_approve("task-1", False) is True
    assert is_task_auto_approve_enabled("task-1") is False


def test_surrounding_whitespace_in_the_task_id_does_not_split_the_switch():
    set_task_auto_approve("  task-1 ", True)

    assert is_task_auto_approve_enabled("task-1") is True


@pytest.mark.parametrize("unusable", [None, "", "   ", 5, [], {}])
def test_an_unusable_task_id_never_turns_anything_on(unusable):
    assert set_task_auto_approve(unusable, True) is False
    assert is_task_auto_approve_enabled(unusable) is False


def test_the_oldest_switch_is_forgotten_first_when_too_many_are_tracked():
    for index in range(MAX_TRACKED_TASKS + 1):
        set_task_auto_approve(f"task-{index}", True)

    assert is_task_auto_approve_enabled("task-0") is False
    assert is_task_auto_approve_enabled("task-1") is True
    assert is_task_auto_approve_enabled(f"task-{MAX_TRACKED_TASKS}") is True


def test_turning_a_switch_on_again_keeps_it_among_the_newest():
    for index in range(MAX_TRACKED_TASKS):
        set_task_auto_approve(f"task-{index}", True)
    set_task_auto_approve("task-0", True)
    set_task_auto_approve("one-more", True)

    assert is_task_auto_approve_enabled("task-0") is True
    assert is_task_auto_approve_enabled("task-1") is False
