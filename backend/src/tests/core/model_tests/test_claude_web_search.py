#!/usr/bin/env python3
"""
Claude Web Search Test Script

This script tests Claude's web search functionality in isolation to identify
why requests are hanging after "Web search tool enabled for Claude".
"""

import os
import sys
import asyncio
import json
import time
from pathlib import Path

# Add the src directory to sys.path to allow imports  
src_path = Path(__file__).parent.parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from config.api_keys import get_api_key
from api.core.models.reasoning.claude_model import ClaudeModel
from api.core.models.model_types import ModelCapability

# Configure logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("test_claude_web_search")

class ClaudeWebSearchTester:
    """Test Claude web search functionality"""
    
    def __init__(self):
        self.model_path = Path.home() / ".basil" / "models" / "test"
        self.model = None
        
    async def setup(self):
        """Setup test environment"""
        logger.info("Setting up Claude web search test...")
        
        # Ensure model path exists
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create Claude model instance
        self.model = ClaudeModel(
            model_path=self.model_path,
            required_capabilities={ModelCapability.REASONING}
        )
        
        # Load the model
        logger.info("Loading Claude model...")
        await self.model.load()
        logger.info(f"Model loaded: {self.model.model_name}")
        
    async def test_basic_request_no_web_search(self):
        """Test basic request without web search"""
        logger.info("Testing basic request without web search...")
        
        start_time = time.time()
        try:
            response = await self.model.generate_response(
                prompt="What is 2 + 2? Just give me the number.",
                max_tokens=10,
                enable_web_search=False  # Explicitly disable
            )
            end_time = time.time()
            
            logger.info(f"✓ Basic request completed in {end_time - start_time:.2f}s")
            logger.info(f"Response: {response}")
            return True
        except Exception as e:
            logger.error(f"✗ Basic request failed: {e}")
            return False
    
    async def test_web_search_request_with_timeout(self):
        """Test web search request with explicit timeout"""
        logger.info("Testing web search request with timeout...")
        
        # The exact query from the logs that's getting stuck
        test_prompt = "Can you do some research and do the QuickBooks Online API? And specifically regarding the estimates object, tell me how we are supposed to know when an estimate is accepted. Is that a different status value or is that a specific parameter?"
        
        start_time = time.time()
        try:
            # Use asyncio.wait_for to add a timeout
            response = await asyncio.wait_for(
                self.model.generate_response(
                    prompt=test_prompt,
                    max_tokens=200,
                    enable_web_search=True
                ),
                timeout=30.0  # 30 second timeout
            )
            end_time = time.time()
            
            logger.info(f"✓ Web search request completed in {end_time - start_time:.2f}s")
            logger.info(f"Response length: {len(response)} characters")
            logger.info(f"Response preview: {response[:200]}...")
            return True
            
        except asyncio.TimeoutError:
            end_time = time.time()
            logger.error(f"✗ Web search request timed out after {end_time - start_time:.2f}s")
            return False
        except Exception as e:
            end_time = time.time()
            logger.error(f"✗ Web search request failed after {end_time - start_time:.2f}s: {e}")
            return False
    
    async def test_simple_web_search(self):
        """Test simple web search request"""
        logger.info("Testing simple web search request...")
        
        start_time = time.time()
        try:
            response = await asyncio.wait_for(
                self.model.generate_response(
                    prompt="What is the current weather in San Francisco? Please search for this information.",
                    max_tokens=100,
                    enable_web_search=True
                ),
                timeout=20.0
            )
            end_time = time.time()
            
            logger.info(f"✓ Simple web search completed in {end_time - start_time:.2f}s")
            logger.info(f"Response: {response}")
            return True
            
        except asyncio.TimeoutError:
            end_time = time.time()
            logger.error(f"✗ Simple web search timed out after {end_time - start_time:.2f}s")
            return False
        except Exception as e:
            end_time = time.time()
            logger.error(f"✗ Simple web search failed after {end_time - start_time:.2f}s: {e}")
            return False
    
    async def test_api_key_and_client_status(self):
        """Test API key and client configuration"""
        logger.info("Testing API key and client status...")
        
        try:
            # Check API key
            api_key = get_api_key("anthropic")
            logger.info(f"✓ API key available: {api_key[:10]}...")
            
            # Check client configuration
            logger.info(f"✓ Sync client: {self.model._client is not None}")
            logger.info(f"✓ Async client: {self.model._async_client is not None}")
            
            # Check model configuration
            logger.info(f"✓ Model supports web search: {self.model._supports_web_search()}")
            logger.info(f"✓ Current model: {self.model.model_name}")
            
            return True
        except Exception as e:
            logger.error(f"✗ API key/client check failed: {e}")
            return False
    
    async def test_direct_anthropic_call(self):
        """Test direct Anthropic API call with web search"""
        logger.info("Testing direct Anthropic API call...")
        
        try:
            from anthropic import AsyncAnthropic
            
            # Use the model's API key
            api_key = get_api_key("anthropic")
            client = AsyncAnthropic(api_key=api_key)
            
            # Make direct API call with web search
            start_time = time.time()
            response = await asyncio.wait_for(
                client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=100,
                    messages=[
                        {"role": "user", "content": "What is 2 + 2? Just give me the number."}
                    ],
                    tools=[
                        {
                            "type": "web_search_20250305",
                            "name": "web_search",
                            "max_uses": 5
                        }
                    ]
                ),
                timeout=15.0
            )
            end_time = time.time()
            
            logger.info(f"✓ Direct API call completed in {end_time - start_time:.2f}s")
            logger.info(f"Response: {response.content[0].text}")
            return True
            
        except asyncio.TimeoutError:
            end_time = time.time()
            logger.error(f"✗ Direct API call timed out after {end_time - start_time:.2f}s")
            return False
        except Exception as e:
            end_time = time.time()
            logger.error(f"✗ Direct API call failed after {end_time - start_time:.2f}s: {e}")
            return False
    
    async def cleanup(self):
        """Cleanup test environment"""
        if self.model:
            await self.model.unload()
    
    async def run_all_tests(self):
        """Run all tests"""
        logger.info("=" * 80)
        logger.info("CLAUDE WEB SEARCH DIAGNOSTIC TEST")
        logger.info("=" * 80)
        
        try:
            await self.setup()
            
            results = {}
            
            # Test API key and client status
            results["api_client_status"] = await self.test_api_key_and_client_status()
            
            # Test basic request without web search
            results["basic_request"] = await self.test_basic_request_no_web_search()
            
            # Test direct Anthropic API call
            results["direct_api_call"] = await self.test_direct_anthropic_call()
            
            # Test simple web search
            results["simple_web_search"] = await self.test_simple_web_search()
            
            # Test the problematic request from logs
            results["problematic_request"] = await self.test_web_search_request_with_timeout()
            
            # Print summary
            logger.info("=" * 80)
            logger.info("TEST RESULTS SUMMARY")
            logger.info("=" * 80)
            
            for test_name, success in results.items():
                status = "✓ PASS" if success else "✗ FAIL"
                logger.info(f"{test_name}: {status}")
            
            # Determine root cause
            logger.info("\nROOT CAUSE ANALYSIS:")
            if not results["api_client_status"]:
                logger.error("❌ API key or client configuration issue")
            elif not results["basic_request"]:
                logger.error("❌ Basic Claude API communication issue")
            elif not results["direct_api_call"]:
                logger.error("❌ Web search tool configuration issue with direct API")
            elif not results["simple_web_search"]:
                logger.error("❌ Web search functionality issue in model wrapper")
            elif not results["problematic_request"]:
                logger.error("❌ Specific request hangs - likely complex web search timeout")
            else:
                logger.info("✅ All tests passed - issue may be intermittent")
                
        except Exception as e:
            logger.error(f"Test setup failed: {e}")
        finally:
            await self.cleanup()

async def main():
    """Main function"""
    tester = ClaudeWebSearchTester()
    await tester.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main()) 