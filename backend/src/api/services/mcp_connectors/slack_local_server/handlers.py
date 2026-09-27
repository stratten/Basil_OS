"""Per-tool async handlers for the embedded Slack MCP server.

Each handler validates its input through the matching Pydantic model
in :mod:`schemas`, calls one or two ``slack_sdk`` async methods, and
returns ``{"text": str, "structured": dict|None}``. That shape is
exactly what ``MCPClientService.call_tool`` ultimately wraps in a
success envelope, so handlers here never call ``make_success`` or
``make_envelope`` directly. Errors are raised as exceptions and the
caller (:mod:`server`) converts them via :mod:`error_mapping`.

Two formatting principles to keep the agent's transcript scannable:

  * ``text`` is a brief human-readable summary plus a short bulleted
    list when the result is a collection. It is what the agent sees
    in its tool-result content blocks.
  * ``structured`` carries the raw Slack-API payload (or the most
    relevant slice of it) so the agent can drill into specific fields
    when the prose summary is insufficient.
"""

from __future__ import annotations

from typing import Any, Dict

from slack_sdk.web.async_client import AsyncWebClient

from .schemas import (
    AddReactionInput,
    CreateCanvasInput,
    CreateChannelInput,
    GetMessageReactionsInput,
    GetUserProfileInput,
    GetWorkspaceInfoInput,
    ListEmojiInput,
    ListChannelsInput,
    ListUnreadMessagesInput,
    ListUsersInput,
    OpenDMInput,
    OpenGroupDMInput,
    ReadCanvasInput,
    ReadChannelHistoryInput,
    ReadThreadInput,
    ScanUnreadMessagesInput,
    SearchFilesInput,
    SearchMessagesInput,
    SendMessageInput,
)


_TEXT_PREVIEW_CHARS = 240
"""How many chars of a Slack message body to inline in the summary
``text`` field. The full body is always present in ``structured``."""


async def _resolve_message_author_display(
    client: AsyncWebClient,
    m: Dict[str, Any],
    cache: Dict[str, str],
) -> str:
    """Pick a human-readable author label for a Slack message dict.

    Precedence:
      1. ``username`` if Slack already supplied one (search results,
         bot messages). This avoids an unnecessary ``users.info`` call
         when Slack has already resolved the name for us.
      2. ``user`` (a Slack user id like ``U01F4U6RENA``) resolved to a
         display name via the cached :func:`_resolve_user_display_name`
         helper. Falls back to the raw id if ``users.info`` errors.
      3. ``"?"`` if neither is present.
    """
    username = m.get("username")
    if isinstance(username, str) and username.strip():
        return username
    user_id = m.get("user")
    if isinstance(user_id, str) and user_id:
        return await _resolve_user_display_name(client, user_id, cache)
    return "?"


async def _format_message_line(
    client: AsyncWebClient,
    m: Dict[str, Any],
    cache: Dict[str, str],
) -> str:
    """One-line summary of a Slack message dict for the prose ``text`` payload.

    Resolves the author through :func:`_resolve_message_author_display`
    so the prose surface the agent reads contains human-readable names
    instead of raw Slack user ids; the structured payload still carries
    the original fields verbatim for any downstream consumer that needs
    the ids.
    """
    author = await _resolve_message_author_display(client, m, cache)
    ts = m.get("ts", "")
    text = (m.get("text") or "").replace("\n", " ").strip()[:_TEXT_PREVIEW_CHARS]
    return f"- [{ts}] {author}: {text}"


async def handle_search_messages(client: AsyncWebClient, args: dict) -> dict:
    parsed = SearchMessagesInput.model_validate(args)
    resp = await client.search_messages(query=parsed.query, count=parsed.count)
    matches = ((resp.get("messages") or {}).get("matches")) or []
    name_cache: Dict[str, str] = {}
    lines: list[str] = []
    for m in matches:
        author = await _resolve_message_author_display(client, m, name_cache)
        channel_name = (m.get("channel") or {}).get("name", "?")
        body = (m.get("text") or "").strip()[:_TEXT_PREVIEW_CHARS]
        lines.append(f"- [{channel_name}] {author}: {body}")
    summary = f"Found {len(matches)} message match(es) for {parsed.query!r}."
    text = "\n".join([summary, *lines]) if matches else summary
    return {"text": text, "structured": {"matches": matches}}


