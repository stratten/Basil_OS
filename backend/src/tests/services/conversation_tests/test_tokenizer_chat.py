"""Test script for tokenizer and chat_completion functionality."""

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Any

from api.core.models.token_utils import (
    estimate_tokens,
    detect_context_window,
    count_conversation_tokens,
    truncate_conversation_to_fit
)
from api.core.models.reasoning.base_reasoning import BaseReasoningModel
from api.core.models.model_types import ModelCapability
from api.core.models.base_model import ModelMetadata, ModelState

# Set up logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Create a mock model that implements BaseReasoningModel
class MockReasoningModel(BaseReasoningModel):
    """Mock reasoning model for testing."""
    
    def __init__(self, context_size: int = 4096):
        super().__init__(Path('.'), {ModelCapability.REASONING})
        self.state = ModelState.READY
        self.n_ctx = context_size
        
        # Try to load tokenizer
        try:
            from transformers import AutoTokenizer
            self.tokenizer = AutoTokenizer.from_pretrained("Upstage/SOLAR-10.7B-Instruct-v1.0")
            logger.info(f"Loaded tokenizer: {self.tokenizer.__class__.__name__}")
        except Exception as e:
            logger.warning(f"Failed to load tokenizer: {e}")
            self.tokenizer = None
        
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
        logger.info(f"MockReasoningModel.generate_response called with prompt: {prompt[:100]}...")
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

async def run_token_utils():
    """Test the token utility functions."""
    logger.info("Testing token utility functions")
    
    # Test estimate_tokens
    text = "This is a test message with some content."
    estimated = estimate_tokens(text)
    logger.info(f"Estimated tokens for '{text}': {estimated}")
    
    # Test detect_context_window
    test_paths = [
        Path("solar-10.7b-instruct-v1.0.gguf"),
        Path("llama-2-7b-chat-4k.gguf"),
        Path("mistral-7b-instruct-v0.2-8k.Q4_K_M.gguf"),
        Path("phi-2.Q4_0.gguf"),
        Path("unknown-model.gguf")
    ]
    
    for path in test_paths:
        context = detect_context_window(path)
        logger.info(f"Detected context window for {path}: {context}")
    
    return True

async def run_conversation_truncation():
    """Test conversation truncation functionality."""
    logger.info("Testing conversation truncation")
    
    # Create a conversation that exceeds token limits
    system_message = {"role": "system", "content": "You are a helpful assistant."}
    
    messages = [system_message]
    
    # Add many messages to exceed token limits
    for i in range(50):
        messages.append({
            "role": "user", 
            "content": f"This is message {i} with some content to take up space and tokens. " * 5
        })
        messages.append({
            "role": "assistant", 
            "content": f"This is response {i} with detailed information to consume tokens. " * 5
        })
    
    # Add a final user message
    messages.append({
        "role": "user", 
        "content": "Final question after a long conversation: What is the capital of France?"
    })
    
    # Count tokens
    total_tokens = count_conversation_tokens(messages)
    logger.info(f"Total conversation has {len(messages)} messages and approximately {total_tokens} tokens")
    
    # Test truncation with different limits
    for limit in [1000, 2000, 4000, 8000]:
        truncated = truncate_conversation_to_fit(messages, limit, reserve_tokens=200)
        truncated_tokens = count_conversation_tokens(truncated)
        logger.info(f"Truncated to {limit} tokens: {len(truncated)} messages, ~{truncated_tokens} tokens")
        
        # Verify system message is preserved
        assert truncated[0]["role"] == "system"
        
        # Verify final message is included
        assert truncated[-1]["content"] == "Final question after a long conversation: What is the capital of France?"
    
    return True

async def run_chat_completion():
    """Test the chat_completion method with different context sizes."""
    logger.info("Testing chat_completion with different context sizes")
    
    # Test with different context sizes
    for context_size in [1000, 4096, 8192]:
        logger.info(f"\nTesting with context size: {context_size}")
        model = MockReasoningModel(context_size=context_size)
        
        # Create a conversation
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, how are you?"},
            {"role": "assistant", "content": "I'm doing well, thank you for asking!"},
            {"role": "user", "content": "What can you help me with?"}
        ]
        
        # Add more messages to test truncation
        if context_size > 1000:
            for i in range(10):
                messages.append({
                    "role": "user", 
                    "content": f"This is message {i} with some content. " * 3
                })
                messages.append({
                    "role": "assistant", 
                    "content": f"This is response {i} with some content. " * 3
                })
        
        # Add final message
        messages.append({
            "role": "user", 
            "content": "Final question: What is the capital of France?"
        })
        
        # Call chat_completion
        result = await model.chat_completion(messages)
        
        # Log results
        logger.info(f"Result metadata: {result.get('metadata', {})}")
        logger.info(f"Response starts with: {result['content'][:100]}...")
        
        # Verify the response contains the final question
        assert "Final question" in result["content"]
    
    return True

async def run_tests():
    """Run all tests."""
    tests = [
        run_token_utils(),
        run_conversation_truncation(),
        run_chat_completion()
    ]
    
    results = await asyncio.gather(*tests)
    return all(results)

if __name__ == "__main__":
    success = asyncio.run(run_tests())
    if success:
        logger.info("All tests completed successfully")
        sys.exit(0)
    else:
        logger.error("Tests failed")
        sys.exit(1) 