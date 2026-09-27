"""
Tests for the shared anti-repetition decode parameters.

Beyond the dict shape, these assert that every kwarg name is actually accepted
by the installed transformers (4.53.1) Whisper generate and faster-whisper
(1.1.1) transcribe APIs - i.e. the "no kwarg/runtime error" half of the venv
harness, deterministically and without loading a 1.6GB model.
"""
import inspect

from api.services.transcription.local_model.whisper_decode_params import (
    hf_generate_kwargs,
    faster_whisper_kwargs,
)


def test_hf_kwargs_shape():
    kwargs = hf_generate_kwargs()
    assert kwargs["no_repeat_ngram_size"] == 3
    assert kwargs["repetition_penalty"] == 1.15
    assert isinstance(kwargs["temperature"], tuple)
    assert kwargs["temperature"][0] == 0.0 and len(kwargs["temperature"]) > 1
    assert kwargs["condition_on_prev_tokens"] is False


def test_faster_whisper_kwargs_shape():
    kwargs = faster_whisper_kwargs()
    assert kwargs["condition_on_previous_text"] is False
    assert kwargs["no_repeat_ngram_size"] == 3
    assert kwargs["repetition_penalty"] == 1.15
    # faster-whisper spells it log_prob_threshold and wants a list.
    assert "log_prob_threshold" in kwargs
    assert isinstance(kwargs["temperature"], list)


def test_hf_kwargs_accepted_by_whisper_generate():
    from transformers.models.whisper.generation_whisper import (
        WhisperGenerationMixin,
    )
    from transformers import GenerationConfig

    generate_params = set(inspect.signature(WhisperGenerationMixin.generate).parameters)
    generation_config_fields = set(vars(GenerationConfig()))

    for name in hf_generate_kwargs():
        assert (
            name in generate_params or name in generation_config_fields
        ), f"HF generate_kwargs key not accepted by transformers: {name}"


def test_faster_whisper_kwargs_accepted_by_transcribe():
    from faster_whisper import WhisperModel

    transcribe_params = set(inspect.signature(WhisperModel.transcribe).parameters)
    for name in faster_whisper_kwargs():
        assert name in transcribe_params, (
            f"faster-whisper kwarg not accepted by transcribe(): {name}"
        )
