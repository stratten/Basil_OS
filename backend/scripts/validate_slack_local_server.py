#!/usr/bin/env python3
"""Validate Basil's embedded Slack MCP server without launching the app.

Run from ``backend/src`` so the ``api`` package is importable:

    poetry run python ../scripts/validate_slack_local_server.py --mode catalog
    poetry run python ../scripts/validate_slack_local_server.py --mode read-only --token-env BASIL_SLACK_ACCESS_TOKEN

Write-capable checks are gated and intentionally not used by the
validation-first workflow unless explicitly approved.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from slack_sdk.web.async_client import AsyncWebClient

from api.services.mcp_connectors.slack_local_server import call_tool, list_tools


WRITE_TOOL_NAMES = {
    "slack_send_message",
    "slack_open_dm",
    "slack_open_group_dm",
    "slack_add_reaction",
    "slack_create_channel",
    "slack_create_canvas",
}


@dataclass
class ValidationRow:
    tool_name: str
    status: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    result_summary: Optional[str] = None
    result_keys: List[str] = field(default_factory=list)
    error_kind: Optional[str] = None
    scope_gap: Optional[Dict[str, Any]] = None
    raw_error: Any = None
    result_structured: Optional[Dict[str, Any]] = None
    attempts: int = 1
    rate_limit_waits_seconds: List[int] = field(default_factory=list)
    rate_limit_exhausted: bool = False
    elapsed_ms: int = 0

    def to_summary(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "status": self.status,
            "arguments": self.arguments,
            "result_summary": self.result_summary,
            "result_keys": self.result_keys,
            "error_kind": self.error_kind,
            "scope_gap": self.scope_gap,
            "raw_error": self.raw_error,
            "attempts": self.attempts,
            "rate_limit_waits_seconds": self.rate_limit_waits_seconds,
            "rate_limit_exhausted": self.rate_limit_exhausted,
            "elapsed_ms": self.elapsed_ms,
        }


def _result_keys(result: Any) -> List[str]:
    if isinstance(result, dict):
        structured = result.get("structured")
        if isinstance(structured, dict):
            return sorted(structured.keys())
        return sorted(result.keys())
    return []


def _result_summary(result: Any) -> str:
    if isinstance(result, dict):
        text = str(result.get("text") or "")
        return text.replace("\n", " ")[:240]
    return str(result)[:240]


def _extract_scope_gap(error: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    raw = error.get("raw") or {}
    body = raw.get("body") or {}
    needed = body.get("needed")
    provided = body.get("provided")
    if body.get("error") != "missing_scope" and not needed:
        return None
    provided_scopes = [
        scope.strip() for scope in str(provided or "").split(",") if scope.strip()
    ]
    return {
        "needed": needed,
        "provided_count": len(provided_scopes),
        "provided": provided_scopes,
    }


def _is_missing_or_zero_cursor(value: Any) -> bool:
    return value in (None, "", "0", "0.000000", "0000000000.000000")


def _rate_limit_options(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "rate_limit_retries": args.rate_limit_retries,
        "rate_limit_buffer_seconds": args.rate_limit_buffer_seconds,
        "max_rate_limit_wait_seconds": args.max_rate_limit_wait_seconds,
    }


def _rate_limit_retry_after(row: ValidationRow) -> Optional[int]:
    raw = ((row.raw_error or {}).get("raw") or {})
    retry_after = raw.get("retry_after")
    try:
        return int(retry_after) if retry_after is not None else None
    except (TypeError, ValueError):
        return None


async def _sleep_for_rate_limit(wait_seconds: int) -> None:
    await asyncio.sleep(wait_seconds)


async def _run_tool_once(
    tool_name: str,
    arguments: Dict[str, Any],
    access_token: str,
) -> ValidationRow:
    started = time.perf_counter()
    envelope = await call_tool(
        tool_name=tool_name,
        arguments=arguments,
        access_token=access_token,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if envelope.get("ok"):
        result = envelope.get("result")
        structured = result.get("structured") if isinstance(result, dict) else None
        return ValidationRow(
            tool_name=tool_name,
            status="passed",
            arguments=arguments,
            result_summary=_result_summary(result),
            result_keys=_result_keys(result),
            result_structured=structured if isinstance(structured, dict) else None,
            elapsed_ms=elapsed_ms,
        )
    error = envelope.get("error") or {}
    return ValidationRow(
        tool_name=tool_name,
        status="failed",
        arguments=arguments,
        error_kind=error.get("kind"),
        scope_gap=_extract_scope_gap(error),
        raw_error=error,
        elapsed_ms=elapsed_ms,
    )


async def _run_tool(
    tool_name: str,
    arguments: Dict[str, Any],
    access_token: str,
    *,
    rate_limit_retries: int = 2,
    rate_limit_buffer_seconds: int = 1,
    max_rate_limit_wait_seconds: int = 180,
) -> ValidationRow:
    attempts = 0
    waits: List[int] = []
    while True:
        attempts += 1
        row = await _run_tool_once(tool_name, arguments, access_token)
        row.attempts = attempts
        row.rate_limit_waits_seconds = list(waits)
        if row.error_kind != "rate_limited":
            return row
        if attempts > rate_limit_retries:
            row.rate_limit_exhausted = True
            return row

        retry_after = _rate_limit_retry_after(row) or 60
        wait_seconds = retry_after + rate_limit_buffer_seconds
        if wait_seconds > max_rate_limit_wait_seconds:
            row.rate_limit_exhausted = True
            return row
        waits.append(wait_seconds)
        print(
            f"[RATE_LIMIT] {tool_name} attempt {attempts} hit rate limit; "
            f"waiting {wait_seconds}s before retry."
        )
        await _sleep_for_rate_limit(wait_seconds)


def _skip(tool_name: str, reason: str, arguments: Optional[Dict[str, Any]] = None) -> ValidationRow:
    return ValidationRow(
        tool_name=tool_name,
        status="skipped",
        arguments=arguments or {},
        result_summary=reason,
    )


def _print_row(row: ValidationRow) -> None:
    suffix = f" - {row.result_summary}" if row.result_summary else ""
    if row.error_kind:
        suffix = f" - {row.error_kind}: {row.raw_error}"
        if row.scope_gap:
            suffix = (
                f" - missing_scope needed={row.scope_gap.get('needed')} "
                f"provided_count={row.scope_gap.get('provided_count')}"
            )
    print(f"[{row.status.upper()}] {row.tool_name} ({row.elapsed_ms}ms){suffix}")


async def run_catalog_mode() -> Dict[str, Any]:
    catalog = await list_tools(access_token=None)
    tools = catalog["tools"]
    for tool in tools:
        schema = tool.get("input_schema") or {}
        fields = sorted((schema.get("properties") or {}).keys())
        mode = "read" if tool.get("is_read_only_hint") else "write"
        print(f"- {tool['name']} [{mode}] fields={fields}")
    return {"mode": "catalog", "tool_count": len(tools), "tools": tools}


async def _discover_channel(
    rows: List[ValidationRow],
    access_token: str,
    rate_limit_options: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    row = await _run_tool(
        "slack_list_channels",
        {"types": "public_channel,private_channel", "limit": 20, "exclude_archived": True},
        access_token,
        **(rate_limit_options or {}),
    )
    rows.append(row)
    _print_row(row)
    if row.status != "passed":
        return None
    envelope = await call_tool(
        tool_name="slack_list_channels",
        arguments={"types": "public_channel,private_channel", "limit": 20, "exclude_archived": True},
        access_token=access_token,
    )
    channels = (((envelope.get("result") or {}).get("structured") or {}).get("channels") or [])
    return channels[0]["id"] if channels else None


async def _discover_user(
    rows: List[ValidationRow],
    access_token: str,
    rate_limit_options: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    row = await _run_tool(
        "slack_list_users",
        {"limit": 20, "include_locale": False},
        access_token,
        **(rate_limit_options or {}),
    )
    rows.append(row)
    _print_row(row)
    if row.status != "passed":
        return None
    envelope = await call_tool(
        tool_name="slack_list_users",
        arguments={"limit": 20, "include_locale": False},
        access_token=access_token,
    )
    members = (((envelope.get("result") or {}).get("structured") or {}).get("members") or [])
    active = [m for m in members if not m.get("deleted")]
    return active[0]["id"] if active else None


async def _find_thread_fixture(
    access_token: str,
    channel_id: str,
    rate_limit_options: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    row = await _run_tool(
        "slack_read_channel_history",
        {"channel": channel_id, "limit": 20},
        access_token,
        **(rate_limit_options or {}),
    )
    if row.status != "passed":
        return None
    messages = ((row.result_structured or {}).get("messages") or [])
    for message in messages:
        if message.get("reply_count") or message.get("thread_ts"):
            return message.get("thread_ts") or message.get("ts")
    return None


async def _find_reacted_message_fixture(
    access_token: str,
    channel_id: str,
    rate_limit_options: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    row = await _run_tool(
        "slack_read_channel_history",
        {"channel": channel_id, "limit": 50},
        access_token,
        **(rate_limit_options or {}),
    )
    if row.status != "passed":
        return None
    for message in ((row.result_structured or {}).get("messages") or []):
        if message.get("reactions"):
            return message.get("ts")
    return None


async def _find_any_reacted_message_fixture(
    access_token: str,
    rate_limit_options: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, str]]:
    row = await _run_tool(
        "slack_list_channels",
        {"types": "public_channel,private_channel", "limit": 20, "exclude_archived": True},
        access_token,
        **(rate_limit_options or {}),
    )
    if row.status != "passed":
        return None
    channels = ((row.result_structured or {}).get("channels") or [])
    for channel in channels:
        channel_id = channel.get("id")
        if not channel_id:
            continue
        timestamp = await _find_reacted_message_fixture(access_token, channel_id, rate_limit_options)
        if timestamp:
            return {"channel": channel_id, "timestamp": timestamp}
    return None


async def _probe_unread_directly(access_token: str, max_conversations: int, message_limit: int) -> Dict[str, Any]:
    client = AsyncWebClient(token=access_token, timeout=30)
    conv_resp = await client.users_conversations(
        types="public_channel,private_channel,im,mpim",
        limit=max_conversations,
        exclude_archived=True,
    )
    probes = []
    for conv in (conv_resp.get("channels") or [])[:max_conversations]:
        info_resp = await client.conversations_info(channel=conv["id"])
        info = info_resp.get("channel") or {}
        last_read = info.get("last_read")
        history_count = None
        history_error = None
        if _is_missing_or_zero_cursor(last_read):
            history_error = "skipped_invalid_cursor"
        else:
            try:
                history_resp = await client.conversations_history(
                    channel=conv["id"],
                    oldest=last_read,
                    inclusive=False,
                    limit=message_limit,
                )
                history_count = len(history_resp.get("messages") or [])
            except Exception as exc:  # surface provider behavior without failing the validator
                history_error = f"{type(exc).__name__}: {exc}"
        probes.append(
            {
                "id": conv.get("id"),
                "name": conv.get("name") or conv.get("user"),
                "is_im": bool(conv.get("is_im")),
                "is_mpim": bool(conv.get("is_mpim")),
                "is_private": bool(conv.get("is_private")),
                "last_read": last_read,
                "unread_count": info.get("unread_count"),
                "unread_count_display": info.get("unread_count_display"),
                "history_after_last_read_count": history_count,
                "history_error": history_error,
            }
        )
    positives = [
        {
            "id": probe["id"],
            "name": probe["name"],
            "last_read": probe["last_read"],
            "history_after_last_read_count": probe["history_after_last_read_count"],
        }
        for probe in probes
        if (probe.get("history_after_last_read_count") or 0) > 0
    ]
    invalid_cursors = [
        {
            "id": probe["id"],
            "name": probe["name"],
            "last_read": probe["last_read"],
            "history_error": probe["history_error"],
        }
        for probe in probes
        if probe.get("history_error") == "skipped_invalid_cursor"
    ]
    return {
        "sampled": len(probes),
        "arguments": {
            "users_conversations": {
                "types": "public_channel,private_channel,im,mpim",
                "limit": max_conversations,
                "exclude_archived": True,
            },
            "conversations_history": {"inclusive": False, "limit": message_limit},
        },
        "positive_unread_probe_count": len(positives),
        "positive_unread_probes": positives,
        "invalid_cursor_probe_count": len(invalid_cursors),
        "invalid_cursor_probes": invalid_cursors,
        "probes": probes,
    }


async def run_read_only_mode(args: argparse.Namespace, access_token: str) -> Dict[str, Any]:
    rows: List[ValidationRow] = []
    requested_tools = set(args.tool or [])
    rate_limit_options = _rate_limit_options(args)

    def wants(tool_name: str) -> bool:
        return not requested_tools or tool_name in requested_tools

    needs_channel = any(
        wants(tool)
        for tool in (
            "slack_list_channels",
            "slack_read_channel_history",
            "slack_read_thread",
            "slack_get_message_reactions",
        )
    )
    needs_user = any(wants(tool) for tool in ("slack_list_users", "slack_get_user_profile"))
    channel_id = await _discover_channel(rows, access_token, rate_limit_options) if needs_channel else None
    user_id = await _discover_user(rows, access_token, rate_limit_options) if needs_user else None

    today_query = f"after:{(date.today() - timedelta(days=30)).isoformat()}"
    checks: list[tuple[str, Dict[str, Any]]] = [
        ("slack_search_messages", {"query": today_query, "count": 5}),
        ("slack_search_files", {"query": today_query, "count": 5}),
        ("slack_get_workspace_info", {}),
        ("slack_list_emoji", {"limit": 50}),
        ("slack_list_unread_messages", {"max_conversations_to_check": args.unread_scan_limit}),
        (
            "slack_scan_unread_messages",
            {
                "max_conversations_to_check": args.unread_scan_limit,
                "message_limit_per_channel": args.unread_message_limit,
                "include_diagnostics": True,
            },
        ),
    ]
    checks = [(tool, arguments) for tool, arguments in checks if wants(tool)]
    if wants("slack_read_channel_history") and channel_id:
        checks.append(("slack_read_channel_history", {"channel": channel_id, "limit": 5}))
    elif wants("slack_read_channel_history"):
        rows.append(_skip("slack_read_channel_history", "no channel discovered"))
    if wants("slack_get_user_profile") and user_id:
        checks.append(("slack_get_user_profile", {"user": user_id, "include_labels": False}))
    elif wants("slack_get_user_profile"):
        rows.append(_skip("slack_get_user_profile", "no active user discovered"))
    if wants("slack_read_canvas") and args.canvas_id:
        checks.append(("slack_read_canvas", {"canvas_id": args.canvas_id}))
    elif wants("slack_read_canvas"):
        rows.append(_skip("slack_read_canvas", "provide --canvas-id to validate"))
    if wants("slack_get_message_reactions") and channel_id:
        reaction_ts = await _find_reacted_message_fixture(access_token, channel_id, rate_limit_options)
        if reaction_ts:
            checks.append(
                (
                    "slack_get_message_reactions",
                    {"channel": channel_id, "timestamp": reaction_ts, "full": True},
                )
            )
        else:
            any_reaction = await _find_any_reacted_message_fixture(access_token, rate_limit_options)
            if any_reaction:
                checks.append(
                    (
                        "slack_get_message_reactions",
                        {
                            "channel": any_reaction["channel"],
                            "timestamp": any_reaction["timestamp"],
                            "full": True,
                        },
                    )
                )
            else:
                rows.append(_skip("slack_get_message_reactions", "no reacted message fixture discovered", {"channel": channel_id}))
    elif wants("slack_get_message_reactions"):
        rows.append(_skip("slack_get_message_reactions", "no channel discovered"))

    for tool_name, arguments in checks:
        row = await _run_tool(tool_name, arguments, access_token, **rate_limit_options)
        rows.append(row)
        _print_row(row)
        if tool_name == "slack_scan_unread_messages" and row.status == "passed":
            next_cursor = (row.result_structured or {}).get("next_cursor")
            if next_cursor:
                continuation_args = dict(arguments)
                continuation_args["cursor"] = next_cursor
                continuation_row = await _run_tool(
                    tool_name,
                    continuation_args,
                    access_token,
                    **rate_limit_options,
                )
                rows.append(continuation_row)
                _print_row(continuation_row)

    if wants("slack_read_thread") and channel_id:
        thread_ts = await _find_thread_fixture(access_token, channel_id, rate_limit_options)
        if thread_ts:
            row = await _run_tool(
                "slack_read_thread",
                {"channel": channel_id, "thread_ts": thread_ts, "limit": 20},
                access_token,
                **rate_limit_options,
            )
        else:
            row = _skip("slack_read_thread", "no thread fixture discovered", {"channel": channel_id})
        rows.append(row)
        _print_row(row)

    unread_probe = None
    if wants("slack_list_unread_messages") or wants("slack_scan_unread_messages"):
        unread_probe = await _probe_unread_directly(
            access_token,
            max_conversations=args.unread_scan_limit,
            message_limit=args.unread_message_limit,
        )
        print("\nUnread direct probe:")
        print(
            "positive_unread_probe_count="
            f"{unread_probe['positive_unread_probe_count']} "
            f"invalid_cursor_probe_count={unread_probe['invalid_cursor_probe_count']}"
        )
        for probe in unread_probe["positive_unread_probes"]:
            print(json.dumps(probe, sort_keys=True))
        for probe in unread_probe["invalid_cursor_probes"]:
            print(json.dumps(probe, sort_keys=True))

    summary = {
        "mode": "read-only",
        "requested_tools": sorted(requested_tools),
        "rows": [row.to_summary() for row in rows],
    }
    if unread_probe is not None:
        summary["unread_direct_probe"] = unread_probe
    return summary


async def run_all_mode(args: argparse.Namespace, access_token: str) -> Dict[str, Any]:
    if not args.allow_writes:
        raise SystemExit("--mode all requires --allow-writes. Refusing to run write-capable checks.")
    if not args.test_channel:
        requested = set(args.write_tool or [])
        if not requested or {"slack_send_message", "slack_add_reaction"} & requested:
            raise SystemExit("--mode all --allow-writes requires --test-channel for message/reaction validation.")
    requested_write_tools = set(args.write_tool or [])
    unknown_write_tools = requested_write_tools - WRITE_TOOL_NAMES
    if unknown_write_tools:
        raise SystemExit(f"Unknown --write-tool value(s): {sorted(unknown_write_tools)}")

    def wants_write(tool_name: str) -> bool:
        if tool_name in {"slack_open_dm", "slack_open_group_dm"}:
            return tool_name in requested_write_tools
        return not requested_write_tools or tool_name in requested_write_tools

    rate_limit_options = _rate_limit_options(args)
    rows: List[ValidationRow] = []
    if not args.skip_read_only_preflight:
        read_only = await run_read_only_mode(args, access_token)
        rows.extend(ValidationRow(**row) for row in read_only["rows"])
    write_artifacts: Dict[str, Any] = {}
    user_id = None
    if wants_write("slack_open_dm"):
        user_id = await _discover_user(rows, access_token, rate_limit_options)

    message_text = f"Basil Slack validator test message {int(time.time())}"
    needs_message_fixture = wants_write("slack_send_message") or wants_write("slack_add_reaction")
    write_checks: list[tuple[str, Dict[str, Any]]] = []
    if needs_message_fixture:
        write_checks.append(("slack_send_message", {"channel": args.test_channel, "text": message_text}))
    if wants_write("slack_open_dm") and user_id:
        write_checks.append(("slack_open_dm", {"user": user_id}))
    elif wants_write("slack_open_dm"):
        rows.append(_skip("slack_open_dm", "no active user discovered"))
    if wants_write("slack_open_group_dm") and args.group_dm_user and len(args.group_dm_user) >= 2:
        write_checks.append(("slack_open_group_dm", {"users": args.group_dm_user[:8]}))
    elif wants_write("slack_open_group_dm"):
        rows.append(_skip("slack_open_group_dm", "provide --group-dm-user at least twice for safe fixture selection"))
    if wants_write("slack_create_canvas") and (args.allow_canvas_write or requested_write_tools):
        write_checks.append(
            ("slack_create_canvas", {"title": "Basil Slack validator", "markdown": message_text})
        )
    if wants_write("slack_create_channel") and (args.allow_channel_create or requested_write_tools):
        write_checks.append(
            (
                "slack_create_channel",
                {"name": f"basil-validator-{int(time.time())}", "is_private": True},
            )
        )

    posted_ts = None
    posted_channel = None
    for tool_name, arguments in write_checks:
        row = await _run_tool(tool_name, arguments, access_token, **rate_limit_options)
        rows.append(row)
        _print_row(row)
        if tool_name == "slack_send_message" and row.status == "passed":
            posted_ts = (row.result_structured or {}).get("ts")
            posted_channel = (row.result_structured or {}).get("channel")
            write_artifacts["posted_message"] = {
                "channel": posted_channel,
                "ts": posted_ts,
            }
        elif tool_name == "slack_create_channel" and row.status == "passed":
            channel = (row.result_structured or {}).get("channel") or {}
            write_artifacts["created_channel"] = {
                "id": channel.get("id"),
                "name": channel.get("name"),
            }
        elif tool_name == "slack_create_canvas" and row.status == "passed":
            canvas_id = (row.result_structured or {}).get("canvas_id")
            write_artifacts["created_canvas"] = {
                "canvas_id": canvas_id,
            }
            if canvas_id:
                readback = await _run_tool(
                    "slack_read_canvas",
                    {"canvas_id": canvas_id},
                    access_token,
                    **rate_limit_options,
                )
                rows.append(readback)
                _print_row(readback)
                write_artifacts["created_canvas"]["readback_status"] = readback.status
                if readback.error_kind:
                    write_artifacts["created_canvas"]["readback_error_kind"] = readback.error_kind
        elif tool_name in {"slack_open_dm", "slack_open_group_dm"} and row.status == "passed":
            write_artifacts[tool_name] = {
                "channel": (row.result_structured or {}).get("channel"),
                "users": (row.result_structured or {}).get("users"),
            }

    if wants_write("slack_add_reaction") and posted_ts and posted_channel:
        row = await _run_tool(
            "slack_add_reaction",
            {"channel": posted_channel, "timestamp": posted_ts, "name": "white_check_mark"},
            access_token,
            **rate_limit_options,
        )
        rows.append(row)
        _print_row(row)
        if row.status == "passed":
            write_artifacts["reaction"] = {
                "channel": posted_channel,
                "timestamp": posted_ts,
                "name": "white_check_mark",
            }
    elif wants_write("slack_add_reaction"):
        rows.append(_skip("slack_add_reaction", "no posted message timestamp available"))

    return {
        "mode": "all",
        "rows": [row.to_summary() for row in rows],
        "write_artifacts": write_artifacts,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["catalog", "read-only", "all"], required=True)
    parser.add_argument(
        "--tool",
        action="append",
        help="Restrict read-only validation to one tool. May be supplied multiple times.",
    )
    parser.add_argument("--token-env", default="BASIL_SLACK_ACCESS_TOKEN")
    parser.add_argument("--canvas-id")
    parser.add_argument("--unread-scan-limit", type=int, default=20)
    parser.add_argument("--unread-message-limit", type=int, default=20)
    parser.add_argument("--rate-limit-retries", type=int, default=2)
    parser.add_argument("--rate-limit-buffer-seconds", type=int, default=1)
    parser.add_argument("--max-rate-limit-wait-seconds", type=int, default=180)
    parser.add_argument("--allow-writes", action="store_true")
    parser.add_argument("--allow-canvas-write", action="store_true")
    parser.add_argument("--allow-channel-create", action="store_true")
    parser.add_argument("--skip-read-only-preflight", action="store_true")
    parser.add_argument("--write-tool", action="append", choices=sorted(WRITE_TOOL_NAMES))
    parser.add_argument("--group-dm-user", action="append", help="User ID fixture for slack_open_group_dm; supply at least two.")
    parser.add_argument("--test-channel")
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    if args.mode == "catalog":
        summary = await run_catalog_mode()
    else:
        access_token = os.environ.get(args.token_env)
        if not access_token:
            raise SystemExit(f"Missing Slack token env var: {args.token_env}")
        if args.mode == "read-only":
            summary = await run_read_only_mode(args, access_token)
        else:
            summary = await run_all_mode(args, access_token)

    print("\nJSON_SUMMARY:")
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    asyncio.run(main())