async def handle_search_files(client: AsyncWebClient, args: dict) -> dict:
    parsed = SearchFilesInput.model_validate(args)
    resp = await client.search_files(query=parsed.query, count=parsed.count)
    matches = ((resp.get("files") or {}).get("matches")) or []
    lines = [
        f"- {f.get('name', '?')} ({f.get('filetype', '?')}, {f.get('size', '?')} bytes)"
        for f in matches
    ]
    summary = f"Found {len(matches)} file match(es) for {parsed.query!r}."
    text = "\n".join([summary, *lines]) if matches else summary
    return {"text": text, "structured": {"files": matches}}


async def handle_list_channels(client: AsyncWebClient, args: dict) -> dict:
    parsed = ListChannelsInput.model_validate(args)
    resp = await client.conversations_list(
        types=parsed.types,
        limit=parsed.limit,
        exclude_archived=parsed.exclude_archived,
    )
    channels = resp.get("channels") or []
    lines = [
        f"- {c.get('id')}  #{c.get('name', '?')}"
        f"{' (private)' if c.get('is_private') else ''}"
        f"{' [archived]' if c.get('is_archived') else ''}"
        for c in channels
    ]
    summary = f"{len(channels)} channel(s) visible."
    text = "\n".join([summary, *lines]) if channels else summary
    return {"text": text, "structured": {"channels": channels}}


async def handle_read_channel_history(client: AsyncWebClient, args: dict) -> dict:
    parsed = ReadChannelHistoryInput.model_validate(args)
    kwargs: Dict[str, Any] = {"channel": parsed.channel, "limit": parsed.limit}
    if parsed.oldest:
        kwargs["oldest"] = parsed.oldest
    if parsed.latest:
        kwargs["latest"] = parsed.latest
    resp = await client.conversations_history(**kwargs)
    messages = resp.get("messages") or []
    name_cache: Dict[str, str] = {}
    lines = [await _format_message_line(client, m, name_cache) for m in messages]
    summary = f"{len(messages)} message(s) from channel {parsed.channel}."
    text = "\n".join([summary, *lines]) if messages else summary
    return {"text": text, "structured": {"messages": messages}}


async def handle_read_thread(client: AsyncWebClient, args: dict) -> dict:
    parsed = ReadThreadInput.model_validate(args)
    resp = await client.conversations_replies(
        channel=parsed.channel,
        ts=parsed.thread_ts,
        limit=parsed.limit,
    )
    messages = resp.get("messages") or []
    name_cache: Dict[str, str] = {}
    lines = [await _format_message_line(client, m, name_cache) for m in messages]
    summary = f"Thread {parsed.thread_ts} in {parsed.channel}: {len(messages)} message(s)."
    text = "\n".join([summary, *lines]) if messages else summary
    return {"text": text, "structured": {"messages": messages}}


async def handle_create_channel(client: AsyncWebClient, args: dict) -> dict:
    parsed = CreateChannelInput.model_validate(args)
    resp = await client.conversations_create(name=parsed.name, is_private=parsed.is_private)
    channel = resp.get("channel") or {}
    text = f"Created channel #{channel.get('name')} (id={channel.get('id')})."
    return {"text": text, "structured": {"channel": channel}}


async def handle_send_message(client: AsyncWebClient, args: dict) -> dict:
    parsed = SendMessageInput.model_validate(args)
    kwargs: Dict[str, Any] = {"channel": parsed.channel, "text": parsed.text}
    if parsed.thread_ts:
        kwargs["thread_ts"] = parsed.thread_ts
    resp = await client.chat_postMessage(**kwargs)
    text = (
        f"Message posted to {resp.get('channel', parsed.channel)} "
        f"at ts={resp.get('ts')}."
    )
    return {
        "text": text,
        "structured": {
            "ts": resp.get("ts"),
            "channel": resp.get("channel"),
            "message": resp.get("message"),
        },
    }


