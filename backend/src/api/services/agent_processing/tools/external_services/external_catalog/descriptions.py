"""Description builders for the external_catalog tool."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# Why this slim:
# - KEEPS: the routing rule that discriminates external_catalog from native
#   tools and web_search; the load-bearing 'tool_name is a FIELD inside an
#   external_catalog call' invariant; the error-recovery rule for the
#   common 'X is not a valid tool' misroute; permission_denied / auth_expired
#   finality. These are the four pieces of the full description that the
#   model would actually fail on if dropped.
# - DROPS: the dynamic CURRENT CONNECTIONS inventory (the agent re-discovers
#   via action='list_servers' when needed; this is a deliberate context-vs-
#   round-trip trade against context); USE / DO NOT USE prose examples
#   (subsumed by the routing rule); the WORKED EXAMPLE block (the schema's
#   action Literal + Pydantic field descriptions cover the call shape);
#   verbose framing prose and the OUTPUT shape (the envelope shape is
#   either documented in the schema or learned from a single error round).
SLIM_DESCRIPTION = (
    "discover/invoke tools on remote MCP services the user has connected "
    "(e.g. Linear, GitHub, Slack); use native tools for local email/files/"
    "activity, web_search for the open web. tool_name is a FIELD inside an "
    "external_catalog call (action='call_tool'), never a top-level tool - "
    "if 'X is not a valid tool' matches a name from describe_server, "
    "re-invoke external_catalog with action='call_tool'. permission_denied "
    "/ auth_expired envelopes are final answers; do not retry. when searching, "
    "prefer a tool's structured/exact parameters over free-text and keep free-text "
    "to a few literal terms; an empty search result means reformulate (exact param, "
    "then broaden, then enumerate-and-filter) before concluding the data is absent. "
    "a connected service may expose action tools that perform work (create a request/"
    "ticket/job, run a recipe), not only read tools; when read/list tools do not already "
    "hold the answer, consider an action tool to have the service do the work, subject to "
    "the user's approval policy."
)


def build_full_external_catalog_description(connection_inventory: str) -> str:
    """Compose the full external_catalog description with the dynamic inventory inlined."""
    return (
        "Discover and invoke tools on remote services the user has connected (Model Context Protocol).\n"
        "\n"
        f"{connection_inventory}\n"
        "\n"
        "**WHEN TO USE:**\n"
        "Use this tool when the user's request targets data or actions that live in an external\n"
        "service the user has connected via Settings → Connections (e.g. Linear, GitHub).\n"
        "\n"
        "**DECISIONING RULE:**\n"
        "If the answer or action lives in the user's own machine (files, email, calendar, screen\n"
        "history), use the corresponding native tool instead. If it lives on the open web with no\n"
        "specific account context, use web_search instead. If it lives in a third-party service\n"
        "the user has authenticated with, use external_catalog.\n"
        "\n"
        "Surface phrasing alone ('look up', 'find', 'create') is not sufficient justification —\n"
        "those verbs apply equally across all data sources. Apply the rule above to decide.\n"
        "\n"
        "- USE: 'list my open Linear issues' → Linear MCP connection.\n"
        "- USE: 'comment on the GitHub PR I opened yesterday' → GitHub MCP connection.\n"
        "- USE: 'ask <service> to pull the latest install link' → an action tool on that\n"
        "  connection (e.g. *_create_request / *_run_recipe), subject to approval.\n"
        "- DO NOT USE: 'find my last email from Sarah' → email_service, not MCP.\n"
        "- DO NOT USE: 'what was I working on this morning' → query_activities, not MCP.\n"
        "- DO NOT USE: 'what is the React 19 changelog' → web_search, not MCP.\n"
        "\n"
        "**ACTUATION — SERVICES CAN DO WORK, NOT JUST ANSWER:**\n"
        "A connected service often exposes action tools that perform work on the user's behalf\n"
        "(create a request/ticket/job, run a recipe, start a process), not only read/list tools.\n"
        "When the user's goal is best served by having the service act — and especially when the\n"
        "read/list tools do not already contain the answer — consider the relevant action tool\n"
        "rather than stopping at what read tools return. Action tools remain governed by the\n"
        "approval policy below: some are auto-approved, some prompt the user, some are refused.\n"
        "Never fabricate connection_ids or tool_names; learn them from describe_server first.\n"
        "\n"
        "**DISCOVER-THEN-CALL PATTERN:**\n"
        "1. Call with action='list_servers' to see which connections the user has. This only returns\n"
        "   connection-level metadata (ids, names, URLs, tool counts), not tool names.\n"
        "2. Call with action='describe_server' on a relevant connection to learn tool names,\n"
        "   descriptions, input schemas, and read-only hints.\n"
        "3. Call with action='call_tool' to invoke a specific tool with arguments.\n"
        "\n"
        "**SEARCH & RETRIEVAL STRATEGY:**\n"
        "When a tool searches or lists records, match your query to how the tool retrieves.\n"
        "- Prefer the most specific structured parameter you hold a value for (an exact id,\n"
        "  number, or key) over free-text search. If the schema exposes an exact-lookup field\n"
        "  and you have a value that fits its described shape, use that field.\n"
        "- Use free-text search only as a high-recall fallback, and keep it to a few salient\n"
        "  terms. Most backends match literally/keyword, not semantically, so a long natural-\n"
        "  language phrase usually matches nothing.\n"
        "- Do not concatenate an entity/account name and a topic into one long phrase; that is\n"
        "  rarely a literal substring of any stored field.\n"
        "\n"
        "**WHEN A SEARCH RETURNS NOTHING:**\n"
        "An empty or low-signal result is a signal to reformulate, not a final answer. Before\n"
        "concluding the data does not exist, climb this ladder:\n"
        "1. Switch free-text to a structured/exact parameter if you hold a value that fits it.\n"
        "2. Broaden or decompose the query into fewer or alternate terms.\n"
        "3. Use an alternate discovery path the server offers (e.g. list entities, then filter\n"
        "   to the match).\n"
        "4. If the connection exposes an action/request tool that could produce the answer\n"
        "   (e.g. create a request to have the service locate or generate it), consider\n"
        "   initiating it — subject to the approval policy below — before concluding not found.\n"
        "Also read any structured guidance the tool returns in its result envelope (fields that\n"
        "name better parameters or describe the search mechanism) and follow it. Only report\n"
        "'not found' after the ladder is exhausted.\n"
        "\n"
        "**WORKED EXAMPLE OF call_tool:**\n"
        "After action='describe_server' tells you that connection 'abc123' has a tool named\n"
        "'linear_get_issues' with input schema {'limit': int}, the invocation that actually runs\n"
        "that tool is:\n"
        "\n"
        "    {\n"
        "      \"action\": \"call_tool\",\n"
        "      \"connection_id\": \"abc123\",\n"
        "      \"tool_name\": \"linear_get_issues\",\n"
        "      \"arguments\": {\"limit\": 10}\n"
        "    }\n"
        "\n"
        "It is NOT a top-level invocation of 'linear_get_issues' by itself. The tool name from\n"
        "describe_server is the value of the 'tool_name' field inside an external_catalog call;\n"
        "it is never a tool you can invoke directly. Same shape applies to every MCP tool\n"
        "(slack_search_messages, github_create_issue, etc.).\n"
        "\n"
        "Do not call a remote tool merely from a guessed name. Before action='call_tool', you must\n"
        "have learned the tool_name and its argument schema from action='describe_server' within\n"
        "this same agent run, unless the user explicitly supplied the exact connection_id and tool_name.\n"
        "Never invent connection_ids or tool_names.\n"
        "\n"
        "**ERROR RECOVERY — 'X is not a valid tool':**\n"
        "If your next action returns '<name> is not a valid tool, try one of [...]' AND <name>\n"
        "matches a tool you just saw via describe_server (or that appears in CURRENT CONNECTIONS\n"
        "at the top of this description), do NOT give up and do NOT ask the user for an\n"
        "alternative. The error is a routing reminder, not a missing capability — you tried to\n"
        "call the MCP tool directly when it must be wrapped. Re-invoke external_catalog with:\n"
        "\n"
        "    action='call_tool', connection_id=<the matching server's id>,\n"
        "    tool_name=<name>, arguments=<the schema you saw>\n"
        "\n"
        "Only treat that error as final if <name> does not appear anywhere in the catalog you\n"
        "have inspected this run.\n"
        "\n"
        "**SAFETY:**\n"
        "- The user controls per-tool approval policy. Some calls will be auto-approved, some\n"
        "  will prompt the user, some will be refused outright. Treat a 'permission_denied'\n"
        "  envelope as a final answer for that call — do NOT retry it.\n"
        "- An 'auth_expired' envelope means the server rejected the credentials. Report the\n"
        "  envelope message/action verbatim and stop; do not claim it is definitely expired\n"
        "  unless the provider explicitly says expired.\n"
        "\n"
        "**OUTPUT:**\n"
        "Returns a JSON envelope. On success: {'ok': true, 'result': ...}. On failure:\n"
        "{'ok': false, 'error': {'kind': '<kind>', 'message': '...', 'retryable': bool, ...}}."
    )


def format_connection_inventory_for_description() -> str:
    """Expose current enabled connections from cache so the agent knows they exist.

    Full schemas still require ``describe_server``. This intentionally stays
    compact: connection names are high-signal for tool selection, while large
    remote schemas would crowd out the user's actual request.
    """
    try:
        from ..external_connection_inventory import render_connection_inventory_for_description

        return render_connection_inventory_for_description()
    except Exception as exc:
        logger.warning("Could not load MCP connection inventory for tool description: %s", exc)
        return "**CURRENT CONNECTIONS:** Unable to load the user's current connection list."
