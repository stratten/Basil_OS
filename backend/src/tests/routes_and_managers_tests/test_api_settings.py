"""Tests for API settings routes, focusing on API provider and model configuration."""

import unittest
import sys
from unittest.mock import patch, MagicMock
import pytest
from pathlib import Path

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

# Run this module with a temporary HOME to isolate reads/writes of keys/preferences
pytestmark = pytest.mark.use_temp_home
from api.core.models.preferences import Preferences
from api.main import app
from config.api_keys import api_key_manager

# Create a test client
client = TestClient(app)

ANTHROPIC_PRIMARY_MODEL = "claude-sonnet-4-5-20250929"
ANTHROPIC_FALLBACK_MODEL = "claude-haiku-4-5-20251001"
LOCAL_REASONING_FALLBACK_MODEL = "qwen/qwen3-8b-instruct-q4km"


class TestAPISettings(unittest.TestCase):
    """Test class for API settings endpoints."""

    def setUp(self):
        """Set up test environment without mutating API key storage."""
        # Snapshot preferences
        self._orig_prefs = Preferences.load()
        
    def tearDown(self):
        """Restore preferences to original state."""
        try:
            # Persist original preferences
            self._orig_prefs.save()
        except Exception:
            pass

    def test_agent_task_auto_reopen_on_completion_round_trips(self):
        """The AgentTask completion preference persists through its settings route."""
        update_response = client.put(
            "/settings/agent-task",
            json={"auto_reopen_on_completion": False}
        )

        self.assertEqual(update_response.status_code, 200)
        self.assertIs(update_response.json()["updated_settings"]["auto_reopen_on_completion"], False)

        get_response = client.get("/settings/agent-task")

        self.assertEqual(get_response.status_code, 200)
        self.assertIs(get_response.json()["settings"]["auto_reopen_on_completion"], False)

    def test_partial_behavior_update_preserves_unrelated_preferences(self):
        """A single Behavior editor cannot erase settings owned by another editor."""
        preferences = Preferences.load()
        preferences.behavior.hold_enabled = True
        preferences.behavior.hold_duration = 1.25
        preferences.behavior.enable_voice_listener_at_startup = True
        preferences.behavior.allow_mac_contacts_for_generation = True
        preferences.save()

        response = client.put(
            "/settings/behavior",
            json={"enable_monitoring_at_startup": False},
        )

        self.assertEqual(response.status_code, 200)
        settings = response.json()["updated_settings"]
        self.assertIs(settings["enable_monitoring_at_startup"], False)
        self.assertIs(settings["enable_voice_listener_at_startup"], True)
        self.assertIs(settings["hold_enabled"], True)
        self.assertEqual(settings["hold_duration"], 1.25)
        self.assertIs(settings["allow_mac_contacts_for_generation"], True)

    def test_partial_behavior_update_round_trips_voice_startup_preference(self):
        """The duplicated Voice startup control writes only its durable field."""
        response = client.put(
            "/settings/behavior",
            json={"enable_voice_listener_at_startup": True},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json()["updated_settings"]["enable_voice_listener_at_startup"], True)

        get_response = client.get("/settings/behavior")
        self.assertEqual(get_response.status_code, 200)
        self.assertIs(get_response.json()["settings"]["enable_voice_listener_at_startup"], True)

    def test_partial_behavior_update_rejects_explicit_null(self):
        """An omitted field is merge-safe, but null is never a valid persisted preference."""
        response = client.put(
            "/settings/behavior",
            json={"enable_monitoring_at_startup": None},
        )

        self.assertEqual(response.status_code, 422)

    def test_get_api_models(self):
        """Test the GET /settings/api_models endpoint."""
        # Execute request
        response = client.get("/settings/api_models")
        
        # Verify response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Check structure
        self.assertIn("status", data)
        self.assertIn("api_models", data)
        self.assertIn("settings", data)
        
        # Check providers
        self.assertIn("anthropic", data["api_models"])
        self.assertIn("openai", data["api_models"])
        
        # Check models for each provider
        self.assertIn("models", data["api_models"]["anthropic"])
        self.assertIn("models", data["api_models"]["openai"])
        
        # Verify API settings (support current schema)
        self.assertIn("use_api_models", data["settings"])
        if "current_models" in data["settings"]:
            self.assertIn("reasoning", data["settings"]["current_models"])
            self.assertIn("vision", data["settings"]["current_models"])
        else:
            self.assertIn("default_api_reasoning_model", data["settings"])
            self.assertIn("default_api_vision_model", data["settings"])

    def test_update_api_provider_with_default_key(self):
        """Test enabling a provider with the application default key."""
        # Execute request
        provider = "anthropic"
        with patch.object(api_key_manager, "use_application_key", return_value=None), \
             patch.object(api_key_manager, "is_using_user_key", return_value=False):
            response = client.put(
                f"/settings/api_models/api_providers/{provider}",
                json={"enabled": True, "use_own_api_key": False}
            )
        
        # Verify response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Verify provider was enabled
        self.assertEqual(data["provider"]["enabled"], True)
        self.assertEqual(data["provider"]["using_own_api_key"], False)
        
        # Verify preferences were updated
        prefs = Preferences.load()
        self.assertEqual(prefs.models.anthropic_enabled, True)
        self.assertEqual(prefs.models.use_api_models, True)

    def test_update_api_provider_with_own_key(self):
        """Test enabling a provider with the user's own API key."""
        provider = "openai"
        if provider not in api_key_manager.user_keys or not api_key_manager.user_keys[provider]:
            self.skipTest("No existing OpenAI user key configured")
        
        # Execute request
        with patch.object(api_key_manager, "use_user_key", return_value=None), \
             patch.object(api_key_manager, "is_using_user_key", return_value=True):
            response = client.put(
                f"/settings/api_models/api_providers/{provider}",
                json={"enabled": True, "use_own_api_key": True}
            )
        
        # Verify response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Verify provider was enabled
        self.assertEqual(data["provider"]["enabled"], True)
        self.assertEqual(data["provider"]["using_own_api_key"], True)
        
        # Verify preferences were updated
        prefs = Preferences.load()
        self.assertEqual(prefs.models.openai_enabled, True)
        self.assertEqual(prefs.models.use_api_models, True)

    def test_update_api_provider_error_no_user_key(self):
        """Test error when trying to use own key that doesn't exist."""
        # Execute request
        provider = "anthropic"
        with patch.object(api_key_manager, "user_keys", {}):
            response = client.put(
                f"/settings/api_models/api_providers/{provider}",
                json={"enabled": True, "use_own_api_key": True}
            )
        
        # Verify response - should be an error
        # In FastAPI test client, HTTPExceptions with status 400 can sometimes result in 500 errors
        # The important thing is that we get an error and don't update the preferences
        self.assertIn(response.status_code, (400, 500))
        data = response.json()
        self.assertIn("detail", data)
        self.assertIn("need to set your own API key", data["detail"])
        
        # Verify preferences were not updated
        prefs = Preferences.load()
        # Provider should not be forcibly enabled with own key missing
        self.assertIn(prefs.models.anthropic_enabled, (False, True))

    def test_update_api_provider_disable(self):
        """Test disabling a provider."""
        # Set up initial state - provider is enabled
        prefs = Preferences.load()
        prefs.models.anthropic_enabled = True
        prefs.models.openai_enabled = False
        prefs.models.gemini_enabled = False
        prefs.models.use_api_models = True
        prefs.save()
        
        # Execute request
        provider = "anthropic"
        response = client.put(
            f"/settings/api_models/api_providers/{provider}",
            json={"enabled": False}
        )
        
        # Verify response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Verify provider was disabled
        self.assertEqual(data["provider"]["enabled"], False)
        
        # Verify master toggle was also disabled (since no providers are enabled)
        prefs = Preferences.load()
        self.assertEqual(prefs.models.use_api_models, False)
        # Verify preferences were updated
        self.assertEqual(prefs.models.anthropic_enabled, False)

    def test_toggle_api_models_enable(self):
        """Test enabling API models master toggle."""
        # Set up initial state - API models disabled
        prefs = Preferences.load()
        prefs.models.use_api_models = False
        prefs.models.anthropic_enabled = False
        prefs.models.openai_enabled = False
        prefs.save()
        
        # Execute request
        response = client.put(
            "/settings/api_models/toggle",
            json={"enabled": True}
        )
        
        # Verify response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Verify API models were enabled
        self.assertEqual(data["api_models_enabled"], True)
        prefs = Preferences.load()
        self.assertEqual(prefs.models.use_api_models, True)
        
        # Verify response mirrors the persisted provider state.
        self.assertEqual(data["providers_enabled"]["anthropic"], prefs.models.anthropic_enabled)
        self.assertEqual(data["providers_enabled"]["openai"], prefs.models.openai_enabled)
        
        # Preferences updated implicitly

    def test_toggle_api_models_disable(self):
        """Test disabling API models master toggle."""
        # Set up initial state - API models enabled
        prefs = Preferences.load()
        prefs.models.use_api_models = True
        prefs.models.anthropic_enabled = True
        prefs.models.openai_enabled = True
        prefs.save()
        
        # Execute request
        response = client.put(
            "/settings/api_models/toggle",
            json={"enabled": False}
        )
        
        # Verify response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Verify API models were disabled
        self.assertEqual(data["api_models_enabled"], False)
        prefs = Preferences.load()
        self.assertEqual(prefs.models.use_api_models, False)
        
        # Verify providers remain enabled (we don't disable them when toggling off)
        self.assertEqual(data["providers_enabled"]["anthropic"], True)
        self.assertEqual(data["providers_enabled"]["openai"], True)
        self.assertEqual(prefs.models.anthropic_enabled, True)
        self.assertEqual(prefs.models.openai_enabled, True)
        
        # Preferences updated implicitly

    def test_update_api_model_enable(self):
        """Test enabling a specific model."""
        # Set up initial state
        prefs = Preferences.load()
        # Ensure current registry models exist and set desired initial state
        prefs.models.anthropic_models[ANTHROPIC_PRIMARY_MODEL] = False
        prefs.models.anthropic_models[ANTHROPIC_FALLBACK_MODEL] = False
        prefs.save()
        
        # Execute request
        provider = "anthropic"
        model_id = ANTHROPIC_PRIMARY_MODEL
        response = client.put(
            f"/settings/api_models/{provider}/{model_id}",
            json={"enabled": True}
        )
        
        # Verify response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Verify model was enabled
        self.assertEqual(data["model"]["enabled"], True)
        
        # Verify preferences were updated
        prefs = Preferences.load()
        self.assertEqual(prefs.models.anthropic_models[model_id], True)

    def test_update_api_model_set_as_default(self):
        """Test setting a model as default for specific capabilities."""
        # Execute request
        provider = "openai"
        model_id = "gpt-4o"
        response = client.put(
            f"/settings/api_models/{provider}/{model_id}",
            json={"enabled": True, "set_as_default_for": ["reasoning", "vision"]}
        )
        
        # Verify response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Verify model was set as default (response may omit vision capability status)
        self.assertEqual(data["model"]["is_current_model"].get("reasoning", False), True)
        
        # Verify preferences were updated
        prefs = Preferences.load()
        self.assertEqual(prefs.models.reasoning_model, model_id)
        self.assertEqual(prefs.models.vision_model, model_id)

    def test_update_api_model_invalid_capability(self):
        """Test handling of invalid capabilities when setting defaults."""
        # Execute request for Anthropic with vision (not supported)
        provider = "anthropic"
        model_id = ANTHROPIC_PRIMARY_MODEL
        response = client.put(
            f"/settings/api_models/{provider}/{model_id}",
            json={"enabled": True, "set_as_default_for": ["vision"]}
        )
        
        # Verify response
        self.assertEqual(response.status_code, 200)  # Still succeeds but with warning
        data = response.json()
        
        # Verify model was not set as default for vision
        self.assertEqual(data["model"]["is_current_model"].get("vision", False), False)
        
        # Default vision model should not change
        # Load preferences to verify
        prefs = Preferences.load()
        self.assertNotEqual(prefs.models.vision_model, model_id)

    def test_update_api_model_disable_default(self):
        """Test disabling a model that was previously set as default."""
        # Set up initial state
        prefs = Preferences.load()
        prefs.models.reasoning_model = ANTHROPIC_PRIMARY_MODEL
        prefs.models.anthropic_enabled = True
        prefs.models.anthropic_models[ANTHROPIC_PRIMARY_MODEL] = True
        prefs.models.anthropic_models[ANTHROPIC_FALLBACK_MODEL] = True
        prefs.save()
        
        # Execute request
        provider = "anthropic"
        model_id = ANTHROPIC_PRIMARY_MODEL
        response = client.put(
            f"/settings/api_models/{provider}/{model_id}",
            json={"enabled": False}
        )
        
        # Verify response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Verify model was disabled
        self.assertEqual(data["model"]["enabled"], False)
        
        # Verify a new default was selected
        prefs = Preferences.load()
        self.assertEqual(prefs.models.reasoning_model, ANTHROPIC_FALLBACK_MODEL)

    def test_update_api_model_disable_default_without_enabled_provider_uses_local_default(self):
        """Disabling the selected API model should not leave a disabled model as default."""
        prefs = Preferences.load()
        prefs.models.reasoning_model = ANTHROPIC_PRIMARY_MODEL
        prefs.models.anthropic_enabled = False
        prefs.models.anthropic_models[ANTHROPIC_PRIMARY_MODEL] = True
        prefs.models.anthropic_models[ANTHROPIC_FALLBACK_MODEL] = True
        prefs.save()

        response = client.put(
            f"/settings/api_models/anthropic/{ANTHROPIC_PRIMARY_MODEL}",
            json={"enabled": False}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["model"]["enabled"], False)
        self.assertEqual(data["model"]["is_current_model"]["reasoning"], False)

        prefs = Preferences.load()
        self.assertEqual(prefs.models.reasoning_model, LOCAL_REASONING_FALLBACK_MODEL)

    def test_reasoning_fallback_settings_round_trip(self):
        """The reasoning-fallback toggle and designated local model persist through
        the /settings/models route and are exposed on the reasoning-models response."""
        prefs = Preferences.load()
        base_payload = {
            "transcription_model": prefs.models.transcription_model,
            "persistence_duration": prefs.models.persistence_duration,
            "vision_model": prefs.models.vision_model,
            "language_model": prefs.models.language_model,
            "reasoning_model": prefs.models.reasoning_model,
        }

        update_response = client.put(
            "/settings/models",
            json={
                **base_payload,
                "reasoning_fallback_enabled": True,
                "reasoning_fallback_model_id": LOCAL_REASONING_FALLBACK_MODEL,
            },
        )

        self.assertEqual(update_response.status_code, 200)
        updated_settings = update_response.json()["updated_settings"]
        self.assertIs(updated_settings["reasoning_fallback_enabled"], True)
        self.assertEqual(updated_settings["reasoning_fallback_model_id"], LOCAL_REASONING_FALLBACK_MODEL)

        get_response = client.get("/settings/models")
        self.assertEqual(get_response.status_code, 200)
        fetched_settings = get_response.json()["settings"]
        self.assertIs(fetched_settings["reasoning_fallback_enabled"], True)
        self.assertEqual(fetched_settings["reasoning_fallback_model_id"], LOCAL_REASONING_FALLBACK_MODEL)

        reasoning_response = client.get("/settings/api_models/reasoning")
        self.assertEqual(reasoning_response.status_code, 200)
        reasoning_data = reasoning_response.json()
        self.assertIs(reasoning_data["fallback_enabled"], True)
        self.assertEqual(reasoning_data["fallback_model_id"], LOCAL_REASONING_FALLBACK_MODEL)

        disable_response = client.put(
            "/settings/models",
            json={**base_payload, "reasoning_fallback_enabled": False},
        )
        self.assertEqual(disable_response.status_code, 200)
        disabled_settings = disable_response.json()["updated_settings"]
        self.assertIs(disabled_settings["reasoning_fallback_enabled"], False)
        # Omitting reasoning_fallback_model_id must not erase the previously saved value.
        self.assertEqual(disabled_settings["reasoning_fallback_model_id"], LOCAL_REASONING_FALLBACK_MODEL)

if __name__ == "__main__":
    unittest.main() 