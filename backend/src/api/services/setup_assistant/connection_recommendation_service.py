"""Connection catalog helpers for setup assistant recommendations."""

from __future__ import annotations

from typing import Any, Dict, List


class SetupAssistantConnectionRecommendationService:
    """Normalize supported connection metadata for onboarding cards."""

    def build_connection_card_inputs(
        self,
        starter_servers: List[Dict[str, Any]],
        registered_connections: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Combine supported and registered connection state for the web UI."""

        registered_by_server_id = {
            str(connection.get("server_id")): connection
            for connection in registered_connections
            if connection.get("server_id")
        }

        card_inputs: List[Dict[str, Any]] = []
        for server in starter_servers:
            server_id = str(server.get("id") or server.get("server_id") or "")
            if not server_id:
                continue

            registered = registered_by_server_id.get(server_id)
            card_inputs.append(
                {
                    "id": server_id,
                    "display_name": server.get("display_name") or server.get("name") or server_id,
                    "description": server.get("description") or "",
                    "auth_status": "connected" if registered else "available",
                    "registered_connection_id": registered.get("id") if registered else None,
                    "metadata": server,
                }
            )

        return card_inputs

