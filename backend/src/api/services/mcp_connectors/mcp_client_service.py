"""Thin async wrapper around the `mcp` SDK's streamable-HTTP client.

This service owns three concerns and nothing else:

  1. Establish an MCP session against a remote streamable-HTTP server,
     optionally with an OAuth bearer token.
  2. Expose ``list_tools`` and ``call_tool`` that always return the
     normalized envelope shape from ``error_normalizer`` so callers
     never have to reason about which exception class came out of the
     SDK.
  3. Be safe to call concurrently from many agent runs without leaking
     transports.

It does NOT own:

  * OAuth (see ``oauth_coordinator.py``)
  * Token storage (the Swift Keychain bridge owns that)
  * Approval policy (the ``external_catalog`` agent tool owns that)
  * Audit logging (the agent tool calls into ``MCPCallLogRepository``
    after this service returns)

Lifetime model: per call. The MCP ``ClientSession`` is bound to the
transport's async-context lifetime, so attempting to cache a "live"
session across distinct asyncio tasks is incorrect by design. Each
``list_tools`` / ``call_tool`` opens its own short-lived session,
performs initialize() + the operation, and closes. The cost is one
extra HTTP roundtrip per call, which is negligible relative to the
agent latencies these tools sit inside, and it eliminates an entire
class of "stale stream" bugs.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .error_normalizer import (
    ERROR_KIND_AUTH_EXPIRED,
    ERROR_KIND_PERMISSION_DENIED,
    ERROR_KIND_RATE_LIMITED,
    ERROR_KIND_SERVER_ERROR,
    make_envelope,
    make_success,
    normalize_call_tool_result,
    normalize_exception,
)

logger = logging.getLogger(__name__)


DEFAULT_TIMEOUT_SECONDS = 30.0
"""Per-operation deadline for list_tools/call_tool. Wall-clock, not
per-roundtrip; covers transport open + initialize + the call itself.
Chosen to match typical user-facing AgentTask latency budgets."""


_LOCAL_SENTINEL_PREFIX = "basil-local://"
"""URL prefix that routes a connection to an in-process MCP server
inside the Basil backend instead of opening an HTTP transport. Today
the only registered local server is ``basil-local://slack``; any
future embedded MCP servers should reuse this same prefix and be
deferred-imported in :meth:`MCPClientService._dispatch_local`."""


class MCPClientService:
    """Stateless dispatcher for remote MCP operations."""

    def __init__(self, default_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS):
        self.default_timeout_seconds = default_timeout_seconds

    async def list_tools(
        self,
        server_url: str,
        access_token: Optional[str] = None,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Return the live tool catalog for ``server_url``.

        Success envelope payload shape::

            {
              "server": {"name": str, "version": str, "protocol": str},
              "tools": [
                {"name": str, "description": str|None,
                 "input_schema": dict, "is_read_only_hint": bool},
                ...
              ]
            }

        Sentinel URLs of the form ``basil-local://<name>`` short-circuit
        to an in-process server module via :meth:`_dispatch_local` and
        never touch the streamable-HTTP transport.
        """
        if server_url.startswith(_LOCAL_SENTINEL_PREFIX):
            return await self._dispatch_local(
                server_url=server_url,
                access_token=access_token,
                timeout_seconds=timeout_seconds,
                op="list_tools",
            )

        async def _op(session: ClientSession) -> Dict[str, Any]:
            init = await session.initialize()
            tools_result = await session.list_tools()
            tools_payload: List[Dict[str, Any]] = []
            for tool in tools_result.tools:
                annotations = getattr(tool, "annotations", None)
                read_only_hint = bool(getattr(annotations, "readOnlyHint", False)) if annotations else False
                tools_payload.append(
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": tool.inputSchema or {},
                        "is_read_only_hint": read_only_hint,
                    }
                )
            return {
                "server": {
                    "name": getattr(init.serverInfo, "name", None),
                    "version": getattr(init.serverInfo, "version", None),
                    "protocol": getattr(init, "protocolVersion", None),
                    # Optional MCP server usage guidance. Secret-free; captured so
                    # routing surfaces can identify which system this connection
                    # serves. getattr keeps this safe across SDK versions and the
                    # local-sentinel path that may not set it.
                    "instructions": getattr(init, "instructions", None),
                },
                "tools": tools_payload,
            }

        return await self._run_in_session(
            server_url=server_url,
            access_token=access_token,
            timeout_seconds=timeout_seconds,
            op=_op,
            envelope_success=True,
        )

    async def call_tool(
        self,
        server_url: str,
        tool_name: str,
        arguments: Dict[str, Any],
        access_token: Optional[str] = None,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Invoke a remote MCP tool and return the normalized envelope.

        On success the envelope's ``result`` is what
        ``normalize_call_tool_result`` produces (text + structured
        content). On any exception or server-flagged failure, the
        envelope is the standard error shape.

        Sentinel URLs of the form ``basil-local://<name>`` short-circuit
        to an in-process server module via :meth:`_dispatch_local` and
        return its already-normalized envelope as-is.
        """
        if server_url.startswith(_LOCAL_SENTINEL_PREFIX):
            return await self._dispatch_local(
                server_url=server_url,
                access_token=access_token,
                timeout_seconds=timeout_seconds,
                op="call_tool",
                tool_name=tool_name,
                arguments=arguments,
            )

        async def _op(session: ClientSession) -> Any:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)

        result_or_envelope = await self._run_in_session(
            server_url=server_url,
            access_token=access_token,
            timeout_seconds=timeout_seconds,
            op=_op,
            envelope_success=False,
        )
        if isinstance(result_or_envelope, dict) and result_or_envelope.get("ok") is False:
            return result_or_envelope
        return normalize_call_tool_result(result_or_envelope)

    async def _dispatch_local(
        self,
        *,
        server_url: str,
        access_token: Optional[str],
        timeout_seconds: Optional[float],
        op: str,
        tool_name: Optional[str] = None,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Dispatch a list_tools / call_tool to an in-process MCP server.

        The server module is identified by the URL host segment after
        the ``basil-local://`` prefix and is **deferred-imported** so
        idle Basil never pays the import cost. Each in-process server
        is responsible for returning a fully normalized envelope; this
        method only enforces the wall-clock deadline and translates
        timeouts / unexpected exceptions into the standard envelope
        shape, mirroring the remote dispatch error contract.
        """
        target = server_url[len(_LOCAL_SENTINEL_PREFIX) :].split("/", 1)[0]
        deadline = timeout_seconds if timeout_seconds is not None else self.default_timeout_seconds

        try:
            if target == "slack":
                # Deferred import: the Slack tooling pulls in slack_sdk +
                # pydantic schemas, which we don't want loaded until the
                # first time a Slack connection is actually exercised.
                from .slack_local_server import call_tool as slack_call
                from .slack_local_server import list_tools as slack_list

                if op == "list_tools":
                    # Local list_tools returns the bare catalog payload,
                    # parallel to the remote ``_op`` returning its dict
                    # before ``_run_in_session`` wraps it. Wrap here so
                    # the local and remote ``list_tools`` envelope shape
                    # is identical at the call site.
                    catalog = await asyncio.wait_for(
                        slack_list(access_token=access_token),
                        timeout=deadline,
                    )
                    return make_success(catalog)
                if op == "call_tool":
                    # Local call_tool already returns a normalized envelope
                    # (success or error), so pass it through unchanged to
                    # match the remote ``call_tool`` post-normalization.
                    return await asyncio.wait_for(
                        slack_call(
                            tool_name=tool_name or "",
                            arguments=arguments or {},
                            access_token=access_token,
                        ),
                        timeout=deadline,
                    )
                return make_envelope(
                    kind=ERROR_KIND_SERVER_ERROR,
                    message=f"Unsupported local op {op!r}.",
                    retryable=False,
                    raw={"server_url": server_url},
                )

            return make_envelope(
                kind=ERROR_KIND_SERVER_ERROR,
                message=f"Unknown local MCP server: {target!r}.",
                retryable=False,
                raw={"server_url": server_url},
            )
        except asyncio.TimeoutError:
            from .error_normalizer import ERROR_KIND_TIMEOUT

            return make_envelope(
                kind=ERROR_KIND_TIMEOUT,
                message=f"Local MCP {op} timed out after {deadline:.1f}s",
                retryable=True,
                raw={"server_url": server_url, "tool_name": tool_name},
            )
        except Exception as exc:
            logger.exception("Local MCP dispatch failed for %s op=%s", server_url, op)
            return make_envelope(
                kind=ERROR_KIND_SERVER_ERROR,
                message=f"Local MCP dispatch failed: {type(exc).__name__}: {exc}",
                retryable=False,
                raw={"server_url": server_url, "tool_name": tool_name, "exc_type": type(exc).__name__},
            )

    async def _run_in_session(
        self,
        *,
        server_url: str,
        access_token: Optional[str],
        timeout_seconds: Optional[float],
        op,
        envelope_success: bool,
    ) -> Any:
        """Open transport+session, run ``op(session)``, normalize errors.

        ``envelope_success=True`` wraps the operation's return value in
        a ``make_success`` envelope. ``False`` returns the raw value
        (used by ``call_tool`` so its caller can run
        ``normalize_call_tool_result`` on the SDK's result object).
        """
        deadline = timeout_seconds if timeout_seconds is not None else self.default_timeout_seconds
        headers = self._build_auth_headers(access_token)

        try:
            preflight_envelope = await self._preflight_initialize(
                server_url=server_url,
                headers=headers,
                timeout_seconds=min(deadline, 10.0),
            )
            if preflight_envelope is not None:
                return preflight_envelope

            async def _run() -> Any:
                async with streamablehttp_client(server_url, headers=headers) as transport:
                    read_stream, write_stream, _close_meta = transport
                    async with ClientSession(read_stream, write_stream) as session:
                        return await op(session)

            value = await asyncio.wait_for(_run(), timeout=deadline)
        except asyncio.TimeoutError as exc:
            from .error_normalizer import ERROR_KIND_TIMEOUT, make_envelope
            return make_envelope(
                kind=ERROR_KIND_TIMEOUT,
                message=f"MCP operation timed out after {deadline:.1f}s",
                retryable=True,
                raw={"server_url": server_url},
            )
        except Exception as exc:
            if access_token and self._looks_like_authenticated_stream_rejection(exc):
                return make_envelope(
                    kind=ERROR_KIND_AUTH_EXPIRED,
                    message=(
                        "MCP server rejected the authenticated stream during dispatch. "
                        "The credential may be invalid, missing scopes, or not entitled for this server."
                    ),
                    retryable=False,
                    user_action_required="Refresh or reconnect this server in Settings → Connections.",
                    raw={
                        "server_url": server_url,
                        "exception_type": type(exc).__name__,
                    },
                )
            return normalize_exception(exc)

        return make_success(value) if envelope_success else value

    @staticmethod
    def _looks_like_authenticated_stream_rejection(exc: Exception) -> bool:
        """Detect SDK-obscured auth rejection after stream initialization.

        Some streamable-HTTP servers accept ``initialize`` but reject a later
        JSON-RPC request (for example, ``tools/list``) with HTTP 403 in the
        SDK's background writer. The foreground exception then only shows
        ``BrokenResourceError`` from the memory stream. With a bearer token
        present, that is actionable as an auth/scope problem, not an unknown
        crash.
        """
        text = repr(exc)
        return "BrokenResourceError" in text or "BrokenResource" in text

    @staticmethod
    async def _preflight_initialize(
        *,
        server_url: str,
        headers: Optional[Dict[str, str]],
        timeout_seconds: float,
    ) -> Optional[Dict[str, Any]]:
        """Probe the MCP server with a JSON-RPC ``initialize`` POST.

        Returns ``None`` on any 2xx response: the SDK transport will run
        its own ``initialize`` handshake immediately after we return, and
        any session id the server issues to us is discarded (servers
        issue a fresh one to the SDK's session). Returns a normalized
        error envelope on any 4xx/5xx, including the response body and
        diagnostically useful headers in the envelope's ``raw`` so the
        backend log, the audit log, and the agent transcript all see
        what the server actually said.

        The MCP SDK's ``streamablehttp_client`` swallows HTTP 4xx/5xx
        responses as background-writer failures that surface to the
        foreground only as ``anyio`` ``BrokenResourceError`` with no
        body, no headers, and no status code. Doing one explicit
        ``initialize`` POST first is the cheapest way to preserve
        diagnostic detail; the cost is one extra HTTP round-trip per
        operation, well below typical MCP call latency.
        """
        request_headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if headers:
            request_headers.update(headers)
        init_request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "basil-preflight", "version": "1.0.0"},
            },
        }

        try:
            async with httpx.AsyncClient(
                timeout=timeout_seconds, follow_redirects=True
            ) as client:
                resp = await client.post(server_url, json=init_request, headers=request_headers)
        except httpx.TimeoutException:
            logger.debug("MCP preflight initialize timed out for %s", server_url)
            return None
        except httpx.HTTPError as exc:
            logger.debug("MCP preflight initialize transport error for %s: %r", server_url, exc)
            return None

        if resp.status_code < 400:
            logger.debug(
                "MCP preflight initialize ok: url=%s status=%d", server_url, resp.status_code
            )
            return None

        body_preview = (resp.text or "")[:1500]
        # Whitelist a handful of headers that are diagnostically useful
        # without leaking opaque tokens or vendor-specific cookies into
        # the audit log.
        diagnostic_header_keys = {
            "www-authenticate",
            "retry-after",
            "content-type",
            "x-slack-req-id",
            "x-request-id",
            "x-trace-id",
        }
        safe_headers = {
            k: v for k, v in resp.headers.items() if k.lower() in diagnostic_header_keys
        }
        logger.warning(
            "MCP server rejected initialize: url=%s status=%d body=%r headers=%r",
            server_url,
            resp.status_code,
            body_preview,
            safe_headers,
        )
        raw = {
            "server_url": server_url,
            "status_code": resp.status_code,
            "body_preview": body_preview,
            "response_headers": safe_headers,
        }

        if resp.status_code in (401, 407):
            return make_envelope(
                kind=ERROR_KIND_AUTH_EXPIRED,
                message=f"MCP server rejected credentials with HTTP {resp.status_code}",
                retryable=False,
                user_action_required="Refresh or reconnect this server in Settings → Connections.",
                raw=raw,
            )
        if resp.status_code == 403:
            return make_envelope(
                kind=ERROR_KIND_PERMISSION_DENIED,
                message=(
                    f"MCP server refused initialize (HTTP 403): "
                    f"{body_preview or '<empty body>'}"
                ),
                retryable=False,
                raw=raw,
            )
        if resp.status_code == 429:
            return make_envelope(
                kind=ERROR_KIND_RATE_LIMITED,
                message=(
                    f"MCP server is rate-limiting requests (HTTP 429): "
                    f"{body_preview or '<empty body>'}"
                ),
                retryable=True,
                raw=raw,
            )
        if 500 <= resp.status_code < 600:
            return make_envelope(
                kind=ERROR_KIND_SERVER_ERROR,
                message=(
                    f"MCP server error during initialize (HTTP {resp.status_code}): "
                    f"{body_preview or '<empty body>'}"
                ),
                retryable=True,
                raw=raw,
            )
        # Any other 4xx (400/405/410/etc.). Slack returns 400 for
        # unlisted apps with a helpful body string; surface that to the
        # user instead of letting it dissolve into a generic 502.
        return make_envelope(
            kind=ERROR_KIND_SERVER_ERROR,
            message=(
                f"MCP server rejected initialize with HTTP {resp.status_code}: "
                f"{body_preview or '<empty body>'}"
            ),
            retryable=False,
            raw=raw,
        )

    @staticmethod
    def _build_auth_headers(access_token: Optional[str]) -> Optional[Dict[str, str]]:
        """Return a Bearer-token header dict, or None if no token.

        Returning None (rather than {}) lets the SDK skip header-merge
        bookkeeping entirely on the no-auth path used by public MCP
        servers like deepwiki.com.
        """
        if not access_token:
            return None
        return {"Authorization": f"Bearer {access_token}"}