async def handle_open_dm(client: AsyncWebClient, args: dict) -> dict:
    parsed = OpenDMInput.model_validate(args)
    resp = await client.conversations_open(users=parsed.user)
    channel = resp.get("channel") or {}
    text = f"Opened DM with {parsed.user}: channel {channel.get('id') or '?'}."
    return {"text": text, "structured": {"channel": channel, "users": [parsed.user]}}


async def handle_open_group_dm(client: AsyncWebClient, args: dict) -> dict:
    parsed = OpenGroupDMInput.model_validate(args)
    users = ",".join(parsed.users)
    resp = await client.conversations_open(users=users)
    channel = resp.get("channel") or {}
    text = f"Opened group DM with {len(parsed.users)} user(s): channel {channel.get('id') or '?'}."
    return {"text": text, "structured": {"channel": channel, "users": parsed.users}}


async def handle_add_reaction(client: AsyncWebClient, args: dict) -> dict:
    parsed = AddReactionInput.model_validate(args)
    await client.reactions_add(
        channel=parsed.channel,
        timestamp=parsed.timestamp,
        name=parsed.name,
    )
    return {
        "text": (
            f"Reaction :{parsed.name}: added to message {parsed.timestamp} "
            f"in {parsed.channel}."
        ),
        "structured": {
            "channel": parsed.channel,
            "timestamp": parsed.timestamp,
            "reaction": parsed.name,
        },
    }


async def handle_create_canvas(client: AsyncWebClient, args: dict) -> dict:
    # Slack exposes two canvas-creation surfaces: ``canvases.create`` for
    # standalone canvases and ``conversations.canvases.create`` for canvases
    # attached to a channel. Pick based on whether the caller supplied a
    # channel id; both return a payload with the new canvas id.
    parsed = CreateCanvasInput.model_validate(args)
    document_content = {"type": "markdown", "markdown": parsed.markdown}
    if parsed.channel_id:
        resp = await client.conversations_canvases_create(
            channel_id=parsed.channel_id,
            document_content=document_content,
            title=parsed.title,
        )
    else:
        resp = await client.canvases_create(
            title=parsed.title,
            document_content=document_content,
        )
    canvas_id = resp.get("canvas_id") or resp.get("file_id")
    raw = dict(resp.data) if hasattr(resp, "data") else dict(resp)
    text = f"Canvas created (id={canvas_id}) titled {parsed.title!r}."
    return {"text": text, "structured": {"canvas_id": canvas_id, "raw": raw}}


async def handle_read_canvas(client: AsyncWebClient, args: dict) -> dict:
    # The public Slack Web API exposes canvases as a file type; ``files.info``
    # returns the canvas content body. Slack's hosted MCP server does
    # additional rendering of canvas sections; here we surface what the
    # public API returns and let the agent parse the structured payload
    # further. If/when ``slack_sdk`` exposes a dedicated canvas-export
    # endpoint, swap the call here without changing the tool surface.
    parsed = ReadCanvasInput.model_validate(args)
    resp = await client.files_info(file=parsed.canvas_id)
    file_obj = resp.get("file") or {}
    body = file_obj.get("plain_text") or file_obj.get("preview") or ""
    text = f"Canvas {parsed.canvas_id} ({file_obj.get('title') or '?'}):\n\n{body}"
    return {"text": text, "structured": {"file": file_obj}}


async def handle_list_users(client: AsyncWebClient, args: dict) -> dict:
    parsed = ListUsersInput.model_validate(args)
    resp = await client.users_list(limit=parsed.limit, include_locale=parsed.include_locale)
    members = resp.get("members") or []
    active = [m for m in members if not m.get("deleted")]
    lines = [
        f"- {u.get('id')}  @{u.get('name', '?')}"
        f" ({(u.get('profile') or {}).get('real_name', '?')})"
        for u in active
    ]
    summary = f"{len(active)} active user(s) (of {len(members)} total)."
    text = "\n".join([summary, *lines]) if active else summary
    return {"text": text, "structured": {"members": members}}


