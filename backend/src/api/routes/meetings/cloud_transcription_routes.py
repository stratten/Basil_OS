"""Cloud transcription routes: opt-in settings, provider keys (write-only), a no-audio connection check, and live status."""

from typing import Callable, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.services.meeting_cloud_asr import settings_store as settings_module
from api.services.meeting_cloud_asr.models import (
    CONNECTION_BASIL_ACCOUNT,
    CONNECTION_OWN_KEY,
    PROVIDER_IDS,
    PROVIDER_LABELS,
    CloudAsrError,
    StreamingAsrProvider,
)
from api.services.meeting_cloud_asr.planner import build_streaming_provider
from api.services.meeting_cloud_asr.registry import cloud_status_registry

router = APIRouter()

ProviderId = Literal["deepgram", "assemblyai"]


class ProviderInfo(BaseModel):
    id: ProviderId
    label: str
    has_key: bool


class CloudStatusModel(BaseModel):
    state: Literal["off", "connecting", "streaming", "fallback"]
    provider: Optional[str] = None
    tier: Optional[str] = None
    reason: Optional[str] = None


class CloudTranscriptionState(BaseModel):
    enabled: bool
    provider: ProviderId
    connection: Literal["own_key", "basil_account"]
    acknowledged: bool
    account_available: bool
    providers: List[ProviderInfo]
    status: CloudStatusModel


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: Optional[bool] = None
    provider: Optional[ProviderId] = None
    connection: Optional[Literal["own_key", "basil_account"]] = None
    acknowledge_disclosure: bool = False


class KeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(min_length=8, max_length=512)

    @field_validator("api_key")
    @classmethod
    def reject_whitespace(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped or any(character.isspace() for character in stripped):
            raise ValueError("An API key cannot contain spaces.")
        return stripped


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ProviderId


class CheckResult(BaseModel):
    ok: bool
    message: str


def get_store() -> settings_module.CloudTranscriptionSettingsStore:
    return settings_module.get_settings_store()


def get_keys() -> settings_module.KeyAccess:
    return settings_module.get_key_access()


def get_account_check() -> Callable[[], bool]:
    return settings_module.account_token_available


def get_provider_builder() -> Callable[[str, str], StreamingAsrProvider]:
    return build_streaming_provider


def build_state(
    store: settings_module.CloudTranscriptionSettingsStore,
    keys: settings_module.KeyAccess,
    account_available: Callable[[], bool],
) -> CloudTranscriptionState:
    settings = store.load()
    aggregate = cloud_status_registry.aggregate()
    return CloudTranscriptionState(
        enabled=settings.enabled,
        provider=settings.provider,
        connection=settings.connection,
        acknowledged=settings.acknowledged,
        account_available=account_available(),
        providers=[
            ProviderInfo(id=provider_id, label=PROVIDER_LABELS[provider_id], has_key=bool(keys.read(provider_id)))
            for provider_id in PROVIDER_IDS
        ],
        status=CloudStatusModel(
            state=aggregate["state"], provider=aggregate["provider"], tier=aggregate["tier"], reason=aggregate["reason"]
        ),
    )


@router.get("/cloud-transcription", response_model=CloudTranscriptionState)
async def read_cloud_transcription(
    store=Depends(get_store), keys=Depends(get_keys), account=Depends(get_account_check)
) -> CloudTranscriptionState:
    return build_state(store, keys, account)


@router.put("/cloud-transcription/settings", response_model=CloudTranscriptionState)
async def update_cloud_transcription(
    request: SettingsUpdateRequest,
    store=Depends(get_store),
    keys=Depends(get_keys),
    account=Depends(get_account_check),
) -> CloudTranscriptionState:
    data = store.load().model_dump()
    if request.provider is not None:
        data["provider"] = request.provider
    if request.connection is not None:
        data["connection"] = request.connection
    if request.acknowledge_disclosure:
        data["acknowledged"] = True
    if request.enabled is not None:
        data["enabled"] = request.enabled
    merged = settings_module.CloudTranscriptionSettings(**data)
    if merged.enabled:
        if not merged.acknowledged:
            raise HTTPException(status_code=400, detail="Read and accept the disclosure before turning on cloud transcription.")
        if merged.connection == CONNECTION_OWN_KEY and not keys.read(merged.provider):
            raise HTTPException(status_code=409, detail=f"Add a {PROVIDER_LABELS[merged.provider]} API key first.")
        if merged.connection == CONNECTION_BASIL_ACCOUNT and not account():
            raise HTTPException(status_code=409, detail="Sign in to Basil to use your account for cloud transcription.")
    store.save(merged)
    return build_state(store, keys, account)


@router.put("/cloud-transcription/keys/{provider}", response_model=CloudTranscriptionState)
async def save_provider_key(
    provider: str,
    request: KeyRequest,
    store=Depends(get_store),
    keys=Depends(get_keys),
    account=Depends(get_account_check),
) -> CloudTranscriptionState:
    if provider not in PROVIDER_IDS:
        raise HTTPException(status_code=404, detail="Unknown cloud transcription provider.")
    if not keys.write(provider, request.api_key):
        raise HTTPException(status_code=500, detail="Could not save the key to the system credential store.")
    return build_state(store, keys, account)


@router.delete("/cloud-transcription/keys/{provider}", response_model=CloudTranscriptionState)
async def delete_provider_key(
    provider: str,
    store=Depends(get_store),
    keys=Depends(get_keys),
    account=Depends(get_account_check),
) -> CloudTranscriptionState:
    if provider not in PROVIDER_IDS:
        raise HTTPException(status_code=404, detail="Unknown cloud transcription provider.")
    keys.clear(provider)
    settings = store.load()
    if settings.enabled and settings.connection == CONNECTION_OWN_KEY and settings.provider == provider:
        store.save(settings.model_copy(update={"enabled": False}))
    return build_state(store, keys, account)


@router.post("/cloud-transcription/check", response_model=CheckResult)
async def check_provider_connection(
    request: CheckRequest,
    keys=Depends(get_keys),
    builder=Depends(get_provider_builder),
) -> CheckResult:
    label = PROVIDER_LABELS[request.provider]
    key = keys.read(request.provider)
    if not key:
        return CheckResult(ok=False, message=f"Add a {label} API key first.")
    provider = builder(request.provider, key)
    try:
        await provider.open()
    except CloudAsrError as error:
        return CheckResult(ok=False, message=str(error))
    await provider.close()
    return CheckResult(ok=True, message=f"Connected to {label}. No meeting audio was sent.")
