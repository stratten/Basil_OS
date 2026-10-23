#!/usr/bin/env python3
"""Plan B.3 build-time telemetry smoke.

Compares the agent build surface (system prompt + tool descriptions +
tool args schemas, OR catalog preamble) under each of the three Plan B
rendering profiles, using a representative subset of the static-factory
tools (the ones whose factories don't require a live coordinator).

The output mirrors the ``[AgentTelemetry]`` lines emitted by
``_log_prompt_tool_surface_telemetry`` and serves as a build-time
proxy for the master-map "pinned telemetry" decision: if the
``slim_text_catalog`` build_chars_total is meaningfully smaller than
``slim_schema``, the Qwen registry default could move to that mode.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api.core.models.reasoning.model_runtime_profile import (  # noqa: E402
    TOOL_RENDERING_FULL_SCHEMA,
    TOOL_RENDERING_SLIM_SCHEMA,
    TOOL_RENDERING_SLIM_TEXT_CATALOG,
    RuntimeModelProfile,
)


def _make_profile(rendering: str) -> RuntimeModelProfile:
    return RuntimeModelProfile(
        model_id="plan-b-telemetry",
        registry_entry=None,
        provider=None,
        handler=None,
        tool_rendering=rendering,
    )


def _build_tools(profile: RuntimeModelProfile) -> List[Any]:
    # Static-factory tools that don't need a live coordinator. (Memory
    # and skill tool factories construct their service singletons at
    # call time, so we exclude them from this build-time slice; the
    # dynamic email/file/applescript/shell tools also need a live
    # service instance and are excluded for the same reason. The build
    # numbers are therefore a *floor* on the real savings.)
    from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import (
        create_checkpoint_tool,
    )
    from api.services.agent_processing.tools.external_services.external_catalog_tool import (
        create_external_catalog_tool,
    )
    from api.services.agent_processing.tools.internal_basil_tools.iterative_work_tool import (
        create_iterative_work_tool,
    )
    from api.services.agent_processing.tools.internal_basil_tools.activity_query_tool import (
        create_activity_query_tool,
    )
    from api.services.agent_processing.tools.external_services.web_search_tool import (
        create_web_search_tool,
    )
    from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_inspect_tool import (
        create_browser_inspect_tool,
    )
    from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_interact_tool import (
        create_browser_interact_tool,
    )
    from api.services.agent_processing.tools.internal_basil_tools.scheduled_agent_task_tool import (
        create_scheduled_agent_task_tool,
    )

    return [
        create_checkpoint_tool(profile=profile),
        create_external_catalog_tool(profile=profile),
        create_iterative_work_tool(profile=profile),
        create_activity_query_tool(profile=profile),
        create_web_search_tool(profile=profile),
        create_browser_inspect_tool(profile=profile),
        create_browser_interact_tool(profile=profile),
        create_scheduled_agent_task_tool(profile=profile),
    ]


def _schema_for(tool: Any) -> str:
    schema_obj = getattr(tool, "args_schema", None)
    if schema_obj is None:
        return ""
    try:
        schema = schema_obj.model_json_schema()
        schema.pop("title", None)
        return json.dumps(schema, separators=(",", ":"))
    except Exception:
        return ""


def _summarize(label: str, tools: List[Any], system_prompt_chars: int) -> dict:
    desc_total = 0
    schema_total = 0
    for t in tools:
        desc_total += len(getattr(t, "description", "") or "")
        schema_total += len(_schema_for(t))
    return {
        "label": label,
        "tool_count": len(tools),
        "desc_total_chars": desc_total,
        "schema_total_chars": schema_total,
        "build_chars_total": system_prompt_chars + desc_total + schema_total,
    }


def main() -> int:
    # System prompt is profile-independent at build time; we approximate
    # it with a fixed length so the deltas across rendering modes
    # reflect ONLY the tool surface change.
    from api.services.agent_processing.lifecycle.execution_graph.system_prompts import (
        get_agent_system_prompt,
    )
    system_prompt = get_agent_system_prompt(user_profile_context="")
    system_prompt_chars = len(system_prompt)

    print(f"system_prompt_chars={system_prompt_chars}")

    full_profile = _make_profile(TOOL_RENDERING_FULL_SCHEMA)
    slim_profile = _make_profile(TOOL_RENDERING_SLIM_SCHEMA)
    catalog_profile = _make_profile(TOOL_RENDERING_SLIM_TEXT_CATALOG)

    full_tools = _build_tools(full_profile)
    slim_tools = _build_tools(slim_profile)
    catalog_tools = _build_tools(catalog_profile)

    full_summary = _summarize("full_schema", full_tools, system_prompt_chars)
    slim_summary = _summarize("slim_schema", slim_tools, system_prompt_chars)
    catalog_summary = _summarize("slim_text_catalog", catalog_tools, system_prompt_chars)

    # For slim_text_catalog the on-the-wire surface is the catalog
    # preamble, NOT desc+schema. Rebuild build_chars_total accordingly.
    from api.services.agent_processing.lifecycle.execution_graph.slim_catalog_renderer import (
        render_slim_catalog_preamble,
    )
    catalog_preamble = render_slim_catalog_preamble(catalog_tools)
    catalog_summary["catalog_chars"] = len(catalog_preamble)
    catalog_summary["build_chars_total"] = system_prompt_chars + len(catalog_preamble)

    headers = (
        "label",
        "tool_count",
        "desc_total_chars",
        "schema_total_chars",
        "catalog_chars",
        "build_chars_total",
        "build_tokens_est",
    )
    rows = []
    for s in (full_summary, slim_summary, catalog_summary):
        s.setdefault("catalog_chars", "-")
        s["build_tokens_est"] = s["build_chars_total"] // 4
        rows.append(s)

    col_widths = {h: max(len(h), max(len(str(r[h])) for r in rows)) for h in headers}
    sep = "  "
    print(sep.join(h.ljust(col_widths[h]) for h in headers))
    for r in rows:
        print(sep.join(str(r[h]).ljust(col_widths[h]) for h in headers))

    full_total = full_summary["build_chars_total"]
    slim_total = slim_summary["build_chars_total"]
    catalog_total = catalog_summary["build_chars_total"]

    print()
    print(
        f"slim_schema vs full_schema: {full_total - slim_total} chars saved "
        f"({100.0 * (full_total - slim_total) / full_total:.1f}% reduction)"
    )
    print(
        f"slim_text_catalog vs full_schema: {full_total - catalog_total} chars saved "
        f"({100.0 * (full_total - catalog_total) / full_total:.1f}% reduction)"
    )
    print(
        f"slim_text_catalog vs slim_schema: {slim_total - catalog_total} chars saved "
        f"({100.0 * (slim_total - catalog_total) / slim_total:.1f}% reduction)"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
