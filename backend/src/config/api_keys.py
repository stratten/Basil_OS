import os
from typing import Dict, Optional
from pathlib import Path
import json
import logging
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_keys")

# Default file locations
USER_CONFIG_DIR = Path.home() / ".basil" / "config"
API_KEYS_FILE = USER_CONFIG_DIR / "api_keys.json"

# Provider API keys are loaded from environment variables or the user's local configuration.
DEFAULT_API_KEYS = {
    "anthropic": "",  # Configure with ANTHROPIC_API_KEY or a user-provided key
    "openai": "",     # Configure with OPENAI_API_KEY or a user-provided key
    "google": "",     # Configure with GOOGLE_API_KEY/GEMINI_API_KEY or a user-provided key
    "gemini": ""      # Alternative key name for Gemini (same as google)
}

class APIKeyManager:
    """Manager for API keys that supports both application default and user-provided keys."""
    
    def __init__(self):
        """Initialize the API key manager."""
        self.user_keys: Dict[str, str] = {}
        self.use_user_keys: Dict[str, bool] = {}
        
        # Create config directory if it doesn't exist
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        
        # Load keys from environment if available
        load_dotenv()
        self._load_env_keys()
        
        # Load user keys from file
        self._load_user_keys()
        
    def _load_env_keys(self) -> None:
        """Load API keys from environment variables."""
        env_anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        if env_anthropic_key:
            DEFAULT_API_KEYS["anthropic"] = env_anthropic_key
            logger.info("Loaded Anthropic API key from environment")
            
        env_openai_key = os.environ.get("OPENAI_API_KEY")
        if env_openai_key:
            DEFAULT_API_KEYS["openai"] = env_openai_key
            logger.info("Loaded OpenAI API key from environment")
        
        # Support both GOOGLE_API_KEY and GEMINI_API_KEY environment variables
        env_google_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if env_google_key:
            DEFAULT_API_KEYS["google"] = env_google_key
            DEFAULT_API_KEYS["gemini"] = env_google_key
            logger.info("Loaded Google/Gemini API key from environment")
    
    def _load_user_keys(self) -> None:
        """Load user API keys from file."""
        if not API_KEYS_FILE.exists():
            logger.info(f"User API keys file not found at {API_KEYS_FILE}, using application defaults")
            return
            
        try:
            with open(API_KEYS_FILE, "r") as f:
                data = json.load(f)
                self.user_keys = data.get("keys", {})
                self.use_user_keys = data.get("use_user_keys", {})
                logger.info(f"Loaded user API keys from {API_KEYS_FILE}")
        except Exception as e:
            logger.error(f"Error loading user API keys: {str(e)}")
    
    def _save_user_keys(self) -> None:
        """Save user API keys to file."""
        try:
            data = {
                "keys": self.user_keys,
                "use_user_keys": self.use_user_keys
            }
            
            with open(API_KEYS_FILE, "w") as f:
                json.dump(data, f, indent=2)
                logger.info(f"Saved user API keys to {API_KEYS_FILE}")
        except Exception as e:
            logger.error(f"Error saving user API keys: {str(e)}")
    
    def get_api_key(self, service: str) -> str:
        """
        Get the API key for the specified service.
        
        Args:
            service: The service name (e.g., 'anthropic', 'openai')
            
        Returns:
            The API key to use
            
        Raises:
            ValueError: If no API key is available for the service
        """
        # Check if we should use user key
        if self.use_user_keys.get(service, False) and service in self.user_keys:
            key = self.user_keys.get(service)
            if key and key.strip():
                return key
        
        # Fall back to application default
        if service in DEFAULT_API_KEYS and DEFAULT_API_KEYS[service]:
            return DEFAULT_API_KEYS[service]
            
        raise ValueError(f"No API key available for {service}")
    
    def set_user_api_key(self, service: str, key: str) -> None:
        """
        Set a user API key for the specified service.
        
        Args:
            service: The service name (e.g., 'anthropic', 'openai')
            key: The API key
        """
        self.user_keys[service] = key
        self.use_user_keys[service] = True
        self._save_user_keys()
        logger.info(f"Set user API key for {service}")
    
    def clear_user_api_key(self, service: str) -> None:
        """
        Clear the user API key for the specified service.
        
        Args:
            service: The service name (e.g., 'anthropic', 'openai')
        """
        if service in self.user_keys:
            del self.user_keys[service]
        self.use_user_keys[service] = False
        self._save_user_keys()
        logger.info(f"Cleared user API key for {service}")
    
    def use_application_key(self, service: str) -> None:
        """
        Set to use the application default key for the specified service.
        
        Args:
            service: The service name (e.g., 'anthropic', 'openai')
        """
        self.use_user_keys[service] = False
        self._save_user_keys()
        logger.info(f"Using application default key for {service}")
    
    def use_user_key(self, service: str) -> None:
        """
        Set to use the user key for the specified service.
        
        Args:
            service: The service name (e.g., 'anthropic', 'openai')
        """
        if service not in self.user_keys or not self.user_keys[service]:
            raise ValueError(f"No user API key set for {service}")
            
        self.use_user_keys[service] = True
        self._save_user_keys()
        logger.info(f"Using user key for {service}")
    
    def is_using_user_key(self, service: str) -> bool:
        """
        Check if using user key for the specified service.
        
        Args:
            service: The service name (e.g., 'anthropic', 'openai')
            
        Returns:
            True if using user key, False if using application default
        """
        return self.use_user_keys.get(service, False)
    
    def has_api_key(self, service: str) -> bool:
        """
        Check if an API key is available for the specified service.
        
        This is useful for custom models to check if their key has been configured.
        
        Args:
            service: The service name (e.g., 'anthropic', 'openai', 'custom_ollama')
            
        Returns:
            True if a key is available (either user-provided or application default)
        """
        # Check user key first.
        if self.use_user_keys.get(service, False) and service in self.user_keys:
            key = self.user_keys.get(service)
            if key and key.strip():
                return True
        
        # Check application default.
        if service in DEFAULT_API_KEYS and DEFAULT_API_KEYS[service]:
            return True
        
        # Also check user keys even if use_user_keys is False (key exists but not active).
        if service in self.user_keys:
            key = self.user_keys.get(service)
            if key and key.strip():
                return True
        
        return False
    
    def get_all_configured_keys(self) -> Dict[str, bool]:
        """
        Get a dictionary of all configured API keys and their status.
        
        Returns:
            Dict mapping service name to whether a key is available.
            Includes both default providers and user-defined custom keys.
        """
        result: Dict[str, bool] = {}
        
        # Add default providers.
        for service in DEFAULT_API_KEYS.keys():
            result[service] = self.has_api_key(service)
        
        # Add any custom user keys not in defaults.
        for service in self.user_keys.keys():
            if service not in result:
                result[service] = self.has_api_key(service)
        
        return result
    
    def list_custom_key_names(self) -> list:
        """
        Get a list of custom (non-default) API key names that have been configured.
        
        Returns:
            List of custom key names (excluding anthropic, openai, google, gemini).
        """
        default_providers = set(DEFAULT_API_KEYS.keys())
        return [
            service for service in self.user_keys.keys()
            if service not in default_providers and self.user_keys[service]
        ]


