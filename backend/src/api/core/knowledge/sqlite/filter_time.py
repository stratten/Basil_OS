"""Time formatting shared by the sidebar list filters of Agent Tasks and conversations."""

from datetime import datetime, timezone


def utc_text(moment: datetime) -> str:
    """Format an instant the way SQLite's ``datetime()`` prints it; naive values are read as local time."""
    aware = moment if moment.tzinfo else moment.astimezone()
    return aware.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

