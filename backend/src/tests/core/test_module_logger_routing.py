"""A module that names its logger after itself must reach the same handlers as the backend's main logger."""

from __future__ import annotations

import logging

from api.core.logging.api_logger import route_module_loggers_to_handlers


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _scratch_loggers(prefix: str):
    """A parent that does not propagate (as "api.main" does) plus the "scratch" tree whose handlers it should lend."""
    source = logging.getLogger(f"{prefix}.main")
    source.propagate = False
    source.setLevel(logging.INFO)
    handler = _Capture()
    for existing in source.handlers[:]:
        source.removeHandler(existing)
    source.addHandler(handler)
    parent = logging.getLogger(prefix)
    parent.propagate = False
    for existing in parent.handlers[:]:
        parent.removeHandler(existing)
    parent.setLevel(logging.NOTSET)
    return source, parent, handler


def test_a_module_logger_reaches_the_handlers_once_routed():
    source, parent, handler = _scratch_loggers("routing_scratch_a")
    module_logger = logging.getLogger("routing_scratch_a.services.example")

    module_logger.info("before routing")
    assert handler.messages == []

    route_module_loggers_to_handlers(source, "routing_scratch_a")
    module_logger.info("after routing")

    assert handler.messages == ["after routing"]


def test_the_routed_level_follows_the_source_logger():
    source, parent, handler = _scratch_loggers("routing_scratch_b")
    route_module_loggers_to_handlers(source, "routing_scratch_b")
    module_logger = logging.getLogger("routing_scratch_b.services.example")

    module_logger.debug("too quiet")
    module_logger.info("loud enough")

    assert handler.messages == ["loud enough"]


def test_routing_twice_does_not_log_a_line_twice():
    source, parent, handler = _scratch_loggers("routing_scratch_c")
    route_module_loggers_to_handlers(source, "routing_scratch_c")
    route_module_loggers_to_handlers(source, "routing_scratch_c")

    logging.getLogger("routing_scratch_c.services.example").info("once")

    assert handler.messages == ["once"]


def test_the_main_logger_and_its_children_are_not_logged_twice():
    source, parent, handler = _scratch_loggers("routing_scratch_d")
    route_module_loggers_to_handlers(source, "routing_scratch_d")

    source.info("from main")
    logging.getLogger("routing_scratch_d.main.turn_timing").info("from a child of main")

    assert handler.messages == ["from main", "from a child of main"]
