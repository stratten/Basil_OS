"""Client for communicating with the Basil Auth Service for authenticated API model requests."""

import httpx
import json
import logging
from typing import Optional, Dict, Any, AsyncGenerator
from pathlib import Path

from ..core.models.preferences import Preferences, APIKeyPreference
from .auth_service_endpoint import AUTH_SERVICE_URL

logger = logging.getLogger(__name__)

# Settings paths
SETTINGS_DIR = Path.home() / ".basil" / "config"
SETTINGS_FILE = SETTINGS_DIR / "preferences.json"

def load_preferences() -> Preferences:
    """Load preferences from file or return defaults."""
    try:
        return Preferences.load()
    except Exception as e:
        logger.warning(f"Failed to load preferences: {e}")
        return Preferences()


def should_route_through_auth_service() -> bool:
    """Check if requests should be routed through the auth service.
    
    Returns True when Basil Cloud is selected. Legacy app_keys and trial values
    are accepted as aliases for older preference files.
    """
    try:
        preferences = load_preferences()
        preference = preferences.auth.api_key_preference
        cloud_preferences = {
            APIKeyPreference.BASIL_CLOUD,
            APIKeyPreference.APP_KEYS,
            APIKeyPreference.TRIAL,
        }
        
        if preference in cloud_preferences:
            logger.info("🔐 Auth routing: Basil Cloud selected - routing through auth service")
            return True
        
        logger.debug(f"🔐 Auth routing: Not routing through auth service (preference={preference})")
        return False
    except Exception as e:
        logger.warning(f"Failed to check auth routing: {e}")
        return False


def get_access_token() -> Optional[str]:
    """Get the access token from the Swift client via a shared mechanism.
    
    Note: The access token is stored in macOS Keychain by the Swift client.
    For the Python backend to access it, we need a bridge mechanism.
    For now, we'll require the token to be passed with requests.
    """
    # TODO: Implement token retrieval mechanism
    # Options:
    # 1. Swift client passes token to backend on startup
    # 2. Shared keychain access (complex)
    # 3. Token stored in a secure temp file
    return None


class AuthServiceClient:
    """Client for proxying LLM requests through the Basil Auth Service."""
    
    def __init__(self, access_token: Optional[str] = None):
        self.base_url = AUTH_SERVICE_URL
        self.access_token = access_token
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client
    
    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def proxy_request(
        self,
        provider: str,
        model: str,
        messages: list,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False
    ) -> Dict[str, Any]:
        """Proxy an LLM request through the auth service for billing.
        
        Args:
            provider: The LLM provider (anthropic, openai, google)
            model: The model ID
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stream: Whether to stream the response
            
        Returns:
            The LLM response from the auth service
        """
        if not self.access_token:
            raise ValueError("Access token required for auth service requests")
        
        client = await self._get_client()
        
        payload = {
            "provider": provider,
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream
        }
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        logger.info(f"🔐 Proxying request to auth service: provider={provider}, model={model}")
        
        response = await client.post(
            f"{self.base_url}/route/request",
            json=payload,
            headers=headers
        )
        
        if response.status_code == 401:
            raise ValueError("Authentication required - token expired or invalid")
        elif response.status_code == 402:
            raise ValueError("Payment required - please add a payment method")
        elif response.status_code == 403:
            raise ValueError("Subscription inactive - please update your subscription")
        elif response.status_code >= 400:
            error_detail = response.text
            raise ValueError(f"Auth service error ({response.status_code}): {error_detail}")
        
        return response.json()
    
    async def proxy_request_stream(
        self,
        provider: str,
        model: str,
        messages: list,
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> AsyncGenerator[str, None]:
        """Proxy a streaming LLM request through the auth service.
        
        Yields chunks of text as they arrive.
        """
        if not self.access_token:
            raise ValueError("Access token required for auth service requests")
        
        payload = {
            "provider": provider,
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True
        }
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        logger.info(f"🔐 Proxying streaming request to auth service: provider={provider}, model={model}")
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/route/request",
                json=payload,
                headers=headers
            ) as response:
                if response.status_code == 401:
                    raise ValueError("Authentication required - token expired or invalid")
                elif response.status_code == 402:
                    raise ValueError("Payment required - please add a payment method")
                elif response.status_code == 403:
                    raise ValueError("Subscription inactive")
                elif response.status_code >= 400:
                    error_detail = await response.aread()
                    raise ValueError(f"Auth service error ({response.status_code}): {error_detail.decode()}")
                
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            if "content" in chunk:
                                yield chunk["content"]
                        except json.JSONDecodeError:
                            continue


# Singleton instance
_auth_client: Optional[AuthServiceClient] = None


def get_auth_service_client(access_token: Optional[str] = None) -> AuthServiceClient:
    """Get the auth service client singleton."""
    global _auth_client
    if _auth_client is None or (access_token and _auth_client.access_token != access_token):
        _auth_client = AuthServiceClient(access_token)
    return _auth_client


async def cleanup_auth_client():
    """Cleanup the auth service client."""
    global _auth_client
    if _auth_client:
        await _auth_client.close()
        _auth_client = None

