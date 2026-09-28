#!/usr/bin/env python3
"""
Test script for evaluating the API models integration.
This script tests the API key management system, Claude model, and OpenAI model implementations.
"""

import os
import sys
import asyncio
import json
from pathlib import Path

# Add the Basil src directory to sys.path to allow imports
# When running from the tests directory, we need to adjust the import path
src_path = Path(__file__).parent.parent.parent.parent / "src"
sys.path.append(str(src_path))

# Import required modules
from config.api_keys import api_key_manager, get_api_key
from api.core.models.reasoning.claude_model import ClaudeModel
from api.core.models.reasoning.openai_model import OpenAIModel
from api.core.models.model_types import ModelCapability
from api.core.logging.api_logger import api_logger

# Configure logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("test_api_models")

class APIModelTester:
    """Tester class for API models"""
    
    def __init__(self):
        """Initialize the tester"""
        self.test_results = {
            "api_key_management": {},
            "claude_model": {},
            "openai_model": {}
        }
        
        # Path where models would be installed (we don't actually install anything)
        self.model_path = Path.home() / ".basil" / "models" / "test"
        
        # Create a test message for model generation
        self.test_messages = [
            {"role": "system", "content": "You are a helpful assistant. Keep your responses short and concise for testing purposes."},
            {"role": "user", "content": "Briefly explain what API stands for and why it's important."}
        ]
        
    async def setup(self):
        """Setup for tests"""
        logger.info("Setting up test environment...")
        
        # Ensure the test model path exists
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Clear any existing test data
        try:
            # Clear user keys for testing (we'll restore them later)
            self.original_use_user_keys = api_key_manager.use_user_keys.copy()
            for service in list(api_key_manager.use_user_keys.keys()):
                api_key_manager.clear_user_api_key(service)
        except Exception as e:
            logger.error(f"Error setting up test environment: {e}")
    
    async def teardown(self):
        """Cleanup after tests"""
        logger.info("Cleaning up test environment...")
        try:
            # Restore original key-usage flags (secret values remain in the OS credential store)
            api_key_manager.use_user_keys = self.original_use_user_keys
            api_key_manager._save_flags()
        except Exception as e:
            logger.error(f"Error cleaning up test environment: {e}")
    
    async def test_api_key_management(self):
        """Test API key management functionality"""
        logger.info("Testing API key management...")
        
        test_service = "test_service"
        test_key = "test_key_123"
        
        results = {}
        
        # Test 1: Set user API key
        try:
            api_key_manager.set_user_api_key(test_service, test_key)
            assert api_key_manager.has_user_key(test_service)
            assert api_key_manager.get_api_key(test_service) == test_key
            assert api_key_manager.use_user_keys.get(test_service, False) == True
            results["set_user_api_key"] = "PASS"
        except Exception as e:
            results["set_user_api_key"] = f"FAIL: {str(e)}"
            
        # Test 2: Get API key (user key)
        try:
            key = get_api_key(test_service)
            assert key == test_key
            results["get_api_key_user"] = "PASS"
        except Exception as e:
            results["get_api_key_user"] = f"FAIL: {str(e)}"
            
        # Test 3: Switch to application key
        try:
            api_key_manager.use_application_key(test_service)
            assert api_key_manager.use_user_keys.get(test_service, True) == False
            results["use_application_key"] = "PASS"
        except Exception as e:
            results["use_application_key"] = f"FAIL: {str(e)}"
            
        # Test 4: Clear user API key
        try:
            api_key_manager.clear_user_api_key(test_service)
            assert not api_key_manager.has_user_key(test_service)
            results["clear_user_api_key"] = "PASS"
        except Exception as e:
            results["clear_user_api_key"] = f"FAIL: {str(e)}"
            
        # Test 5: Get API key for existing service (anthropic)
        try:
            key = get_api_key("anthropic")
            assert key is not None and len(key) > 0
            results["get_anthropic_key"] = "PASS"
        except Exception as e:
            results["get_anthropic_key"] = f"FAIL: {str(e)}"
        
        self.test_results["api_key_management"] = results
        
        # Print test results
        logger.info("API Key Management Test Results:")
        for test_name, result in results.items():
            logger.info(f"  {test_name}: {result}")
    
    async def test_claude_model_initialization(self):
        """Test Claude model initialization"""
        logger.info("Testing Claude model initialization...")
        
        results = {}
        claude_model = None
        
        # Test 1: Create model instance
        try:
            claude_model = ClaudeModel(
                model_path=self.model_path,
                required_capabilities={ModelCapability.REASONING}
            )
            assert claude_model is not None
            results["create_instance"] = "PASS"
        except Exception as e:
            results["create_instance"] = f"FAIL: {str(e)}"
            self.test_results["claude_model"] = results
            return

        # Test 2: Check model names dict
        try:
            assert len(claude_model.CLAUDE_MODELS) > 0
            results["model_names"] = "PASS"
        except Exception as e:
            results["model_names"] = f"FAIL: {str(e)}"
        
        # Test 3: Load model
        try:
            await claude_model.load()
            assert claude_model.is_loaded
            results["load_model"] = "PASS"
            
            # Log model information
            logger.info(f"Loaded model: {claude_model.model_name}")
            logger.info(f"Context window: {claude_model.max_context_length}")
            logger.info(f"Max output tokens: {claude_model.max_output_tokens}")
            
        except Exception as e:
            results["load_model"] = f"FAIL: {str(e)}"
            self.test_results["claude_model"] = results
            return
            
        # Test 4: Test model configuration
        try:
            # Configure to use Claude 3.5 Sonnet
            claude_model.configure(model_name="claude-3-5-sonnet-20240620")
            assert claude_model.model_name == "claude-3-5-sonnet-20240620"
            
            # Test Claude 3.7 with extended thinking
            claude_model.configure(model_name="claude-3-7-sonnet-thinking-20250219")
            assert claude_model.extended_thinking_enabled
            assert claude_model.model_name == "claude-3-7-sonnet-thinking-20250219"
            
            # Reset to default model for other tests
            claude_model.configure(model_name="claude-3-5-sonnet-20240620")
            
            results["model_configuration"] = "PASS"
        except Exception as e:
            results["model_configuration"] = f"FAIL: {str(e)}"
        
        self.test_results["claude_model"]["initialization"] = results
        
        # Print test results
        logger.info("Claude Model Initialization Test Results:")
        for test_name, result in results.items():
            logger.info(f"  {test_name}: {result}")
            
        return claude_model
    
    async def test_claude_model_generation(self, claude_model):
        """Test Claude model generation"""
        if claude_model is None or not claude_model.is_loaded:
            logger.error("Claude model is not loaded, skipping generation test")
            self.test_results["claude_model"]["generation"] = {"all_tests": "SKIPPED - Model not loaded"}
            return
            
        logger.info("Testing Claude model generation...")
        
        results = {}
        
        # Test 1: Generate a response
        try:
            response = await claude_model.generate_response(
                prompt="Explain what API stands for and why it's important. Be very brief.",
                max_tokens=100
            )
            
            assert response is not None and len(response) > 0
            logger.info(f"Generated response: {response}")
            results["generate_response"] = "PASS"
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            results["generate_response"] = f"FAIL: {str(e)}"
        
        # Test 2: Chat completion
        try:
            # Convert test messages for the API
            response = ""
            async for token in claude_model.chat_completion_streaming(self.test_messages):
                response += token
                # Print the first token and then dots for progress
                if len(response) <= len(token):
                    print(f"\nFirst token: {token}", end="", flush=True)
                else:
                    print(".", end="", flush=True)
                
            assert response is not None and len(response) > 0
            print("\n")  # New line after dots
            logger.info(f"Generated streaming response: {response}")
            results["chat_completion_streaming"] = "PASS"
        except Exception as e:
            logger.error(f"Error in chat completion streaming: {e}")
            results["chat_completion_streaming"] = f"FAIL: {str(e)}"
            
        self.test_results["claude_model"]["generation"] = results
        
        # Print test results
        logger.info("Claude Model Generation Test Results:")
        for test_name, result in results.items():
            logger.info(f"  {test_name}: {result}")
    
    async def validate_claude_model_output(self, claude_model):
        """Validate the quality of Claude model output with a comprehensive prompt"""
        if claude_model is None or not claude_model.is_loaded:
            logger.error("Claude model is not loaded, skipping validation test")
            self.test_results["claude_model"]["validation"] = {"all_tests": "SKIPPED - Model not loaded"}
            return
            
        logger.info("Validating Claude model output quality...")
        
        results = {}
        
        # Test with a more challenging prompt that tests capabilities
        validation_prompt = [
            {"role": "system", "content": "You are a helpful AI assistant."},
            {"role": "user", "content": "Please demonstrate your capabilities by:\n1. Summarizing what an API is in 2-3 sentences\n2. Listing three best practices for API security\n3. Explaining the difference between REST and GraphQL APIs\n\nKeep your answer concise."}
        ]
        
        try:
            print("\nGenerating comprehensive response:")
            response = ""
            async for token in claude_model.chat_completion_streaming(validation_prompt):
                response += token
                print(".", end="", flush=True)
                
            assert response is not None and len(response) > 0
            print("\n")  # New line after dots
            logger.info(f"Validation response:\n{response}")
            
            # Check if response contains expected sections
            has_api_definition = "API" in response and ("Application Programming Interface" in response or "interfaces" in response.lower())
            has_security = "security" in response.lower() or "authentication" in response.lower() or "authorization" in response.lower()
            has_rest_graphql = "REST" in response and "GraphQL" in response
            
            if has_api_definition and has_security and has_rest_graphql:
                results["comprehensive_response"] = "PASS"
            else:
                missing = []
                if not has_api_definition: missing.append("API definition")
                if not has_security: missing.append("security practices")
                if not has_rest_graphql: missing.append("REST vs GraphQL")
                results["comprehensive_response"] = f"PARTIAL - Missing: {', '.join(missing)}"
        except Exception as e:
            logger.error(f"Error in validation test: {e}")
            results["comprehensive_response"] = f"FAIL: {str(e)}"
            
        self.test_results["claude_model"]["validation"] = results
        
        # Print test results
        logger.info("Claude Model Validation Results:")
        for test_name, result in results.items():
            logger.info(f"  {test_name}: {result}")
    
    async def test_openai_model_initialization(self):
        """Test OpenAI model initialization"""
        logger.info("Testing OpenAI model initialization...")
        
        results = {}
        openai_model = None
        
        # Test 1: Create model instance
        try:
            openai_model = OpenAIModel(
                model_path=self.model_path,
                required_capabilities={ModelCapability.REASONING}
            )
            assert openai_model is not None
            results["create_instance"] = "PASS"
        except Exception as e:
            results["create_instance"] = f"FAIL: {str(e)}"
            self.test_results["openai_model"] = results
            return

        # Test 2: Check model names dict
        try:
            assert len(openai_model.OPENAI_MODELS) > 0
            results["model_names"] = "PASS"
        except Exception as e:
            results["model_names"] = f"FAIL: {str(e)}"
        
        # Test 3: Load model
        try:
            await openai_model.load()
            assert openai_model.is_loaded
            results["load_model"] = "PASS"
            
            # Log model information
            logger.info(f"Loaded model: {openai_model.model_name}")
            logger.info(f"Context window: {openai_model.max_context_length}")
            logger.info(f"Max output tokens: {openai_model.max_output_tokens}")
            logger.info(f"Vision support: {openai_model.vision_enabled}")
            
        except Exception as e:
            results["load_model"] = f"FAIL: {str(e)}"
            self.test_results["openai_model"] = results
            return
            
        # Test 4: Test model configuration
        try:
            # Configure to use GPT-4o
            openai_model.configure(model_name="gpt-4o-2024-05-13")
            assert openai_model.model_name == "gpt-4o-2024-05-13"
            assert openai_model.vision_enabled == True
            
            # Test GPT-4o Mini
            openai_model.configure(model_name="gpt-4o-mini-2024-07-18")
            assert openai_model.model_name == "gpt-4o-mini-2024-07-18"
            assert openai_model.vision_enabled == True
            
            # Test response format parameter
            openai_model.configure(response_format="json_object")
            assert openai_model.response_format == "json_object"
            
            # Reset to default model for other tests
            openai_model.configure(model_name="gpt-4o-2024-05-13", response_format=None)
            
            results["model_configuration"] = "PASS"
        except Exception as e:
            results["model_configuration"] = f"FAIL: {str(e)}"
        
        self.test_results["openai_model"]["initialization"] = results
        
        # Print test results
        logger.info("OpenAI Model Initialization Test Results:")
        for test_name, result in results.items():
            logger.info(f"  {test_name}: {result}")
            
        return openai_model
    
    async def test_openai_model_generation(self, openai_model):
        """Test OpenAI model generation"""
        if openai_model is None or not openai_model.is_loaded:
            logger.error("OpenAI model is not loaded, skipping generation test")
            self.test_results["openai_model"]["generation"] = {"all_tests": "SKIPPED - Model not loaded"}
            return
            
        logger.info("Testing OpenAI model generation...")
        
        results = {}
        
        # Test 1: Generate a response
        try:
            response = await openai_model.generate_response(
                prompt="Explain what API stands for and why it's important. Be very brief.",
                max_tokens=100
            )
            
            assert response is not None and len(response) > 0
            logger.info(f"Generated response: {response}")
            results["generate_response"] = "PASS"
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            results["generate_response"] = f"FAIL: {str(e)}"
        
        # Test 2: Chat completion
        try:
            # Convert test messages for the API
            response = ""
            async for token in openai_model.chat_completion_streaming(self.test_messages):
                response += token
                # Print the first token and then dots for progress
                if len(response) <= len(token):
                    print(f"\nFirst token: {token}", end="", flush=True)
                else:
                    print(".", end="", flush=True)
                
            assert response is not None and len(response) > 0
            print("\n")  # New line after dots
            logger.info(f"Generated streaming response: {response}")
            results["chat_completion_streaming"] = "PASS"
        except Exception as e:
            logger.error(f"Error in chat completion streaming: {e}")
            results["chat_completion_streaming"] = f"FAIL: {str(e)}"
        
        self.test_results["openai_model"]["generation"] = results
        
        # Print test results
        logger.info("OpenAI Model Generation Test Results:")
        for test_name, result in results.items():
            logger.info(f"  {test_name}: {result}")
        
        return True
        
    async def validate_openai_model_output(self, openai_model):
        """Validate OpenAI model output quality"""
        if openai_model is None or not openai_model.is_loaded:
            logger.error("OpenAI model is not loaded, skipping validation test")
            self.test_results["openai_model"]["validation"] = {"all_tests": "SKIPPED - Model not loaded"}
            return
            
        logger.info("Testing OpenAI model output quality...")
        
        results = {}
        
        # Test: Comprehensive response with JSON format
        try:
            print("\nGenerating comprehensive response with JSON format:")
            
            # Configure for JSON output
            openai_model.configure(response_format="json_object")
            
            # Request for a structured analysis in JSON format
            prompt = """
            Generate a structured analysis with the following information:
            1. API Summary: What is an API and its basic purpose
            2. API Security Best Practices: 3 critical security practices
            3. REST vs GraphQL APIs: Key differences
            
            Format your response as a JSON object with these three keys.
            """
            
            # Execute the streaming completion
            response = ""
            async for token in openai_model.chat_completion_streaming([
                {"role": "system", "content": "You are a technical expert. Provide accurate, structured information in JSON format."},
                {"role": "user", "content": prompt}
            ]):
                response += token
                print(".", end="", flush=True)
                
            print("\n")  # New line after dots
            
            # Log the structured response
            logger.info(f"Validation response:\n{response}")
            
            # Check if response seems to be in JSON format
            assert "{" in response and "}" in response
            
            # Reset response format
            openai_model.configure(response_format=None)
            
            results["comprehensive_response"] = "PASS"
        except Exception as e:
            logger.error(f"Error in validation test: {e}")
            results["comprehensive_response"] = f"FAIL: {str(e)}"
        
        self.test_results["openai_model"]["validation"] = results
        
        # Print test results
        logger.info("OpenAI Model Validation Results:")
        for test_name, result in results.items():
            logger.info(f"  {test_name}: {result}")
    
    async def save_test_results(self):
        """Save test results to a file"""
        try:
            results_file = Path(__file__).parent / "api_models_test_results.json"
            with open(results_file, "w") as f:
                json.dump(self.test_results, f, indent=2)
            logger.info(f"Test results saved to {results_file}")
        except Exception as e:
            logger.error(f"Error saving test results: {e}")
    
    async def run_all_tests(self):
        """Run all tests"""
        await self.setup()
        
        # Test API key management
        await self.test_api_key_management()
        
        # Test Claude model
        claude_model = await self.test_claude_model_initialization()
        if claude_model and claude_model.is_loaded:
            await self.test_claude_model_generation(claude_model)
            await self.validate_claude_model_output(claude_model)
            await claude_model.unload()
        
        # Test OpenAI model
        openai_model = await self.test_openai_model_initialization()
        if openai_model and openai_model.is_loaded:
            await self.test_openai_model_generation(openai_model)
            await self.validate_openai_model_output(openai_model)
            await openai_model.unload()
            
        # Save test results
        await self.save_test_results()
        
        # Print test summary
        self.print_summary()
        
        # Clean up
        await self.teardown()
    
    def print_summary(self):
        """Print test summary in a formatted way"""
        print("\n" + "=" * 80)
        print(" " * 30 + "TEST SUMMARY")
        print("=" * 80 + "\n")
        
        def print_category(category, results, indent=0):
            """Print test results for a category"""
            for test_name, result in results.items():
                if isinstance(result, dict):
                    print(" " * indent + f"{test_name}:")
                    print_category(test_name, result, indent + 2)
                else:
                    status = "✅" if "PASS" in result else "❌"
                    print(" " * indent + f"{status} {test_name}: {result}")
        
        # Print each category
        for category, results in self.test_results.items():
            category_display = category.upper().replace("_", " ")
            print(f"{category_display}:")
            print_category(category, results, 2)
            print()
            
        print("=" * 80)


async def main():
    """Main function to run the tests"""
    # Create and run the tester
    tester = APIModelTester()
    await tester.run_all_tests()


if __name__ == "__main__":
    # Run the tests
    asyncio.run(main()) 