"""Unit tests for per-turn stage timing (P6)."""

import time

import pytest

from api.services.agent_processing.lifecycle.runtime.turn_timing import (
    TURN_TIMING_CONTEXT_KEY,
    TurnTiming,
    get_or_create_turn_timing,
)


def test_start_stop_records_positive_span():
    timing = TurnTiming(agent_task_id="task-1", root_task_id="root-1")
    timing.start("agent_loop")
    time.sleep(0.01)
    timing.stop("agent_loop")
    assert timing.spans_ms["agent_loop"] >= 5.0


def test_mark_point_first_write_wins():
    timing = TurnTiming()
    timing.mark_point("first_reasoning_token")
    first = timing.spans_ms["first_reasoning_token"]
    time.sleep(0.01)
    timing.mark_point("first_reasoning_token")
    assert timing.spans_ms["first_reasoning_token"] == first


def test_summary_dict_includes_total():
    timing = TurnTiming()
    timing.start("synthesis")
    timing.stop("synthesis")
    summary = timing.summary_dict()
    assert "total" in summary
    assert summary["total"] >= 0


def test_get_or_create_turn_timing_returns_same_instance():
    ctx = {"agent_task_id": "a1", "root_task_id": "r1"}
    first = get_or_create_turn_timing(ctx)
    second = get_or_create_turn_timing(ctx)
    assert first is second
    assert ctx[TURN_TIMING_CONTEXT_KEY] is first
    assert first.agent_task_id == "a1"
    assert first.root_task_id == "r1"


def test_get_or_create_turn_timing_none_for_non_dict():
    assert get_or_create_turn_timing(None) is None
    assert get_or_create_turn_timing("not-a-dict") is None


def test_the_summary_is_logged_where_the_backend_log_handlers_listen():
    import logging

    from api.services.agent_processing.lifecycle.runtime import turn_timing as turn_timing_module

    assert turn_timing_module.logger.name.startswith("api.main.")
    main_logger = logging.getLogger("api.main")
    assert turn_timing_module.logger.parent is main_logger or turn_timing_module.logger.name.rsplit(".", 1)[0] == main_logger.name


def test_emit_writes_one_summary_line_with_the_task_ids():
    import logging

    from api.services.agent_processing.lifecycle.runtime import turn_timing as turn_timing_module

    messages: list[str] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            messages.append(record.getMessage())

    handler = _Collect(level=logging.INFO)
    previous_level = turn_timing_module.logger.level
    turn_timing_module.logger.addHandler(handler)
    turn_timing_module.logger.setLevel(logging.INFO)
    try:
        timing = TurnTiming(agent_task_id="task-9", root_task_id="root-9")
        timing.start("agent_loop")
        timing.stop("agent_loop")
        timing.emit()
    finally:
        turn_timing_module.logger.removeHandler(handler)
        turn_timing_module.logger.setLevel(previous_level)
    summaries = [message for message in messages if "TURN_TIMING" in message]
    assert len(summaries) == 1
    assert "agent_task_id=task-9" in summaries[0]
    assert "root=root-9" in summaries[0]
    assert "agent_loop=" in summaries[0]
    assert "total=" in summaries[0]
