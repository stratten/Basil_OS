"""Routes for user-authored MCP connection metadata."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from .connection_route_helpers import (
    connection_to_dto,
    find_connection_or_404,
    load_connection_preferences,
    save_connection_preferences,
)
from .models import ConnectionDTO, ConnectionMetadataUpdateRequest


def register_metadata_routes(router: APIRouter) -> None:
    """Attach metadata-management endpoints to the connections router."""
    router.add_api_route(
        "/{connection_id}/metadata",
        update_connection_metadata,
        methods=["PUT"],
        response_model=ConnectionDTO,
        name="update_connection_metadata",
    )


async def update_connection_metadata(
    connection_id: str,
    payload: ConnectionMetadataUpdateRequest,
) -> ConnectionDTO:
    """Update user-authored connection name/description metadata."""
    friendly_name = payload.friendly_name.strip()
    if not friendly_name:
        raise HTTPException(status_code=400, detail="Connection name cannot be empty")

    prefs = load_connection_preferences()
    record = find_connection_or_404(prefs, connection_id)
    record.friendly_name = friendly_name
    record.description = _normalize_optional_description(payload.description)
    save_connection_preferences(prefs)
    return connection_to_dto(record)


def _normalize_optional_description(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


__all__ = ["register_metadata_routes", "update_connection_metadata"]
