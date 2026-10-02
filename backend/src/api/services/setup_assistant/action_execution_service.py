"""Approved setup assistant tool-call validation primitives."""

from __future__ import annotations

import asyncio
import math
from typing import Any, Awaitable, Callable, Dict, List, Optional

from api.core.appearance.token_contract import contrast_ratio, meets_minimum_contrast
from api.core.logging.api_logger import api_logger
from api.core.models.preference_models.model_settings import ASSISTANT_OUTPUT_PASTE_MODES
from api.services.appearance_broadcast import broadcast_appearance_update
from api.routes.setup_assistant.models import (
    SetupAction,
    SetupActionKind,
    SetupActionExecutionItem,
    SetupExecutionStatus,
    SetupToolApprovalState,
    SetupToolCall,
)

ConnectionRefreshCallable = Callable[[str], Awaitable[Dict[str, Any]]]


MODEL_SETTINGS_ALLOWLIST = {
    "reasoning_model",
    "transcription_model",
    "language_model",
    "vision_model",
    "use_api_models",
    "close_assistant_session_on_insert",
    "assistant_output_paste_mode",
    "use_region_selection",
}

BEHAVIOR_SETTINGS_ALLOWLIST = {
    "enable_monitoring_at_startup",
    "enable_voice_listener_at_startup",
}

MEMORY_INTELLIGENCE_SETTINGS_ALLOWLIST = {
    "memory_after_task_enabled",
    "memory_daily_enabled",
    "memory_daily_time_local",
    "memory_processing_model",
    "skill_after_task_enabled",
    "skill_daily_enabled",
    "skill_daily_time_local",
    "skill_processing_model",
}

# RGB triplets persisted on UIPreferences. Setup Assistant is stricter than the
# direct Settings PUT /appearance route, which has no range validation today
# (a pre-existing gap outside this package's scope).
UI_COLOR_SETTINGS_KEYS = {
    "background_color_red", "background_color_green", "background_color_blue",
    "primary_color_red", "primary_color_green", "primary_color_blue",
    "secondary_color_red", "secondary_color_green", "secondary_color_blue",
    "text_color_red", "text_color_green", "text_color_blue",
    "processing_color_red", "processing_color_green", "processing_color_blue",
    "processing_accent_color_red", "processing_accent_color_green", "processing_accent_color_blue",
}

# Mirrors client/Sources/Support/AestheticSystem.swift's `availableFonts`.
# That native list is the source of truth; update both together if it changes.
UI_AVAILABLE_FONTS = {"Helvetica-Light", "Arial", "Avenir-Light", "SF Pro Text", "Menlo"}

UI_SETTINGS_ALLOWLIST = UI_COLOR_SETTINGS_KEYS | {"preferred_font"}


def validate_model_settings_payload(updates: Dict[str, Any]) -> None:
    """Reject setup-assistant model setting values that ``setattr`` would otherwise store unvalidated."""
    if "assistant_output_paste_mode" in updates and updates["assistant_output_paste_mode"] not in ASSISTANT_OUTPUT_PASTE_MODES:
        raise ValueError("models.assistant_output_paste_mode must be one of: always, auto, never.")


def validate_ui_settings_payload(updates: Dict[str, Any]) -> None:
    """Validate a partial `ui` settings payload before it mutates or reaches the user.

    Shared by the proposal-time check in `setup_agent_tooling/schemas.py` (so a
    malformed appearance proposal self-corrects before becoming a receipt) and
    the execution-time check below (defense in depth). Raises ValueError with a
    corrective message; never mutates anything.
    """

    for key, value in updates.items():
        if key not in UI_SETTINGS_ALLOWLIST:
            raise ValueError(f"Setting 'ui.{key}' is not allowed during setup.")
        if key in UI_COLOR_SETTINGS_KEYS:
            is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
            if not is_number or not math.isfinite(value) or not (0.0 <= value <= 1.0):
                raise ValueError(f"Setting 'ui.{key}' must be a number from 0.0 through 1.0.")
        elif value not in UI_AVAILABLE_FONTS:
            raise ValueError(
                f"Setting 'ui.preferred_font' must be one of: {', '.join(sorted(UI_AVAILABLE_FONTS))}."
            )


