import sys
sys.path.append('.')

import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Set

from api.core.models.reasoning.base_reasoning import BaseReasoningModel
from api.core.models.model_types import ModelCapability
from api.core.models.base_model import ModelMetadata, ModelState
from api.services.conversation.conversation_models import MessageRole

# Set up logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Create a mock model that implements BaseReasoningModel
class MockReasoningModel(BaseReasoningModel):
    """Mock reasoning model for testing."""
    
    def __init__(self):
        super().__init__(Path('.'), {ModelCapability.REASONING})
        self.state = ModelState.READY
        
    async def load(self) -> None:
        """Mock implementation of load."""
        self.state = ModelState.READY
        
    async def unload(self) -> None:
        """Mock implementation of unload."""
        self.state = ModelState.UNLOADED
        
    def _generate(self, prompt: str, max_tokens: int = 1000) -> str:
        """Mock implementation of _generate."""
        return f"Mock response to: {prompt}"
    
    async def _generate_async(self, prompt: str, max_tokens: int = 1000) -> str:
        """Mock implementation of _generate_async."""
        return self._generate(prompt, max_tokens)
    
    async def generate_response(
        self,
        prompt: str,
        context: Dict[str, Any] = None,
        max_tokens: int = 1000
    ) -> str:
        """Mock implementation of generate_response."""
        logger.info(f"MockReasoningModel.generate_response called with prompt: {prompt[:50]}...")
        if context:
            return f"Mock response with context: {prompt}"
        return f"Mock response: {prompt}"
    
    def validate(self) -> bool:
        """Mock implementation of validate."""
        return True
    
    def get_metadata(self) -> ModelMetadata:
        """Mock implementation of get_metadata."""
        return ModelMetadata(
            name="mock",
            version="1.0",
            source="test",
            capabilities={ModelCapability.REASONING},
            description="Mock model for testing",
            parameters={},
            requirements={},
            memory_requirements="1MB",
            supports_gpu=False
        )

async def run_chat_completion():
    """Test the chat_completion method in BaseReasoningModel."""
    logger.info("Creating mock reasoning model")
    model = MockReasoningModel()
    
    # Test with a simple message
    logger.info("Testing chat_completion with a single message")
    messages = [
        {"role": "user", "content": "Hello, how are you?"}
    ]
    result = await model.chat_completion(messages)
    logger.info(f"Result with single message: {result}")
    assert "content" in result
    assert isinstance(result["content"], str)
    
    # Test with a conversation
    logger.info("Testing chat_completion with a conversation")
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, how are you?"},
        {"role": "assistant", "content": "I'm doing well, thank you for asking!"},
        {"role": "user", "content": "What can you help me with?"}
    ]
    result = await model.chat_completion(messages)
    logger.info(f"Result with conversation: {result}")
    assert "content" in result
    assert isinstance(result["content"], str)
    
    # Test the _format_chat_messages method
    formatted = model._format_chat_messages(messages)
    logger.info(f"Formatted messages:\n{formatted}")
    
    # Verify the formatting
    assert "System: You are a helpful assistant." in formatted
    assert "User: Hello, how are you?" in formatted
    assert "Assistant: I'm doing well, thank you for asking!" in formatted
    assert "User: What can you help me with?" in formatted
    assert formatted.endswith("Assistant: ")
    
    logger.info("All tests passed!")
    return True

if __name__ == "__main__":
    success = asyncio.run(run_chat_completion())
    if success:
        logger.info("Test completed successfully")
        sys.exit(0)
    else:
        logger.error("Test failed")
        sys.exit(1) 