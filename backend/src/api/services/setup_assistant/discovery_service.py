"""Read-only discovery collection for the setup assistant."""

from __future__ import annotations

from datetime import datetime
from typing import List

from api.core.runtime.hardware_capability_service import (
    HardwareCapabilityProfile,
    HardwareCapabilityService,
)
from api.core.services.model_service import ModelService
from api.routes.setup_assistant.models import (
    SetupDiscoveryFact,
    SetupDiscoveryFactKind,
    SetupDiscoveryResponse,
    SetupDiscoverySource,
)


class SetupAssistantDiscoveryService:
    """Collect non-mutating facts for onboarding recommendations."""

    def __init__(self, model_service: ModelService) -> None:
        self.model_service = model_service

    async def collect_low_risk_setup_facts(self) -> SetupDiscoveryResponse:
        """Collect setup facts that do not inspect user content."""

        from api.core.preferences.preferences_io import load_preferences
        from api.routes.onboarding import STARTER_MODELS

        collected_at = datetime.utcnow()
        facts: List[SetupDiscoveryFact] = []
        preferences = load_preferences()

        facts.append(
            SetupDiscoveryFact(
                id="activity-capture-enabled",
                source=SetupDiscoverySource.activity_capture,
                kind=SetupDiscoveryFactKind.current_setting,
                value=str(preferences.activity_capture.enabled).lower(),
                confidence=1.0,
                collected_at=collected_at,
                user_visible_summary=(
                    "Basil checked whether automatic activity capture is currently enabled."
                ),
                metadata={
                    "frequency_minutes": str(preferences.activity_capture.frequency_minutes),
                    "processing_mode": preferences.activity_capture.processing_mode,
                },
            )
        )

        facts.append(
            SetupDiscoveryFact(
                id="assistant-session-close-on-insert",
                source=SetupDiscoverySource.basil_settings,
                kind=SetupDiscoveryFactKind.current_setting,
                value=str(preferences.models.close_assistant_session_on_insert).lower(),
                confidence=1.0,
                collected_at=collected_at,
                user_visible_summary=(
                    "Basil checked whether Dill currently closes after inserting a suggestion."
                ),
                metadata={},
            )
        )

        facts.append(
            SetupDiscoveryFact(
                id="hotkey-monitoring-at-startup",
                source=SetupDiscoverySource.basil_settings,
                kind=SetupDiscoveryFactKind.current_setting,
                value=str(preferences.behavior.enable_monitoring_at_startup).lower(),
                confidence=1.0,
                collected_at=collected_at,
                user_visible_summary=(
                    "Basil checked whether global hotkey monitoring is enabled at startup."
                ),
                metadata={
                    "settings_path": "behavior.enable_monitoring_at_startup",
                    "customization_location": "Settings > General",
                },
            )
        )

        facts.append(
            SetupDiscoveryFact(
                id="voice-listener-at-startup",
                source=SetupDiscoverySource.basil_settings,
                kind=SetupDiscoveryFactKind.current_setting,
                value=str(preferences.behavior.enable_voice_listener_at_startup).lower(),
                confidence=1.0,
                collected_at=collected_at,
                user_visible_summary=(
                    "Basil checked whether the voice listener starts automatically."
                ),
                metadata={
                    "settings_path": "behavior.enable_voice_listener_at_startup",
                    "wake_phrase": "Hey Basil",
                    "customization_location": "Settings > General",
                },
            )
        )

        facts.extend(self._build_hotkey_facts(preferences.hotkeys, collected_at))
        facts.extend(self._build_hardware_capability_facts(collected_at))

        for starter_model in STARTER_MODELS:
            model_type = starter_model["model_type"]
            variant = starter_model["variant"]
            model_id = f"{model_type}-{variant}"
            is_installed = self.model_service.is_model_downloaded(model_type, variant)

            facts.append(
                SetupDiscoveryFact(
                    id=f"starter-model-{model_id}",
                    source=SetupDiscoverySource.model_status,
                    kind=SetupDiscoveryFactKind.available_model,
                    value="installed" if is_installed else "missing",
                    confidence=1.0,
                    collected_at=collected_at,
                    user_visible_summary=(
                        f"Basil checked starter model status for {starter_model['description']}."
                    ),
                    metadata={
                        "model_type": model_type,
                        "variant": variant,
                        "model_id": model_id,
                        "description": starter_model["description"],
                    },
                )
            )

        await self._append_existing_profile_facts(facts, collected_at)

        return SetupDiscoveryResponse(facts=facts, collected_at=collected_at)

    def _build_hotkey_facts(self, hotkeys, collected_at: datetime) -> List[SetupDiscoveryFact]:
        """Expose current invocation shortcuts as read-only setup facts."""

        capabilities = [
            (
                "conversation_toggle",
                "conversation",
                "Conversation",
                "Opens Basil's main conversation surface.",
            ),
            (
                "transcribe_audio",
                "transcription",
                "Transcription",
                "Starts push-to-talk transcription.",
            ),
            (
                "assistant_session",
                "dill",
                "Dill",
                "Opens Dill, Basil's writing and reply partner.",
            ),
            (
                "agent_task",
                "paprika",
                "Paprika",
                "Starts or stops Paprika agent task capture.",
            ),
            (
                "home_board_toggle",
                "basil_home",
                "Basil Home",
                "Opens or hides Basil Home, the workspace for conversations, To-Dos, and agent-task progress.",
            ),
        ]

        facts: List[SetupDiscoveryFact] = []
        for hotkey_id, capability_id, display_name, summary in capabilities:
            binding = hotkeys.get(hotkey_id)
            current_binding = self._format_hotkey_binding(binding)
            facts.append(
                SetupDiscoveryFact(
                    id=f"hotkey-{hotkey_id}",
                    source=SetupDiscoverySource.basil_settings,
                    kind=SetupDiscoveryFactKind.current_setting,
                    value=current_binding,
                    confidence=1.0,
                    collected_at=collected_at,
                    user_visible_summary=f"Basil checked the current {display_name} hotkey.",
                    metadata={
                        "hotkey_id": hotkey_id,
                        "capability_id": capability_id,
                        "capability_name": display_name,
                        "enabled": str(getattr(binding, "enabled", False)).lower(),
                        "description": getattr(binding, "description", "") or summary,
                        "customization_location": "Settings > Hotkeys",
                    },
                )
            )

        return facts

    def _format_hotkey_binding(self, binding) -> str:
        if binding is None:
            return "not configured"

        if getattr(binding, "is_double_press", False):
            double_press_key = getattr(binding, "double_press_key", None)
            if double_press_key:
                readable_key = self._format_hotkey_token(double_press_key)
                return f"{readable_key}+{readable_key}"

        parts = [
            self._format_hotkey_token(modifier)
            for modifier in getattr(binding, "modifiers", [])
        ]
        key = getattr(binding, "key", "")
        if key:
            parts.append(self._format_hotkey_token(key))

        if not parts:
            return "not configured"
        return "+".join(parts)

    def _format_hotkey_token(self, token: str) -> str:
        return {
            "cmd": "Command",
            "command": "Command",
            "ctrl": "Control",
            "control": "Control",
            "opt": "Option",
            "option": "Option",
            "alt": "Option",
            "shift": "Shift",
            "space": "Space",
        }.get(token.lower(), token)

    def _build_hardware_capability_facts(
        self,
        collected_at: datetime,
    ) -> List[SetupDiscoveryFact]:
        """Expose local runtime capacity for setup recommendations."""

        profile = HardwareCapabilityService().get_profile()
        summary = (
            f"Basil detected a {profile.memory_tier.replace('_', ' ')} memory local-model runtime "
            f"with {profile.total_ram_gb}GB RAM."
        )
        return [
            SetupDiscoveryFact(
                id="hardware-runtime-profile",
                source=SetupDiscoverySource.runtime_operations,
                kind=SetupDiscoveryFactKind.capability_available,
                value=profile.memory_tier,
                confidence=1.0,
                collected_at=collected_at,
                user_visible_summary=summary,
                metadata={
                    "platform": profile.platform,
                    "machine": profile.machine,
                    "chip_label": profile.chip_label or "",
                    "total_ram_gb": str(profile.total_ram_gb),
                    "local_model_memory_budget_gb": str(profile.local_model_memory_budget_gb),
                    "is_apple_silicon": str(profile.is_apple_silicon).lower(),
                    "gpu_available": str(profile.gpu_available).lower(),
                    "gpu_backend": str(profile.gpu_backend or ""),
                    "mps_available": str(profile.mps_available).lower(),
                    "cuda_available": str(profile.cuda_available).lower(),
                    "coreml_execution_provider_available": str(
                        profile.coreml_execution_provider_available
                    ).lower(),
                    "mlx_whisper_available": str(profile.mlx_whisper_available).lower(),
                    "faster_whisper_available": str(profile.faster_whisper_available).lower(),
                    "recommended_threads": str(profile.recommended_threads),
                    "recommended_llama_batch": str(profile.recommended_llama_batch),
                    "recommended_llama_ubatch": str(profile.recommended_llama_ubatch),
                },
            )
        ]

    async def collect_model_catalog_facts(self) -> SetupDiscoveryResponse:
        """Collect catalog-driven local model recommendation facts."""

        from api.core.models.models_registry import (
            get_local_reasoning_models,
            get_transcription_models,
        )

        collected_at = datetime.utcnow()
        facts: List[SetupDiscoveryFact] = []
        hardware_profile = HardwareCapabilityService().get_profile()

        for model_id, config in get_local_reasoning_models().items():
            if "reasoning" not in config.get("capabilities", []):
                continue
            facts.append(
                SetupDiscoveryFact(
                    id=f"model-catalog-{model_id}",
                    source=SetupDiscoverySource.model_status,
                    kind=SetupDiscoveryFactKind.available_model,
                    value=model_id,
                    confidence=1.0,
                    collected_at=collected_at,
                    user_visible_summary=(
                        f"Basil found local reasoning model option {config.get('display_name', model_id)}."
                    ),
                    metadata=self._build_model_metadata(config, hardware_profile),
                )
            )

        for model_id, config in get_transcription_models().items():
            facts.append(
                SetupDiscoveryFact(
                    id=f"model-catalog-{model_id}",
                    source=SetupDiscoverySource.model_status,
                    kind=SetupDiscoveryFactKind.available_model,
                    value=model_id,
                    confidence=1.0,
                    collected_at=collected_at,
                    user_visible_summary=(
                        f"Basil found transcription model option {config.get('display_name', model_id)}."
                    ),
                    metadata=self._build_model_metadata(config, hardware_profile),
                )
            )

        return SetupDiscoveryResponse(facts=facts, collected_at=collected_at)

    async def collect_email_client_facts(self) -> SetupDiscoveryResponse:
        """Detect available email clients without reading message contents."""

        from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_client_service import (
            EmailClientService,
        )

        collected_at = datetime.utcnow()
        facts: List[SetupDiscoveryFact] = []
        service = EmailClientService()
        detected_clients = await service.detect_email_clients()
        primary_client = await service.select_primary_client()

        for client in detected_clients:
            facts.append(
                SetupDiscoveryFact(
                    id=f"email-client-{client.bundle_id}",
                    source=SetupDiscoverySource.email_clients,
                    kind=SetupDiscoveryFactKind.detected_email_client,
                    value=client.name,
                    confidence=0.95 if client == primary_client else 0.8,
                    collected_at=collected_at,
                    user_visible_summary=(
                        f"Basil detected {client.name} as an available email client."
                    ),
                    metadata={
                        "bundle_id": client.bundle_id,
                        "is_running": str(client.is_running).lower(),
                        "automation_method": client.automation_method,
                        "capabilities": ",".join(client.capabilities),
                        "is_primary": str(client == primary_client).lower(),
                    },
                )
            )

        return SetupDiscoveryResponse(facts=facts, collected_at=collected_at)

    async def collect_connection_catalog_facts(self) -> SetupDiscoveryResponse:
        """Collect supported and registered connection state for onboarding."""

        from api.core.preferences.preferences_io import load_preferences
        from api.routes.connections.models import STARTER_SERVERS

        collected_at = datetime.utcnow()
        preferences = load_preferences()
        registered_by_url = {
            connection.server_url: connection
            for connection in preferences.connections.mcp_connections
        }
        facts: List[SetupDiscoveryFact] = []

        for server in STARTER_SERVERS:
            registered = registered_by_url.get(server.server_url)
            facts.append(
                SetupDiscoveryFact(
                    id=f"connection-catalog-{server.id}",
                    source=SetupDiscoverySource.connections,
                    kind=SetupDiscoveryFactKind.detected_connection,
                    value=server.id,
                    confidence=1.0,
                    collected_at=collected_at,
                    user_visible_summary=(
                        f"Basil found {server.friendly_name} in the supported connection catalog."
                    ),
                    metadata={
                        "friendly_name": server.friendly_name,
                        "server_url": server.server_url,
                        "description": server.description,
                        "auth_status": "connected" if registered else "available",
                        "connection_id": registered.id if registered else "",
                        "tool_count": str(len(registered.cached_tools)) if registered else "0",
                    },
                )
            )

        return SetupDiscoveryResponse(facts=facts, collected_at=collected_at)

    async def collect_sent_email_metadata_facts(
        self,
        days_back: int = 14,
        limit: int = 25,
    ) -> SetupDiscoveryResponse:
        """Collect opt-in sent-email metadata for writing-sample triage."""

        from datetime import timedelta

        from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_client_service import (
            EmailClientService,
        )
        from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_models import (
            EmailSearchCriteria,
        )

        collected_at = datetime.utcnow()
        facts: List[SetupDiscoveryFact] = []
        service = EmailClientService()
        await service.initialize()
        primary_client = await service.select_primary_client()
        if primary_client is None:
            return SetupDiscoveryResponse(facts=facts, collected_at=collected_at)

        bounded_days = min(max(days_back, 1), 60)
        bounded_limit = min(max(limit, 1), 50)
        metadata_records = await service.get_email_metadata(
            folder="sent",
            limit=bounded_limit,
            search_criteria=EmailSearchCriteria(
                date_from=datetime.utcnow() - timedelta(days=bounded_days),
                folder="sent",
            ),
            client_name=primary_client.name,
            deduplicate_threads=True,
            skip_default_filter=True,
        )

        for email in metadata_records:
            facts.append(
                SetupDiscoveryFact(
                    id=f"sent-email-metadata-{email.id}",
                    source=SetupDiscoverySource.writing_samples,
                    kind=SetupDiscoveryFactKind.writing_sample_summary,
                    value=email.subject or "(no subject)",
                    confidence=0.75,
                    collected_at=collected_at,
                    user_visible_summary=(
                        "Basil found sent-email metadata that may help select representative writing samples."
                    ),
                    metadata={
                        "email_id": email.id,
                        "client_name": primary_client.name,
                        "folder": "sent",
                        "recipient": email.recipient,
                        "subject": email.subject,
                        "date_sent": email.date_sent.isoformat() if email.date_sent else "",
                        "content_available": str(bool(email.content)).lower(),
                    },
                )
            )

        return SetupDiscoveryResponse(facts=facts, collected_at=collected_at)

    async def _append_existing_profile_facts(
        self,
        facts: List[SetupDiscoveryFact],
        collected_at: datetime,
    ) -> None:
        """Append existing personalization profile facts without blocking discovery."""

        try:
            from api.core.knowledge.personalization_service import PersonalizationService

            profile = await PersonalizationService().get_user_profile()
            if profile is None:
                return

            profile_values = profile.model_dump()
            for field_name in [
                "full_name",
                "preferred_name",
                "email",
                "job_title",
                "company_name",
                "industry",
                "default_formality",
                "default_tone",
            ]:
                field_value = profile_values.get(field_name)
                if not field_value:
                    continue

                facts.append(
                    SetupDiscoveryFact(
                        id=f"profile-field-{field_name}",
                        source=SetupDiscoverySource.user_profile,
                        kind=SetupDiscoveryFactKind.profile_field,
                        value=str(field_value),
                        confidence=1.0,
                        collected_at=collected_at,
                        user_visible_summary=(
                            f"Basil found an existing profile value for {field_name}."
                        ),
                        metadata={"field": field_name},
                    )
                )
        except Exception:
            # Profile discovery should not block the rest of setup discovery.
            return

    def _build_model_metadata(
        self,
        config: dict,
        hardware_profile: HardwareCapabilityProfile | None = None,
    ) -> dict[str, str]:
        """Normalize model registry metadata for setup discovery facts."""

        metadata = {
            "display_name": str(config.get("display_name", "")),
            "provider": str(config.get("provider", "")),
            "handler": str(config.get("handler", "")),
            "location": str(config.get("location", "")),
            "capabilities": ",".join(str(item) for item in config.get("capabilities", [])),
            "features": ",".join(str(item) for item in config.get("features", [])),
            "size": str(config.get("size", "")),
            "recommended_ram": str(config.get("recommended_ram", "")),
            "speed_rating": str(config.get("speed_rating", "")),
            "accuracy_rating": str(config.get("accuracy_rating", "")),
            "recommended": str(config.get("recommended", False)).lower(),
            "recommended_for_onboarding": str(config.get("recommended_for_onboarding", False)).lower(),
            "recommended_reason": str(config.get("recommended_reason", "")),
        }
        if hardware_profile is not None:
            metadata.update(self._build_model_hardware_metadata(config, hardware_profile))
        return metadata

    def _build_model_hardware_metadata(
        self,
        config: dict,
        hardware_profile: HardwareCapabilityProfile,
    ) -> dict[str, str]:
        handler = str(config.get("handler", ""))
        features = config.get("features", [])
        recommended_ram_gb = self._parse_recommended_ram_gb(config.get("recommended_ram"))
        fits_memory_budget = (
            recommended_ram_gb is None
            or recommended_ram_gb <= hardware_profile.local_model_memory_budget_gb
        )

        backend_hint = "cpu"
        if handler in {"llama_cpp", "llama_cpp_vision"} and hardware_profile.gpu_available:
            backend_hint = (
                "metal_all_gpu_layers"
                if hardware_profile.gpu_backend == "metal"
                else str(hardware_profile.gpu_backend or "gpu")
            )
        elif handler == "parakeet" and hardware_profile.prefer_coreml_onnx:
            backend_hint = "coreml_onnx"
        elif handler == "whisper" and hardware_profile.prefer_mlx_whisper:
            backend_hint = "mlx_whisper"
        elif handler == "whisper" and hardware_profile.faster_whisper_available:
            backend_hint = "faster_whisper_cpu"

        return {
            "hardware_fits_memory_budget": str(fits_memory_budget).lower(),
            "hardware_recommended_backend": backend_hint,
            "hardware_supports_gpu_feature": str(
                "gpu_acceleration" in features and hardware_profile.gpu_available
            ).lower(),
            "hardware_memory_tier": hardware_profile.memory_tier,
        }

    @staticmethod
    def _parse_recommended_ram_gb(value) -> int | None:
        if value is None:
            return None
        digits = "".join(ch for ch in str(value) if ch.isdigit())
        if not digits:
            return None
        return int(digits)

