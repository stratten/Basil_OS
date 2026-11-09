"""A model download must be refused up front when the models volume cannot hold it."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api.core.models.model_download import disk_space
from api.core.models.model_download.disk_space import (
    InsufficientDiskSpaceError,
    cached_repo_gb,
    detected_free_disk_gb,
    disk_shortfall_message,
    download_disk_required_gb,
    format_gb,
    larger_model_blocked_message,
    parse_registry_size_gb,
)
from api.core.runtime import mlx_support
from api.core.services.model_download_manager import DownloadManager

MLX_35B = "Qwen-qwen36-35b-a3b-mlx-4bit"
MLX_35B_TYPE = "Qwen"
MLX_35B_VARIANT = "qwen36-35b-a3b-mlx-4bit"
_BYTES_PER_GB = 1024 ** 3


@pytest.fixture(autouse=True)
def mlx_supported(monkeypatch):
    monkeypatch.setattr(mlx_support, "mlx_runtime_available", lambda: True)


def _manager(tmp_path: Path) -> DownloadManager:
    return DownloadManager(max_concurrent=1, model_downloader=SimpleNamespace(models_dir=tmp_path))


def _free_disk(monkeypatch, free_gb, cached_gb=0.0):
    monkeypatch.setattr(
        "api.core.services.model_download_manager.detected_free_disk_gb", lambda path=None: free_gb
    )
    monkeypatch.setattr("api.core.services.model_download_manager.cached_repo_gb", lambda repo_id: cached_gb)


def test_sizes_are_formatted_for_people():
    assert format_gb(5.64) == "5.6"
    assert format_gb(9.96) == "10.0"
    assert format_gb(41.9) == "42"
    assert format_gb(42.0) == "42"


def test_the_shortfall_message_names_the_model_the_need_the_free_space_and_how_much_to_free():
    message = disk_shortfall_message("Qwen3.6-35B-A3B MLX 4-bit", 42.0, 30.0)

    assert message == (
        "Not enough free disk space to download Qwen3.6-35B-A3B MLX 4-bit. "
        "It needs about 42 GB free while it installs, and this Mac has 30 GB free. "
        "Free up about 12 GB and try again."
    )


def test_the_shortfall_message_never_asks_to_free_less_than_one_gb():
    assert "Free up about 1 GB" in disk_shortfall_message("Model", 10.0, 9.99)


def test_the_larger_model_message_strongly_recommends_freeing_the_space():
    message = larger_model_blocked_message("Qwen3.6-35B-A3B MLX 4-bit", "Qwen3.5-9B MLX 4-bit", 42.0, 30.0)

    assert "memory to run Qwen3.6-35B-A3B MLX 4-bit" in message
    assert "much more capable than Qwen3.5-9B MLX 4-bit" in message
    assert "needs about 42 GB free" in message and "has 30 GB free" in message
    assert "strongly recommends freeing up about 12 GB" in message
    assert "Until then Basil will offer Qwen3.5-9B MLX 4-bit" in message


@pytest.mark.parametrize(
    ("size", "expected"),
    [("20GB", 20.0), ("5.6GB", 5.6), (" 17 gb ", 17.0), ("151MB", None), ("", None), (None, None), ("big", None)],
)
def test_registry_sizes_are_read_only_when_they_are_in_gb(size, expected):
    assert parse_registry_size_gb(size) == expected


def test_a_download_needs_twice_the_size_plus_the_margin():
    assert download_disk_required_gb("20GB") == 42.0
    assert download_disk_required_gb("151MB") is None


def test_what_an_earlier_attempt_left_in_the_cache_counts_toward_the_need():
    assert download_disk_required_gb("20GB", cached_gb=15.0) == 27.0


def test_a_complete_cache_copy_still_leaves_the_need_for_the_installed_copy():
    assert download_disk_required_gb("20GB", cached_gb=20.0) == 22.0
    assert download_disk_required_gb("20GB", cached_gb=500.0) == 22.0


def test_a_negative_cache_reading_is_ignored():
    assert download_disk_required_gb("20GB", cached_gb=-5.0) == 42.0


def test_free_space_is_measured_through_the_nearest_existing_parent(tmp_path: Path):
    free = detected_free_disk_gb(tmp_path / "not" / "created" / "yet")

    assert free is not None and free > 0


def test_an_unreadable_volume_reports_none(monkeypatch, tmp_path: Path):
    def boom(path):
        raise OSError("no volume")

    monkeypatch.setattr(disk_space.shutil, "disk_usage", boom)

    assert detected_free_disk_gb(tmp_path) is None


def test_the_cache_credit_sums_finished_and_partial_files_in_the_repo_blobs_folder(tmp_path: Path):
    blobs = tmp_path / "models--owner--name" / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "finished").write_bytes(b"x" * 1024)
    (blobs / "abc.incomplete").write_bytes(b"x" * 2048)
    (tmp_path / "models--other--repo" / "blobs").mkdir(parents=True)
    (tmp_path / "models--other--repo" / "blobs" / "unrelated").write_bytes(b"x" * 4096)

    assert cached_repo_gb("owner/name", cache_dir=tmp_path) == pytest.approx(3072 / _BYTES_PER_GB)


def test_the_cache_credit_is_zero_for_a_missing_repo_a_missing_id_or_a_missing_cache(tmp_path: Path):
    assert cached_repo_gb("owner/missing", cache_dir=tmp_path) == 0.0
    assert cached_repo_gb(None, cache_dir=tmp_path) == 0.0
    assert cached_repo_gb("owner/name", cache_dir=tmp_path / "no-cache") == 0.0


@pytest.mark.asyncio
async def test_the_manager_refuses_a_model_the_disk_cannot_hold_and_enqueues_nothing(monkeypatch, tmp_path: Path):
    _free_disk(monkeypatch, 30.0)
    manager = _manager(tmp_path)

    with patch.object(manager, "_is_installed", return_value=False), patch.object(manager, "_run", new=AsyncMock()) as run:
        with pytest.raises(InsufficientDiskSpaceError) as raised:
            await manager.start(MLX_35B_TYPE, MLX_35B_VARIANT)

    assert raised.value.model_id == MLX_35B
    assert raised.value.required_gb == 42.0
    assert raised.value.free_gb == 30.0
    assert "Free up about 12 GB and try again." in str(raised.value)
    assert "Qwen3.6-35B-A3B MLX 4-bit" in str(raised.value)
    assert manager.get(MLX_35B) is None
    assert manager.list_all() == []
    run.assert_not_called()


@pytest.mark.asyncio
async def test_the_manager_enqueues_a_model_the_disk_can_hold(monkeypatch, tmp_path: Path):
    _free_disk(monkeypatch, 42.0)
    manager = _manager(tmp_path)

    with patch.object(manager, "_is_installed", return_value=False), patch.object(manager, "_run", new=AsyncMock()), patch(
        "api.services.websocket_connection_manager.broadcast_json_text", new_callable=AsyncMock
    ):
        entry = await manager.start(MLX_35B_TYPE, MLX_35B_VARIANT)

    assert entry.status == "queued"


@pytest.mark.asyncio
async def test_a_retry_is_only_asked_for_the_room_it_still_needs(monkeypatch, tmp_path: Path):
    _free_disk(monkeypatch, 30.0, cached_gb=15.0)
    manager = _manager(tmp_path)

    with patch.object(manager, "_is_installed", return_value=False), patch.object(manager, "_run", new=AsyncMock()), patch(
        "api.services.websocket_connection_manager.broadcast_json_text", new_callable=AsyncMock
    ):
        entry = await manager.start(MLX_35B_TYPE, MLX_35B_VARIANT)

    assert entry.status == "queued"


@pytest.mark.asyncio
async def test_an_installed_model_is_never_refused_for_disk_space(monkeypatch, tmp_path: Path):
    _free_disk(monkeypatch, 0.5)
    manager = _manager(tmp_path)

    with patch.object(manager, "_is_installed", return_value=True):
        entry = await manager.start(MLX_35B_TYPE, MLX_35B_VARIANT)

    assert entry.status == "skipped_installed"


@pytest.mark.asyncio
async def test_a_download_already_in_flight_is_returned_without_a_disk_check(monkeypatch, tmp_path: Path):
    _free_disk(monkeypatch, 42.0)
    manager = _manager(tmp_path)
    with patch.object(manager, "_is_installed", return_value=False), patch.object(manager, "_run", new=AsyncMock()), patch(
        "api.services.websocket_connection_manager.broadcast_json_text", new_callable=AsyncMock
    ):
        first = await manager.start(MLX_35B_TYPE, MLX_35B_VARIANT)
        _free_disk(monkeypatch, 1.0)
        second = await manager.start(MLX_35B_TYPE, MLX_35B_VARIANT)

    assert second is first


@pytest.mark.asyncio
async def test_an_unreadable_free_space_does_not_block_a_download(monkeypatch, tmp_path: Path):
    _free_disk(monkeypatch, None)
    manager = _manager(tmp_path)

    with patch.object(manager, "_is_installed", return_value=False), patch.object(manager, "_run", new=AsyncMock()), patch(
        "api.services.websocket_connection_manager.broadcast_json_text", new_callable=AsyncMock
    ):
        entry = await manager.start(MLX_35B_TYPE, MLX_35B_VARIANT)

    assert entry.status == "queued"


@pytest.mark.asyncio
async def test_a_model_with_no_registry_entry_is_not_checked(monkeypatch, tmp_path: Path):
    _free_disk(monkeypatch, 0.1)
    manager = _manager(tmp_path)

    with patch.object(manager, "_is_installed", return_value=False), patch.object(manager, "_run", new=AsyncMock()), patch(
        "api.services.websocket_connection_manager.broadcast_json_text", new_callable=AsyncMock
    ):
        entry = await manager.start("Nobody", "unregistered-model")

    assert entry.status == "queued"


@pytest.mark.asyncio
async def test_the_download_route_answers_507_with_the_message_the_person_should_read():
    from api.routes.model_routes.predefined_routes import (
        DownloadRequest,
        ModelDownloadRequest,
        download_model,
    )

    error = InsufficientDiskSpaceError(MLX_35B, "Qwen3.6-35B-A3B MLX 4-bit", 42.0, 30.0)
    manager = SimpleNamespace(start=AsyncMock(side_effect=error))
    http_request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(download_manager=manager)))

    with pytest.raises(HTTPException) as raised:
        await download_model(
            DownloadRequest(request=ModelDownloadRequest(model_type=MLX_35B_TYPE, variant=MLX_35B_VARIANT)),
            http_request,
        )

    assert raised.value.status_code == 507
    assert raised.value.detail == str(error)


@pytest.mark.asyncio
async def test_the_download_route_still_answers_500_for_other_failures():
    from api.routes.model_routes.predefined_routes import (
        DownloadRequest,
        ModelDownloadRequest,
        download_model,
    )

    manager = SimpleNamespace(start=AsyncMock(side_effect=RuntimeError("queue broke")))
    http_request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(download_manager=manager)))

    with pytest.raises(HTTPException) as raised:
        await download_model(
            DownloadRequest(request=ModelDownloadRequest(model_type=MLX_35B_TYPE, variant=MLX_35B_VARIANT)),
            http_request,
        )

    assert raised.value.status_code == 500
    assert "queue broke" in raised.value.detail
