"""
Direct HTTP streaming implementation for OpenAI APIs to bypass SDK hanging issues.

This module provides direct HTTP request implementations for OpenAI streaming
to bypass the problematic OpenAI SDK async handling that causes hangs when
web search is enabled.
"""

import json
import requests
from typing import Generator, List, Dict
import logging

# Get logger for this module
api_logger = logging.getLogger("basil.api.openai_direct_http")


class OpenAIDirectHTTPStreaming:
    """Direct HTTP implementation for OpenAI streaming APIs using synchronous requests."""
    
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
    
    def _create_session(self) -> requests.Session:
        """Create a fresh HTTP session for each request."""
        session = requests.Session()
        session.timeout = (10.0, 120.0)  # (connect, read) timeouts
        return session
    
    def stream_responses_api(self, model: str, messages: List[Dict], 
                           max_tokens: int = 1000, enable_web_search: bool = False,
                           reasoning_effort: str | None = None) -> Generator[str, None, None]:
        """Stream responses using OpenAI Responses API with synchronous requests."""
        api_logger.info(f"🔍 CHECKPOINT 1: stream_responses_api called with model={model}, web_search={enable_web_search}")
        
        # Create fresh session for this request
        session = self._create_session()
        api_logger.info(f"🔍 CHECKPOINT 2: HTTP session created successfully")
        
        try:
            # Build request data
            payload = {
                "model": model,
                "instructions": "You are a helpful assistant.",
                "input": messages,
                "max_output_tokens": max_tokens,
                "stream": True
            }
            if reasoning_effort:
                payload["reasoning"] = {"effort": reasoning_effort}
            
            # Add web search tool if enabled
            if enable_web_search:
                payload["tools"] = [{"type": "web_search"}]
                api_logger.info(f"🔍 DIRECT_HTTP_RESPONSES: Added web_search tool")
            
            # Headers
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            # URL
            url = f"{self.base_url}/responses"
            
            api_logger.info(f"🌐 DIRECT_HTTP_RESPONSES: Starting stream for {model} with web_search={enable_web_search}")
            api_logger.info(f"🚀 DIRECT_HTTP_RESPONSES: Making request to {url}")
            
            # Add checkpoint right before the HTTP call
            api_logger.info(f"🔍 CHECKPOINT 4: About to initiate session.post() call")
            api_logger.info(f"🔍 CHECKPOINT 4.1: URL={url}")
            api_logger.info(f"🔍 CHECKPOINT 4.2: Headers present: {bool(headers)}")
            api_logger.info(f"🔍 CHECKPOINT 4.3: Payload keys: {list(payload.keys())}")
            api_logger.info(f"🔍 CHECKPOINT 4.4: Payload size: {len(str(payload))} chars")
            api_logger.info(f"🔍 CHECKPOINT 4.5: EXACT PAYLOAD: {payload}")
            
            # Test connectivity before main request
            api_logger.info(f"🔍 CHECKPOINT 4.9: Testing basic connectivity to OpenAI...")
            try:
                # Simple GET request to test connectivity
                test_response = session.get("https://api.openai.com/v1/models", 
                                          headers={"Authorization": f"Bearer {self.api_key}"})
                api_logger.info(f"🔍 CHECKPOINT 4.9.1: Connectivity test completed - status: {test_response.status_code}")
                if test_response.status_code != 200:
                    api_logger.error(f"🔍 CHECKPOINT 4.9.2: Connectivity test failed - response: {test_response.text[:200]}")
                else:
                    api_logger.info(f"🔍 CHECKPOINT 4.9.3: Connectivity test successful")
            except Exception as e:
                api_logger.error(f"🔍 CHECKPOINT 4.9.4: Connectivity test exception: {e}")
                raise
            
            # Make streaming request
            api_logger.info(f"🔍 CHECKPOINT 5: Starting streaming POST request")
            
            response = session.post(
                url,
                headers=headers,
                json=payload,
                stream=True
            )
            
            api_logger.info(f"🔍 CHECKPOINT 6: Response received - status: {response.status_code}")
            
            if response.status_code != 200:
                api_logger.error(f"❌ HTTP {response.status_code}: {response.text}")
                raise Exception(f"OpenAI API error: {response.status_code} - {response.text}")
            
            api_logger.info(f"🔍 CHECKPOINT 7: Starting to read response lines")
            
            # Process streaming response
            for line in response.iter_lines():
                if not line:
                    continue
                    
                api_logger.info(f"🔍 CHECKPOINT 8: Processing line: {line.decode()[:100]}...")
                
                line_str = line.decode('utf-8')
                if line_str.startswith('data: '):
                    data_str = line_str[6:]  # Remove 'data: ' prefix
                    
                    if data_str.strip() == '[DONE]':
                        api_logger.info(f"🔍 CHECKPOINT 10: Stream completed")
                        break
                    
                    try:
                        data = json.loads(data_str)
                        
                        # Handle Responses API format
                        if data.get("type") == "response.output_text.delta":
                            delta = data.get("delta", "")
                            if delta:
                                api_logger.info(f"🔍 CHECKPOINT 9: Extracted token: '{delta[:50]}{'...' if len(delta) > 50 else ''}'")
                                yield delta
                        
                        # Also handle Chat Completions format as fallback
                        elif 'choices' in data and len(data['choices']) > 0:
                            choice = data['choices'][0]
                            if 'delta' in choice and 'content' in choice['delta']:
                                content = choice['delta']['content']
                                if content:
                                    api_logger.info(f"🔍 CHECKPOINT 9: Extracted token: '{content[:50]}{'...' if len(content) > 50 else ''}'")
                                    yield content
                    except json.JSONDecodeError:
                        api_logger.warning(f"⚠️ Failed to parse JSON: {data_str}")
                        continue
            
            api_logger.info(f"🔍 CHECKPOINT 11: Stream processing completed")
            
        except Exception as e:
            api_logger.error(f"❌ DIRECT_HTTP_RESPONSES error: {e}")
            raise
        finally:
            session.close()
            api_logger.info(f"🔍 CHECKPOINT 12: HTTP session closed")
    
    def stream_chat_completions_api(self, model: str, messages: List[Dict], 
                                  max_tokens: int = 1000, enable_web_search: bool = False) -> Generator[str, None, None]:
        """Stream responses using OpenAI Chat Completions API with synchronous requests."""
        api_logger.info(f"🌊 CHAT_COMPLETIONS_DIRECT_HTTP: Starting with model={model}, max_tokens={max_tokens}, web_search={enable_web_search}")
        
        # Create fresh session for this request
        session = self._create_session()
        
        try:
            # Build request data
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "stream": True
            }
            
            # Add web search tool if enabled  
            if enable_web_search:
                payload["tools"] = [{"type": "web_search"}]
                api_logger.info(f"🌐 CHAT_COMPLETIONS_DIRECT_HTTP: Added web_search tool")
            
            # Headers
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            # URL
            url = f"{self.base_url}/chat/completions"
            
            api_logger.info(f"🚀 CHAT_COMPLETIONS_DIRECT_HTTP: Making request to {url}")
            
            # Make streaming request
            response = session.post(
                url,
                headers=headers,
                json=payload,
                stream=True
            )
            
            if response.status_code != 200:
                api_logger.error(f"❌ HTTP {response.status_code}: {response.text}")
                raise Exception(f"OpenAI API error: {response.status_code} - {response.text}")
            
            # Process streaming response
            for line in response.iter_lines():
                if not line:
                    continue
                    
                line_str = line.decode('utf-8')
                if line_str.startswith('data: '):
                    data_str = line_str[6:]  # Remove 'data: ' prefix
                    
                    if data_str.strip() == '[DONE]':
                        break
                    
                    try:
                        data = json.loads(data_str)
                        
                        # Handle Chat Completions format
                        if 'choices' in data and len(data['choices']) > 0:
                            choice = data['choices'][0]
                            if 'delta' in choice and 'content' in choice['delta']:
                                content = choice['delta']['content']
                                if content:
                                    api_logger.info(f"🔍 CHAT_COMPLETIONS: Extracted token: '{content[:50]}{'...' if len(content) > 50 else ''}'")
                                    yield content
                        
                        # Also handle Responses API format as fallback
                        elif data.get("type") == "response.output_text.delta":
                            delta = data.get("delta", "")
                            if delta:
                                api_logger.info(f"🔍 CHAT_COMPLETIONS: Extracted token: '{delta[:50]}{'...' if len(delta) > 50 else ''}'")
                                yield delta
                    except json.JSONDecodeError:
                        api_logger.warning(f"⚠️ Failed to parse JSON: {data_str}")
                        continue
            
        except Exception as e:
            api_logger.error(f"❌ CHAT_COMPLETIONS_DIRECT_HTTP error: {e}")
            raise
        finally:
            session.close()


def create_direct_http_streamer(api_key: str) -> OpenAIDirectHTTPStreaming:
    """Factory function to create a direct HTTP streaming client."""
    return OpenAIDirectHTTPStreaming(api_key) 