# API Key Management

This module provides a centralized system for managing API keys for external services like Anthropic (Claude), OpenAI, and Google (Gemini).

## Features

- **Default Application Keys**: Built-in API keys that can be used as fallbacks
- **User-Provided Keys**: Users can add their own API keys
- **Secure Storage**: Secret key values are never written to a plaintext file. By default they are stored via the OS-native credential store (`config/credential_store.py`, backed by the `keyring` package). When the Basil app launches the backend it sets `BASIL_CREDENTIAL_HOST=client`, and the keys instead live in the app's single Keychain vault: the backend receives them over the local websocket when the app connects (`api/services/provider_keys_bridge.py`), holds them in memory (`config/client_hosted_credential_store.py`), and asks the app to save or remove them
- **Environment Variables**: Supports loading keys from environment variables
- **Flexible Configuration**: Users can switch between application default keys and their own keys

## File Locations

- **Config Directory**: `~/.basil/config/`
- **Key-Usage Flags File**: `~/.basil/config/api_key_flags.json` — stores only which provider currently prefers a user key (`use_user_keys`) and any custom key names; it never contains a secret value
- **Secret Values**: stored only in the Keychain on macOS (in the app's single vault when the app hosts the credentials, otherwise in the OS credential store through `keyring`), keyed by provider name. Earlier keyring items are moved into the vault once by `api/services/provider_keys_migration.py`

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
- `GOOGLE_API_KEY` or `GEMINI_API_KEY`: API key for Google Gemini models (`GOOGLE_API_KEY` wins when both are set)

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

- Secret key values are stored in the Keychain (the app's single vault, or the OS credential store through `keyring`), not in plain text, and are sent only to and from the app's host connection, never to a webview connection
- The application default keys should be stored in environment variables, not hardcoded
- For production use, API key usage should be monitored and rate-limited

## Adding New Services

To add support for a new service:

1. Add the service to the `DEFAULT_API_KEYS` dictionary in `api_keys.py`
2. Add the service to the `api_keys.providers` list in `default_config.yaml`
3. Update the `_load_env_keys` method to check for relevant environment variables
4. Update any model implementations to use the key manager 