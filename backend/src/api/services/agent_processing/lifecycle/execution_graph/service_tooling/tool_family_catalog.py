"""Tool-family catalog for staged agent tool exposure.

The catalog reduces the initial bound tool surface without replacing any
tool's exact execution contract. The model first sees a small loader tool,
then the executor is rebuilt with the full schemas for the selected families.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Sequence, Set

from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from .tool_input_normalization import normalize_structured_tool_args_schema


@dataclass(frozen=True)
class ToolFamilyDefinition:
    """Compact metadata for a stable group of exact tools."""

    name: str
    purpose: str
    when_to_load: str
    tool_names: tuple[str, ...] = ()
    tool_prefixes: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    routing_hints: tuple[str, ...] = ()
    risk_class: str = "normal"


@dataclass(frozen=True)
class FamilyLoadNormalization:
    """Structured interpretation of a staged family-load request."""

    requested_names: list[str]
    valid_families: list[str]
    mapped_families: list[str]
    invalid_names: list[str]
    name_mappings: dict[str, list[str]]

    @property
    def resolved_families(self) -> list[str]:
        return _dedupe_names([*self.valid_families, *self.mapped_families])


class LoadToolFamilyInput(BaseModel):
    """Input for selecting one or more full tool families."""

    family_names: List[str] = Field(
        description=(
            "One or more tool family names to load before doing work. "
            "Load every family likely needed for the task in one call."
        )
    )
    reason: str = Field(
        default="",
        description="Brief reason these families are needed for the user's task.",
    )


FAMILY_DEFINITIONS: tuple[ToolFamilyDefinition, ...] = (
    ToolFamilyDefinition(
        name="core",
        purpose="Always-available collaboration, tool-family loading, and skill catalog access.",
        when_to_load="Already present at startup; do not load unless repairing a mistaken unavailable-tool attempt.",
        tool_names=("load_tool_family", "request_user_input", "skill_search", "skill_load"),
        examples=("ask the user", "load a tool family", "search/load a saved skill"),
    ),
    ToolFamilyDefinition(
        name="file",
        purpose=(
            "Find, read, prepare, create, or modify local files and folders. This is the "
            "preferred tool for a plain local file/folder find-read-write -- reach for it "
            "before a raw shell command when it already covers the job."
        ),
        when_to_load="Load when the task mentions files, folders, documents, paths, attachments, or local artifacts.",
        tool_prefixes=("file_service_",),
        examples=("find a file", "work with a dropped folder", "prepare current document"),
        routing_hints=("local files/folders", "explicit paths", "document content", "plain-text writes"),
        risk_class="local file mutations possible",
    ),
    ToolFamilyDefinition(
        name="email",
        purpose="Search, read, organize, or draft email through configured email clients.",
        when_to_load="Load when the task involves mailboxes, messages, inbox triage, drafts, or email sending.",
        tool_prefixes=("email_service_",),
        examples=("summarize inbox", "draft reply", "organize messages"),
        routing_hints=("mailboxes", "messages", "threads", "drafts"),
        risk_class="user-visible writes possible",
    ),
    ToolFamilyDefinition(
        name="browser",
        purpose="Inspect tabs/pages, click, fill, select, navigate, highlight targets, or capture browser screenshots.",
        when_to_load="Load for website/page interaction when no connected external-service tool applies, or when the user explicitly needs browser UI work.",
        tool_prefixes=("browser_",),
        tool_names=("analyze_with_vision",),
        examples=("use Amazon", "fill a web form", "inspect current browser page"),
        routing_hints=("ordinary websites", "DOM/page interaction", "forms", "not configured service records"),
        risk_class="user-visible web actions",
    ),
    ToolFamilyDefinition(
        name="vision",
        purpose="Analyze screenshots and image files with model vision when text/DOM tools are insufficient.",
        when_to_load="Load when the task depends on screenshot/image understanding or browser DOM inspection is insufficient.",
        tool_names=("analyze_with_vision",),
        examples=("inspect a screenshot", "understand an image", "read a visual target"),
        risk_class="image content analysis",
    ),
    ToolFamilyDefinition(
        name="shell",
        purpose="Run deterministic non-interactive command-line work; also the universal last-resort scripting floor (bash/zsh/Python) when specialized tools cannot do what the task needs.",
        when_to_load="Always available. Use for bounded CLI/tests/repo work AND as a fallback whenever a specialized tool is missing, refuses, or cannot perform a needed sub-step. Do not conclude a task is impossible before attempting it here.",
        tool_prefixes=("shell_service_",),
        examples=("run tests", "inspect git status", "call a CLI", "script a step no specialized tool covers"),
        routing_hints=("bounded CLI", "tests", "repo inspection", "scripts", "last-resort scripting"),
        risk_class="approval-gated mutations possible",
    ),
    ToolFamilyDefinition(
        name="automation",
        purpose="Drive macOS apps and inspect app/system state through AppleScript; the universal last-resort scripting floor when specialized tools cannot do (or cannot fully do) what the task needs.",
        when_to_load="Always available. Use for native macOS app control AND as the fallback whenever a specialized tool is missing, refuses, or cannot perform a needed sub-step (for example, reading raw email headers). Do not conclude a task is impossible before attempting it here.",
        tool_prefixes=("applescript_service_",),
        examples=("control TextEdit", "use app menus", "inspect raw email headers", "automate a native app"),
        risk_class="foreground app control",
    ),
    ToolFamilyDefinition(
        name="external",
        purpose="Use connected remote services and current web search.",
        when_to_load="Load when the request names a connected external service, account-backed remote data, or current open-web facts.",
        tool_names=("external_catalog", "web_search"),
        examples=("GitHub/Linear/Speakeasy connector", "current web facts"),
        routing_hints=("connected third-party services", "MCP connections", "account-backed external tools", "open web search"),
        risk_class="remote service access",
    ),
    ToolFamilyDefinition(
        name="provider",
        purpose="Inspect registered ACP coding-agent providers, record a grounded target proposal, authorize it against live authority, and resolve a focused target checkpoint without creating grants, launching a provider, delegating, or invoking MCP services.",
        when_to_load="Load when a task may benefit from delegated coding or repository work, when the user names a provider or workspace, or when phrases such as 'this project' require grounded current-context discovery.",
        tool_names=("provider_catalog",),
        examples=("inspect eligible coding agents", "find an authorized repository workspace", "propose and authorize a grounded coding-agent target"),
        routing_hints=("ACP providers", "coding-agent delegation candidates", "authorized workspaces", "provider capabilities", "target authorization checkpoint"),
        risk_class="durable non-authorizing provider proposal and target authorization",
    ),
    ToolFamilyDefinition(
        name="delegation",
        purpose="Delegate independent bounded work to Basil-native child AgentTasks.",
        when_to_load="Load only when independent subproblems can safely run in parallel.",
        tool_names=("delegated_agent",),
        examples=("parallel independent file reviews", "bounded research subtask"),
        routing_hints=("internal subagents", "parallel work", "independent child tasks"),
        risk_class="durable child-task admission",
    ),
    ToolFamilyDefinition(
        name="memory",
        purpose="Read or search Basil working memory.",
        when_to_load="Load when remembered preferences, saved notes, or persistent Basil context are relevant.",
        tool_prefixes=("memory_",),
        examples=("remembered preferences", "saved user context"),
        routing_hints=("saved Basil memory", "remembered preferences", "persistent notes"),
    ),
    ToolFamilyDefinition(
        name="todos",
        purpose="Create, inspect, and manage durable Basil To-Dos, including scoped workspace notes and worker delegation.",
        when_to_load="Load when the user asks to capture, inspect, update, discuss, or delegate a Basil To-Do.",
        tool_names=(
            "create_todos",
            "list_todos",
            "inspect_todo",
            "append_todo_note",
            "delegate_todo_work",
        ),
        examples=("create a To-Do", "add a note to this To-Do", "delegate selected To-Do work"),
        routing_hints=("Basil To-Dos", "action items", "workspace notes", "To-Do delegation"),
        risk_class="durable To-Do mutations and worker admission",
    ),
    ToolFamilyDefinition(
        name="schedule",
        purpose="Create scheduled Basil agent tasks, wait briefly before checking something again, or come back to this task later with a durable follow-up check.",
        when_to_load="Load when Basil itself needs to run an agent task later or on a recurrence, when this task must wait for something to finish or change before checking again, or when this task should resume later (minutes to days) to re-check a result.",
        tool_names=(
            "create_scheduled_agent_task_from_prompt",
            "wait_before_checking_again",
            "schedule_agent_follow_up",
            "cancel_agent_follow_ups",
        ),
        examples=(
            "run this every morning",
            "schedule recurring agent work",
            "wait for a build to finish and check again",
            "check back on this in an hour",
        ),
        routing_hints=("future agent work", "waiting and re-checking", "follow-up checks", "recurring schedules"),
        risk_class="future tool execution",
    ),
    ToolFamilyDefinition(
        name="retrieval",
        purpose="Search, browse, aggregate, and retrieve detail from Basil's local historical records.",
        when_to_load="Already available at startup for historical facts, semantic recall, chronological reviews, and local-history aggregates.",
        tool_names=("retrieve_basil_history", "query_unified_history"),
        examples=("find prior client work", "what happened yesterday", "count failures by day"),
        routing_hints=("local history", "prior work", "semantic recall", "historical aggregates"),
    ),
    ToolFamilyDefinition(
        name="activity",
        purpose="Inspect raw screen-capture, app, and OCR evidence.",
        when_to_load="Load when the answer requires exact visible screen text or raw capture details.",
        tool_names=("query_activities",),
        examples=("what was I doing", "time in app", "screen context history"),
        routing_hints=("prior screen activity", "app usage history", "what was visible"),
    ),
    ToolFamilyDefinition(
        name="recall",
        purpose="Recall prior Agent Task turns, current screen context, and the Conversation that delegated this task.",
        when_to_load="Already available at startup; use recall_agent_tasks for earlier work in this Agent Task chain and recall_conversations for the bounded Conversation thread that delegated this task. Use retrieval for broader local-history search.",
        tool_names=("recall_agent_tasks", "recall_conversations"),
        examples=("what did I already do in this task", "what did the user say earlier in this conversation", "which file did I pick earlier"),
        routing_hints=("prior agent tasks", "delegating conversation", "current chain turns", "earlier results/files"),
    ),
    ToolFamilyDefinition(
        name="iterative",
        purpose="Track large or uncertain multi-item work with a durable ledger.",
        when_to_load="Load when work has many items, uncertain cardinality, repeated actions, or coverage risk.",
        tool_names=("iterative_work",),
        examples=("many emails", "large review set", "unknown item count"),
    ),
)


CORE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "request_user_input",
        "load_tool_family",
        # Keep skill discovery available exactly as before; this plan does not
        # change skill behavior.
        "skill_search",
        "skill_load",
    }
)

BASELINE_FALLBACK_FAMILY_NAMES: frozenset[str] = frozenset(
    {
        # Keep generic execution fallbacks available from the first executor
        # pass so the staged catalog cannot turn "no specialized family" into
        # an artificial hard stop. These are capability classes, not task-
        # specific heuristics: native app automation plus bounded shell access
        # covers AppleScript, bash, Python scripts, installed package probes,
        # and package-based implementation paths when specialized tools are
        # not the right fit.
        "automation",
        "shell",
        # recall_agent_tasks must be present from the first pass: the agent most
        # needs to re-read its own chain exactly when it has already lost the
        # thread and would not think to load a family to recover it. Without this,
        # the tool is bound to the graph but never rendered into the core surface,
        # so the model reports it "doesn't exist" (select_core_tools promotes only
        # CORE_TOOL_NAMES + tools whose family is in this set).
        "recall",
        "retrieval",
    }
)


def get_family_definitions() -> tuple[ToolFamilyDefinition, ...]:
    """Return stable family metadata in display order."""

    return FAMILY_DEFINITIONS


def get_family_names() -> list[str]:
    """Return all known family names."""

    return [family.name for family in FAMILY_DEFINITIONS]


def describe_tool_families() -> list[dict[str, Any]]:
    """Return compact JSON-safe family descriptions for the loader output."""
    connected_services = _connected_external_services_for_routing()
    descriptions: list[dict[str, Any]] = []
    for family in FAMILY_DEFINITIONS:
        description = {
            "name": family.name,
            "purpose": family.purpose,
            "when_to_load": _family_when_to_load(family, connected_services),
            "examples": list(family.examples),
            "routing_hints": list(family.routing_hints),
            "risk_class": family.risk_class,
        }
        if family.name == "external" and connected_services:
            description["connected_services"] = connected_services
        descriptions.append(description)
    return descriptions


def _connected_external_services_for_routing() -> list[str]:
    try:
        from api.services.agent_processing.tools.external_services.external_connection_inventory import (
            enabled_connection_routing_labels,
        )

        # Labels include the served system (e.g. "Speakeasy (Salesforce)") when
        # the captured MCP server name adds signal, so first-pass family routing
        # can recognize which connection serves a named system.
        return enabled_connection_routing_labels()
    except Exception:
        return []


def _family_when_to_load(family: ToolFamilyDefinition, connected_services: list[str]) -> str:
    if family.name != "external" or not connected_services:
        return family.when_to_load
    return (
        f"{family.when_to_load} Currently enabled external services: "
        f"{', '.join(connected_services)}. Load this family when the request names one of these services."
    )


def render_family_routing_catalog() -> str:
    """Render family-level routing metadata for the initial loader description."""
    lines = ["Available tool families for first-pass routing:"]
    for family in describe_tool_families():
        hints = ", ".join(family.get("routing_hints") or [])
        examples = ", ".join(family.get("examples") or [])
        connected = ""
        if family.get("connected_services"):
            connected = f"; connected services: {', '.join(family['connected_services'])}"
        lines.append(
            f"- {family['name']}: {family['purpose']} When to load: {family['when_to_load']}"
            f"{connected}; hints: {hints}; examples: {examples}"
        )
    return "\n".join(lines)


def _tool_name(tool_item: Any) -> str:
    return str(getattr(tool_item, "name", "") or "")


def family_for_tool_name(tool_name: str) -> str | None:
    """Return the family name that owns a tool name, if known."""

    family_names = family_names_for_tool_name(tool_name)
    return family_names[0] if family_names else None


def family_names_for_tool_name(tool_name: str) -> list[str]:
    """Return all family names that include a tool name."""

    family_names: list[str] = []
    for family in FAMILY_DEFINITIONS:
        if tool_name in family.tool_names:
            family_names.append(family.name)
            continue
        if any(tool_name.startswith(prefix) for prefix in family.tool_prefixes):
            family_names.append(family.name)
    return family_names


def _dedupe_names(names: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for name in names:
        normalized = str(name).strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def normalize_family_load_request(family_names: Iterable[str]) -> FamilyLoadNormalization:
    """Resolve staged-loader inputs against family names and owned Basil tool names."""
    requested = _dedupe_names(family_names)
    available_names = set(get_family_names())
    valid: list[str] = []
    mapped: list[str] = []
    invalid: list[str] = []
    mappings: dict[str, list[str]] = {}

    for requested_name in requested:
        if requested_name in available_names:
            valid.append(requested_name)
            continue

        owning_families = family_names_for_tool_name(requested_name)
        if owning_families:
            mappings[requested_name] = owning_families
            mapped.extend(owning_families)
            continue

        invalid.append(requested_name)

    return FamilyLoadNormalization(
        requested_names=requested,
        valid_families=_dedupe_names(valid),
        mapped_families=_dedupe_names(mapped),
        invalid_names=invalid,
        name_mappings=mappings,
    )


def select_core_tools(tools: Sequence[Any], loader_tool: Any) -> list[Any]:
    """Return the minimal initial tool surface."""

    selected: list[Any] = [loader_tool]
    for tool_item in tools:
        tool_name = _tool_name(tool_item)
        tool_families = set(family_names_for_tool_name(tool_name))
        if tool_name in CORE_TOOL_NAMES or tool_families.intersection(BASELINE_FALLBACK_FAMILY_NAMES):
            selected.append(tool_item)
    return _dedupe_tools(selected)


def select_tools_for_families(
    tools: Sequence[Any],
    family_names: Iterable[str],
    *,
    include_core_tools: bool = True,
    loader_tool: Any | None = None,
) -> list[Any]:
    """Select exact existing tools for loaded families."""

    requested: Set[str] = {str(name).strip().lower() for name in family_names if str(name).strip()}
    selected: list[Any] = []
    if include_core_tools:
        if loader_tool is not None:
            selected.append(loader_tool)
        for tool_item in tools:
            if _tool_name(tool_item) in CORE_TOOL_NAMES:
                selected.append(tool_item)

    for tool_item in tools:
        family_names = set(family_names_for_tool_name(_tool_name(tool_item)))
        if family_names.intersection(requested):
            selected.append(tool_item)

    return _dedupe_tools(selected)


def _dedupe_tools(tools: Sequence[Any]) -> list[Any]:
    seen: set[str] = set()
    deduped: list[Any] = []
    for tool_item in tools:
        name = _tool_name(tool_item)
        if not name or name in seen:
            continue
        seen.add(name)
        deduped.append(tool_item)
    return deduped


def create_load_tool_family_tool(
    all_tools: Sequence[Any],
    get_available_families: Callable[[], Iterable[str]] | None = None,
) -> StructuredTool:
    """Create the agent-visible loader for staged tool exposure."""

    async def _load_tool_family(family_names: List[str], reason: str = "") -> str:
        normalized = normalize_family_load_request(family_names)
        loaded_families = normalized.resolved_families

        tool_names_by_family: Dict[str, list[str]] = {}
        for family_name in loaded_families:
            family_tools = select_tools_for_families(
                all_tools,
                [family_name],
                include_core_tools=False,
            )
            tool_names_by_family[family_name] = [_tool_name(tool_item) for tool_item in family_tools]

        available_families = {
            str(name).strip().lower()
            for name in (get_available_families() if get_available_families else [])
            if str(name).strip()
        }
        already_available = [f for f in loaded_families if f in available_families]
        newly_loaded = [f for f in loaded_families if f not in available_families]

        if not loaded_families:
            next_step = "Choose one or more names from available_families and call load_tool_family again."
        elif newly_loaded:
            next_step = (
                "The exact full schemas for loaded_families are available on your next step. "
                "Call those tools directly; do not call load_tool_family for these families again."
            )
        else:
            available_tool_names = sorted(
                {name for family in already_available for name in tool_names_by_family.get(family, [])}
            )
            next_step = (
                f"Families {already_available} are ALREADY available; their exact tools "
                f"({', '.join(available_tool_names)}) are bound right now. Call the appropriate tool directly to do the work. Do NOT call load_tool_family for these families again."
            )

        return json.dumps(
            {
                "success": bool(loaded_families) and not normalized.invalid_names,
                "loaded_families": loaded_families,
                "newly_loaded_families": newly_loaded,
                "already_available_families": already_available,
                "invalid_families": normalized.invalid_names,
                "reason": reason,
                "requested_family_inputs": normalized.requested_names,
                "mapped_family_inputs": normalized.name_mappings,
                "suggested_families": loaded_families,
                "available_families": describe_tool_families(),
                "tool_names_by_family": tool_names_by_family,
                "next_step": next_step,
            },
            ensure_ascii=False,
        )

    loader_tool = StructuredTool.from_function(
        func=_load_tool_family,
        coroutine=_load_tool_family,
        name="load_tool_family",
        description=(
            "Load exact full tool schemas for one or more needed tool families before doing work. Use this first when the task needs files, email, browser, shell, automation, external services, memory, scheduling, activity history, or iterative tracking.\n\n"
            + render_family_routing_catalog()
        ),
        args_schema=LoadToolFamilyInput,
    )
    return normalize_structured_tool_args_schema(loader_tool)


def extract_loaded_families_from_steps(intermediate_steps: Sequence[Any]) -> list[str]:
    """Parse load_tool_family observations from LangChain intermediate steps."""

    loaded: list[str] = []
    for step in intermediate_steps or []:
        if not isinstance(step, tuple) or len(step) < 2:
            continue
        action, observation = step[0], step[1]
        if getattr(action, "tool", None) != "load_tool_family":
            continue
        try:
            data = json.loads(observation if isinstance(observation, str) else str(observation))
        except Exception:
            continue
        for family_name in data.get("loaded_families") or []:
            normalized = str(family_name).strip().lower()
            if normalized and normalized not in loaded:
                loaded.append(normalized)
    return loaded


def extract_suggested_families_from_loader_observation(
    intermediate_steps: Sequence[Any],
    loaded_families: Iterable[str] | None = None,
) -> list[str]:
    """Extract mapped/suggested families from staged-loader observations."""
    already_loaded = {
        str(family_name).strip().lower()
        for family_name in (loaded_families or [])
        if str(family_name).strip()
    }
    suggested: list[str] = []

    for step in intermediate_steps or []:
        if not isinstance(step, tuple) or len(step) < 2:
            continue
        action, observation = step[0], step[1]
        if getattr(action, "tool", None) != "load_tool_family":
            continue
        try:
            data = json.loads(observation if isinstance(observation, str) else str(observation))
        except Exception:
            continue

        candidates = []
        candidates.extend(data.get("suggested_families") or [])
        candidates.extend(data.get("loaded_families") or [])

        mappings = data.get("mapped_family_inputs") or {}
        if isinstance(mappings, dict):
            for mapped_values in mappings.values():
                if isinstance(mapped_values, list):
                    candidates.extend(mapped_values)

        for invalid_name in data.get("invalid_families") or []:
            candidates.extend(family_names_for_tool_name(str(invalid_name)))

        for family_name in _dedupe_names(candidates):
            if family_name in already_loaded or family_name in suggested:
                continue
            suggested.append(family_name)

    return suggested


def extract_repair_families_from_steps(
    intermediate_steps: Sequence[Any],
    loaded_families: Iterable[str] | None = None,
) -> list[str]:
    """Infer families to load after an unavailable-tool observation."""

    already_loaded = {
        str(family_name).strip().lower()
        for family_name in (loaded_families or [])
        if str(family_name).strip()
    }
    repairs: list[str] = []
    for step in intermediate_steps or []:
        if not isinstance(step, tuple) or len(step) < 2:
            continue
        action, observation = step[0], step[1]
        tool_name = str(getattr(action, "tool", "") or "")
        if not tool_name or tool_name == "load_tool_family":
            continue

        observation_text = observation if isinstance(observation, str) else str(observation)
        observation_lower = observation_text.lower()
        if (
            "not a valid tool" not in observation_lower
            and "invalid tool" not in observation_lower
            and "available tools" not in observation_lower
        ):
            continue

        for family_name in family_names_for_tool_name(tool_name):
            if family_name in already_loaded or family_name in repairs:
                continue
            repairs.append(family_name)

    return repairs
