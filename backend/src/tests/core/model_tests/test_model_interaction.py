import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pathlib import Path

from api.core.services.model_service import ModelService, ModelNotFoundError
from api.core.models.model_types import ModelCapability
from api.core.models.base_model import BaseAIModel
from api.core.models.model_downloader import ModelDownloader
from huggingface_hub import snapshot_download  # type: ignore


def _solar_available(model_service: ModelService) -> bool:
    """Return True if Solar is installed or present in HF cache."""
    try:
        if model_service.is_model_downloaded("solar", "base"):
            return True
        # Use the app's own downloader logic to detect installed models
        try:
            downloader = ModelDownloader(model_service.models_dir)
            installed = downloader.get_installed_models()
            if "Solar" in installed and "solar" in installed["Solar"].get("variants", {}):
                return True
        except Exception:
            pass
        # Check HF cache using ModelDownloader config
        cfg = ModelDownloader.MODELS_CONFIG.get("Solar", {}).get("variants", {}).get("solar")
        if cfg and "repo" in cfg and cfg["repo"].get("url", "").startswith("https://huggingface.co/"):
            repo_id = cfg["repo"]["url"].replace("https://huggingface.co/", "")
            revision = cfg["repo"].get("revision", "main")
            # local_files_only=True: succeed if present in local HF cache
            snapshot_download(repo_id=repo_id, revision=revision, local_files_only=True)
            return True
    except Exception:
        pass
    return False


def _resolve_solar_variant(model_service: ModelService) -> str:
    """Return the variant key to use with ModelService.load_model for Solar.

    Prefers the on-disk variant key ('solar') when detected via ModelDownloader,
    otherwise falls back to 'base' to preserve prior behavior.
    """
    try:
        downloader = ModelDownloader(model_service.models_dir)
        installed = downloader.get_installed_models()
        # Installed providers use capitalized provider name per MODELS_CONFIG
        if "Solar" in installed and "solar" in installed["Solar"].get("variants", {}):
            return "solar"
    except Exception:
        pass
    return "base"


def _resolve_solar_model_type(model_service: ModelService) -> str:
    """Return the provider key to use with ModelService.load_model for Solar.

    Prefers the capitalized provider key ('Solar') when detected via
    ModelDownloader (which mirrors app logs), else falls back to 'solar'.
    """
    try:
        downloader = ModelDownloader(model_service.models_dir)
        installed = downloader.get_installed_models()
        if "Solar" in installed:
            return "Solar"
    except Exception:
        pass
    return "solar"

@pytest.fixture
def model_service():
    """Create a test instance of ModelService."""
    models_dir = Path.home() / ".basil" / "models"
    service = ModelService(models_dir=models_dir)
    service.initialize()  # Initialize the service
    return service

@pytest_asyncio.fixture
async def loaded_model(model_service: ModelService) -> BaseAIModel:
    """Load the Solar model once for all tests."""
    # Ensure the target model is actually available; otherwise skip integration tests
    if not _solar_available(model_service):
        pytest.skip("SOLAR model not downloaded. Run download_models.py first.")
    model_type = _resolve_solar_model_type(model_service)
    variant = _resolve_solar_variant(model_service)
    model = await model_service.load_model(model_type, variant, {ModelCapability.REASONING})
    assert model is not None
    return model

@pytest.mark.asyncio
async def test_model_loading(loaded_model: BaseAIModel):
    """Test that we can load the Solar model."""
    assert loaded_model is not None
    assert hasattr(loaded_model, "generate")

@pytest.mark.asyncio
async def test_basic_generation(loaded_model: BaseAIModel):
    """Test basic text generation with Phi-3.5-mini model."""
    prompt = "What is the capital of France?"
    print(f"\nTest basic generation:")
    print(f"Prompt: {prompt}")
    try:
        response = await loaded_model.generate_async(prompt, max_tokens=50)
        print(f"Full response: '{response}'")
        print(f"Response length: {len(response)}")
        print(f"Contains 'Paris': {'Paris' in response}")
    except Exception as e:
        print(f"Error during generation: {str(e)}")
        raise
    
    assert isinstance(response, str)
    assert len(response) > 0
    assert "Paris" in response  # Basic sanity check

