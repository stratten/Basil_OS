"""Tell connected Basil clients that settings changed, so an open screen can reload instead of showing stale values."""

from __future__ import annotations

from typing import Iterable, List

from api.services.websocket_connection_manager import broadcast_json_text

_settings_revision = 0


def current_settings_revision() -> int:
    """Return the process-local revision for settings-changed broadcasts."""
    return _settings_revision


async def broadcast_settings_changed(keys: Iterable[str]) -> int:
    """Broadcast which setting keys changed and return the revision. Clients re-read the settings they show; the event carries no values."""
    global _settings_revision

    changed: List[str] = sorted({key for key in keys if key})
    _settings_revision += 1
    await broadcast_json_text(
        {
            "event_type": "settings_changed",
            "revision": _settings_revision,
            "keys": changed,
            "sections": sorted({key.split(".", 1)[0] for key in changed}),
        }
    )
    return _settings_revision
