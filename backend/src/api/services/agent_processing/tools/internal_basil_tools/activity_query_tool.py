"""
Activity Query Tool for Agent

Provides direct, structured access to the activities database for the agent.
Instead of using QueryIntentHandler (which adds redundant LLM calls), this tool
gives the agent transparent access to activity data with structured parameters.
"""

import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile

logger = logging.getLogger(__name__)


class ActivityQueryInput(BaseModel):
    """Input schema for activity query tool."""
    start_time: Optional[str] = Field(
        default=None,
        description=(
            "Start time for query. Can be:\n"
            "  - ISO timestamp: '2025-01-20T00:00:00'\n"
            "  - Relative: 'today', 'yesterday', 'this_week', 'last_week', 'this_month', 'last_month'\n"
            "  - If omitted, queries from beginning of today"
        )
    )
    end_time: Optional[str] = Field(
        default=None,
        description=(
            "End time for query. Can be:\n"
            "  - ISO timestamp: '2025-01-21T23:59:59'\n"
            "  - Relative: 'now', 'today', 'yesterday'\n"
            "  - If omitted, queries up to current time"
        )
    )
    app_name_filter: Optional[str] = Field(
        default=None,
        description="Filter by specific application name (case-sensitive exact match)"
    )
    window_title_search: Optional[str] = Field(
        default=None,
        description="Search window titles (case-insensitive substring match)"
    )
    limit: Optional[int] = Field(
        default=100,
        description="Maximum number of activities to return (default 100, max 1000)"
    )
    sort_order: Literal["newest", "oldest"] = Field(
        default="newest",
        description="Sort order: 'newest' (most recent first) or 'oldest' (chronological)."
    )


def _parse_relative_time(relative_str: str) -> datetime:
    """Parse relative time strings into datetime objects.
    
    Args:
        relative_str: Relative time string like 'today', 'yesterday', etc.
        
    Returns:
        datetime object in local timezone
    """
    now = datetime.now().astimezone()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    relative_map = {
        'now': now,
        'today': today_start,
        'yesterday': today_start - timedelta(days=1),
        'this_week': today_start - timedelta(days=now.weekday()),  # Monday of this week
        'last_week': today_start - timedelta(days=now.weekday() + 7),  # Monday of last week
        'this_month': today_start.replace(day=1),  # First day of this month
        'last_month': (today_start.replace(day=1) - timedelta(days=1)).replace(day=1),  # First day of last month
    }
    
    return relative_map.get(relative_str.lower(), today_start)


def _parse_time_parameter(time_str: Optional[str], default: Optional[datetime] = None) -> Optional[datetime]:
    """Parse a time parameter that can be ISO timestamp or relative string.
    
    Args:
        time_str: Time string (ISO or relative)
        default: Default datetime if time_str is None
        
    Returns:
        datetime object or None
    """
    if time_str is None:
        return default
    
    # Try to parse as ISO timestamp first
    try:
        # Handle various ISO formats
        time_clean = time_str.replace('Z', '+00:00') if 'Z' in time_str else time_str
        dt = datetime.fromisoformat(time_clean)
        # Ensure timezone-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone()  # Convert to local timezone
    except (ValueError, AttributeError):
        pass
    
    # Try to parse as relative time
    try:
        return _parse_relative_time(time_str)
    except Exception as e:
        logger.warning(f"Could not parse time parameter '{time_str}': {e}")
        return default


async def _query_activities_impl(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    app_name_filter: Optional[str] = None,
    window_title_search: Optional[str] = None,
    limit: int = 100,
    sort_order: str = "newest"
) -> str:
    """Implementation of activity query tool.
    
    Returns:
        JSON string containing array of activity records
    """
    try:
        from api.dependencies import get_sqlite_knowledge_service
        
        # Get database service
        sqlite_service = get_sqlite_knowledge_service()
        
        # Parse time parameters
        now = datetime.now().astimezone()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        parsed_start_time = _parse_time_parameter(start_time, default=today_start)
        parsed_end_time = _parse_time_parameter(end_time, default=now)
        
        logger.info(f"Querying activities: start={parsed_start_time}, end={parsed_end_time}, "
                   f"app_filter={app_name_filter}, title_search={window_title_search}, "
                   f"limit={limit}, sort={sort_order}")
        
        # Build time range dict
        time_range = {}
        if parsed_start_time:
            time_range['start'] = parsed_start_time
        if parsed_end_time:
            time_range['end'] = parsed_end_time
        
        # Enforce reasonable limits
        limit = min(max(1, limit), 1000)  # Clamp between 1 and 1000
        
        # Query activities using SQLiteKnowledgeService
        activities = await sqlite_service.search_activities(
            time_range=time_range if time_range else None,
            text_search=None,  # We'll filter in post-processing if needed
            metadata_filters=None,
            limit=limit * 2  # Get extra to allow for filtering
        )
        
        logger.info(f"Retrieved {len(activities)} activities from database")
        
        # Convert Activity objects to dicts and apply filters
        result_activities = []
        for activity in activities:
            # Apply app name filter (exact match, case-sensitive)
            if app_name_filter and activity.app_name != app_name_filter:
                continue
            
            # Apply window title search (case-insensitive substring)
            if window_title_search and window_title_search.lower() not in (activity.window_title or "").lower():
                continue
            
            # Build activity dict with all relevant fields
            activity_dict = {
                "id": activity.id,
                "timestamp": activity.timestamp.isoformat() if activity.timestamp else None,
                "app_name": activity.app_name,
                "window_title": activity.window_title,
                "extracted_text": activity.extracted_text,
                "duration": activity.duration,
                "ai_analysis": activity.ai_analysis if isinstance(activity.ai_analysis, dict) else None,
                "capture_frequency_minutes": activity.capture_frequency_minutes
            }
            
            result_activities.append(activity_dict)
            
            # Stop if we've reached the limit
            if len(result_activities) >= limit:
                break
        
        # Sort activities
        if sort_order == "oldest":
            result_activities.sort(key=lambda x: x['timestamp'] or "")
        else:  # newest (default)
            result_activities.sort(key=lambda x: x['timestamp'] or "", reverse=True)
        
        logger.info(f"Returning {len(result_activities)} filtered activities")
        
        # Return as JSON
        return json.dumps({
            "success": True,
            "count": len(result_activities),
            "activities": result_activities,
            "query_params": {
                "start_time": parsed_start_time.isoformat() if parsed_start_time else None,
                "end_time": parsed_end_time.isoformat() if parsed_end_time else None,
                "app_filter": app_name_filter,
                "title_search": window_title_search,
                "limit": limit,
                "sort_order": sort_order
            }
        }, ensure_ascii=False, indent=2)
        
    except Exception as e:
        logger.error(f"Error querying activities: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": str(e),
            "activities": []
        }, ensure_ascii=False)