def test_model_capabilities(model_service: ModelService):
    """Test that model capabilities are correctly reported."""
    available_models = model_service.get_available_models()
    assert len(available_models) > 0

    for model_data in available_models.values():
        variants = model_data.get("variants", {"default": model_data})
        for variant_data in variants.values():
            assert "capabilities" in variant_data
            assert isinstance(variant_data["capabilities"], list)
            for capability in variant_data["capabilities"]:
                assert capability in {item.name.lower() for item in ModelCapability}

@pytest.mark.asyncio
async def test_error_handling(model_service: ModelService):
    """Test error handling for invalid model requests."""
    with pytest.raises(ModelNotFoundError):
        await model_service.load_model(
            "nonexistent_model",
            "nonexistent_variant",
            {ModelCapability.REASONING}
        )
    
    with pytest.raises(ModelNotFoundError):
        await model_service.load_model(
            "phi35-mini",
            "nonexistent_variant",
            {ModelCapability.REASONING}
        )

@pytest.mark.asyncio
async def test_async_generation(loaded_model: BaseAIModel):
    """Test asynchronous text generation with Phi-3.5-mini model."""
    prompt = "Write a haiku about Python programming."
    print(f"\nTest async generation:")
    print(f"Prompt: {prompt}")
    response = await loaded_model.generate_async(prompt, max_tokens=50)
    print(f"Response: {response}")
    
    assert isinstance(response, str)
    assert len(response) > 0 

@pytest.mark.asyncio
async def test_solar_model_basic(model_service: ModelService):
    """Test basic functionality of the SOLAR model."""
    # Check if model is installed or available in HF cache
    if not _solar_available(model_service):
        pytest.skip("SOLAR model not downloaded. Run download_models.py first.")

    # Load the model
    model_type = _resolve_solar_model_type(model_service)
    variant = _resolve_solar_variant(model_service)
    model = await model_service.load_model(model_type, variant, {ModelCapability.REASONING})
    assert model is not None
    assert model.is_loaded

    # Test basic generation
    response = await model.generate_response(
        "What is the capital of France?",
        max_tokens=50
    )
    assert response is not None
    assert "Paris" in response

    # Test longer context generation
    response = await model.generate_response(
        """Write a short story about a programmer who discovers an AI.
        Keep it under 100 words.""",
        max_tokens=200
    )
    assert response is not None
    assert len(response.split()) <= 100

    # Test instruction following
    response = await model.generate_response(
        """List three programming best practices.
        Format your response as a numbered list.""",
        max_tokens=200
    )
    assert response is not None
    assert "1." in response
    assert "2." in response
    assert "3." in response

@pytest.mark.asyncio
async def test_solar_model_analysis(model_service: ModelService):
    """Test text analysis capabilities of the SOLAR model using generate_response."""
    if not _solar_available(model_service):
        pytest.skip("SOLAR model not downloaded. Run download_models.py first.")

    model_type = _resolve_solar_model_type(model_service)
    variant = _resolve_solar_variant(model_service)
    model = await model_service.load_model(model_type, variant, {ModelCapability.REASONING})

    # Test that the model can analyze text when given an appropriate prompt
    text = """The new software update has significantly improved performance
    and fixed several critical bugs. Users are reporting faster response times
    and better stability."""

    analysis_prompt = f"""Analyze the following text and provide:
1. Overall sentiment (positive, negative, or neutral)
2. Key points
3. Brief summary

Text: {text}

Analysis:"""

    response = await model.generate_response(analysis_prompt, max_tokens=300)
    assert response is not None
    assert len(response) > 0
    # The model should produce some meaningful analysis
    assert len(response) > 50

@pytest.mark.asyncio
async def test_solar_model_error_handling(model_service: ModelService):
    """Test error handling in the SOLAR model."""
    if not _solar_available(model_service):
        pytest.skip("SOLAR model not downloaded. Run download_models.py first.")

    model_type = _resolve_solar_model_type(model_service)
    variant = _resolve_solar_variant(model_service)
    model = await model_service.load_model(
        model_type,
        variant,
        {ModelCapability.REASONING}
    )

    # Test empty prompt
    with pytest.raises(Exception):
        await model.generate_response("")

    # Test invalid max_tokens
    with pytest.raises(Exception):
        await model.generate_response("Test prompt", max_tokens=-1) 