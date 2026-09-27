"""Pydantic input schemas for the embedded Slack MCP server.

One model per tool. The ``model_json_schema()`` of each is what gets
returned to the agent inside the ``input_schema`` field of a tool
descriptor, so the field descriptions here are user-facing for the LLM.

Defaults and bounds matter: ``ge=1, le=200`` on ``limit`` keeps a
runaway agent from accidentally paginating thousands of records, and
the conservative defaults match the rate-limit tier each Slack
endpoint sits in. Adjust per-tool if a specific endpoint warrants it.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class SearchMessagesInput(BaseModel):
    query: str = Field(
        description=(
            "Slack search query string. Supports operators like "
            "'from:@user', 'in:#channel', 'after:YYYY-MM-DD', 'has:link'."
        )
    )
    count: int = Field(default=20, ge=1, le=100, description="Maximum number of matches to return.")


class SearchFilesInput(BaseModel):
    query: str = Field(
        description=(
            "File search query. Supports the same operators as message "
            "search plus 'type:pdf', 'type:image', etc."
        )
    )
    count: int = Field(default=20, ge=1, le=100)


class ListChannelsInput(BaseModel):
    types: str = Field(
        default="public_channel,private_channel",
        description="Comma-separated channel types: public_channel, private_channel, mpim, im.",
    )
    limit: int = Field(default=100, ge=1, le=200)
    exclude_archived: bool = Field(default=True)


class ReadChannelHistoryInput(BaseModel):
    channel: str = Field(description="Channel ID, e.g. C12345 or D12345.")
    limit: int = Field(default=50, ge=1, le=200)
    oldest: Optional[str] = Field(default=None, description="Unix timestamp; only messages after this are returned.")
    latest: Optional[str] = Field(default=None, description="Unix timestamp; only messages before this are returned.")


class ReadThreadInput(BaseModel):
    channel: str = Field(description="Channel ID containing the thread.")
    thread_ts: str = Field(description="Timestamp (ts) of the thread's parent message.")
    limit: int = Field(default=100, ge=1, le=200)


class CreateChannelInput(BaseModel):
    name: str = Field(
        description="Channel name. Lowercase letters, numbers, hyphens, underscores only; max 80 chars."
    )
    is_private: bool = Field(default=False, description="True creates a private channel, False creates public.")


class SendMessageInput(BaseModel):
    channel: str = Field(description="Channel ID, '#channel-name', or DM user ID.")
    text: str = Field(description="Message body. Slack mrkdwn formatting supported.")
    thread_ts: Optional[str] = Field(default=None, description="If set, posts as a reply in the given thread.")


class OpenDMInput(BaseModel):
    user: str = Field(description="User ID to open a DM with, e.g. U12345.")


class OpenGroupDMInput(BaseModel):
    users: List[str] = Field(
        min_length=2,
        max_length=8,
        description="Two to eight user IDs to open a group DM with. The current user is included by Slack automatically.",
    )


class AddReactionInput(BaseModel):
    channel: str = Field(description="Channel ID containing the message.")
    timestamp: str = Field(description="Timestamp (ts) of the message to react to.")
    name: str = Field(description="Emoji name without colons, e.g. 'thumbsup' or 'tada'.")


class CreateCanvasInput(BaseModel):
    title: str = Field(description="Canvas title.")
    markdown: str = Field(description="Canvas content as Markdown.")
    channel_id: Optional[str] = Field(
        default=None,
        description=(
            "If set, attaches the canvas to this channel instead of the user's "
            "standalone canvases."
        ),
    )


class ReadCanvasInput(BaseModel):
    canvas_id: str = Field(description="Canvas file ID, e.g. F12345.")


class ListUsersInput(BaseModel):
    limit: int = Field(default=100, ge=1, le=200)
    include_locale: bool = Field(default=False)


class GetUserProfileInput(BaseModel):
    user: str = Field(description="User ID, e.g. U12345.")
    include_labels: bool = Field(
        default=False,
        description=(
            "Request custom profile field labels. The users.info-backed "
            "fallback reports labels_supported=false because Slack does not "
            "return custom label metadata through this scope-compatible call."
        ),
    )


class GetWorkspaceInfoInput(BaseModel):
    team_id: Optional[str] = Field(default=None, description="Optional Slack team ID. Omit for the current workspace.")


class ListEmojiInput(BaseModel):
    limit: int = Field(default=200, ge=1, le=1000, description="Maximum emoji entries to include in the summary payload.")


class GetMessageReactionsInput(BaseModel):
    channel: str = Field(description="Channel ID containing the message.")
    timestamp: str = Field(description="Message timestamp (ts) to inspect.")
    full: bool = Field(default=True, description="Ask Slack for full reaction details when available.")


class ListUnreadMessagesInput(BaseModel):
    types: str = Field(
        default="public_channel,private_channel,im,mpim",
        description=(
            "Comma-separated conversation types to scan for unread messages. "
            "Default covers all four conversation kinds the user can be a "
            "member of (public channels, private channels, DMs, group DMs)."
        ),
    )
    max_conversations_to_check: int = Field(
        default=50,
        ge=1,
        le=200,
        description=(
            "Cap on how many conversations to inspect for unread state. "
            "This is a bounded scan, not a guarantee that every Slack sidebar "
            "unread badge has been inspected. "
            "users.conversations returns conversations in recent-activity "
            "order, so the default 50 covers practical 'what's unread' usage "
            "while staying within Slack Tier 3 rate limits (50 calls/minute "
            "per user). Each conversation costs up to two extra API calls "
            "(conversations.info + conversations.history), so values above "
            "~25 may begin to hit rate-limit retries on busy workspaces. "
            "Raise only when the agent specifically needs to scan deeper."
        ),
    )
    message_limit_per_channel: int = Field(
        default=50,
        ge=1,
        le=200,
        description=(
            "Cap on unread messages returned per conversation. Conversations "
            "with more unread than this will be truncated to the most recent "
            "N; the truncation is reflected in the structured payload."
        ),
    )


class ScanUnreadMessagesInput(BaseModel):
    types: str = Field(
        default="public_channel,private_channel,im,mpim",
        description="Comma-separated conversation types to scan: public_channel, private_channel, im, mpim.",
    )
    max_conversations_to_check: int = Field(
        default=20,
        ge=1,
        le=100,
        description=(
            "Maximum conversations to inspect in this staged scan page. "
            "If next_cursor is returned, call slack_scan_unread_messages again "
            "with that cursor to continue."
        ),
    )
    message_limit_per_channel: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Maximum unread messages to return per conversation in this staged page.",
    )
    cursor: Optional[str] = Field(
        default=None,
        description="Slack users.conversations pagination cursor from a previous staged scan.",
    )
    start_after_channel_id: Optional[str] = Field(
        default=None,
        description=(
            "Compatibility continuation marker. Prefer cursor; this field is "
            "reported as unsupported because Slack cursor pagination is the reliable continuation mechanism."
        ),
    )
    include_diagnostics: bool = Field(
        default=True,
        description="Include per-conversation scan diagnostics in the structured result.",
    )


__all__ = [
    "AddReactionInput",
    "CreateCanvasInput",
    "CreateChannelInput",
    "GetMessageReactionsInput",
    "GetUserProfileInput",
    "GetWorkspaceInfoInput",
    "ListEmojiInput",
    "ListChannelsInput",
    "ListUnreadMessagesInput",
    "ListUsersInput",
    "OpenDMInput",
    "OpenGroupDMInput",
    "ReadCanvasInput",
    "ReadChannelHistoryInput",
    "ReadThreadInput",
    "ScanUnreadMessagesInput",
    "SearchFilesInput",
    "SearchMessagesInput",
    "SendMessageInput",
]
