"""Tests for the Parakeet ONNX session factory and its CoreML compile cache."""

import os
from pathlib import Path

import pytest

from api.services.transcription.backends.parakeet_components.parakeet_session_factory import (
    COREML_CACHE_OPTION,
    COREML_PROVIDER,
    coreml_cache_directory,
    create_parakeet_session_pair,
    providers_with_coreml_cache,
)


class FakeOnnxRuntime:
    """Stands in for the onnxruntime module and records every session creation."""

    def __init__(self, version="1.22.1", fail_when_cache_option_present=False):
        self.__version__ = version
        self.fail_when_cache_option_present = fail_when_cache_option_present
        self.created = []

    def InferenceSession(self, path, sess_options=None, providers=None):
        has_cache_option = any(isinstance(provider, tuple) for provider in providers)
        if self.fail_when_cache_option_present and has_cache_option:
            raise RuntimeError("corrupted compile cache")
        self.created.append((Path(path).name, list(providers)))
        return object()


@pytest.fixture
def bundle(tmp_path):
    bundle_dir = tmp_path / "models" / "parakeet-bundle"
    bundle_dir.mkdir(parents=True)
    encoder = bundle_dir / "encoder-model.onnx"
    decoder = bundle_dir / "decoder_joint-model.onnx"
    encoder.write_bytes(b"encoder-weights")
    decoder.write_bytes(b"decoder-weights")
    return bundle_dir, encoder, decoder


def test_cache_directory_is_stable_for_the_same_files_and_version(tmp_path, bundle):
    bundle_dir, encoder, decoder = bundle
    first = coreml_cache_directory(tmp_path / "storage", "1.22.1", bundle_dir, (encoder, decoder))
    second = coreml_cache_directory(tmp_path / "storage", "1.22.1", bundle_dir, (encoder, decoder))
    assert first == second
    assert first.parent == tmp_path / "storage" / "cache" / "coreml_ep" / "ort-1.22.1"
    assert first.name.startswith("parakeet-bundle-")


def test_cache_directory_changes_when_a_model_file_changes(tmp_path, bundle):
    bundle_dir, encoder, decoder = bundle
    before = coreml_cache_directory(tmp_path / "storage", "1.22.1", bundle_dir, (encoder, decoder))
    encoder.write_bytes(b"encoder-weights-updated")
    os.utime(encoder, ns=(1_000_000_000, 2_000_000_000))
    after = coreml_cache_directory(tmp_path / "storage", "1.22.1", bundle_dir, (encoder, decoder))
    assert before != after


def test_cache_directory_changes_with_the_onnxruntime_version(tmp_path, bundle):
    bundle_dir, encoder, decoder = bundle
    old = coreml_cache_directory(tmp_path / "storage", "1.22.1", bundle_dir, (encoder, decoder))
    new = coreml_cache_directory(tmp_path / "storage", "1.23.0", bundle_dir, (encoder, decoder))
    assert old != new
    assert old.name == new.name
    assert old.parent != new.parent


def test_missing_model_file_raises_instead_of_hashing_nothing(tmp_path, bundle):
    bundle_dir, encoder, _decoder = bundle
    with pytest.raises(FileNotFoundError):
        coreml_cache_directory(
            tmp_path / "storage", "1.22.1", bundle_dir, (encoder, bundle_dir / "missing.onnx")
        )


def test_only_the_coreml_provider_receives_the_cache_option(tmp_path):
    cache_dir = tmp_path / "cache"
    resolved = providers_with_coreml_cache([COREML_PROVIDER, "CPUExecutionProvider"], cache_dir)
    assert resolved == [(COREML_PROVIDER, {COREML_CACHE_OPTION: str(cache_dir)}), "CPUExecutionProvider"]


def test_providers_pass_through_unchanged_without_a_cache_directory():
    assert providers_with_coreml_cache([COREML_PROVIDER, "CPUExecutionProvider"], None) == [
        COREML_PROVIDER,
        "CPUExecutionProvider",
    ]


def test_session_pair_uses_the_cache_for_both_sessions_when_coreml_is_requested(tmp_path, bundle):
    bundle_dir, encoder, decoder = bundle
    ort = FakeOnnxRuntime()
    storage = tmp_path / "storage"
    encoder_session, decoder_session, cache_dir = create_parakeet_session_pair(
        ort, encoder, decoder, object(), [COREML_PROVIDER, "CPUExecutionProvider"], storage, bundle_dir
    )
    assert encoder_session is not None and decoder_session is not None
    assert cache_dir is not None and cache_dir.is_dir()
    expected = [(COREML_PROVIDER, {COREML_CACHE_OPTION: str(cache_dir)}), "CPUExecutionProvider"]
    assert ort.created == [("encoder-model.onnx", expected), ("decoder_joint-model.onnx", expected)]


def test_session_pair_skips_the_cache_when_coreml_is_not_requested(tmp_path, bundle):
    bundle_dir, encoder, decoder = bundle
    ort = FakeOnnxRuntime()
    storage = tmp_path / "storage"
    _enc, _dec, cache_dir = create_parakeet_session_pair(
        ort, encoder, decoder, object(), ["CPUExecutionProvider"], storage, bundle_dir
    )
    assert cache_dir is None
    assert not storage.exists()
    assert ort.created == [
        ("encoder-model.onnx", ["CPUExecutionProvider"]),
        ("decoder_joint-model.onnx", ["CPUExecutionProvider"]),
    ]


def test_corrupted_cache_is_discarded_and_creation_is_retried_without_it(tmp_path, bundle):
    bundle_dir, encoder, decoder = bundle
    ort = FakeOnnxRuntime(fail_when_cache_option_present=True)
    storage = tmp_path / "storage"
    providers = [COREML_PROVIDER, "CPUExecutionProvider"]
    _enc, _dec, cache_dir = create_parakeet_session_pair(
        ort, encoder, decoder, object(), providers, storage, bundle_dir
    )
    assert cache_dir is None
    assert ort.created == [("encoder-model.onnx", providers), ("decoder_joint-model.onnx", providers)]
    leftover = storage / "cache" / "coreml_ep"
    assert not any(path.is_dir() and path.name.startswith("parakeet-bundle-") for path in leftover.rglob("*"))


def test_uncached_failure_is_not_swallowed(tmp_path, bundle):
    bundle_dir, encoder, decoder = bundle

    class AlwaysFails(FakeOnnxRuntime):
        def InferenceSession(self, path, sess_options=None, providers=None):
            raise RuntimeError("model is invalid")

    with pytest.raises(RuntimeError, match="model is invalid"):
        create_parakeet_session_pair(
            AlwaysFails(), encoder, decoder, object(), ["CPUExecutionProvider"], tmp_path / "storage", bundle_dir
        )


def test_unwritable_storage_falls_back_to_loading_without_a_cache(tmp_path, bundle):
    bundle_dir, encoder, decoder = bundle
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("occupied")
    ort = FakeOnnxRuntime()
    providers = [COREML_PROVIDER, "CPUExecutionProvider"]
    _enc, _dec, cache_dir = create_parakeet_session_pair(
        ort, encoder, decoder, object(), providers, blocking_file, bundle_dir
    )
    assert cache_dir is None
    assert ort.created == [("encoder-model.onnx", providers), ("decoder_joint-model.onnx", providers)]
