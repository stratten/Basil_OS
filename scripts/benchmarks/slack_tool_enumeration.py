"""Enumerate the embedded Slack tool catalog and requested OAuth scopes from code (read-only, no network, no Slack call).

Run: PYTHONPATH=scripts:backend/src .venv/bin/python -m benchmarks.slack_tool_enumeration
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.common.results import build_result, write_result  # noqa: E402


def main() -> int:
    from api.services.mcp_connectors.slack_local_server import server
    from api.services.mcp_connectors.slack_pkce_coordinator import SLACK_DEFAULT_USER_SCOPES

    tools = []
    for descriptor in server._TOOL_REGISTRY:
        tools.append(
            {
                "name": descriptor.name,
                "read_only_hint": bool(descriptor.is_read_only_hint),
                "input_fields": sorted(descriptor.input_model.model_fields.keys()),
            }
        )
    read_only = sum(1 for t in tools if t["read_only_hint"])
    writes = [t["name"] for t in tools if not t["read_only_hint"]]
    for tool in tools:
        print(f"{'R' if tool['read_only_hint'] else 'W'}  {tool['name']}  {tool['input_fields']}")
    print(f"total {len(tools)}, read-only {read_only}, write-capable {len(writes)}")
    print("scopes:", ",".join(SLACK_DEFAULT_USER_SCOPES))

    result = build_result(
        "slack_tool_enumeration",
        mode="full",
        subject={"label": "embedded-slack-server"},
        parameters={"source": "slack_local_server.server._TOOL_REGISTRY", "scopes": list(SLACK_DEFAULT_USER_SCOPES)},
        metrics={
            "tool_count": {"unit": "tools", "n": 1, "median": len(tools), "min": len(tools), "max": len(tools), "stdev": 0.0},
            "read_only_tool_count": {"unit": "tools", "n": 1, "median": read_only, "min": read_only, "max": read_only, "stdev": 0.0},
            "write_capable_tool_count": {"unit": "tools", "n": 1, "median": len(writes), "min": len(writes), "max": len(writes), "stdev": 0.0},
        },
        runs=tools,
        notes=["Counted from the code registry only. No Slack workspace was contacted, so tool behavior, rate limits, and scope grants on a real workspace are untested.", f"Write-capable tools: {', '.join(writes)}."],
    )
    print(f"wrote {write_result(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
