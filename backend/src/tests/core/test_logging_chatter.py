"""The per-item chatter logger drops debug lines by default, and the HTTP client request lines are quieted."""

import importlib
import logging

from api.core.logging import chatter
from api.core.logging.api_logger import api_logger


def test_debug_chatter_is_dropped_by_default_even_though_the_main_logger_is_at_debug(monkeypatch):
    monkeypatch.delenv(chatter.VERBOSE_CHATTER_ENV, raising=False)
    reloaded = importlib.reload(chatter)

    assert api_logger.isEnabledFor(logging.DEBUG)
    assert not reloaded.chatter_logger.isEnabledFor(logging.DEBUG)
    assert reloaded.chatter_logger.isEnabledFor(logging.INFO)
    assert reloaded.chatter_logger.isEnabledFor(logging.WARNING)


def test_verbose_chatter_switch_restores_the_debug_lines(monkeypatch):
    monkeypatch.setenv(chatter.VERBOSE_CHATTER_ENV, "1")
    reloaded = importlib.reload(chatter)
    try:
        assert reloaded.chatter_logger.isEnabledFor(logging.DEBUG)
    finally:
        monkeypatch.delenv(chatter.VERBOSE_CHATTER_ENV, raising=False)
        importlib.reload(chatter)


def test_chatter_records_reach_the_main_logger_handlers(monkeypatch):
    monkeypatch.delenv(chatter.VERBOSE_CHATTER_ENV, raising=False)
    reloaded = importlib.reload(chatter)
    seen = []

    class Capture(logging.Handler):
        def emit(self, record):
            seen.append((record.levelno, record.getMessage()))

    handler = Capture(level=logging.DEBUG)
    api_logger.addHandler(handler)
    try:
        reloaded.chatter_logger.debug("dropped")
        reloaded.chatter_logger.info("kept")
        reloaded.chatter_logger.warning("also kept")
    finally:
        api_logger.removeHandler(handler)

    assert seen == [(logging.INFO, "kept"), (logging.WARNING, "also kept")]


def test_http_client_request_lines_are_quieted_but_failures_still_log():
    for name in ("httpx", "httpx2", "httpcore"):
        logger = logging.getLogger(name)
        assert not logger.isEnabledFor(logging.INFO)
        assert logger.isEnabledFor(logging.WARNING)
