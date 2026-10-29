"""Detects which calendar apps are available, and how well Paprika can drive each one.

Basil has no calendar connector of its own: a calendar task is carried out by scripting the app on the Mac. Apple's Calendar app is scriptable end to end and can sync Exchange, Outlook, Google and iCloud accounts, while Microsoft Outlook's scripting interface returns recurring series instead of their individual occurrences, so a check of "the next seven days" silently misses most recurring meetings. The setup agent reads these facts so it can steer a calendar task toward the app that will work, instead of assuming that the calendar app of a running mail app is the right one.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

from api.core.utc_time import utc_now_naive
from api.routes.setup_assistant.models import (
    SetupDiscoveryFact,
    SetupDiscoveryFactKind,
    SetupDiscoveryResponse,
    SetupDiscoverySource,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CalendarAppDefinition:
    name: str
    bundle_id: str
    process_name: str
    install_paths: Sequence[str]
    scripting_reliability: str
    guidance: str


CALENDAR_APP_DEFINITIONS: Sequence[CalendarAppDefinition] = (
    CalendarAppDefinition(
        name="Calendar",
        bundle_id="com.apple.iCal",
        process_name="Calendar",
        install_paths=("/System/Applications/Calendar.app", "/Applications/Calendar.app"),
        scripting_reliability="high",
        guidance=(
            "Apple Calendar is fully scriptable, expands recurring events into the occurrences in a date range, and can show the user's Outlook, Exchange, Google, and iCloud calendars once the account is added in System Settings > Internet Accounts."
        ),
    ),
    CalendarAppDefinition(
        name="Microsoft Outlook",
        bundle_id="com.microsoft.Outlook",
        process_name="Microsoft Outlook",
        install_paths=("/Applications/Microsoft Outlook.app",),
        scripting_reliability="limited",
        guidance=(
            "Outlook's scripting interface returns a recurring series once, with its original start date, instead of each occurrence, so a check of upcoming days misses most recurring meetings and cannot reliably detect conflicts or back-to-back meetings. Creating a single one-off event works, but reading a schedule does not."
        ),
    ),
)


def _is_installed(definition: CalendarAppDefinition) -> bool:
    candidates = list(definition.install_paths)
    candidates.append(str(Path.home() / "Applications" / Path(definition.install_paths[0]).name))
    return any(Path(candidate).exists() for candidate in candidates)


async def _is_running(process_name: str) -> bool:
    try:
        process = await asyncio.create_subprocess_exec(
            "/usr/bin/pgrep",
            "-x",
            process_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return (await process.wait()) == 0
    except Exception as exc:
        logger.debug("Could not check whether %s is running: %s", process_name, exc)
        return False


async def collect_calendar_app_facts() -> SetupDiscoveryResponse:
    """One fact per installed calendar app, with whether it is running and how reliably Paprika can use it."""
    collected_at = utc_now_naive()
    facts: List[SetupDiscoveryFact] = []
    for definition in CALENDAR_APP_DEFINITIONS:
        if not _is_installed(definition):
            continue
        is_running = await _is_running(definition.process_name)
        facts.append(
            SetupDiscoveryFact(
                id=f"calendar-app-{definition.bundle_id}",
                source=SetupDiscoverySource.installed_applications,
                kind=SetupDiscoveryFactKind.detected_application,
                value=definition.name,
                confidence=0.95,
                collected_at=collected_at,
                user_visible_summary=f"{definition.name} is available as a calendar app.",
                metadata={
                    "role": "calendar_app",
                    "bundle_id": definition.bundle_id,
                    "is_running": str(is_running).lower(),
                    "scripting_reliability": definition.scripting_reliability,
                    "guidance": definition.guidance,
                },
            )
        )
    return SetupDiscoveryResponse(facts=facts, collected_at=collected_at)
