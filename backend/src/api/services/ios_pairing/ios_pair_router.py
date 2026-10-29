from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from api.core.config.api_settings import settings
from api.services.ios_pairing.pair_token_store import PairTokenStore


router = APIRouter(prefix="/ios-pair", tags=["ios-pairing"])


class PairStartResponse(BaseModel):
    pairing_id: str
    secret: str
    expires_at: str


class PairCompleteRequest(BaseModel):
    pairing_id: str
    secret: str
    device_id: str = Field(min_length=1)
    device_name: str = Field(min_length=1)


class PairCompleteResponse(BaseModel):
    device_id: str
    device_name: str
    token: str
    issued_at: str


class PairedDeviceResponse(BaseModel):
    device_id: str
    device_name: str
    issued_at: str


class RevokePairRequest(BaseModel):
    device_id: str = Field(min_length=1)


def get_pair_token_store() -> PairTokenStore:
    return PairTokenStore(Path(settings.STORAGE_DIR) / "ios_pairing.sqlite3")


def require_pairing_enabled() -> None:
    if not settings.IOS_PAIR_ENABLED:
        raise HTTPException(status_code=404, detail="iOS pairing is not enabled")


async def require_pair_token(
    authorization: Optional[str] = Header(default=None),
    store: PairTokenStore = Depends(get_pair_token_store),
) -> None:
    require_pairing_enabled()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing pair token")
    token = authorization.removeprefix("Bearer ").strip()
    if not store.validate_token(token):
        raise HTTPException(status_code=403, detail="Invalid pair token")


@router.post("/start", response_model=PairStartResponse)
async def start_pairing(store: PairTokenStore = Depends(get_pair_token_store)) -> PairStartResponse:
    require_pairing_enabled()
    pairing_secret = store.create_pairing_secret()
    return PairStartResponse(
        pairing_id=pairing_secret.pairing_id,
        secret=pairing_secret.secret,
        expires_at=pairing_secret.expires_at.isoformat(),
    )


@router.post("/complete", response_model=PairCompleteResponse)
async def complete_pairing(
    request: PairCompleteRequest,
    store: PairTokenStore = Depends(get_pair_token_store),
) -> PairCompleteResponse:
    require_pairing_enabled()
    token = store.complete_pairing(
        pairing_id=request.pairing_id,
        secret=request.secret,
        device_id=request.device_id,
        device_name=request.device_name,
    )
    if token is None:
        raise HTTPException(status_code=400, detail="Invalid or expired pairing secret")
    return PairCompleteResponse(
        device_id=token.device_id,
        device_name=token.device_name,
        token=token.token,
        issued_at=token.issued_at.isoformat(),
    )


@router.get("/devices", response_model=list[PairedDeviceResponse], dependencies=[Depends(require_pair_token)])
async def list_paired_devices(store: PairTokenStore = Depends(get_pair_token_store)) -> list[PairedDeviceResponse]:
    return [PairedDeviceResponse(**device) for device in store.list_devices()]


@router.post("/revoke", dependencies=[Depends(require_pair_token)])
async def revoke_pairing(
    request: RevokePairRequest,
    store: PairTokenStore = Depends(get_pair_token_store),
) -> dict[str, bool]:
    return {"revoked": store.revoke_device(request.device_id)}

