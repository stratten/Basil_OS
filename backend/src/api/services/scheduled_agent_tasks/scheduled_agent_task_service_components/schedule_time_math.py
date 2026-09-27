"""Pure time / timezone helpers and next-run computation.

This module is the lowest layer of the scheduled-agent-tasks component split: it
has no dependencies on any other component module and no I/O beyond a single
``os.readlink("/etc/localtime")`` probe used to detect the host's IANA
timezone. Everything here is deterministic given its inputs.

Originally lived as a mix of free functions and ``ScheduledAgentTaskService``
methods in ``scheduled_agent_task_service.py``. Split out so the higher-layer
modules (interpretation, lifecycle, execution) can import these helpers
without dragging in the orchestrator's class state.

Public surface:
    utc_now()                       -- timezone-aware "now" in UTC.
    detect_local_timezone_name()    -- best-effort host IANA zone name,
                                       cached for the process lifetime.
    get_zone(tz_name)               -- ``ZoneInfo`` lookup with a UTC fallback
                                       and a warn-once log on bad input.
    split_hhmm(value)               -- parse ``"HH:MM"`` 24h strings.
    compute_next_run_at(...)        -- next UTC ISO timestamp for a structured
                                       schedule definition.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@lru_cache(maxsize=1)
def detect_local_timezone_name() -> str:
    """Best-effort detection of the host machine's IANA timezone name.

    Used as the default user timezone for schedule interpretation when the
    caller (the result widget, the agent_task agent tool, etc.) does not
    explicitly supply one. Basil runs on the user's own machine, so the
    server's local zone IS the user's local zone in the overwhelming common
    case.

    Strategy, in order:
      1. Resolve the /etc/localtime symlink. On macOS and most Linux distros
         this points at something like
         /var/db/timezone/zoneinfo/America/Los_Angeles or
         /usr/share/zoneinfo/America/Los_Angeles, and the suffix after the
         "zoneinfo/" segment is the IANA name. Validated by attempting
         to load it via ZoneInfo.
      2. Honor the TZ environment variable if it looks like an IANA name.
      3. Fall back to "UTC" so the LLM still gets *some* explicit default
         instead of the prior behavior (no default -> mandatory clarification).

    The result is cached for the process lifetime; the user's system zone
    does not change at runtime in any scenario we need to support.
    """
    try:
        link_target = os.readlink("/etc/localtime")
        marker = "zoneinfo/"
        idx = link_target.find(marker)
        if idx != -1:
            candidate = link_target[idx + len(marker):]
            ZoneInfo(candidate)
            return candidate
    except OSError:
        pass
    except Exception as exc:
        logger.debug("Failed to resolve IANA name from /etc/localtime: %s", exc)

    tz_env = (os.environ.get("TZ") or "").strip()
    if tz_env and "/" in tz_env:
        try:
            ZoneInfo(tz_env)
            return tz_env
        except Exception:
            pass

    logger.warning(
        "Could not detect local IANA timezone; schedule interpretation will "
        "default to UTC. The user will see clarification prompts for any "
        "schedule without an explicit timezone."
    )
    return "UTC"


def get_zone(tz_name: Optional[str]) -> ZoneInfo:
    if not tz_name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_name)
    except Exception:
        logger.warning("Unknown timezone '%s', defaulting to UTC", tz_name)
        return ZoneInfo("UTC")


def split_hhmm(value: str) -> Tuple[int, int]:
    parts = value.split(":", 1)
    if len(parts) != 2:
        raise ValueError("time must be HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("time must be HH:MM in 24h range")
    return hour, minute


def compute_next_run_at(
    schedule_type: str,
    schedule_config: Dict[str, Any],
    timezone_name: str,
    *,
    from_time: Optional[datetime] = None,
) -> Optional[str]:
    """Compute next UTC ISO timestamp from schedule definition."""
    base_utc = from_time or utc_now()
    zone = get_zone(timezone_name)
    base_local = base_utc.astimezone(zone)

    if schedule_type == "one_time":
        run_at_raw = schedule_config.get("run_at")
        if not isinstance(run_at_raw, str) or not run_at_raw:
            return None
        run_at = datetime.fromisoformat(run_at_raw.replace("Z", "+00:00"))
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=zone)
        return run_at.astimezone(timezone.utc).isoformat()

    if schedule_type != "recurring":
        return None

    mode = schedule_config.get("mode", "daily")
    if mode == "interval":
        minutes = int(schedule_config.get("minutes", 0))
        if minutes <= 0:
            return None
        next_utc = base_utc + timedelta(minutes=minutes)
        return next_utc.isoformat()

    if mode == "daily":
        raw_time = str(schedule_config.get("time", "09:00"))
        hour, minute = split_hhmm(raw_time)
        candidate = base_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= base_local:
            candidate = candidate + timedelta(days=1)
        return candidate.astimezone(timezone.utc).isoformat()

    if mode == "weekly":
        raw_time = str(schedule_config.get("time", "09:00"))
        hour, minute = split_hhmm(raw_time)
        days = schedule_config.get("days", [base_local.weekday()])
        try:
            target_days = sorted({int(day) for day in days if 0 <= int(day) <= 6})
        except Exception:
            target_days = [base_local.weekday()]
        if not target_days:
            target_days = [base_local.weekday()]

        for delta in range(0, 8):
            candidate = base_local + timedelta(days=delta)
            if candidate.weekday() not in target_days:
                continue
            candidate = candidate.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate > base_local:
                return candidate.astimezone(timezone.utc).isoformat()
        return None

    return None
