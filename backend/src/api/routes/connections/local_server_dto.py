"""The local-server part of the connection response."""

from __future__ import annotations

from typing import Optional

from api.core.models.preferences import MCPConnectionRecord, MCPInstallRecipe
from api.services.mcp_connectors.companion_supervisor import get_companion_supervisor
from api.services.mcp_connectors.local_server_paths import ConnectionFolders, connection_folders
from api.services.mcp_connectors.local_server_prepare import (
    artifact_is_ready,
    describe_method,
    get_local_server_preparer,
    requirement_install_command,
)
from api.services.mcp_connectors.stdio_transport import spec_summary

from .models import ArtifactStatusDTO, CompanionStatusDTO, InstallStatusDTO, LocalServerDTO, RequirementStatusDTO


def build_install_status_dto(connection_id: str, recipe: MCPInstallRecipe, folders: ConnectionFolders) -> InstallStatusDTO:
    """The recipe's requirements and artifacts, and how far preparing them has got."""
    status = get_local_server_preparer().status(connection_id, recipe, folders)
    artifacts = [
        ArtifactStatusDTO(
            name=artifact.name,
            expects=artifact.expects,
            ready=artifact_is_ready(artifact, folders),
            sources=[describe_method(method) for method in artifact.methods],
        )
        for artifact in recipe.artifacts
    ]
    return InstallStatusDTO(
        phase=status.phase,
        message=status.message,
        ready=all(item.ready for item in artifacts),
        active=status.active,
        artifact=status.artifact,
        requirement=status.requirement,
        can_install=status.can_install,
        detail=status.detail,
        requirements=[
            RequirementStatusDTO(name=item.name, reason=item.reason, for_method=item.for_method, install_command=requirement_install_command(item))
            for item in recipe.requirements
        ],
        artifacts=artifacts,
    )


def build_local_server_dto(record: MCPConnectionRecord) -> Optional[LocalServerDTO]:
    """The command, source address, secret names and background-program status for a local server, or None for any other connection."""
    spec = record.stdio
    if spec is None:
        return None
    companion_dto: Optional[CompanionStatusDTO] = None
    companion = spec.companion
    if companion is not None:
        supervisor = get_companion_supervisor()
        snapshot = supervisor.snapshot(record.id)
        health = snapshot.health
        companion_dto = CompanionStatusDTO(
            command_summary=" ".join([companion.command, *companion.args]).strip(),
            start_with_basil=companion.start_with_basil,
            fixed_port=companion.fixed_port,
            secret_env=list(companion.secret_env),
            status=snapshot.status,
            port=snapshot.port,
            last_error=snapshot.last_error,
            log_tail=supervisor.log_tail(record.id) if snapshot.status == "failed" else "",
            restart_count=snapshot.restart_count,
            has_probe=companion.probe is not None,
            health_phase=health.phase if health is not None else None,
            health_message=health.message if health is not None else None,
            action_kind=health.action_kind if health is not None else None,
            action_value=health.action_value if health is not None else None,
            action_expires_at=health.action_expires_at if health is not None else None,
        )
    install_dto = build_install_status_dto(record.id, spec.install, connection_folders(get_companion_supervisor().state_dir, record.id)) if spec.install is not None else None
    return LocalServerDTO(
        command_summary=spec_summary(spec),
        source_url=spec.source_url,
        secret_env=list(spec.secret_env),
        companion=companion_dto,
        install=install_dto,
    )
