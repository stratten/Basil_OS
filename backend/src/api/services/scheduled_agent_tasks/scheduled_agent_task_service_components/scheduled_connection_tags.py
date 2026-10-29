"""Connections (MCP) a scheduled agent task is tied to.

A schedule can be tagged with one or more Connections, the same way it can be given reference files. A tag is a hint and a precondition, never a grant:

* Every run states the tagged connections in its prompt, so the agent uses exactly those connections instead of guessing among several accounts or workspaces.
* Before a run is submitted, each tagged connection is checked. A connection that no longer exists, is switched off, or is known to need signing in again fails the run with a plain message, because an unattended run that quietly works around its connection would report a result the user did not ask for.
* Per-tool approval policy is untouched. A tagged connection's `always_ask` tools still ask, and `never_allow` tools are still refused.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional

logger = logging.getLogger(__name__)

# `last_connection_status` values that mean the stored sign-in cannot be used until the user reconnects.
RECONNECT_STATUSES = frozenset({"needs_reconnect", "token_unavailable"})


@dataclass
class ConnectionTagAssessment:
    """The tagged connections that exist, and one plain-language problem for each tag that cannot be used."""

    records: List[Any] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)


def normalize_connection_ids(connection_ids: Optional[Iterable[Any]]) -> List[str]:
    """Unique, non-empty ids in the order given."""
    cleaned = [str(item).strip() for item in (connection_ids or []) if isinstance(item, str) and str(item).strip()]
    return list(dict.fromkeys(cleaned))


def _connection_records() -> List[Any]:
    from api.services.agent_processing.tools.external_services.external_catalog.auth import (
        load_external_catalog_preferences,
    )

    return list(load_external_catalog_preferences().connections.mcp_connections)


def connection_names_by_id() -> dict:
    """Every registered connection's current friendly name, keyed by id."""
    return {record.id: record.friendly_name for record in _connection_records()}


def unknown_connection_ids(connection_ids: Optional[Iterable[Any]]) -> List[str]:
    """The ids that do not match any registered connection."""
    known = {record.id for record in _connection_records()}
    return [connection_id for connection_id in normalize_connection_ids(connection_ids) if connection_id not in known]


def assess_connection_tags(connection_ids: Optional[Iterable[Any]]) -> ConnectionTagAssessment:
    """Looks up each tagged connection and reports every one that cannot be used right now."""
    wanted = normalize_connection_ids(connection_ids)
    assessment = ConnectionTagAssessment()
    if not wanted:
        return assessment
    by_id = {record.id: record for record in _connection_records()}
    for connection_id in wanted:
        record = by_id.get(connection_id)
        if record is None:
            assessment.problems.append(f"A connection this schedule uses (id {connection_id}) has been removed. Edit the schedule to choose another.")
            continue
        assessment.records.append(record)
        name = record.friendly_name
        if not record.enabled:
            assessment.problems.append(f"The {name} connection is switched off. Turn it on in Settings, or edit the schedule.")
        elif (record.last_connection_status or "") in RECONNECT_STATUSES:
            assessment.problems.append(f"The {name} connection needs to be signed in again. Reconnect it in Settings.")
    return assessment


def connection_tag_blocker(assessment: ConnectionTagAssessment) -> Optional[str]:
    """The message a run fails with when any tagged connection cannot be used, or None when every one can."""
    if not assessment.problems:
        return None
    return " ".join(assessment.problems)


def render_connection_tag_block(records: Iterable[Any]) -> str:
    """The paragraph added to a run's prompt naming the connections it must use. Empty when nothing is tagged."""
    lines = []
    for record in records:
        detail = f" ({record.description.strip()})" if (record.description or "").strip() else ""
        lines.append(f"- {record.friendly_name}{detail}: connection_id `{record.id}`")
    if not lines:
        return ""
    return (
        "CONNECTIONS FOR THIS SCHEDULE:\n"
        "The user tied this scheduled task to the connections below. Use these exact connections through `external_catalog` (you can skip `list_servers` and go straight to `describe_server` with the connection_id) and do not substitute a different connection. "
        "Each tool's approval policy still applies, so a denied call stays denied.\n"
        "Do not route around these connections. If a tool on one of them fails (access not enabled, signed out, denied, or any other error), do not get the same data a different way, such as the local Mail app, AppleScript, other email or messaging tools, or a browser. "
        "Stop, tell the user which connection failed and quote the error and its user_action_required text, and finish the run with that report instead of a result.\n"
        + "\n".join(lines)
    )
