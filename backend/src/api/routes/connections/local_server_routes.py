"""Route that registers a local stdio MCP server as a connection."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from api.core.security.backend_request_guard import require_host_credential
from api.services.mcp_connectors.local_server_registration import (
    DuplicateLocalServerError,
    discard_local_server_record,
    register_local_server_record,
)
from api.services.mcp_connectors.stdio_transport import StdioSpecError

from .connection_route_helpers import connection_to_dto
from .models import ConnectionDTO, RegisterLocalServerRequest


def register_local_server_routes(router: APIRouter) -> None:
    @router.post("/local_server", response_model=ConnectionDTO, dependencies=[Depends(require_host_credential)])
    async def register_local_server(payload: RegisterLocalServerRequest, request: Request) -> ConnectionDTO:
        """Register a local server, start it once to read its tools, and keep it only if it starts.

        A command that does not start is removed again, so a broken entry never stays in Settings → Connections. Nothing is stored for a rejected command.
        """
        from .routes import refresh_tools

        try:
            record = register_local_server_record(
                friendly_name=payload.friendly_name,
                command=payload.command,
                args=payload.args,
                cwd=payload.cwd,
                env=payload.env,
                description=payload.description,
                source_url=payload.source_url,
            )
        except DuplicateLocalServerError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StdioSpecError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            return await refresh_tools(record.id, request)
        except HTTPException:
            discard_local_server_record(record.id)
            raise
        except Exception:
            discard_local_server_record(record.id)
            raise