async def handle_get_user_profile(client: AsyncWebClient, args: dict) -> dict:
    parsed = GetUserProfileInput.model_validate(args)
    resp = await client.users_info(user=parsed.user)
    user = resp.get("user") or {}
    profile = user.get("profile") or {}
    text = (
        f"{profile.get('real_name', '?')} ({profile.get('email', 'no email scope')})\n"
        f"Title: {profile.get('title', '')}\n"
        f"Status: {profile.get('status_text', '')}"
    )
    return {
        "text": text,
        "structured": {
            "user": user,
            "profile": profile,
            "labels_supported": False,
            "labels_note": (
                "Custom profile field labels are not available through users.info."
                if parsed.include_labels
                else None
            ),
        },
    }


async def handle_get_workspace_info(client: AsyncWebClient, args: dict) -> dict:
    parsed = GetWorkspaceInfoInput.model_validate(args)
    kwargs: Dict[str, Any] = {}
    if parsed.team_id:
        kwargs["team"] = parsed.team_id
    resp = await client.team_info(**kwargs)
    team = resp.get("team") or {}
    text = (
        f"Workspace {team.get('name') or '?'} "
        f"(id={team.get('id') or parsed.team_id or '?'}, domain={team.get('domain') or '?'})."
    )
    return {"text": text, "structured": {"team": team}}


async def handle_list_emoji(client: AsyncWebClient, args: dict) -> dict:
    parsed = ListEmojiInput.model_validate(args)
    resp = await client.emoji_list()
    emoji = resp.get("emoji") or {}
    entries = [
        {"name": name, "value": value, "is_alias": str(value).startswith("alias:")}
        for name, value in sorted(emoji.items())[: parsed.limit]
    ]
    text = f"{len(emoji)} custom emoji visible; returning {len(entries)} entrie(s)."
    if entries:
        text = "\n".join([text, *[f"- :{entry['name']}: {entry['value']}" for entry in entries[:20]]])
    return {
        "text": text,
        "structured": {
            "emoji": entries,
            "returned_count": len(entries),
            "total_count": len(emoji),
            "truncated": len(entries) < len(emoji),
        },
    }


async def handle_get_message_reactions(client: AsyncWebClient, args: dict) -> dict:
    parsed = GetMessageReactionsInput.model_validate(args)
    resp = await client.reactions_get(
        channel=parsed.channel,
        timestamp=parsed.timestamp,
        full=parsed.full,
    )
    message = resp.get("message") or {}
    reactions = message.get("reactions") or []
    total_count = sum(int(reaction.get("count") or 0) for reaction in reactions)
    lines = [
        f"- :{reaction.get('name', '?')}: {reaction.get('count', 0)}"
        for reaction in reactions
    ]
    summary = (
        f"Message {parsed.timestamp} in {parsed.channel} has "
        f"{total_count} reaction(s) across {len(reactions)} emoji."
    )
    text = "\n".join([summary, *lines]) if lines else summary
    return {
        "text": text,
        "structured": {
            "channel": parsed.channel,
            "timestamp": parsed.timestamp,
            "message": message,
            "reactions": reactions,
            "total_reaction_count": total_count,
        },
    }


async def _resolve_user_display_name(
    client: AsyncWebClient,
    user_id: str,
    cache: Dict[str, str],
) -> str:
    # Cheap per-call cache so a single handle_list_unread_messages call only
    # ever does one users.info lookup per distinct user id, even if the same
    # user appears in multiple DMs/MPIMs. Falls back gracefully to the raw id
    # when users.info errors out (e.g. missing users:read scope on legacy
    # workspaces) so the handler never aborts on display-name resolution.
    if not user_id:
        return "?"
    cached = cache.get(user_id)
    if cached is not None:
        return cached
    try:
        resp = await client.users_info(user=user_id)
        user = resp.get("user") or {}
        profile = user.get("profile") or {}
        name = (
            profile.get("display_name")
            or profile.get("real_name")
            or user.get("name")
            or user_id
        )
    except Exception:
        name = user_id
    cache[user_id] = name
    return name


def _format_unread_channel_label(conv: Dict[str, Any], dm_display: str) -> str:
    # Centralizes the #name / DM @name / MPIM <name> rule so the text summary
    # and any future surface stay in lockstep with what the agent reads.
    if conv.get("is_im"):
        return f"DM @{dm_display}"
    if conv.get("is_mpim"):
        return f"MPIM {conv.get('name') or dm_display}"
    return f"#{conv.get('name') or '?'}"


