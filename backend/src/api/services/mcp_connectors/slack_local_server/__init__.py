"""In-process Slack MCP server, dispatched via ``basil-local://slack``.

This package exists so Basil can ship Slack tooling to users whose
Slack workspaces have not approved Basil for hosted MCP access.
``mcp.slack.com/mcp`` enforces a Marketplace / internal-app gate that
returns HTTP 400 to every JSON-RPC request from unlisted apps,
regardless of OAuth correctness. Until Basil's Slack app is
Marketplace-approved, this package substitutes for that hosted server
by translating MCP tool calls into ``slack_sdk`` Web API calls using
the same OAuth user token the rest of the system already manages.

Design choices the rest of the system depends on:

  * **Same OAuth flow.** The PKCE coordinator, the token bridge, the
    Keychain storage, the WebSocket round-trip — all unchanged.
    ``access_token`` arrives at this package the same way it arrives
    at the streamable-HTTP transport for remote MCP servers.
  * **Same envelope shapes.** ``list_tools`` returns the catalog dict
    that ``MCPClientService.list_tools`` already produces; ``call_tool``
    returns either ``make_success({"text": ..., "structured": ...})``
    or a normalized error envelope. The agent surface
    (``external_catalog_tool``) cannot tell the difference.
  * **Lazy everything.** The package is deferred-imported by the
    dispatcher only when a ``basil-local://`` connection is touched.
    Each ``call_tool`` builds its own ``AsyncWebClient`` for the one
    request and tears it down. Nothing is kept warm between calls.
  * **Twelve tools matching the hosted MCP surface.** When Basil is
    Marketplace-approved, swapping ``server_url`` back to the hosted
    endpoint should be agent-transparent. Tool names, required args,
    and structured-response keys are kept as close to Slack's hosted
    MCP server's documented surface as the public Slack Web API allows.

Modular layout (each file enforced to stay under the 600-line budget):

  * ``schemas.py``       — Pydantic input models, one per tool.
  * ``handlers.py``      — Async handler functions invoking ``slack_sdk``.
  * ``error_mapping.py`` — Slack error-code → standard envelope mapping.
  * ``server.py``        — Tool registry plus the ``list_tools`` and
                           ``call_tool`` public entry points.

Migration path back to hosted MCP after Marketplace approval is one
line in ``slack_routes._persist_slack_connection`` plus deleting this
package; the dispatcher's sentinel-URL branch is harmless if no
records reference it.
"""

from .server import LOCAL_SLACK_SENTINEL_URL, call_tool, list_tools

__all__ = [
    "LOCAL_SLACK_SENTINEL_URL",
    "call_tool",
    "list_tools",
]
