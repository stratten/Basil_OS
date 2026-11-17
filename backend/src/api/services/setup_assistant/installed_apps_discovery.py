"""Reads the names of the apps installed on this Mac, so the setup agent can notice what it could help the person set up.

Only the names of the top-level apps in the usual install folders are read. Nothing inside an app is opened, and no list is shipped with Basil: the agent decides at runtime whether anything it sees has a real way to be helped, and says so only when that is true.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Optional, Sequence

from api.core.utc_time import utc_now_naive
from api.routes.setup_assistant.models import (
    SetupDiscoveryFact,
    SetupDiscoveryFactKind,
    SetupDiscoveryResponse,
    SetupDiscoverySource,
)

MAX_LISTED_APPS = 250


def _default_folders() -> Sequence[Path]:
    return (Path("/Applications"), Path.home() / "Applications")


def _list_app_names(folders: Sequence[Path]) -> List[str]:
    names: dict[str, str] = {}
    for folder in folders:
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.suffix == ".app" and not entry.name.startswith("."):
                # The Mac's file system ignores case, so the same app in two folders counts once.
                names.setdefault(entry.stem.casefold(), entry.stem)
    return [names[key] for key in sorted(names)]


async def collect_installed_app_facts(folders: Optional[Sequence[Path]] = None) -> SetupDiscoveryResponse:
    """One fact that carries the sorted names of installed apps, capped so a very large install list stays readable."""
    collected_at = utc_now_naive()
    names = await asyncio.to_thread(_list_app_names, folders if folders is not None else _default_folders())
    if not names:
        return SetupDiscoveryResponse(facts=[], collected_at=collected_at)
    listed = names[:MAX_LISTED_APPS]
    fact = SetupDiscoveryFact(
        id="installed-apps",
        source=SetupDiscoverySource.installed_applications,
        kind=SetupDiscoveryFactKind.detected_application,
        value=str(len(names)),
        confidence=0.95,
        collected_at=collected_at,
        user_visible_summary=f"{len(names)} apps are installed on this Mac.",
        metadata={
            "role": "installed_apps",
            "app_names": "; ".join(listed),
            "listed_count": str(len(listed)),
            "total_count": str(len(names)),
        },
    )
    return SetupDiscoveryResponse(facts=[fact], collected_at=collected_at)