def _is_missing_or_zero_cursor(value: Any) -> bool:
    return value in (None, "", "0", "0.000000", "0000000000.000000")


async def handle_list_unread_messages(client: AsyncWebClient, args: dict) -> dict:
    # Composite tool. Slack's user-token API does not expose a single "unread
    # feed" endpoint, so we walk recent conversations and return the unread
    # tail of every conversation that still has new messages. Capping the
    # scan at ``max_conversations_to_check`` keeps us inside Slack's Tier 3
    # rate limits on busy workspaces. NOTE: this composite tool is local to
    # Basil's embedded Slack MCP server; the hosted ``mcp.slack.com`` server
    # does not expose it. If we ever flip the connection back to the hosted
    # server, the agent will need to orchestrate the underlying calls
    # (``users.conversations`` -> ``conversations.info`` -> ``conversations.history``)
    # itself.
    parsed = ListUnreadMessagesInput.model_validate(args)
    conv_resp = await client.users_conversations(
        types=parsed.types,
        limit=parsed.max_conversations_to_check,
        exclude_archived=True,
    )
    conversations = (conv_resp.get("channels") or [])[: parsed.max_conversations_to_check]

    name_cache: Dict[str, str] = {}
    unread_buckets: list[Dict[str, Any]] = []
    truncated_buckets: list[str] = []
    diagnostics: list[Dict[str, Any]] = []

    for conv in conversations:
        info_resp = await client.conversations_info(channel=conv["id"])
        info = info_resp.get("channel") or {}
        api_unread_count = info.get("unread_count_display")
        if api_unread_count is None:
            api_unread_count = info.get("unread_count")
        last_read = info.get("last_read")
        dm_display = await _resolve_user_display_name(
            client,
            conv.get("user") or info.get("user") or "",
            name_cache,
        ) if (conv.get("is_im") or conv.get("is_mpim")) else ""
        label = _format_unread_channel_label(conv, dm_display)
        diagnostic: Dict[str, Any] = {
            "channel_id": conv["id"],
            "label": label,
            "last_read": last_read,
            "api_unread_count": api_unread_count,
            "scan_method": "history_after_last_read",
            "messages_returned": 0,
            "has_more": False,
        }
        if _is_missing_or_zero_cursor(last_read):
            diagnostic["scan_method"] = "unread_state_unknown"
            diagnostic["skip_reason"] = "unread_state_unknown"
            diagnostics.append(diagnostic)
            continue
        try:
            history_resp = await client.conversations_history(
                channel=conv["id"],
                oldest=last_read,
                inclusive=False,
                limit=parsed.message_limit_per_channel,
            )
        except Exception as exc:
            diagnostic["skip_reason"] = "history_error"
            diagnostic["history_error"] = f"{type(exc).__name__}: {exc}"
            diagnostics.append(diagnostic)
            continue
        messages = history_resp.get("messages") or []
        diagnostic["messages_returned"] = len(messages)
        diagnostic["has_more"] = bool(history_resp.get("has_more"))
        diagnostics.append(diagnostic)
        if not messages:
            continue
        if len(messages) >= parsed.message_limit_per_channel or history_resp.get("has_more"):
            truncated_buckets.append(conv["id"])

        unread_buckets.append(
            {
                "channel": {
                    "id": conv["id"],
                    "label": label,
                    "name": conv.get("name"),
                    "is_private": bool(conv.get("is_private")),
                    "is_im": bool(conv.get("is_im")),
                    "is_mpim": bool(conv.get("is_mpim")),
                    "user": conv.get("user"),
                },
                "unread_count_reported": api_unread_count,
                "unread_count_returned": len(messages),
                "messages": messages,
            }
        )

    total_unread = sum(b["unread_count_returned"] for b in unread_buckets)
    unknown_count = sum(1 for d in diagnostics if d.get("skip_reason") == "unread_state_unknown")
    history_error_count = sum(1 for d in diagnostics if d.get("skip_reason") == "history_error")
    if unread_buckets:
        summary = (
            f"{total_unread} unread message(s) across {len(unread_buckets)} "
            f"conversation(s) (scanned {len(conversations)} of "
            f"{parsed.max_conversations_to_check} max)."
        )
    else:
        summary = (
            "No unread messages found in the scanned conversations "
            f"(scanned {len(conversations)} of {parsed.max_conversations_to_check} max)."
        )
        if unknown_count:
            summary += f" Unread state was unknown for {unknown_count} conversation(s)."
        if history_error_count:
            summary += f" History checks failed for {history_error_count} conversation(s)."
    bucket_lines: list[str] = []
    for bucket in unread_buckets:
        ch = bucket["channel"]
        bucket_lines.append(
            f"- {ch['label']} ({bucket['unread_count_returned']} unread)"
        )
        for m in bucket["messages"][:3]:
            line = await _format_message_line(client, m, name_cache)
            bucket_lines.append(f"    {line.lstrip('- ')}")
        if bucket["unread_count_returned"] > 3:
            bucket_lines.append(
                f"    ... and {bucket['unread_count_returned'] - 3} more"
            )
    text = "\n".join([summary, *bucket_lines]) if unread_buckets else summary
    return {
        "text": text,
        "structured": {
            "total_unread": total_unread,
            "conversation_count": len(unread_buckets),
            "scanned": len(conversations),
            "max_scanned": parsed.max_conversations_to_check,
            "truncated_conversation_ids": truncated_buckets,
            "unread_buckets": unread_buckets,
            "unread_state_unknown_count": unknown_count,
            "history_error_count": history_error_count,
            "diagnostics": diagnostics,
        },
    }


