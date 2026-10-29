#!/usr/bin/env python3
"""
Test script for evaluating conversation service model selection.
This script tests the conversation service's ability to select API models based on preferences.
"""

import os
import sys
import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

# Add the Basil src directory to sys.path to allow imports
# When running from the tests directory, we need to adjust the import path
src_path = Path(__file__).parent.parent.parent.parent / "src"
sys.path.append(str(src_path))

# Import required modules
from api.services.conversation.conversation_service import ConversationService
from api.services.conversation.conversation_models import (
    Message,
    MessageRole,
    Conversation,
    ConversationError,
    ModelNotAvailableError,
    ConversationResponse
)
from api.core.models.model_types import ModelCapability
from api.core.models.preferences import Preferences, ModelSettings

class ConversationServiceApiModelSelectionManualChecks(unittest.TestCase):
    """Test the conversation service's API model selection."""

    def setUp(self):
        """Set up test environment."""
        # Create mock model service
        self.mock_model_service = MagicMock()
        self.mock_model = AsyncMock()
        
        # Configure the mock model to return a valid response
        self.mock_model.chat_completion.return_value = {
            "content": "This is a test response",
            "metadata": {"model": "test-model"}
        }
        
        # Configure the model service to return the mock model
        self.mock_model_service.load_model = AsyncMock(return_value=self.mock_model)
        self.mock_model_service.get_installed_models.return_value = {
            "test-model": {
                "variants": {
                    "default": {
                        "name": "Test Model",
                        "capabilities": ["reasoning"],
                        "path": "/path/to/model"
                    }
                }
            }
        }
        
        # Create conversation service
        self.conversation_service = ConversationService(self.mock_model_service)

    def create_fresh_conversation(self):
        """Create a fresh conversation for the test."""
        conversation_id = str(uuid.uuid4())
        self.conversation_service._conversations[conversation_id] = Conversation(
            id=conversation_id,
            messages=[
                Message(id=str(uuid.uuid4()), role=MessageRole.SYSTEM, content="You are a helpful assistant."),
            ]
        )
        return conversation_id

    async def run_send_message_with_anthropic_model(self):
        """Test sending a message with Anthropic API model enabled."""
        # Create a fresh conversation for this test
        conversation_id = self.create_fresh_conversation()
        
        # Mock the preferences to enable API models
        with patch('api.core.models.preferences.Preferences.load') as mock_preferences:
            # Configure preferences with API models enabled
            mock_prefs = MagicMock()
            mock_prefs.models.use_api_models = True
            mock_prefs.models.api_provider = "anthropic"
            mock_prefs.models.api_reasoning_model = "claude-3-5-sonnet-20240620"
            mock_preferences.return_value = mock_prefs
            
            # Mock load_model to verify it was called with correct parameters
            self.mock_model_service.load_model = AsyncMock()
            mock_model = AsyncMock()
            mock_model.chat_completion.return_value = {
                "content": "This is a response from Claude API",
                "metadata": {"model": "claude-3-5-sonnet-20240620"}
            }
            self.mock_model_service.load_model.return_value = mock_model
            
            # Send a message
            response = await self.conversation_service.send_message(conversation_id, "Hello, API model!")
            
            # Verify the API model was loaded with correct parameters
            self.mock_model_service.load_model.assert_called_once()
            args, kwargs = self.mock_model_service.load_model.call_args
            self.assertEqual(args[0], "claude")  # model_type
            self.assertEqual(args[1], "claude-3-5-sonnet-20240620")  # variant
            self.assertIn(ModelCapability.REASONING, args[2])  # capabilities
            
            # Verify the response
            self.assertEqual(response.message.content, "This is a response from Claude API")
            self.assertEqual(response.metadata["model"], "claude-3-5-sonnet-20240620")
            
            # Check that the messages were added to the conversation
            self.assertEqual(len(self.conversation_service._conversations[conversation_id].messages), 3)
            self.assertEqual(self.conversation_service._conversations[conversation_id].messages[1].role, MessageRole.USER)
            self.assertEqual(self.conversation_service._conversations[conversation_id].messages[1].content, "Hello, API model!")
            self.assertEqual(self.conversation_service._conversations[conversation_id].messages[2].role, MessageRole.ASSISTANT)
            self.assertEqual(self.conversation_service._conversations[conversation_id].messages[2].content, "This is a response from Claude API")

    async def run_send_message_with_openai_model(self):
        """Test sending a message with OpenAI API model enabled."""
        # Create a fresh conversation for this test
        conversation_id = self.create_fresh_conversation()
        
        # Mock the preferences to enable API models
        with patch('api.core.models.preferences.Preferences.load') as mock_preferences:
            # Configure preferences with API models enabled
            mock_prefs = MagicMock()
            mock_prefs.models.use_api_models = True
            mock_prefs.models.api_provider = "openai"
            mock_prefs.models.api_reasoning_model = "gpt-4o-2024-05-13"
            mock_preferences.return_value = mock_prefs
            
            # Mock load_model to verify it was called with correct parameters
            self.mock_model_service.load_model = AsyncMock()
            mock_model = AsyncMock()
            mock_model.chat_completion.return_value = {
                "content": "This is a response from OpenAI API",
                "metadata": {"model": "gpt-4o-2024-05-13"}
            }
            self.mock_model_service.load_model.return_value = mock_model
            
            # Send a message
            response = await self.conversation_service.send_message(conversation_id, "Hello, OpenAI API model!")
            
            # Verify the API model was loaded with correct parameters
            self.mock_model_service.load_model.assert_called_once()
            args, kwargs = self.mock_model_service.load_model.call_args
            self.assertEqual(args[0], "openai")  # model_type
            self.assertEqual(args[1], "gpt-4o-2024-05-13")  # variant
            self.assertIn(ModelCapability.REASONING, args[2])  # capabilities
            
            # Verify the response
            self.assertEqual(response.message.content, "This is a response from OpenAI API")
            self.assertEqual(response.metadata["model"], "gpt-4o-2024-05-13")
            
            # Check that the messages were added to the conversation
            self.assertEqual(len(self.conversation_service._conversations[conversation_id].messages), 3)
            self.assertEqual(self.conversation_service._conversations[conversation_id].messages[1].role, MessageRole.USER)
            self.assertEqual(self.conversation_service._conversations[conversation_id].messages[1].content, "Hello, OpenAI API model!")
            self.assertEqual(self.conversation_service._conversations[conversation_id].messages[2].role, MessageRole.ASSISTANT)
            self.assertEqual(self.conversation_service._conversations[conversation_id].messages[2].content, "This is a response from OpenAI API")

    async def run_send_message_api_fallback_to_local(self):
        """Test sending a message with API models enabled but API model load fails."""
        # Create a fresh conversation for this test
        conversation_id = self.create_fresh_conversation()
        
        # Mock the preferences to enable API models
        with patch('api.core.models.preferences.Preferences.load') as mock_preferences:
            # Configure preferences with API models enabled
            mock_prefs = MagicMock()
            mock_prefs.models.use_api_models = True
            mock_prefs.models.api_provider = "anthropic"
            mock_prefs.models.api_reasoning_model = "claude-3-5-sonnet-20240620"
            mock_prefs.models.reasoning_model = "Test Model"  # Local model preference
            mock_preferences.return_value = mock_prefs
            
            # Mock load_model to fail for API model but succeed for local model
            self.mock_model_service.load_model = AsyncMock()
            
            # First call (for API model) raises an exception
            local_model = AsyncMock()
            local_model.chat_completion.return_value = {
                "content": "This is a response from local model",
                "metadata": {"model": "test-model"}
            }
            self.mock_model_service.load_model.side_effect = [
                Exception("API model loading failed"),
                local_model
            ]
            
            # Send a message
            response = await self.conversation_service.send_message(conversation_id, "Hello, with fallback!")
            
            # Verify API model was attempted first, then local model
            self.assertEqual(self.mock_model_service.load_model.call_count, 2)
            
            # Verify the response came from the local model
            self.assertEqual(response.message.content, "This is a response from local model")
            
            # Check that the messages were added to the conversation
            self.assertEqual(len(self.conversation_service._conversations[conversation_id].messages), 3)
            self.assertEqual(self.conversation_service._conversations[conversation_id].messages[2].content, "This is a response from local model")

async def run_tests():
    """Run the tests."""
    # Create test instance
    test = ConversationServiceApiModelSelectionManualChecks()
    
    # Set up environment
    test.setUp()
    
    # Run each test
    print("\n==== Testing Anthropic API Model Selection ====")
    await test.run_send_message_with_anthropic_model()
    print("✅ run_send_message_with_anthropic_model: PASSED")
    
    print("\n==== Testing OpenAI API Model Selection ====")
    await test.run_send_message_with_openai_model()
    print("✅ run_send_message_with_openai_model: PASSED")
    
    print("\n==== Testing API Model Fallback ====")
    await test.run_send_message_api_fallback_to_local()
    print("✅ run_send_message_api_fallback_to_local: PASSED")
    
    print("\n==== All tests passed! ====")

if __name__ == "__main__":
    # Run tests
    asyncio.run(run_tests()) 