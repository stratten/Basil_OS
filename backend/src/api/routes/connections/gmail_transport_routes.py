"""Routes for choosing how Gmail connections reach Gmail."""

from __future__ import annotations

import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.core.security.backend_request_guard import require_host_credential
from api.services.mcp_connectors.gmail_local_server.transport import GMAIL_TRANSPORT_ENV, gmail_transport

from .connection_route_helpers import load_connection_preferences, save_connection_preferences


class GmailTransportResponse(BaseModel):
    """The saved choice and the transport actually in effect."""

    saved: Literal["direct", "mcp"]
    effective: Literal["direct", "mcp"]
    pinned_by_environment: bool


class GmailTransportUpdate(BaseModel):
    transport: Literal["direct", "mcp"]


def _response() -> GmailTransportResponse:
    saved = load_connection_preferences().connections.gmail_transport
    pinned = os.environ.get(GMAIL_TRANSPORT_ENV, "").strip().lower() in ("direct", "mcp")
    return GmailTransportResponse(saved=saved, effective=gmail_transport(), pinned_by_environment=pinned)


async def get_gmail_transport_route() -> GmailTransportResponse:
    """Report the saved Gmail transport and whether an environment variable overrides it."""
    return _response()


async def set_gmail_transport_route(payload: GmailTransportUpdate) -> GmailTransportResponse:
    """Save the Gmail transport. Both transports use the same sign-in scope, so no reconnect is needed."""
    prefs = load_connection_preferences()
    if prefs.connections.gmail_transport != payload.transport:
        prefs.connections.gmail_transport = payload.transport
        save_connection_preferences(prefs)
    return _response()


def register_gmail_transport_routes(router: APIRouter) -> None:
    """Attach the Gmail transport endpoints to the connections router."""
    router.add_api_route(
        "/gmail_transport",
        get_gmail_transport_route,
        methods=["GET"],
        response_model=GmailTransportResponse,
        name="get_gmail_transport",
    )
    router.add_api_route(
        "/gmail_transport",
        set_gmail_transport_route,
        methods=["PUT"],
        response_model=GmailTransportResponse,
        dependencies=[Depends(require_host_credential)],
        name="set_gmail_transport",
    )


__all__ = [
    "GmailTransportResponse",
    "GmailTransportUpdate",
    "get_gmail_transport_route",
    "register_gmail_transport_routes",
    "set_gmail_transport_route",
]