class SetupAssistantActionExecutionService:
    """Validate approved onboarding actions before deterministic execution."""

    def __init__(
        self,
        *,
        download_manager: Optional[Any] = None,
        model_service: Optional[Any] = None,
        connection_refresher: Optional[ConnectionRefreshCallable] = None,
    ) -> None:
        self.download_manager = download_manager
        self.model_service = model_service
        self.connection_refresher = connection_refresher

    def build_sequential_action_queue(self, actions: List[SetupAction]) -> List[SetupAction]:
        """Return actions in execution order after enforcing approval boundaries."""

        for action in actions:
            if action.kind == SetupActionKind.no_mutation:
                continue
            if action.requires_explicit_approval is not True:
                raise ValueError(f"Setup action '{action.id}' requires explicit approval.")

        return actions

    def validate_approved_tool_calls(self, tool_calls: List[SetupToolCall]) -> List[SetupToolCall]:
        """Validate approved schema-bound setup tool calls."""

        for tool_call in tool_calls:
            if tool_call.approval_state != SetupToolApprovalState.approved:
                raise ValueError(f"Setup tool call '{tool_call.id}' is not approved.")

        return tool_calls

    async def execute_approved_setup_actions(
        self,
        actions: List[SetupAction],
        tool_calls: List[SetupToolCall],
    ) -> List[SetupActionExecutionItem]:
        """Execute approved setup actions that have backend-owned paths."""

        validated_actions = self.build_sequential_action_queue(actions)
        validated_tool_calls = self.validate_approved_tool_calls(tool_calls)
        all_actions = [
            *validated_actions,
            *(self._tool_call_to_action(tool_call) for tool_call in validated_tool_calls),
        ]
        results: List[SetupActionExecutionItem] = []

        for action in all_actions:
            try:
                results.extend(await self._execute_action(action))
            except Exception as exc:
                results.append(
                    SetupActionExecutionItem(
                        id=action.id,
                        kind=action.kind.value,
                        status=SetupExecutionStatus.failed,
                        message=str(exc),
                    )
                )

        return results

    async def _execute_action(self, action: SetupAction) -> List[SetupActionExecutionItem]:
        if action.kind == SetupActionKind.start_model_downloads:
            return await self._execute_model_download_action(action)
        if action.kind == SetupActionKind.update_settings:
            item = self._execute_settings_update_action(action)
            appearance_settings = (item.result_payload or {}).get("appearance_settings")
            if appearance_settings:
                await broadcast_appearance_update(appearance_settings)
            return [item]
        if action.kind == SetupActionKind.refresh_connection_tools:
            return [await self._execute_connection_refresh_action(action)]
        if action.kind in {SetupActionKind.launch_assistant_session, SetupActionKind.launch_agent_task}:
            return [
                SetupActionExecutionItem(
                    id=action.id,
                    kind=action.kind.value,
                    status=SetupExecutionStatus.skipped,
                    message=f"Action '{action.kind.value}' is handled by the native setup bridge.",
                    result_payload={"requires_native_bridge": True},
                )
            ]
        if action.kind in {SetupActionKind.no_mutation, SetupActionKind.defer_recommendation}:
            return [
                SetupActionExecutionItem(
                    id=action.id,
                    kind=action.kind.value,
                    status=SetupExecutionStatus.skipped,
                    message="No setup change was needed.",
                )
            ]

        return [
            SetupActionExecutionItem(
                id=action.id,
                kind=action.kind.value,
                status=SetupExecutionStatus.skipped,
                message=f"Action '{action.kind.value}' is handled by the native setup bridge.",
            )
        ]

    async def _execute_model_download_action(self, action: SetupAction) -> List[SetupActionExecutionItem]:
        if self.download_manager is None or self.model_service is None:
            raise ValueError("Model download execution is unavailable.")

        model_ids = self._extract_model_ids(action.payload)
        if not model_ids:
            raise ValueError("No model ids were provided for download.")

        results: List[SetupActionExecutionItem] = []
        for model_id in model_ids:
            model_type, variant = self._resolve_model_type_and_variant(model_id)
            entry = await self.download_manager.start(model_type, variant)
            if (
                entry.status in {"queued", "downloading", "skipped_installed"}
                and self._is_transcription_model(model_id)
            ):
                self._schedule_transcription_default_update(entry.model_id, model_id)
            status = (
                SetupExecutionStatus.applied
                if entry.status in {"queued", "downloading", "skipped_installed"}
                else SetupExecutionStatus.failed
            )
            results.append(
                SetupActionExecutionItem(
                    id=f"{action.id}:{model_id}",
                    kind=action.kind.value,
                    status=status,
                    message=f"{model_id} is {entry.status.replace('_', ' ')}.",
                    result_payload={
                        "model_id": model_id,
                        "model_type": model_type,
                        "variant": variant,
                        "download_status": entry.status,
                    },
                )
            )

        return results

    def _schedule_transcription_default_update(
        self, download_id: str, transcription_model_id: str
    ) -> None:
        asyncio.create_task(
            self._set_transcription_default_after_download(
                download_id, transcription_model_id
            ),
            name=f"setup-transcription-default::{download_id}",
        )

    async def _set_transcription_default_after_download(
        self, download_id: str, transcription_model_id: str
    ) -> None:
        """Persist a setup-selected transcription model after a successful download."""
        entry = await self.download_manager.wait_for_terminal_status(download_id)
        if entry is None or entry.status not in {"completed", "skipped_installed"}:
            return

        try:
            from api.core.preferences.preferences_io import load_preferences, save_preferences

            preferences = load_preferences()
            preferences.models.transcription_model = transcription_model_id
            save_preferences(preferences)
        except Exception:
            api_logger.exception(
                "Could not set setup-selected transcription model '%s' as default.",
                transcription_model_id,
            )

    @staticmethod
    def _is_transcription_model(model_id: str) -> bool:
        from api.core.models.models_registry import (
            get_parakeet_transcription_models,
            get_transcription_models,
        )

        return (
            model_id in get_parakeet_transcription_models()
            or model_id in get_transcription_models()
        )

    def _execute_settings_update_action(self, action: SetupAction) -> SetupActionExecutionItem:
        from api.core.preferences.preferences_io import load_preferences, save_preferences

        preferences = load_preferences()
        settings_payload = action.payload.get("settings", action.payload)
        if not isinstance(settings_payload, dict):
            raise ValueError("Settings update payload must be an object.")

        applied_paths: List[str] = []
        ui_changes: List[Dict[str, Any]] = []
        for section_name, updates in settings_payload.items():
            if not isinstance(updates, dict):
                raise ValueError(f"Settings section '{section_name}' must be an object.")
            if section_name == "models":
                validate_model_settings_payload(updates)
                applied_paths.extend(
                    self._apply_allowed_settings(preferences.models, updates, MODEL_SETTINGS_ALLOWLIST, "models")
                )
            elif section_name == "behavior":
                applied_paths.extend(
                    self._apply_allowed_settings(preferences.behavior, updates, BEHAVIOR_SETTINGS_ALLOWLIST, "behavior")
                )
            elif section_name == "memory_intelligence":
                applied_paths.extend(
                    self._apply_allowed_settings(
                        preferences.memory_intelligence,
                        updates,
                        MEMORY_INTELLIGENCE_SETTINGS_ALLOWLIST,
                        "memory_intelligence",
                    )
                )
            elif section_name == "ui":
                ui_changes = self._apply_ui_settings(preferences.ui, updates)
                applied_paths.extend(change["path"] for change in ui_changes)
            else:
                raise ValueError(f"Settings section '{section_name}' is not allowed during setup.")

        if not applied_paths:
            raise ValueError("No allowed settings were provided.")

        save_preferences(preferences)
        message = f"Updated {len(applied_paths)} setting{'s' if len(applied_paths) != 1 else ''}."
        result_payload: Dict[str, Any] = {"updated_paths": applied_paths}
        if ui_changes:
            result_payload["ui_changes"] = ui_changes
            result_payload["appearance_settings"] = {
                key: getattr(preferences.ui, key)
                for key in sorted(UI_SETTINGS_ALLOWLIST)
            }
            text_rgb = (preferences.ui.text_color_red, preferences.ui.text_color_green, preferences.ui.text_color_blue)
            background_rgb = (
                preferences.ui.background_color_red,
                preferences.ui.background_color_green,
                preferences.ui.background_color_blue,
            )
            if not meets_minimum_contrast(text_rgb, background_rgb, "normal"):
                ratio = contrast_ratio(text_rgb, background_rgb)
                result_payload["contrast_warning"] = {"ratio": round(ratio, 2), "required_ratio": 4.5}
                message += (
                    f" Note: your text and background colors have a contrast ratio of {ratio:.1f}:1, "
                    "below the 4.5:1 recommended for normal text -- the change was saved as requested."
                )

        return SetupActionExecutionItem(
            id=action.id,
            kind=action.kind.value,
            status=SetupExecutionStatus.applied,
            message=message,
            result_payload=result_payload,
        )

    def _apply_ui_settings(self, ui_preferences: Any, updates: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Apply a validated partial `ui` payload, recording each change's prior value.

        Unlike `_apply_allowed_settings` (models/behavior/memory_intelligence,
        key-membership and attribute-existence only), this validates numeric
        range and font-catalog membership via `validate_ui_settings_payload`
        and records old/new values for the setup receipt's audit trail.
        """

        validate_ui_settings_payload(updates)
        changes: List[Dict[str, Any]] = []
        for key, value in updates.items():
            old_value = getattr(ui_preferences, key)
            setattr(ui_preferences, key, value)
            changes.append({"path": f"ui.{key}", "old_value": old_value, "new_value": value})
        return changes

    async def _execute_connection_refresh_action(self, action: SetupAction) -> SetupActionExecutionItem:
        if self.connection_refresher is None:
            raise ValueError("Connection tool refresh is unavailable.")

        connection_id = (
            action.payload.get("connection_id")
            or action.payload.get("connectionId")
            or action.payload.get("connector_id")
            or action.payload.get("connectorId")
        )
        if not isinstance(connection_id, str) or not connection_id.strip():
            raise ValueError("Connection tool refresh requires connection_id.")

        refreshed = await self.connection_refresher(connection_id.strip())
        tools = refreshed.get("tools", [])
        return SetupActionExecutionItem(
            id=action.id,
            kind=action.kind.value,
            status=SetupExecutionStatus.applied,
            message=f"Refreshed {len(tools)} tool{'s' if len(tools) != 1 else ''}.",
            result_payload={
                "connection_id": refreshed.get("id", connection_id),
                "tool_count": len(tools),
            },
        )

    def _extract_model_ids(self, payload: Dict[str, Any]) -> List[str]:
        raw_model_ids = payload.get("model_ids")
        if raw_model_ids is None and payload.get("model_id") is not None:
            raw_model_ids = [payload.get("model_id")]
        if not isinstance(raw_model_ids, list):
            return []
        return [model_id for model_id in raw_model_ids if isinstance(model_id, str) and model_id.strip()]

    def _resolve_model_type_and_variant(self, model_id: str) -> tuple[str, str]:
        available_models = self.model_service.model_downloader.get_available_models()
        for model_type, model_data in available_models.items():
            variants = model_data.get("variants", {})
            for variant, config in variants.items():
                if config.get("model_id") == model_id:
                    return model_type, variant
        raise ValueError(f"Model '{model_id}' is not available for download.")

    def _apply_allowed_settings(
        self,
        settings_obj: Any,
        updates: Dict[str, Any],
        allowed_keys: set[str],
        section_name: str,
    ) -> List[str]:
        applied: List[str] = []
        for key, value in updates.items():
            if key not in allowed_keys:
                raise ValueError(f"Setting '{section_name}.{key}' is not allowed during setup.")
            if not hasattr(settings_obj, key):
                raise ValueError(f"Setting '{section_name}.{key}' does not exist.")
            setattr(settings_obj, key, value)
            applied.append(f"{section_name}.{key}")
        return applied

    def _tool_call_to_action(self, tool_call: SetupToolCall) -> SetupAction:
        tool_name_to_kind = {
            "start_model_downloads": SetupActionKind.start_model_downloads,
            "update_basil_settings": SetupActionKind.update_settings,
            "refresh_connection_tools": SetupActionKind.refresh_connection_tools,
            "launch_assistant_session": SetupActionKind.launch_assistant_session,
            "launch_agent_task": SetupActionKind.launch_agent_task,
        }
        kind = tool_name_to_kind.get(tool_call.tool_name)
        if kind is None:
            raise ValueError(f"Setup tool call '{tool_call.tool_name}' is handled outside the backend executor.")
        return SetupAction(
            id=tool_call.id,
            kind=kind,
            payload=tool_call.payload,
            requires_explicit_approval=True,
            mutates_external_state=tool_call.mutates_external_state,
        )

