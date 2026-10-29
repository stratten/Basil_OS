import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from api.core.logging.api_logger import QuietPollingAccessLogFilter
from api.core.services.model_download_manager import DownloadManager


def _access_record(method: str, path: str, status: int) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:54806", method, path, "1.1", status),
        exc_info=None,
    )


def test_successful_active_download_polls_are_dropped_from_the_access_log() -> None:
    assert QuietPollingAccessLogFilter().filter(_access_record("GET", "/models/download/active", 200)) is False
    assert QuietPollingAccessLogFilter().filter(_access_record("GET", "/models/download/active?x=1", 200)) is False


def test_failed_polls_and_other_requests_stay_in_the_access_log() -> None:
    log_filter = QuietPollingAccessLogFilter()

    assert log_filter.filter(_access_record("GET", "/models/download/active", 500)) is True
    assert log_filter.filter(_access_record("POST", "/models/download/active", 200)) is True
    assert log_filter.filter(_access_record("GET", "/models/download/status", 200)) is True


def test_unexpected_access_record_shapes_are_kept() -> None:
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, "plain message", None, None)

    assert QuietPollingAccessLogFilter().filter(record) is True


def _manager(tmp_path: Path) -> DownloadManager:
    return DownloadManager(max_concurrent=1, model_downloader=SimpleNamespace(models_dir=tmp_path))


@pytest.mark.asyncio
async def test_enqueuing_a_download_announces_it_so_clients_poll_immediately(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    with patch.object(manager, "_is_installed", return_value=False), patch.object(
        manager, "_run", new=AsyncMock()
    ), patch(
        "api.services.websocket_connection_manager.broadcast_json_text", new_callable=AsyncMock
    ) as send:
        entry = await manager.start("whisper", "base")
        await manager.start("whisper", "base")

    assert entry.status == "queued"
    send.assert_awaited_once_with({"event_type": "model_download_activity"})


@pytest.mark.asyncio
async def test_already_installed_models_are_not_announced(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    with patch.object(manager, "_is_installed", return_value=True), patch(
        "api.services.websocket_connection_manager.broadcast_json_text", new_callable=AsyncMock
    ) as send:
        entry = await manager.start("whisper", "base")

    assert entry.status == "skipped_installed"
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failed_announcement_never_blocks_the_enqueue(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    with patch.object(manager, "_is_installed", return_value=False), patch.object(
        manager, "_run", new=AsyncMock()
    ), patch(
        "api.services.websocket_connection_manager.broadcast_json_text",
        new=AsyncMock(side_effect=RuntimeError("socket closed")),
    ):
        entry = await manager.start("whisper", "base")

    assert entry.status == "queued"
