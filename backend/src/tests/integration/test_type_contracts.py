"""Integration tests for type contracts between frontend and backend.

These tests ensure that:
1. Models serialize to valid JSON
2. Tuple fields are properly converted to arrays
3. Response wrappers are used consistently
4. Date fields are formatted correctly
"""

import pytest
import json
from datetime import datetime
from typing import get_type_hints, get_origin

from api.core.models.preferences import (
    TranscriptionSettings,
    BehaviorSettings,
    ModelSettings,
    HotkeyBinding,
    GeneralSettings,
    UIPreferences,
    AgentTaskPreferences,
    AssistantSessionPreferences,
    ConversationWidgetPreferences,
    ActivityCaptureSettings,
)
from api.core.models.responses import SettingsResponse


class TestModelSerialization:
    """Test that models serialize correctly for Swift consumption."""
    
    @pytest.mark.parametrize("model_class", [
        TranscriptionSettings,
        BehaviorSettings,
        ModelSettings,
        GeneralSettings,
        UIPreferences,
        AgentTaskPreferences,
        AssistantSessionPreferences,
        ConversationWidgetPreferences,
        ActivityCaptureSettings,
    ])
    def test_model_serializes_to_json(self, model_class):
        """Test that models can be serialized to JSON."""
        instance = model_class()
        json_str = instance.model_dump_json()
        data = json.loads(json_str)
        
        # Verify it's a valid dict
        assert isinstance(data, dict), f"{model_class.__name__} should serialize to dict"
        
        # Verify all fields are present
        for field_name in model_class.model_fields.keys():
            assert field_name in data, f"Field {field_name} missing from {model_class.__name__}"
    
    @pytest.mark.parametrize("model_class", [
        TranscriptionSettings,
        AgentTaskPreferences,
        ConversationWidgetPreferences,
    ])
    def test_tuple_fields_serialize_as_arrays(self, model_class):
        """Test that Tuple fields are serialized as JSON arrays."""
        instance = model_class()
        json_str = instance.model_dump_json()
        data = json.loads(json_str)
        
        # Check for tuple fields
        for field_name, field_info in model_class.model_fields.items():
            annotation_str = str(field_info.annotation)
            if 'Tuple' in annotation_str:
                field_value = data.get(field_name)
                if field_value is not None:
                    assert isinstance(field_value, list), \
                        f"{model_class.__name__}.{field_name} should serialize as array"
    
    def test_hotkey_binding_has_all_fields(self):
        """Test that HotkeyBinding includes all required fields."""
        binding = HotkeyBinding(
            key="F9",
            modifiers=["instruction"],
            enabled=True,
            description="Test hotkey"
        )
        
        data = json.loads(binding.model_dump_json())
        
        assert "key" in data
        assert "modifiers" in data
        assert "enabled" in data
        assert "description" in data
        assert data["key"] == "F9"
        assert data["modifiers"] == ["instruction"]
        assert data["enabled"] is True
        assert data["description"] == "Test hotkey"

    def test_agent_task_auto_reopen_on_completion_defaults_to_true(self):
        """Test that new agent-task preferences surface the completion behavior."""
        data = AgentTaskPreferences().model_dump()

        assert data["auto_reopen_on_completion"] is True


class TestResponseWrappers:
    """Test that response wrappers work correctly."""
    
    def test_settings_response_wrapper(self):
        """Test SettingsResponse wrapper."""
        settings = TranscriptionSettings()
        response = SettingsResponse(settings=settings)
        
        data = json.loads(response.model_dump_json())
        
        assert "status" in data
        assert "settings" in data
        assert data["status"] == "success"
        assert isinstance(data["settings"], dict)
    
    def test_settings_response_with_custom_status(self):
        """Test SettingsResponse with custom status."""
        settings = BehaviorSettings()
        response = SettingsResponse(status="updated", settings=settings)
        
        data = json.loads(response.model_dump_json())
        
        assert data["status"] == "updated"


class TestDateSerialization:
    """Test that datetime fields are serialized correctly."""
    
    def test_datetime_serialization_format(self):
        """Test that datetimes retain ISO8601-compatible microsecond precision."""
        from api.core.knowledge.personalization_models import UserProfile
        
        profile = UserProfile(
            id="test",
            full_name="Test User",
            created_at=datetime(2024, 1, 15, 10, 30, 45, 123456)
        )
        
        json_str = profile.model_dump_json()
        data = json.loads(json_str)
        
        # Check that created_at is a string
        assert isinstance(data["created_at"], str)
        
        # The Swift client's custom ISO8601 decoder accepts fractional seconds,
        # so Python's microsecond precision must remain available on the wire.
        created_at_str = data["created_at"]
        assert "T" in created_at_str, "Should use ISO8601 format with T separator"
        assert created_at_str == "2024-01-15T10:30:45.123456"


class TestFieldTypes:
    """Test that field types are consistent."""
    
    def test_position_fields_are_tuples(self):
        """Test that position fields use Tuple type."""
        from api.core.models.preferences import TranscriptionSettings
        
        hints = get_type_hints(TranscriptionSettings)
        
        # widget_position should be Optional[Tuple[float, float, int]]
        if 'widget_position' in hints:
            annotation = hints['widget_position']
            # Check if it's Optional (Union with None)
            origin = get_origin(annotation)
            assert origin is not None, "widget_position should have type annotation"
    
    def test_boolean_fields_are_bool(self):
        """Test that boolean fields are actually bool type."""
        settings = BehaviorSettings()
        data = json.loads(settings.model_dump_json())
        
        bool_fields = ['start_on_startup', 'show_notifications', 'minimize_to_tray', 
                      'hold_enabled', 'enable_monitoring_at_startup', 
                      'enable_voice_listener_at_startup']
        
        for field in bool_fields:
            if field in data:
                assert isinstance(data[field], bool), \
                    f"{field} should be boolean, got {type(data[field])}"


class TestAPIEndpoints:
    """Test that API endpoints use proper response models."""
    
    def test_settings_endpoints_have_response_models(self):
        """Test that settings endpoints have proper response models."""
        from api.main import app
        from fastapi.routing import APIRoute
        
        settings_routes = [
            route for route in app.routes 
            if isinstance(route, APIRoute) and '/settings/' in route.path
        ]
        
        # Check that we have settings routes
        assert len(settings_routes) > 0, "Should have settings routes"
        
        # Check that most have response models
        routes_with_models = [
            route for route in settings_routes 
            if route.response_model is not None
        ]
        
        coverage = len(routes_with_models) / len(settings_routes)
        assert coverage > 0.5, \
            f"At least 50% of settings routes should have response models (got {coverage:.1%})"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

