# API Key Management

This module provides a centralized system for managing API keys for external services like Anthropic (Claude) and OpenAI.

## Features

- **Default Application Keys**: Built-in API keys that can be used as fallbacks
- **User-Provided Keys**: Users can add their own API keys
- **Secure Storage**: Secret key values are stored via the OS-native credential store (`config/credential_store.py`, backed by the `keyring` package), never in a plaintext file
- **Environment Variables**: Supports loading keys from environment variables
- **Flexible Configuration**: Users can switch between application default keys and their own keys

## File Locations

- **Config Directory**: `~/.basil/config/`
- **Key-Usage Flags File**: `~/.basil/config/api_key_flags.json` — stores only which provider currently prefers a user key (`use_user_keys`) and any custom key names; it never contains a secret value
- **Secret Values**: stored only in the OS credential store (Keychain on macOS), keyed by provider name

## Key-Usage Flags Structure

`api_key_flags.json` stores the following non-secret format:

```json
{
  "use_user_keys": {
    "anthropic": true,
    "openai": false
  },
  "custom_key_names": []
}
```

## Environment Variables

The following environment variables can be used to override the default API keys:

- `ANTHROPIC_API_KEY`: API key for Anthropic Claude models
- `OPENAI_API_KEY`: API key for OpenAI models

## Usage

### In Python Code

```python
from config.api_keys import get_api_key, api_key_manager

# Get the current API key for a service
anthropic_key = get_api_key("anthropic")

# Set a user-provided API key
api_key_manager.set_user_api_key("anthropic", "sk-ant-...")

# Switch to using application default key
api_key_manager.use_application_key("anthropic")

# Check if using user key
is_user_key = api_key_manager.is_using_user_key("anthropic")
```

## Security Considerations

- Secret key values are stored via the OS-native credential store, not in plain text
- The application default keys should be stored in environment variables, not hardcoded
- For production use, API key usage should be monitored and rate-limited

## Adding New Services

To add support for a new service:

1. Add the service to the `DEFAULT_API_KEYS` dictionary in `api_keys.py`
2. Add the service to the `api_keys.providers` list in `default_config.yaml`
3. Update the `_load_env_keys` method to check for relevant environment variables
4. Update any model implementations to use the key manager 