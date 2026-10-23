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


ENGINE_LOCAL = "local"
ENGINE_CHOICES = frozenset({ENGINE_LOCAL, PROVIDER_DEEPGRAM, PROVIDER_ASSEMBLYAI, CONNECTION_BASIL_ACCOUNT})


def normalize_engine_override(value: Optional[str]) -> Optional[str]:
    """The per-recording engine choice from a socket, or None when absent or not a known choice (the saved default then applies)."""
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned if cleaned in ENGINE_CHOICES else None


def plan_cloud_session(
    *,
    store: Optional[settings_module.CloudTranscriptionSettingsStore] = None,
    keys: Optional[settings_module.KeyAccess] = None,
    account_available: Optional[Callable[[], bool]] = None,
    engine_override: Optional[str] = None,
) -> Optional[CloudPlan]:
    """The plan for a new socket, or None when cloud transcription is off or not usable (local transcription then applies).

    ``engine_override`` is the choice for this one recording. It replaces the saved default (the on/off switch, provider and connection) but never the disclosure acknowledgment, the saved key or the signed-in account, and it is never written back to the settings.
    """
    override = normalize_engine_override(engine_override)
    settings = (store or settings_module.get_settings_store()).load()
    if override is None:
        if not settings.enabled or not settings.acknowledged:
            return None
        connection, provider = settings.connection, settings.provider
    else:
        if override == ENGINE_LOCAL or not settings.acknowledged:
            return None
        if override == CONNECTION_BASIL_ACCOUNT:
            connection, provider = CONNECTION_BASIL_ACCOUNT, settings.provider
        else:
            connection, provider = CONNECTION_OWN_KEY, override
    if connection == CONNECTION_OWN_KEY:
        key = (keys or settings_module.get_key_access()).read(provider)
        if not key:
            return None
        return CloudPlan(provider, TIER_STREAMING, lambda: build_streaming_provider(provider, key))
    if connection == CONNECTION_BASIL_ACCOUNT:
        if not (account_available or settings_module.account_token_available)():
            return None
        return CloudPlan(CONNECTION_BASIL_ACCOUNT, TIER_CHUNKED, lambda: ChunkedProxyProvider())
    return None


def cloud_transcription_available(engine_override: Optional[str] = None) -> bool:
    return plan_cloud_session(engine_override=engine_override) is not None


def create_cloud_session(
    *,
    base_sample: int,
    timeline_for_sample: Callable[[int], Optional[float]],
    meeting_recorder: Any,
    send_json: Callable[[dict], Any],
    on_failure: Callable[[str], None],
    engine_override: Optional[str] = None,
) -> Optional[CloudAsrSession]:
    """A not-yet-started session for the current settings and this recording's engine choice; None selects local transcription."""
    plan = plan_cloud_session(engine_override=engine_override)
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