# Global instance for convenience
api_key_manager = APIKeyManager()


def get_api_key(service: str) -> str:
    """
    Convenience function to get API key for a service.
    
    Args:
        service: The service name (e.g., 'anthropic', 'openai')
        
    Returns:
        The API key to use
    """
    return api_key_manager.get_api_key(service)

def set_api_key(service: str, key: str) -> bool:
    """
    Convenience function to set API key for a service.
    
    Args:
        service: The service name (e.g., 'anthropic', 'openai')
        key: The API key to set
        
    Returns:
        True if successful, False otherwise
    """
    try:
        api_key_manager.set_user_api_key(service, key)
        if key:  # If key is not empty, use user key
            api_key_manager.use_user_key(service)
        return True
    except Exception as e:
        logger.error(f"Error setting API key: {e}")
        return False

def list_available_providers() -> list[str]:
    """
    Get a list of available API providers.
    
    Returns:
        List of provider names (e.g., ['anthropic', 'openai'])
    """
    return list(DEFAULT_API_KEYS.keys())


def has_api_key(service: str) -> bool:
    """
    Convenience function to check if an API key is available for a service.
    
    Args:
        service: The service name (e.g., 'anthropic', 'openai', 'custom_ollama')
        
    Returns:
        True if a key is available
    """
    return api_key_manager.has_api_key(service)


def get_all_configured_keys() -> Dict[str, bool]:
    """
    Convenience function to get all configured API keys and their status.
    
    Returns:
        Dict mapping service name to whether a key is available.
    """
    return api_key_manager.get_all_configured_keys()


def list_custom_key_names() -> list:
    """
    Convenience function to get custom (non-default) API key names.
    
    Returns:
        List of custom key names.
    """
    return api_key_manager.list_custom_key_names() 