"""
Unit tests for the Whisper model source resolver.

Covers display-name vs registry-id equivalence, repo-id derivation, the
unknown-model error, and the cache_key local/repo selection that lets the
on-demand and post-processing stacks share one warm entry.
"""
from pathlib import Path

import pytest

from api.services.transcription.local_model.whisper_source_resolver import (
    WhisperModelSource,
    resolve_whisper_source,
)


def test_resolve_by_display_name_and_id_match():
    by_name = resolve_whisper_source("Whisper Large V3 Turbo")
    by_id = resolve_whisper_source("OpenAI-whisper-large-v3-turbo")

    assert by_name.model_id == "OpenAI-whisper-large-v3-turbo"
    assert by_id.model_id == by_name.model_id
    assert by_name.on_disk_name == "whisper-large-v3-turbo"
    assert by_name.repo_id == "openai/whisper-large-v3-turbo"
    # Same model resolved two ways must produce the same warm-cache key.
    assert by_name.cache_key == by_id.cache_key


def test_local_dir_uses_models_dir_and_on_disk_name():
    source = resolve_whisper_source("Whisper Large V3 Turbo")
    assert source.local_dir.name == "whisper-large-v3-turbo"
    assert source.local_dir.parent.name == "models"


def test_unknown_model_raises():
    with pytest.raises(ValueError):
        resolve_whisper_source("Not A Real Model 9000")


def test_cache_key_prefers_local_when_present():
    local = WhisperModelSource(
        model_id="id",
        display_name="Model",
        on_disk_name="model-dir",
        local_dir=Path("/tmp/models/model-dir"),
        repo_id="org/model",
        revision="main",
        exists_locally=True,
    )
    assert local.cache_key == "local:/tmp/models/model-dir"


def test_cache_key_falls_back_to_repo_when_absent():
    remote = WhisperModelSource(
        model_id="id",
        display_name="Model",
        on_disk_name="model-dir",
        local_dir=Path("/tmp/models/model-dir"),
        repo_id="org/model",
        revision="main",
        exists_locally=False,
    )
    assert remote.cache_key == "hf:org/model"
