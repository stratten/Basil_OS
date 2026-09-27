#!/usr/bin/env python3
"""Plan B coverage smoke: every bound tool ships a hand-authored slim form.

This script drives the construction layer with a synthetic slim
``RuntimeModelProfile`` (``tool_rendering="slim_schema"``) and, for every
tool the agent can bind, asserts that the description that comes back is
distinct from the full form. It exercises:

  * Static factories for ``request_user_input``, ``external_catalog``,
    ``iterative_work``, ``query_activities``, ``web_search``,
    ``browser_inspect``, ``browser_interact``, ``memory_read``,
    ``memory_search``, ``skill_search``, ``skill_load``,
    ``create_scheduled_agent_task_from_prompt``, ``analyze_with_vision``.
  * The dynamic services that own ``slim_doc`` companions:
    ``email_service``, ``file_service``, ``applescript_service``,
    ``shell_service``.

The finalizer is exercised separately via its own description constant
(it depends on coordinator state and is not safely instantiable here).

A nonzero exit means a slim companion is missing or wired wrong, and the
slim profile would silently fall back to the full description in
production.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api.core.models.reasoning.model_runtime_profile import (  # noqa: E402
    TOOL_RENDERING_FULL_SCHEMA,
    TOOL_RENDERING_SLIM_SCHEMA,
    RuntimeModelProfile,
)


def _make_profile(tool_rendering: str) -> RuntimeModelProfile:
    return RuntimeModelProfile(
        model_id="plan-b-smoke",
        registry_entry=None,
        provider=None,
        handler=None,
        tool_rendering=tool_rendering,
    )


# Captured for the aggregate savings line at end of main().
_COLLECTED: List[Tuple[str, str, str]] = []


def _check(label: str, full: str, slim: str, errors: List[str]) -> None:
    if not slim:
        errors.append(f"{label}: slim description is empty")
        return
    if slim == full:
        errors.append(f"{label}: slim description matches full description (no slimming)")
        return
    _COLLECTED.append((label, full, slim))
    print(f"  OK  {label}: full={len(full)} chars, slim={len(slim)} chars")


def _check_static_factory(
    label: str,
    create_fn,
    errors: List[str],
    *,
    factory_args: Tuple = (),
    factory_kwargs: Dict[str, Any] | None = None,
) -> None:
    factory_kwargs = factory_kwargs or {}
    full_profile = _make_profile(TOOL_RENDERING_FULL_SCHEMA)
    slim_profile = _make_profile(TOOL_RENDERING_SLIM_SCHEMA)
    try:
        full_tool = create_fn(*factory_args, profile=full_profile, **factory_kwargs)
        slim_tool = create_fn(*factory_args, profile=slim_profile, **factory_kwargs)
    except Exception as exc:
        errors.append(f"{label}: factory raised {type(exc).__name__}: {exc}")
        return

    if isinstance(full_tool, list) and isinstance(slim_tool, list):
        if len(full_tool) != len(slim_tool):
            errors.append(f"{label}: factory returned different counts under full vs slim")
            return
        for idx, (full_t, slim_t) in enumerate(zip(full_tool, slim_tool)):
            _check(
                f"{label}[{idx}:{getattr(full_t, 'name', '?')}]",
                getattr(full_t, "description", "") or "",
                getattr(slim_t, "description", "") or "",
                errors,
            )
        return

    _check(
        label,
        getattr(full_tool, "description", "") or "",
        getattr(slim_tool, "description", "") or "",
        errors,
    )


def _check_dynamic_service(
    label: str,
    capabilities: Dict[str, Any],
    errors: List[str],
) -> None:
    # Three shapes are emitted by the agent's services and ServiceToolFactory
    # already accepts all three (see service_tools.py):
    #   (a) ``methods`` as a ``Dict[method_name, info_dict]``
    #       (email_service, shell_service)
    #   (b) ``methods`` as a ``List[info_dict]`` where each entry has a
    #       ``name`` key (file_service)
    #   (c) ``supported_methods`` as a ``Dict[method_name, info_dict]``
    #       (applescript_service)
    methods = capabilities.get("methods") or capabilities.get("supported_methods")
    if not methods:
        errors.append(f"{label}: no methods reported")
        return
    if isinstance(methods, dict):
        items = methods.items()
    elif isinstance(methods, list):
        items = ((m.get("name", "?"), m) for m in methods if isinstance(m, dict))
    else:
        errors.append(f"{label}: unexpected methods shape {type(methods).__name__}")
        return

    for method_name, info in items:
        # ``doc`` is the canonical field for static intro; ``description``
        # is the file_service shorthand. Either may be present alongside
        # the slim_doc; we only care that slim_doc is authored.
        full_doc = (info.get("doc") or info.get("description") or "").strip()
        slim_doc = (info.get("slim_doc") or "").strip()
        if not slim_doc:
            errors.append(f"{label}.{method_name}: slim_doc missing or empty")
            continue
        if full_doc and slim_doc == full_doc:
            errors.append(f"{label}.{method_name}: slim_doc identical to full doc (no slimming)")
            continue
        _COLLECTED.append((f"{label}.{method_name}", full_doc, slim_doc))
        print(f"  OK  {label}.{method_name}: doc={len(full_doc)}, slim_doc={len(slim_doc)}")


def main() -> int:
    errors: List[str] = []

    print("== static-factory tools ==")

    from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import (
        create_checkpoint_tool,
    )
    _check_static_factory("request_user_input", create_checkpoint_tool, errors)

    from api.services.agent_processing.tools.external_services.external_catalog_tool import (
        create_external_catalog_tool,
    )
    _check_static_factory("external_catalog", create_external_catalog_tool, errors)

    from api.services.agent_processing.tools.internal_basil_tools.iterative_work_tool import (
        create_iterative_work_tool,
    )
    _check_static_factory("iterative_work", create_iterative_work_tool, errors)

    from api.services.agent_processing.tools.internal_basil_tools.activity_query_tool import (
        create_activity_query_tool,
    )
    _check_static_factory("query_activities", create_activity_query_tool, errors)

    from api.services.agent_processing.tools.external_services.web_search_tool import (
        create_web_search_tool,
    )
    _check_static_factory("web_search", create_web_search_tool, errors)

    from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_inspect_tool import (
        create_browser_inspect_tool,
    )
    _check_static_factory("browser_inspect", create_browser_inspect_tool, errors)

    from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_interact_tool import (
        create_browser_interact_tool,
    )
    _check_static_factory("browser_interact", create_browser_interact_tool, errors)

    from api.services.agent_processing.lifecycle.execution_graph.service_tooling.memory_tools import (
        create_memory_tools,
    )
    _check_static_factory("memory_tools", create_memory_tools, errors)

    from api.services.agent_processing.lifecycle.execution_graph.service_tooling.skill_tools import (
        create_skill_tools,
    )
    _check_static_factory("skill_tools", create_skill_tools, errors)

    from api.services.agent_processing.tools.internal_basil_tools.scheduled_agent_task_tool import (
        create_scheduled_agent_task_tool,
    )
    _check_static_factory(
        "create_scheduled_agent_task_from_prompt",
        create_scheduled_agent_task_tool,
        errors,
    )

    print("== finalizer (constant check) ==")
    from api.services.agent_processing.lifecycle.execution_graph.agent_executor_factory import (
        FINALIZER_SLIM_DESCRIPTION,
    )
    if not FINALIZER_SLIM_DESCRIPTION or len(FINALIZER_SLIM_DESCRIPTION) < 80:
        errors.append("finalize_agent_task_result: FINALIZER_SLIM_DESCRIPTION missing or too short")
    else:
        print(f"  OK  finalize_agent_task_result: slim={len(FINALIZER_SLIM_DESCRIPTION)} chars")

    print("== analyze_with_vision (constant check) ==")
    from api.services.agent_processing.tools.internal_basil_tools.vision_analysis_tool import (
        SLIM_DESCRIPTION as VISION_SLIM,
    )
    if not VISION_SLIM or len(VISION_SLIM) < 80:
        errors.append("analyze_with_vision: SLIM_DESCRIPTION missing or too short")
    else:
        print(f"  OK  analyze_with_vision: slim={len(VISION_SLIM)} chars")

    print("== dynamic services ==")

    # email_service: 14 hand-authored slim_doc entries live in
    # _SLIM_DOCS_BY_METHOD (build_service_capabilities reads them at
    # runtime). We verify the dict directly so the smoke check never has
    # to construct a real EmailClientService.
    from api.services.agent_processing.tools.direct_application_interactions.email_integration import (
        email_service_capabilities as email_caps,
    )
    email_methods = [
        'get_emails', 'get_email_metadata', 'expand_email_details',
        'process_email_request', 'organize_emails', 'search_emails',
        'get_folders', 'create_folder', 'bulk_organize_emails',
        'create_email_draft', 'get_inbox_emails', 'reply_to_email',
        'create_new_email_draft', 'create_reply_email_draft',
    ]
    slim_docs = getattr(email_caps, "_SLIM_DOCS_BY_METHOD", {})
    if not isinstance(slim_docs, dict) or not slim_docs:
        errors.append("email_service: _SLIM_DOCS_BY_METHOD missing or empty")
    else:
        for method_name in email_methods:
            slim = (slim_docs.get(method_name) or "").strip()
            if not slim:
                errors.append(f"email_service.{method_name}: slim_doc missing or empty")
                continue
            _COLLECTED.append((f"email_service.{method_name}", "", slim))
            print(f"  OK  email_service.{method_name}: slim={len(slim)} chars")

    # file_service / applescript_service / shell_service: each holds its
    # slim_doc inline inside ``get_service_capabilities`` and is safe to
    # construct without external dependencies.
    from api.services.agent_processing.tools.direct_application_interactions.file_system.file_system_service import (
        FileSystemService,
    )
    _check_dynamic_service(
        "file_service",
        FileSystemService().get_service_capabilities(),
        errors,
    )

    from api.services.agent_processing.tools.direct_application_interactions.applescript_automation.generic_applescript_service import (
        GenericAppleScriptService,
    )
    _check_dynamic_service(
        "applescript_service",
        GenericAppleScriptService().get_service_capabilities(),
        errors,
    )

    from api.services.agent_processing.tools.direct_application_interactions.shell.shell_service import (
        ShellService,
    )
    _check_dynamic_service(
        "shell_service",
        ShellService().get_service_capabilities(),
        errors,
    )

    print()
    if errors:
        print(f"FAILED: {len(errors)} issue(s):")
        for err in errors:
            print(f"  - {err}")
        return 1

    # Aggregate description-character savings so the smoke output doubles
    # as a build-time telemetry pin for the master map.
    full_total = 0
    slim_total = 0
    for label, full, slim in _COLLECTED:
        full_total += len(full)
        slim_total += len(slim)
    if full_total:
        delta = full_total - slim_total
        pct = (100.0 * delta / full_total) if full_total else 0.0
        print(
            "Description-text savings (static-factory tools + dynamic methods): "
            f"full_total_chars={full_total} slim_total_chars={slim_total} "
            f"delta={delta} ({pct:.1f}% reduction)"
        )

    print("PASS: all bound tools emit hand-authored slim companions under slim_schema profile.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
