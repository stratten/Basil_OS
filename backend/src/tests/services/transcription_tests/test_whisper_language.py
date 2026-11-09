"""The on-demand Whisper path pins the user's language only when the checkpoint can use it."""

from types import SimpleNamespace

from api.services.transcription.processing.whisper_language import whisper_language_kwargs


def _multilingual_model():
    lang_to_id = {"<|en|>": 50259, "<|fr|>": 50265, "<|haw|>": 50352}
    return SimpleNamespace(generation_config=SimpleNamespace(lang_to_id=lang_to_id))


def _english_only_model():
    return SimpleNamespace(generation_config=SimpleNamespace())


def test_supported_language_is_pinned_through_generate_kwargs():
    assert whisper_language_kwargs(_multilingual_model(), "fr") == {"generate_kwargs": {"language": "fr"}}


def test_language_is_normalized_for_case_and_whitespace():
    assert whisper_language_kwargs(_multilingual_model(), "  EN ") == {"generate_kwargs": {"language": "en"}}


def test_three_letter_codes_are_supported():
    assert whisper_language_kwargs(_multilingual_model(), "haw") == {"generate_kwargs": {"language": "haw"}}


def test_auto_unset_and_blank_leave_detection_on():
    model = _multilingual_model()
    assert whisper_language_kwargs(model, "auto") == {}
    assert whisper_language_kwargs(model, None) == {}
    assert whisper_language_kwargs(model, "") == {}
    assert whisper_language_kwargs(model, "   ") == {}


def test_unknown_language_falls_back_to_detection():
    assert whisper_language_kwargs(_multilingual_model(), "xx") == {}


def test_english_only_checkpoint_never_receives_a_language():
    assert whisper_language_kwargs(_english_only_model(), "en") == {}


def test_missing_model_never_raises():
    assert whisper_language_kwargs(None, "en") == {}
