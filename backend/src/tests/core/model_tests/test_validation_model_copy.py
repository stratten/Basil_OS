"""Tests for copying an installed model between models folders in a validation session."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Dict

import pytest

from api.core.models.model_download import artifacts as artifacts_module
from api.core.models.model_download import validation_model_copy as copy_module
from api.core.models.model_download.validation_model_copy import (
    ModelCopyCanceled,
    copy_model,
    plan_model_copy,
)

FILE_MODEL_ID = "Fixture-file-model"
DIRECTORY_MODEL_ID = "Fixture-directory-model"
MANIFEST_MODEL_ID = "Fixture-manifest-model"
COMPANION_MODEL_ID = "Fixture-companion-model"

REGISTRY: Dict[str, dict] = {
    FILE_MODEL_ID: {"download_url": "https://example.test/file/model.gguf", "on_disk_name": "file-model"},
    DIRECTORY_MODEL_ID: {"on_disk_name": "directory-model"},
    MANIFEST_MODEL_ID: {
        "on_disk_name": "manifest-model",
        "artifact_root": "manifest-model",
        "primary_artifact": "model-00001-of-00002.gguf",
        "artifact_files": [
            {"file": "model-00001-of-00002.gguf"},
            {"file": "model-00002-of-00002.gguf"},
        ],
    },
    COMPANION_MODEL_ID: {
        "download_url": "https://example.test/companion/model.gguf",
        "on_disk_name": "companion-model",
        "companion_downloads": [{"file": "mmproj-companion.gguf", "download_url": "https://example.test/mmproj.gguf"}],
    },
}


@pytest.fixture(autouse=True)
def fixture_registry(monkeypatch):
    monkeypatch.setattr(copy_module, "get_model", lambda model_id: REGISTRY.get(model_id))
    monkeypatch.setattr(artifacts_module, "get_model", lambda model_id: REGISTRY.get(model_id))
    monkeypatch.setattr(
        artifacts_module,
        "get_on_disk_name",
        lambda model_id: (REGISTRY.get(model_id) or {}).get("on_disk_name"),
    )


@pytest.fixture
def roots(tmp_path):
    source = tmp_path / "normal-basil-models"
    destination = tmp_path / "session-models"
    source.mkdir()
    destination.mkdir()
    return source, destination


def test_file_model_is_copied_byte_for_byte_and_the_source_is_untouched(roots):
    source, destination = roots
    (source / "file-model.gguf").write_bytes(b"weights" * 4096)

    plan = plan_model_copy(FILE_MODEL_ID, source, destination)
    assert plan is not None
    copy_model(plan)

    assert (destination / "file-model.gguf").read_bytes() == b"weights" * 4096
    assert (source / "file-model.gguf").read_bytes() == b"weights" * 4096
    assert not list(destination.glob("*.copying"))


def test_directory_model_copies_nested_files_and_skips_housekeeping_entries(roots):
    source, destination = roots
    model_dir = source / "directory-model"
    (model_dir / "sub").mkdir(parents=True)
    (model_dir / "config.json").write_text("{}")
    (model_dir / "sub" / "weights.bin").write_bytes(b"abc")
    (model_dir / ".DS_Store").write_bytes(b"junk")
    (model_dir / ".cache").mkdir()
    (model_dir / ".cache" / "metadata").write_text("resume state")

    plan = plan_model_copy(DIRECTORY_MODEL_ID, source, destination)
    assert plan is not None
    copy_model(plan)

    copied = destination / "directory-model"
    assert (copied / "config.json").read_text() == "{}"
    assert (copied / "sub" / "weights.bin").read_bytes() == b"abc"
    assert not (copied / ".DS_Store").exists()
    assert not (copied / ".cache").exists()
    assert not [path for path in destination.iterdir() if path.name.endswith(".copying")]


def test_manifest_model_copies_every_part_and_the_primary_artifact_last(roots):
    source, destination = roots
    root = source / "manifest-model"
    root.mkdir()
    (root / "model-00001-of-00002.gguf").write_bytes(b"one")
    (root / "model-00002-of-00002.gguf").write_bytes(b"two")

    plan = plan_model_copy(MANIFEST_MODEL_ID, source, destination)
    assert plan is not None
    assert plan.files[-1][0].name == "model-00001-of-00002.gguf"
    copy_model(plan)

    assert (destination / "manifest-model" / "model-00001-of-00002.gguf").read_bytes() == b"one"
    assert (destination / "manifest-model" / "model-00002-of-00002.gguf").read_bytes() == b"two"


def test_incomplete_manifest_has_no_plan(roots):
    source, destination = roots
    root = source / "manifest-model"
    root.mkdir()
    (root / "model-00001-of-00002.gguf").write_bytes(b"one")

    assert plan_model_copy(MANIFEST_MODEL_ID, source, destination) is None


def test_companion_file_is_copied_with_the_model_and_a_missing_one_blocks_the_copy(roots):
    source, destination = roots
    (source / "companion-model.gguf").write_bytes(b"main")
    assert plan_model_copy(COMPANION_MODEL_ID, source, destination) is None

    (source / "mmproj-companion.gguf").write_bytes(b"projector")
    plan = plan_model_copy(COMPANION_MODEL_ID, source, destination)
    assert plan is not None
    copy_model(plan)
    assert (destination / "mmproj-companion.gguf").read_bytes() == b"projector"
    assert (destination / "companion-model.gguf").read_bytes() == b"main"


def test_model_the_source_does_not_hold_has_no_plan(roots):
    source, destination = roots
    assert plan_model_copy(FILE_MODEL_ID, source, destination) is None
    assert plan_model_copy("Fixture-not-in-registry", source, destination) is None


def test_canceling_mid_copy_leaves_nothing_that_looks_installed(roots, monkeypatch):
    source, destination = roots
    monkeypatch.setattr(copy_module, "_COPY_CHUNK_BYTES", 1024)
    (source / "file-model.gguf").write_bytes(b"x" * 10_000)
    plan = plan_model_copy(FILE_MODEL_ID, source, destination)
    assert plan is not None
    cancel_event = asyncio.Event()

    def cancel_after_first_chunk(progress, status, metadata=None):
        cancel_event.set()

    with pytest.raises(ModelCopyCanceled):
        copy_model(plan, cancel_after_first_chunk, cancel_event)

    assert not (destination / "file-model.gguf").exists()
    assert not list(destination.glob("*.copying"))


def test_progress_reports_bytes_and_stays_below_complete_until_the_manager_finishes(roots, monkeypatch):
    source, destination = roots
    monkeypatch.setattr(copy_module, "_COPY_CHUNK_BYTES", 1024)
    (source / "file-model.gguf").write_bytes(b"x" * 4096)
    plan = plan_model_copy(FILE_MODEL_ID, source, destination)
    assert plan is not None
    seen = []

    copy_model(plan, lambda progress, status, metadata=None: seen.append((progress, status, dict(metadata or {}))))

    assert seen and all(status == "downloading" for _, status, _ in seen)
    assert all(progress < 1.0 for progress, _, _ in seen)
    assert seen[-1][2]["total_downloaded"] == 4096
    assert seen[-1][2]["total_size"] == 4096
    assert seen[-1][2]["message"] == "Copying from your normal Basil"


class _StubDownloader:
    def __init__(self, models_dir: Path):
        self.models_dir = models_dir

    def get_installed_models(self):
        return {}

    async def download_model(self, *args, **kwargs):  # pragma: no cover - must not run in copy mode
        raise AssertionError("A copy must not start a network download")


def test_download_manager_copy_mode_completes_without_downloading(roots):
    from api.core.services.model_download_manager import DownloadManager

    source, destination = roots
    (source / "file-model.gguf").write_bytes(b"weights" * 100)

    async def scenario():
        manager = DownloadManager(model_downloader=_StubDownloader(destination))
        entry = await manager.start("Fixture", "file-model", copy_source_root=source)
        assert entry.copy_source_root == source
        finished = await manager.wait_for_terminal_status(entry.model_id)
        return finished

    finished = asyncio.run(scenario())

    assert finished is not None
    assert finished.status == "completed"
    assert finished.progress == 1.0
    assert (destination / "file-model.gguf").read_bytes() == b"weights" * 100


def test_download_manager_copy_mode_fails_cleanly_when_the_source_lacks_the_model(roots):
    from api.core.services.model_download_manager import DownloadManager

    source, destination = roots

    async def scenario():
        manager = DownloadManager(model_downloader=_StubDownloader(destination))
        entry = await manager.start("Fixture", "file-model", copy_source_root=source)
        return await manager.wait_for_terminal_status(entry.model_id)

    finished = asyncio.run(scenario())

    assert finished is not None
    assert finished.status == "failed"
    assert "does not have a complete copy" in (finished.error or "")
    assert not (destination / "file-model.gguf").exists()
