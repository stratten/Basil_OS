"""Route that registers a local stdio MCP server as a connection."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from pydantic import BaseModel

from api.core.models.preferences import MCPConnectionRecord
from api.core.security.backend_request_guard import require_host_credential
from api.services.mcp_connectors.companion_supervisor import CompanionError, get_companion_supervisor
from api.services.mcp_connectors.local_server_lifecycle import discard_local_server
from api.services.mcp_connectors.local_server_paths import connection_folders
from api.services.mcp_connectors.local_server_prepare import (
    PrepareError,
    artifacts_ready,
    find_requirement,
    get_local_server_preparer,
    requirement_install_command,
)
from api.services.mcp_connectors.local_server_registration import (
    DuplicateLocalServerError,
    register_local_server_record,
)
from api.services.mcp_connectors.stdio_transport import StdioSpecError

from .connection_route_helpers import (
    connection_to_dto,
    find_connection_or_404,
    load_connection_preferences,
    save_connection_preferences,
)
from .models import ConnectionDTO, InstallRequirementRequest, RegisterLocalServerRequest

logger = logging.getLogger(__name__)


class CompanionSettingsRequest(BaseModel):
    """The one setting of a background program that can change after the server is added."""

    start_with_basil: bool


_background_tasks: set = set()


async def _start_when_prepared(connection_id: str) -> None:
    """Once a preparation finishes with everything in place, start the server's background program so any step it needs from the person (such as a code to scan) appears. Never raises."""
    preparer = get_local_server_preparer()
    try:
        status = await preparer.wait(connection_id)
        if status.phase == "ready":
            await get_companion_supervisor().start(connection_id)
    except Exception:
        logger.exception("Starting local server %s after preparing it failed", connection_id)


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
                secret_env=payload.secret_env,
                companion=payload.companion.model_dump() if payload.companion is not None else None,
                install=payload.install,
                connection_id=payload.connection_id,
            )
        except DuplicateLocalServerError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StdioSpecError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if record.stdio is not None and not artifacts_ready(record.stdio.install, connection_folders(get_companion_supervisor().state_dir, record.id)):
            # Its files are not in place, so there is nothing to start yet. The row shows what will be downloaded or built, and the person chooses Prepare.
            return connection_to_dto(record)

        try:
            if record.stdio is not None and record.stdio.companion is not None:
                snapshot = await get_companion_supervisor().start(record.id)
                if not snapshot.running:
                    raise HTTPException(
                        status_code=502,
                        detail={
                            "kind": "companion_not_running",
                            "message": snapshot.last_error or "The background program did not start.",
                            "user_action_required": "Check the background program's command, folder and secrets, then add the server again.",
                        },
                    )
            return await refresh_tools(record.id, request)
        except HTTPException:
            await discard_local_server(record.id, record.stdio)
            raise
        except Exception:
            await discard_local_server(record.id, record.stdio)
            raise

    def _record_with_companion(connection_id: str) -> MCPConnectionRecord:
        record = find_connection_or_404(load_connection_preferences(), connection_id)
        if record.stdio is None or record.stdio.companion is None:
            raise HTTPException(status_code=409, detail="This server does not use a background program.")
        return record

    def _record_with_install(connection_id: str) -> MCPConnectionRecord:
        record = find_connection_or_404(load_connection_preferences(), connection_id)
        if record.stdio is None or record.stdio.install is None:
            raise HTTPException(status_code=409, detail="This server has nothing to prepare.")
        return record

    @router.get("/local_server/{connection_id}/status", response_model=ConnectionDTO, dependencies=[Depends(require_host_credential)])
    async def local_server_status(connection_id: str) -> ConnectionDTO:
        """The server as the Connections tab shows it now, for the row to poll while a preparation runs or the program waits for the person."""
        return connection_to_dto(find_connection_or_404(load_connection_preferences(), connection_id))

    @router.post("/local_server/{connection_id}/prepare", response_model=ConnectionDTO, dependencies=[Depends(require_host_credential)])
    async def prepare_local_server(connection_id: str) -> ConnectionDTO:
        """Start putting the server's files in place, then start its background program. Progress is read from the status route. A requirement that needs installing waits for the person."""
        record = _record_with_install(connection_id)
        preparer = get_local_server_preparer()
        preparer.start(connection_id, record.stdio.install, get_companion_supervisor().folders(connection_id))
        if record.stdio.companion is not None:
            follow_up = asyncio.create_task(_start_when_prepared(connection_id))
            _background_tasks.add(follow_up)
            follow_up.add_done_callback(_background_tasks.discard)
        return connection_to_dto(record)

    @router.post("/local_server/{connection_id}/prepare/cancel", response_model=ConnectionDTO, dependencies=[Depends(require_host_credential)])
    async def cancel_prepare_local_server(connection_id: str) -> ConnectionDTO:
        """Stop a preparation that is running. What was already finished stays in place."""
        record = _record_with_install(connection_id)
        await get_local_server_preparer().cancel(connection_id)
        return connection_to_dto(record)

    @router.post("/local_server/{connection_id}/requirements/install", response_model=ConnectionDTO, dependencies=[Depends(require_host_credential)])
    async def install_local_server_requirement(connection_id: str, payload: InstallRequirementRequest) -> ConnectionDTO:
        """Run one requirement's install command because the person chose Install next to it. The command they were shown must still be the recipe's command."""
        record = _record_with_install(connection_id)
        recipe = record.stdio.install
        requirement = find_requirement(recipe, payload.name)
        if requirement is None or requirement_install_command(requirement) != payload.command:
            raise HTTPException(status_code=409, detail="That install command is not the one in this server's recipe any more. Refresh and read it again before installing.")

        async def approved(_requirement) -> bool:
            return True

        try:
            get_local_server_preparer().start_install_requirement(connection_id, recipe, payload.name, approve_install=approved)
        except PrepareError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return connection_to_dto(record)

    @router.post("/local_server/{connection_id}/companion/start", response_model=ConnectionDTO, dependencies=[Depends(require_host_credential)])
    async def start_companion(connection_id: str) -> ConnectionDTO:
        """Start the server's background program now. A failed start is returned in the connection's status, not as an error."""
        record = _record_with_companion(connection_id)
        try:
            await get_companion_supervisor().start(connection_id)
        except CompanionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return connection_to_dto(record)

    @router.post("/local_server/{connection_id}/companion/stop", response_model=ConnectionDTO, dependencies=[Depends(require_host_credential)])
    async def stop_companion(connection_id: str) -> ConnectionDTO:
        """Stop the server's background program and keep it stopped until it is started again or the server is used."""
        record = _record_with_companion(connection_id)
        await get_companion_supervisor().stop(connection_id)
        return connection_to_dto(record)

    @router.put("/local_server/{connection_id}/companion", response_model=ConnectionDTO, dependencies=[Depends(require_host_credential)])
    async def update_companion(connection_id: str, payload: CompanionSettingsRequest) -> ConnectionDTO:
        """Choose whether the background program starts whenever Basil starts or the first time its server is used."""
        prefs = load_connection_preferences()
        record = find_connection_or_404(prefs, connection_id)
        if record.stdio is None or record.stdio.companion is None:
            raise HTTPException(status_code=409, detail="This server does not use a background program.")
        record.stdio.companion.start_with_basil = payload.start_with_basil
        save_connection_preferences(prefs)
        return connection_to_dto(record)
