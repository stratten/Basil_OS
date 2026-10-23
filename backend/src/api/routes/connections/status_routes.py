"""Routes for evaluating MCP connection credential status."""

from __future__ import annotations

from fastapi import APIRouter

from api.services.mcp_connectors.connection_status_service import (
    apply_status_result_to_record,
    check_connection_status,
)

from .connection_route_helpers import (
    connection_to_dto,
    find_connection_or_404,
    load_connection_preferences,
    save_connection_preferences,
)
from .models import ConnectionStatusResponse


def register_status_routes(router: APIRouter) -> None:
    """Attach connection status endpoints to the connections router."""
    router.add_api_route(
        "/{connection_id}/status",
        check_connection_status_route,
        methods=["POST"],
        response_model=ConnectionStatusResponse,
        name="check_connection_status",
    )


async def check_connection_status_route(connection_id: str) -> ConnectionStatusResponse:
    """Validate and, when possible, refresh one connection's credentials."""
    prefs = load_connection_preferences()
    record = find_connection_or_404(prefs, connection_id)
    result = await check_connection_status(record)
    apply_status_result_to_record(record, result)
    save_connection_preferences(prefs)
    return ConnectionStatusResponse(
        connection=connection_to_dto(record),
        status=result.status,
        message=result.message,
        checked_at=result.checked_at,
        refreshed_credentials=result.refreshed_credentials,
        user_action_required=result.user_action_required,
    )


__all__ = ["check_connection_status_route", "register_status_routes"]
