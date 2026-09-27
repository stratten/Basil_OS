"""
API Connection Testing Service.

Provides connection testing for custom API endpoints and local path validation.
"""

import logging
from pathlib import Path

from .schemas import (
    ConnectionTestRequest,
    ConnectionTestResponse,
    PathValidationRequest,
    PathValidationResponse,
)
from .huggingface_service import format_size


logger = logging.getLogger(__name__)


# =============================================================================
# CONNECTION TESTER
# =============================================================================


class ConnectionTester:
    """Tests connections to custom model API endpoints."""
    
    async def test_connection(self, request: ConnectionTestRequest) -> ConnectionTestResponse:
        """Test connection to a custom model endpoint.
        
        Dispatches to the appropriate handler based on the handler type.
        """
        from api.core.models.models_registry import ModelHandler
        
        try:
            handler = ModelHandler(request.handler)
        except ValueError:
            return ConnectionTestResponse(
                success=False,
                message=f"Unknown handler type: {request.handler}",
            )
        
        if handler == ModelHandler.OPENAI_COMPATIBLE:
            return await self._test_openai_compatible(request)
        elif handler == ModelHandler.ANTHROPIC_COMPATIBLE:
            return await self._test_anthropic_compatible(request)
        else:
            return ConnectionTestResponse(
                success=False,
                message=f"Connection testing not supported for handler: {handler}",
            )
    
    async def _test_openai_compatible(self, request: ConnectionTestRequest) -> ConnectionTestResponse:
        """Test an OpenAI-compatible endpoint."""
        try:
            from openai import AsyncOpenAI
            
            # Build client with custom base URL.
            client = AsyncOpenAI(
                base_url=request.base_url,
                api_key=request.api_key or "test-key",
            )
            
            # Make a minimal request to verify connectivity.
            response = await client.chat.completions.create(
                model=request.model_identifier,
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1,
            )
            
            return ConnectionTestResponse(
                success=True,
                message=f"Successfully connected to {request.base_url}",
                details={
                    "model": request.model_identifier,
                    "response_id": response.id,
                },
            )
            
        except Exception as e:
            logger.warning(f"OpenAI-compatible test failed: {e}")
            return ConnectionTestResponse(
                success=False,
                message=f"Connection failed: {e}",
            )
    
    async def _test_anthropic_compatible(self, request: ConnectionTestRequest) -> ConnectionTestResponse:
        """Test an Anthropic-compatible endpoint."""
        try:
            from anthropic import AsyncAnthropic
            
            # Build client with custom base URL.
            client = AsyncAnthropic(
                base_url=request.base_url,
                api_key=request.api_key or "test-key",
            )
            
            # Make a minimal request to verify connectivity.
            response = await client.messages.create(
                model=request.model_identifier,
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1,
            )
            
            return ConnectionTestResponse(
                success=True,
                message=f"Successfully connected to {request.base_url}",
                details={
                    "model": request.model_identifier,
                    "response_id": response.id,
                },
            )
            
        except Exception as e:
            logger.warning(f"Anthropic-compatible test failed: {e}")
            return ConnectionTestResponse(
                success=False,
                message=f"Connection failed: {e}",
            )


# =============================================================================
# LOCAL PATH VALIDATION
# =============================================================================


def validate_local_path(request: PathValidationRequest) -> PathValidationResponse:
    """Validate a local model file path.
    
    Checks if the file exists, is readable, and has a valid model extension.
    """
    path = Path(request.path).expanduser().resolve()
    
    if not path.exists():
        return PathValidationResponse(
            valid=False,
            error=f"File does not exist: {path}",
        )
    
    if not path.is_file():
        return PathValidationResponse(
            valid=False,
            error=f"Path is not a file: {path}",
        )
    
    # Check for valid model file extensions.
    valid_extensions = {".gguf", ".bin", ".safetensors", ".pt", ".pth", ".onnx"}
    if path.suffix.lower() not in valid_extensions:
        return PathValidationResponse(
            valid=False,
            error=f"Unsupported file type: {path.suffix}. Expected one of: {', '.join(valid_extensions)}",
        )
    
    # Check readability.
    try:
        with open(path, "rb") as f:
            f.read(1)  # Just try to read 1 byte.
    except PermissionError:
        return PathValidationResponse(
            valid=False,
            error=f"File is not readable: {path}",
        )
    except Exception as e:
        return PathValidationResponse(
            valid=False,
            error=f"Error accessing file: {e}",
        )
    
    # Get file size.
    size_bytes = path.stat().st_size
    
    return PathValidationResponse(
        valid=True,
        resolved_path=str(path),
        size_bytes=size_bytes,
        size_human=format_size(size_bytes),
    )


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

connection_tester = ConnectionTester()
