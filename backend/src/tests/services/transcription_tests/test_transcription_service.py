import pytest
from api.services.transcription import HuggingFaceTranscriptionService

def test_transcription_service_initialization():
    """Test that the service initializes correctly."""
    service = HuggingFaceTranscriptionService()
    assert not service.is_model_loaded()

def test_model_loading():
    """Test HuggingFace Whisper model loading.

    Pinned to an explicit Whisper model so the test is deterministic
    regardless of the user's selected transcription preference. Without the
    pin, load_model() resolves to whatever model is selected in preferences
    (e.g. a Parakeet/NeMo ONNX model), which the HuggingFace Seq2Seq loader
    cannot parse ('nemo-conformer-tdt'), producing an unrelated failure.
    """
    service = HuggingFaceTranscriptionService(model_id="Whisper Base")
    service.load_model()
    assert service.is_model_loaded()

@pytest.mark.asyncio
async def test_basic_transcription():
    """Test basic transcription with a sample audio file."""
    service = HuggingFaceTranscriptionService()

    async def fake_process_transcription(audio_data, context_info=None):
        assert audio_data == b"test audio data"
        assert context_info is None
        return "test transcription"

    service.transcription_processor.process_transcription = fake_process_transcription

    result = await service.transcribe(b"test audio data")
    assert isinstance(result, str)
    assert len(result) > 0

@pytest.mark.asyncio
async def test_transcription_delegates_before_model_loaded():
    """Test that transcription delegates to the processor before explicit model loading."""
    service = HuggingFaceTranscriptionService()

    async def fake_process_transcription(audio_data, context_info=None):
        assert audio_data == b"test audio data"
        return "lazy transcription"

    service.transcription_processor.process_transcription = fake_process_transcription

    result = await service.transcribe(b"test audio data")
    assert result == "lazy transcription"