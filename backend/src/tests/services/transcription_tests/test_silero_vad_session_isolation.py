"""Silero live VAD must use a private ONNX session per stream.

Sharing one TorchScript model between the microphone and system-audio
processors has aborted the backend with malloc corruption. These tests
lock the safer load path without starting a live transcription session.
"""

import threading

import numpy as np

from api.services.live_transcription.config_mapper import map_basil_config_to_upstream
from api.services.whisper_live_core.silero_vad_iterator import (
    FixedVADIterator,
    OnnxWrapper,
    load_silero_vad,
)


def test_load_silero_vad_defaults_to_a_fresh_onnx_session() -> None:
    first = load_silero_vad()
    second = load_silero_vad()

    assert isinstance(first, OnnxWrapper)
    assert isinstance(second, OnnxWrapper)
    assert first is not second
    assert first.session is not second.session
    assert isinstance(first._state, np.ndarray)
    assert isinstance(second._state, np.ndarray)


def test_two_onnx_sessions_keep_independent_state() -> None:
    first = load_silero_vad(onnx=True)
    second = load_silero_vad(onnx=True)
    frame = np.zeros(512, dtype=np.float32)

    first_score = float(np.asarray(first(frame, 16000)).item())
    second.reset_states()
    second_score = float(np.asarray(second(frame, 16000)).item())

    assert 0.0 <= first_score <= 1.0
    assert 0.0 <= second_score <= 1.0
    assert first._last_batch_size == 1
    assert second._last_batch_size == 1
    first.reset_states()
    assert first._last_batch_size == 0
    assert second._last_batch_size == 1
    assert isinstance(first._state, np.ndarray)
    assert isinstance(second._state, np.ndarray)


def test_two_onnx_sessions_can_infer_concurrently() -> None:
    first = load_silero_vad(onnx=True)
    second = load_silero_vad(onnx=True)
    frame = np.zeros(512, dtype=np.float32)
    errors: list[BaseException] = []

    def run(model: OnnxWrapper) -> None:
        try:
            for _ in range(40):
                score = float(np.asarray(model(frame, 16000)).item())
                assert 0.0 <= score <= 1.0
        except BaseException as error:
            errors.append(error)

    workers = [
        threading.Thread(target=run, args=(first,)),
        threading.Thread(target=run, args=(second,)),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert errors == []
    assert first.session is not second.session


def test_fixed_vad_iterator_scores_numpy_without_a_torch_tensor() -> None:
    model = load_silero_vad(onnx=True)
    iterator = FixedVADIterator(model)
    result = iterator(np.zeros(512, dtype=np.float32))

    assert result is None or isinstance(result, dict)
    assert isinstance(model._state, np.ndarray)


def test_config_mapper_requests_onnx_vad() -> None:
    mapped = map_basil_config_to_upstream({"model": "Base", "vac": True})

    assert mapped["vac"] is True
    assert mapped["vac_onnx"] is True
