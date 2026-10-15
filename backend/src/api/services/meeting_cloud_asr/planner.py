"""Chooses whether and how a socket transcribes in the cloud, and builds the session for it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from . import settings_store as settings_module
from .assemblyai_provider import AssemblyAIProvider
from .chunked_provider import ChunkedProxyProvider
from .deepgram_provider import DeepgramProvider
from .models import (
    CONNECTION_BASIL_ACCOUNT,
    CONNECTION_OWN_KEY,
    PROVIDER_ASSEMBLYAI,
    PROVIDER_DEEPGRAM,
    TIER_CHUNKED,
    TIER_STREAMING,
    StreamingAsrProvider,
)
from .session import CloudAsrSession


def build_streaming_provider(provider_id: str, key: str) -> StreamingAsrProvider:
    """The vendor provider for a key the user supplied."""
    if provider_id == PROVIDER_DEEPGRAM:
        return DeepgramProvider(key)
    if provider_id == PROVIDER_ASSEMBLYAI:
        return AssemblyAIProvider(key)
    raise ValueError(f"Unknown cloud transcription provider: {provider_id}")


@dataclass(frozen=True)
class CloudPlan:
    provider_id: str
    tier: str
    build_provider: Callable[[], StreamingAsrProvider]


def plan_cloud_session(
    *,
    store: Optional[settings_module.CloudTranscriptionSettingsStore] = None,
    keys: Optional[settings_module.KeyAccess] = None,
    account_available: Optional[Callable[[], bool]] = None,
) -> Optional[CloudPlan]:
    """The plan for a new socket, or None when cloud transcription is off or not usable (local transcription then applies)."""
    settings = (store or settings_module.get_settings_store()).load()
    if not settings.enabled or not settings.acknowledged:
        return None
    if settings.connection == CONNECTION_OWN_KEY:
        key = (keys or settings_module.get_key_access()).read(settings.provider)
        if not key:
            return None
        provider_id = settings.provider
        return CloudPlan(provider_id, TIER_STREAMING, lambda: build_streaming_provider(provider_id, key))
    if settings.connection == CONNECTION_BASIL_ACCOUNT:
        if not (account_available or settings_module.account_token_available)():
            return None
        return CloudPlan(CONNECTION_BASIL_ACCOUNT, TIER_CHUNKED, lambda: ChunkedProxyProvider())
    return None


def cloud_transcription_available() -> bool:
    return plan_cloud_session() is not None


def create_cloud_session(
    *,
    base_sample: int,
    timeline_for_sample: Callable[[int], Optional[float]],
    meeting_recorder: Any,
    send_json: Callable[[dict], Any],
    on_failure: Callable[[str], None],
) -> Optional[CloudAsrSession]:
    """A not-yet-started session for the current settings; None selects local transcription."""
    plan = plan_cloud_session()
    if plan is None:
        return None
    return CloudAsrSession(
        provider=plan.build_provider(),
        provider_id=plan.provider_id,
        tier=plan.tier,
        base_sample=base_sample,
        timeline_for_sample=timeline_for_sample,
        meeting_recorder=meeting_recorder,
        send_json=send_json,
        on_failure=on_failure,
    )
