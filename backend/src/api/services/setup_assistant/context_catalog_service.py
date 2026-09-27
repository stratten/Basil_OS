"""Catalog and tool context exposed to the model-backed setup agent."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from api.core.models.models_registry.cloud_reasoning_registry import CLOUD_REASONING_MODELS
from api.core.models.models_registry import get_local_reasoning_models, get_model
from api.routes.setup_assistant.models import (
    SetupAgentModelAccess,
    SetupAgentModelAccessMode,
    SetupAgentModelMetadata,
    SetupPermissionKind,
    SetupPrivacyImpact,
    SetupToolDefinition,
)


@dataclass(frozen=True)
class SetupAgentModelSelection:
    model_id: str
    config: Dict[str, Any]
    access_mode: SetupAgentModelAccessMode = SetupAgentModelAccessMode.default_proxy
    override_model_id: Optional[str] = None

    @property
    def is_local(self) -> bool:
        return self.config.get("location") == "local"

    @property
    def model_type_and_variant(self) -> tuple[str, str]:
        model_type, _, variant = self.model_id.partition("-")
        if not model_type or not variant:
            raise ValueError(f"Local setup agent model '{self.model_id}' is not a valid registry model id.")
        return model_type, variant


class SetupAssistantContextCatalogService:
    """Build the deterministic context Basil may reason over."""

    def resolve_setup_agent_model(
        self,
        override_model_id: Optional[str] = None,
        model_access: Optional[SetupAgentModelAccess] = None,
    ) -> SetupAgentModelSelection:
        """Resolve the user-selected setup-agent model route.

        The default path uses the proxy model marked for setup-agent use. Users
        may explicitly request a local or custom model up front.
        """

        if model_access and model_access.mode == SetupAgentModelAccessMode.local:
            return self._resolve_local_setup_agent_model(model_access.local_model_id)

        if model_access and model_access.mode == SetupAgentModelAccessMode.custom:
            selected_model_id = model_access.custom_model_id or override_model_id
            if not selected_model_id:
                raise ValueError("Custom setup agent model selection requires a registry model id.")
            return self._resolve_custom_setup_agent_model(selected_model_id)

        if override_model_id:
            return self._resolve_custom_setup_agent_model(override_model_id)

        for model_id, config in CLOUD_REASONING_MODELS.items():
            if config.get("used_by_setup_agent") is True:
                if not config.get("supports_openrouter_proxy"):
                    raise ValueError(f"Setup agent model '{model_id}' is not proxy-compatible.")
                return SetupAgentModelSelection(model_id=model_id, config=config)

        raise ValueError("No proxy-compatible model is marked used_by_setup_agent in the model registry.")

    def build_setup_agent_model_metadata(
        self,
        selection: SetupAgentModelSelection,
    ) -> SetupAgentModelMetadata:
        return SetupAgentModelMetadata(
            provider=str(selection.config.get("provider", "proxy")),
            model_id=selection.model_id,
            display_name=str(selection.config.get("display_name", selection.model_id)),
            openrouter_model_id=selection.config.get("openrouter_id"),
            override_model_id=selection.override_model_id,
            access_mode=selection.access_mode,
        )

    def _resolve_local_setup_agent_model(
        self,
        requested_model_id: Optional[str],
    ) -> SetupAgentModelSelection:
        local_models = get_local_reasoning_models()
        model_id = requested_model_id
        if model_id is None:
            model_id = next(
                (
                    candidate_id
                    for candidate_id, config in local_models.items()
                    if config.get("recommended_for_onboarding") is True
                    and "reasoning" in config.get("capabilities", [])
                ),
                None,
            )

        if not model_id or model_id not in local_models:
            raise ValueError("No local reasoning model is available for setup-agent use.")

        config = local_models[model_id]
        if "reasoning" not in config.get("capabilities", []):
            raise ValueError(f"Local setup agent model '{model_id}' does not support reasoning.")

        return SetupAgentModelSelection(
            model_id=model_id,
            config=config,
            access_mode=SetupAgentModelAccessMode.local,
        )

    def _resolve_custom_setup_agent_model(self, model_id: str) -> SetupAgentModelSelection:
        config = get_model(model_id)
        if not config:
            raise ValueError(f"Setup agent model override '{model_id}' is not in the model registry.")

        access_mode = SetupAgentModelAccessMode.custom
        if config.get("location") == "local":
            if "reasoning" not in config.get("capabilities", []):
                raise ValueError(f"Custom setup agent model '{model_id}' does not support reasoning.")
        elif not config.get("supports_openrouter_proxy"):
            raise ValueError(f"Setup agent model override '{model_id}' is not proxy-compatible.")

        return SetupAgentModelSelection(
            model_id=model_id,
            config=config,
            access_mode=access_mode,
            override_model_id=model_id,
        )

    def build_available_tools(self) -> List[SetupToolDefinition]:
        """Return schema-bound setup call sites Basil may propose."""

        return [
            SetupToolDefinition(
                name="save_profile_updates",
                description="Persist approved profile field updates from the profile schema.",
                input_schema={"type": "object", "properties": {"updates": {"type": "object"}}},
                privacy_impact=SetupPrivacyImpact.modifies_settings,
            ),
            SetupToolDefinition(
                name="save_writing_samples",
                description="Persist approved writing samples selected during setup.",
                input_schema={"type": "object", "properties": {"sample_ids": {"type": "array", "items": {"type": "string"}}}},
                privacy_impact=SetupPrivacyImpact.reads_local_data,
            ),
            SetupToolDefinition(
                name="update_basil_settings",
                description="Persist approved Basil settings changes.",
                input_schema={"type": "object", "properties": {"settings": {"type": "object"}}},
                privacy_impact=SetupPrivacyImpact.modifies_settings,
            ),
            SetupToolDefinition(
                name="start_model_downloads",
                description="Start approved local model downloads through the native model download flow.",
                input_schema={"type": "object", "properties": {"model_ids": {"type": "array", "items": {"type": "string"}}}},
                privacy_impact=SetupPrivacyImpact.local_only,
                bridge_action="startModelDownloads",
            ),
            SetupToolDefinition(
                name="start_connection_auth",
                description="Start approved authentication for a supported connection catalog entry.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "connector_id": {"type": "string"},
                        "server_url": {"type": "string"},
                        "friendly_name": {"type": "string"},
                    },
                    "required": ["connector_id", "server_url", "friendly_name"],
                },
                privacy_impact=SetupPrivacyImpact.authenticates_service,
                bridge_action="startConnectionAuth",
            ),
            SetupToolDefinition(
                name="refresh_connection_tools",
                description="Refresh auth-aware tool metadata for approved connection cards.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "connection_id": {"type": "string"},
                        "connector_id": {"type": "string"},
                    },
                    "required": ["connection_id"],
                },
                privacy_impact=SetupPrivacyImpact.none,
            ),
            SetupToolDefinition(
                name="launch_assistant_session",
                description="Launch the real Dill AssistantSession UI with approved shimmed context.",
                input_schema={"type": "object", "properties": {"context": {"type": "object"}, "prompt": {"type": "string"}}},
                privacy_impact=SetupPrivacyImpact.launches_real_task,
                bridge_action="launchAssistantSession",
            ),
            SetupToolDefinition(
                name="launch_agent_task",
                description="Launch the real Paprika AgentTask UI with approved shimmed context.",
                input_schema={"type": "object", "properties": {"context": {"type": "object"}, "prompt": {"type": "string"}}},
                privacy_impact=SetupPrivacyImpact.launches_real_task,
                bridge_action="launchAgentTask",
            ),
            SetupToolDefinition(
                name="collect_sent_email_metadata",
                description="Collect approved sent-email metadata for writing-sample triage.",
                input_schema={"type": "object", "properties": {"days_back": {"type": "integer"}, "limit": {"type": "integer"}}},
                privacy_impact=SetupPrivacyImpact.reads_local_data,
                required_permissions=[SetupPermissionKind.apple_events],
            ),
            # NOTE: `pull_inbox_email_for_dill` is intentionally NOT listed here.
            # This catalog is the allowlist of tool names that may flow through
            # `propose_consent_receipt` → `/proposals/{id}/approve` →
            # `SetupAssistantActionExecutionService._tool_call_to_action`. That
            # executor only knows how to run mutation/refresh actions or hand
            # `launch_*` actions to the native bridge — it cannot execute a
            # read-only Python LangChain tool that needs the active agent SSE
            # `event_emitter` to fire `inline_email_context`. The setup agent
            # calls `pull_inbox_email_for_dill` directly inside its own turn
            # (registered in `tool_registry.py`, gated by the user's chip
            # click), so listing it here would re-enable a receipt shape that
            # passes proposal-time validation only to crash at approve time
            # with "is handled outside the backend executor."
            SetupToolDefinition(
                name="open_system_settings",
                description="Open the correct OS settings page for an approved permission request.",
                input_schema={"type": "object", "properties": {"permission": {"type": "string"}}},
                privacy_impact=SetupPrivacyImpact.none,
                bridge_action="openSystemSettings",
            ),
        ]

    def build_platform_permission_catalog(self) -> Dict[str, Any]:
        system_name = platform.system().lower()
        if system_name == "darwin":
            return {
                "platform": "macos",
                "supported": True,
                "permissions": [
                    {
                        "kind": SetupPermissionKind.microphone.value,
                        "label": "Microphone",
                        "purpose": "Lets Dill and Basil hear approved voice requests.",
                    },
                    {
                        "kind": SetupPermissionKind.accessibility.value,
                        "label": "Accessibility",
                        "purpose": "Lets approved automations inspect and control app UI.",
                    },
                    {
                        "kind": SetupPermissionKind.input_monitoring.value,
                        "label": "Input Monitoring",
                        "purpose": "Lets global hotkeys and double-tap gestures work from other apps.",
                    },
                    {
                        "kind": SetupPermissionKind.screen_recording.value,
                        "label": "Screen Recording",
                        "purpose": "Lets approved visual context tools understand what is on screen.",
                    },
                    {
                        "kind": SetupPermissionKind.apple_events.value,
                        "label": "Automation",
                        "purpose": "Lets approved AppleScript-backed tools work with apps like Mail.",
                    },
                ],
            }

        return {
            "platform": "windows" if system_name == "windows" else "linux",
            "supported": False,
            "permissions": [],
            "stub": "Platform-specific permission handling is reserved for a future build.",
        }