# Why this slim:
# - KEEPS: the discriminating question ('answer must exist on the user's
#   screen at some point in time') that routes between this tool, email,
#   calendar, web_search, and external_catalog; relative-time tokens are
#   a load-bearing feature that the agent can't infer from typing alone
#   (the schema's start_time/end_time are str so the Literal hint matters).
# - DROPS: the activities-database column inventory (the schema only takes
#   queryable filters, the columns are returned in results which the agent
#   can introspect at result time); per-call usage examples (subsumed by
#   the relative-time hint and the schema's field descriptions); the
#   PROCESSING RESULTS section (post-result work is not the tool's concern).
SLIM_DESCRIPTION = (
    "Query the user's screen-capture/window-title activity history. Use only "
    "for questions answerable from what was visible on the user's screen at "
    "some point in time (which app, which window title, OCR'd content, time "
    "spent per app). Do NOT use for calendar / email / file / to-do answers - "
    "those live in their own services. For questions spanning multiple kinds "
    "of activity (\"what did I do yesterday\"), prefer query_unified_history. "
    "start_time and end_time accept ISO "
    "timestamps OR relative tokens: 'today', 'yesterday', 'this_week', "
    "'last_week', 'this_month', 'last_month', 'now'. Default range is from "
    "today at midnight through now."
)

_FULL_DESCRIPTION = """Query the user's activity history with structured parameters.

**WHEN TO USE:**
Use this tool when the user wants to know what they had on screen, which app they were
in, what window title was visible, or what text appeared on their display — questions
answerable from the OCR-and-window-title capture stream that Basil records continuously.

The discriminating question is: does the answer exist in what was visible on the user's
screen at some point in time? If yes, use this tool. If no, use a different tool.

- USE: "What was I working on yesterday afternoon?" → screen capture shows apps and content.
- USE: "How much time did I spend in Cursor last week?" → app durations are in activity records.
- DO NOT USE: "What meetings do I have today?" → answer is in Calendar, not screen captures.
- DO NOT USE: "Find the email Sarah sent me about the proposal" → answer is in email_service.
- DO NOT USE: "What's on my to-do list?" → answer may be in a specific app, not capture stream.

**ACTIVITIES DATABASE SCHEMA:**
The activities table contains records of user's computer activities captured over time:
- `id` (str): Unique activity identifier
- `timestamp` (ISO datetime): When the activity occurred
- `app_name` (str): Name of the application (e.g., "Cursor", "Chrome", "Slack")
- `window_title` (str): Title of the application window
- `extracted_text` (str): OCR-extracted text from the screen
- `duration` (float): Activity duration in seconds
- `ai_analysis` (object): AI-generated analysis with fields:
    - `summary` (str): Brief description of what user was doing
    - `activity_type` (str): Type of activity (e.g., "coding", "communication")
    - `context` (str): Context/project information
    - `content_summary` (str): Summary of content
- `capture_frequency_minutes` (int): How often this activity was captured

**USAGE EXAMPLES:**
- Simple today query: query_activities(start_time="today")
- Yesterday: query_activities(start_time="yesterday", end_time="today")
- Specific app: query_activities(start_time="today", app_name_filter="Cursor")
- Search titles: query_activities(start_time="today", window_title_search="README")
- Date range: query_activities(start_time="2025-01-20T00:00:00", end_time="2025-01-21T00:00:00")
- Last week: query_activities(start_time="last_week", end_time="this_week", limit=500)

**PROCESSING RESULTS:**
The tool returns raw activity data that you can:
- Group by app, time period, or project
- Filter further based on content
- Summarize for user reports
- Export to files (CSV, JSON, PDF)
- Analyze for patterns

**TIMEFRAME TIPS:**
- Use relative times for convenience ("today", "yesterday", "this_week", "last_week")
- Use ISO timestamps for precise control ("2025-01-20T14:30:00")
- Default start_time is today at midnight
- Default end_time is now
"""


def create_activity_query_tool(profile=None) -> StructuredTool:
    """Factory for the ``query_activities`` tool.

    Under a slim rendering profile the description is swapped to
    ``SLIM_DESCRIPTION`` above; otherwise ``_FULL_DESCRIPTION`` flows
    through unchanged.
    """
    tool_description = select_description_for_profile(
        profile, _FULL_DESCRIPTION, SLIM_DESCRIPTION
    )

    return StructuredTool.from_function(
        func=_query_activities_impl,
        name="query_activities",
        description=tool_description,
        args_schema=ActivityQueryInput,
        coroutine=_query_activities_impl  # Mark as async
    )