async def handle_scan_unread_messages(client: AsyncWebClient, args: dict) -> dict:
    parsed = ScanUnreadMessagesInput.model_validate(args)
    conv_kwargs: Dict[str, Any] = {
        "types": parsed.types,
        "limit": parsed.max_conversations_to_check,
        "exclude_archived": True,
    }
    if parsed.cursor:
        conv_kwargs["cursor"] = parsed.cursor
    conv_resp = await client.users_conversations(**conv_kwargs)
    conversations = (conv_resp.get("channels") or [])[: parsed.max_conversations_to_check]
    next_cursor = ((conv_resp.get("response_metadata") or {}).get("next_cursor") or "") or None

    name_cache: Dict[str, str] = {}
    unread_buckets: list[Dict[str, Any]] = []
    truncated_buckets: list[str] = []
    diagnostics: list[Dict[str, Any]] = []

    for conv in conversations:
        info_resp = await client.conversations_info(channel=conv["id"])
        info = info_resp.get("channel") or {}
        api_unread_count = info.get("unread_count_display")
        if api_unread_count is None:
            api_unread_count = info.get("unread_count")
        last_read = info.get("last_read")
        dm_display = await _resolve_user_display_name(
            client,
            conv.get("user") or info.get("user") or "",
            name_cache,
        ) if (conv.get("is_im") or conv.get("is_mpim")) else ""
        label = _format_unread_channel_label(conv, dm_display)
        diagnostic: Dict[str, Any] = {
            "channel_id": conv["id"],
            "label": label,
            "last_read": last_read,
            "api_unread_count": api_unread_count,
            "scan_method": "history_after_last_read",
            "messages_returned": 0,
            "has_more": False,
        }
        if _is_missing_or_zero_cursor(last_read):
            diagnostic["scan_method"] = "unread_state_unknown"
            diagnostic["skip_reason"] = "unread_state_unknown"
            diagnostics.append(diagnostic)
            continue
        try:
            history_resp = await client.conversations_history(
                channel=conv["id"],
                oldest=last_read,
                inclusive=False,
                limit=parsed.message_limit_per_channel,
            )
        except Exception as exc:
            diagnostic["skip_reason"] = "history_error"
            diagnostic["history_error"] = f"{type(exc).__name__}: {exc}"
            diagnostics.append(diagnostic)
            continue
        messages = history_resp.get("messages") or []
        diagnostic["messages_returned"] = len(messages)
        diagnostic["has_more"] = bool(history_resp.get("has_more"))
        diagnostics.append(diagnostic)
        if not messages:
            continue
        if len(messages) >= parsed.message_limit_per_channel or history_resp.get("has_more"):
            truncated_buckets.append(conv["id"])
        unread_buckets.append(
            {
                "channel": {
                    "id": conv["id"],
                    "label": label,
                    "name": conv.get("name"),
                    "is_private": bool(conv.get("is_private")),
                    "is_im": bool(conv.get("is_im")),
                    "is_mpim": bool(conv.get("is_mpim")),
                    "user": conv.get("user"),
                },
                "unread_count_reported": api_unread_count,
                "unread_count_returned": len(messages),
                "messages": messages,
            }
        )

    total_unread = sum(b["unread_count_returned"] for b in unread_buckets)
    unknown_count = sum(1 for d in diagnostics if d.get("skip_reason") == "unread_state_unknown")
    history_error_count = sum(1 for d in diagnostics if d.get("skip_reason") == "history_error")
    is_complete = next_cursor is None
    scan_state = "completed" if is_complete else "partial"
    if unread_buckets:
        summary = (
            f"{scan_state.capitalize()} unread scan found {total_unread} unread message(s) "
            f"across {len(unread_buckets)} conversation(s) in this page "
            f"(scanned {len(conversations)} conversation(s))."
        )
    elif is_complete and not unknown_count and not history_error_count:
        summary = (
            "No unread messages found in the completed staged scan "
            f"(scanned {len(conversations)} conversation(s) in this page)."
        )
    else:
        summary = (
            "No unread messages found in this partial staged scan page "
            f"(scanned {len(conversations)} conversation(s))."
        )
    if next_cursor:
        summary += " Continue with next_cursor to scan more conversations."
    if unknown_count:
        summary += f" Unread state was unknown for {unknown_count} conversation(s)."
    if history_error_count:
        summary += f" History checks failed for {history_error_count} conversation(s)."
    if parsed.start_after_channel_id:
        summary += " start_after_channel_id is not used; continue with Slack next_cursor instead."

    bucket_lines: list[str] = []
    for bucket in unread_buckets:
        ch = bucket["channel"]
        bucket_lines.append(f"- {ch['label']} ({bucket['unread_count_returned']} unread)")
        for m in bucket["messages"][:3]:
            line = await _format_message_line(client, m, name_cache)
            bucket_lines.append(f"    {line.lstrip('- ')}")
        if bucket["unread_count_returned"] > 3:
            bucket_lines.append(f"    ... and {bucket['unread_count_returned'] - 3} more")
    text = "\n".join([summary, *bucket_lines]) if unread_buckets else summary
    structured = {
        "total_unread": total_unread,
        "conversation_count": len(unread_buckets),
        "scanned": {
            "conversation_count": len(conversations),
            "cursor": parsed.cursor,
            "next_cursor": next_cursor,
            "is_complete": is_complete,
            "remaining_estimate": "unknown" if next_cursor else 0,
        },
        "next_cursor": next_cursor,
        "is_complete": is_complete,
        "truncated_conversation_ids": truncated_buckets,
        "unread_buckets": unread_buckets,
        "unread_state_unknown_count": unknown_count,
        "history_error_count": history_error_count,
        "scope_notes": [
            "Slack has no single unread-feed endpoint; Basil stages users.conversations pages and checks history after each last_read cursor."
        ],
        "rate_limit_notes": [
            "Each scanned conversation costs conversations.info and sometimes conversations.history; continue in small pages if Slack rate limits."
        ],
    }
    if parsed.include_diagnostics:
        structured["diagnostics"] = diagnostics
    if parsed.start_after_channel_id:
        structured["start_after_channel_id_supported"] = False
    return {"text": text, "structured": structured}


__all__ = [
    "handle_add_reaction",
    "handle_create_canvas",
    "handle_create_channel",
    "handle_get_message_reactions",
    "handle_get_user_profile",
    "handle_get_workspace_info",
    "handle_list_emoji",
    "handle_list_channels",
    "handle_list_unread_messages",
    "handle_list_users",
    "handle_open_dm",
    "handle_open_group_dm",
    "handle_read_canvas",
    "handle_read_channel_history",
    "handle_read_thread",
    "handle_scan_unread_messages",
    "handle_search_files",
    "handle_search_messages",
    "handle_send_message",
]
