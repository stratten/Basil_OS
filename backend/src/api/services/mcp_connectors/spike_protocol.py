"""Spike: validate the `mcp` SDK shape before depending on it in production code.

Connects to a public unauthenticated remote MCP server, lists tools, and
calls one read-only tool. Records the import paths, class names, and
exception types actually exposed by the installed `mcp` package version,
so the production client/oauth modules can import the right symbols.

Run:  poetry run python -m api.services.mcp.spike_protocol
"""

from __future__ import annotations

import asyncio
import logging
import sys
import traceback
from typing import Any

logger = logging.getLogger("mcp_spike")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


SPIKE_SERVER_URL = "https://mcp.deepwiki.com/mcp"


async def main() -> int:
    import mcp

    logger.info("mcp package: %s (file=%s)", getattr(mcp, "__version__", "unknown"), mcp.__file__)

    try:
        from mcp.client.streamable_http import streamablehttp_client
    except Exception as exc:
        logger.error("Failed to import streamablehttp_client: %s", exc)
        return 2
    logger.info("transport: streamablehttp_client OK")

    try:
        from mcp import ClientSession
    except Exception as exc:
        logger.error("Failed to import ClientSession: %s", exc)
        return 2
    logger.info("session: mcp.ClientSession OK")

    try:
        async with streamablehttp_client(SPIKE_SERVER_URL) as transport:
            read_stream, write_stream, _close_meta = transport
            async with ClientSession(read_stream, write_stream) as session:
                init_result = await session.initialize()
                logger.info(
                    "initialize OK: server_name=%s server_version=%s protocol=%s",
                    getattr(init_result.serverInfo, "name", "?"),
                    getattr(init_result.serverInfo, "version", "?"),
                    getattr(init_result, "protocolVersion", "?"),
                )

                tools_result = await session.list_tools()
                tool_names = [t.name for t in tools_result.tools]
                logger.info("list_tools OK: %d tools", len(tool_names))
                for t in tools_result.tools[:10]:
                    logger.info(
                        "  tool: name=%s desc=%r input_schema_keys=%s",
                        t.name,
                        (t.description or "")[:80],
                        list((t.inputSchema or {}).get("properties", {}).keys()),
                    )

                target = next((t for t in tools_result.tools if "ask" in t.name.lower() or "search" in t.name.lower() or "read" in t.name.lower()), None)
                if target is None and tools_result.tools:
                    target = tools_result.tools[0]
                if target is None:
                    logger.warning("No tools to invoke; spike still confirmed transport+initialize+list_tools")
                    return 0

                logger.info("invoking tool: %s", target.name)
                args = _build_minimal_args(target.inputSchema or {})
                logger.info("  with args: %s", args)
                try:
                    result = await session.call_tool(target.name, args)
                    has_error = bool(getattr(result, "isError", False))
                    content_blocks = getattr(result, "content", []) or []
                    preview = "".join(getattr(b, "text", "") for b in content_blocks)[:200]
                    logger.info("call_tool OK: isError=%s content_preview=%r", has_error, preview)
                except Exception as exc:
                    logger.warning(
                        "call_tool raised %s.%s: %s",
                        type(exc).__module__,
                        type(exc).__name__,
                        exc,
                    )
    except Exception as exc:
        logger.error("Spike failed: %s.%s: %s", type(exc).__module__, type(exc).__name__, exc)
        traceback.print_exc()
        return 1

    try:
        from mcp.shared.exceptions import McpError
        logger.info("exception: mcp.shared.exceptions.McpError OK")
    except Exception as exc:
        logger.warning("Could not import McpError: %s", exc)

    logger.info("Spike complete: SDK shape validated.")
    return 0


def _build_minimal_args(schema: dict[str, Any]) -> dict[str, Any]:
    """Build the smallest valid args dict for a tool from its JSON schema."""
    props = (schema or {}).get("properties", {}) or {}
    required = (schema or {}).get("required", []) or []
    out: dict[str, Any] = {}
    for name in required:
        spec = props.get(name, {})
        t = spec.get("type")
        if t == "string":
            out[name] = "modelcontextprotocol/python-sdk" if "repo" in name.lower() else "ping"
        elif t == "number" or t == "integer":
            out[name] = 1
        elif t == "boolean":
            out[name] = False
        elif t == "array":
            out[name] = []
        elif t == "object":
            out[name] = {}
        else:
            out[name] = ""
    return out


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
