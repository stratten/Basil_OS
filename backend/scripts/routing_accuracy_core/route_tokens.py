"""Pure routing logic: turn ordered work-ledger receipts into route tokens and score them against a case's expectation.

A route token names one routing decision the model made.
  load:<family>                      one family named in a load_tool_family call
  ext:<action>                       an external_catalog call (list_servers, describe_server, call_tool)
  ext:call_tool@<connection_id>      the same call, with the connection it targeted
  tool:<method>                      any other direct tool (web_search, retrieve_basil_history, ...)
  svc:<service>.<method>             a service tool (shell_service.execute_command, file_service.read_text_file, ...)

Only the first ``window_size`` substantive receipts are scored, because routing is the model's first few choices and later calls depend on tool results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any, Callable, Iterable, Optional

DEFAULT_WINDOW_SIZE = 4

# Bookkeeping tools that say nothing about routing, so they neither count toward the window nor produce tokens.
IGNORED_DIRECT_TOOLS = frozenset({"checklist", "checklist_notes", "skill_search", "skill_load"})

PASS = "PASS"
PASS_ALT = "PASS_ALT"
FAIL = "FAIL"
INCOMPLETE = "INCOMPLETE"
VERDICTS = (PASS, PASS_ALT, FAIL, INCOMPLETE)


@dataclass(frozen=True)
class Receipt:
    """One ledger row, reduced to what routing needs."""

    service: str
    method: str
    parameters: dict[str, Any] = field(default_factory=dict)
    implied: bool = False


@dataclass(frozen=True)
class RoutingExpectation:
    """What a correct route looks like for one prompt.

    ``preferred`` and ``acceptable`` are alternatives; an alternative is satisfied when every one of its token patterns matches some token in the window.
    ``forbidden`` patterns fail the case when any token in the window matches.
    ``expect_no_tools`` is for prompts the model should answer directly, and fails the case if it uses any tool.
    ``answerable_from_context`` is for prompts whose answer is already in the model's prompt (for example the connected-service inventory), so using the preferred tool still passes and answering without any tool also passes.
    Scoring checks the route only, never whether the answer is correct; the evidence snapshot keeps the answer for that.
    """

    preferred: tuple[frozenset[str], ...] = ()
    acceptable: tuple[frozenset[str], ...] = ()
    forbidden: tuple[str, ...] = ()
    expect_no_tools: bool = False
    answerable_from_context: bool = False


@dataclass(frozen=True)
class RoutingVerdict:
    verdict: str
    reason: str
    route: tuple[str, ...]
    first_call: tuple[str, ...]
    load_calls: int
    substantive_calls: int
    forbidden_hits: tuple[str, ...] = ()


def is_substantive(receipt: Receipt) -> bool:
    return not (receipt.service == "direct_tool" and receipt.method in IGNORED_DIRECT_TOOLS)


def _family_names(parameters: dict[str, Any]) -> list[str]:
    raw = parameters.get("family_names")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(name).strip().lower() for name in raw if str(name).strip()]


def tokens_for(receipt: Receipt) -> tuple[str, ...]:
    """The route tokens one receipt contributes, in a stable order."""
    if receipt.service == "direct_tool":
        if receipt.method == "load_tool_family":
            return tuple(f"load:{name}" for name in _family_names(receipt.parameters))
        if receipt.method == "external_catalog":
            action = str(receipt.parameters.get("action") or "unknown").strip().lower()
            tokens = [f"ext:{action}"]
            connection_id = str(receipt.parameters.get("connection_id") or "").strip()
            if connection_id:
                tokens.append(f"ext:{action}@{connection_id}")
            return tuple(tokens)
        return (f"tool:{receipt.method}",)
    return (f"svc:{receipt.service}.{receipt.method}",)


def receipt_from_pending_approval(approval: dict[str, Any]) -> Receipt:
    """The call a pending approval card stands for.

    A gated call leaves no ledger receipt until its approval resolves, but the card already names what the model asked for, which is the routing decision.
    Shell and AppleScript cards map to their service tools; any other card kind becomes ``svc:approval.<execution_type>``.
    """
    execution_type = str(approval.get("execution_type") or "shell").strip().lower()
    command = str(approval.get("command") or "")
    if execution_type == "shell":
        return Receipt("shell_service", "execute_command", {"command": command})
    if execution_type == "applescript":
        return Receipt("applescript_service", "execute_applescript", {"command": command})
    return Receipt("approval", execution_type, {"command": command})


def _tool_name_for(receipt: Receipt) -> str:
    return receipt.method if receipt.service == "direct_tool" else f"{receipt.service}_{receipt.method}"


def _default_family_resolver() -> Optional[Callable[[str], list[str]]]:
    """The backend's tool-name to family mapping, or None when the backend source is not importable."""
    try:
        from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_family_catalog import (
            BASELINE_FALLBACK_FAMILY_NAMES,
            family_names_for_tool_name,
        )
    except ImportError:
        return None
    always_bound = {*BASELINE_FALLBACK_FAMILY_NAMES, "core"}
    return lambda tool_name: [family for family in family_names_for_tool_name(tool_name) if family not in always_bound]


def with_implied_loads(receipts: Iterable[Receipt], family_resolver: Optional[Callable[[str], list[str]]] = None) -> list[Receipt]:
    """Insert a ``load:<family>`` receipt before a direct call to a tool whose family was not yet loaded.

    The tool index lets the model call any tool directly, and Basil loads that tool's family on the spot (call-through).
    That is the same routing decision as a load_tool_family call followed by the tool, so it scores as both.
    The inserted receipts are marked ``implied`` and never count toward the scoring window.
    Families that are bound from the first step (shell, automation, retrieval, recall, follow_up, core) never produce an implied load.
    """
    resolver = family_resolver or _default_family_resolver()
    if resolver is None:
        return list(receipts)
    loaded: set[str] = set()
    expanded: list[Receipt] = []
    for receipt in receipts:
        if not is_substantive(receipt):
            expanded.append(receipt)
            continue
        if receipt.service == "direct_tool" and receipt.method == "load_tool_family":
            loaded.update(_family_names(receipt.parameters))
        else:
            for family in resolver(_tool_name_for(receipt)):
                if family not in loaded:
                    loaded.add(family)
                    expanded.append(Receipt("direct_tool", "load_tool_family", {"family_names": [family]}, implied=True))
        expanded.append(receipt)
    return expanded


def substantive_window(receipts: Iterable[Receipt], window_size: int = DEFAULT_WINDOW_SIZE) -> list[Receipt]:
    """The first ``window_size`` substantive receipts, in ledger order.

    Implied loads travel with the call that caused them and do not use up a window slot.
    """
    window: list[Receipt] = []
    counted = 0
    for receipt in receipts:
        if not is_substantive(receipt):
            continue
        window.append(receipt)
        if not receipt.implied:
            counted += 1
        if counted >= window_size:
            break
    return window


def _matches(pattern: str, tokens: Iterable[str]) -> bool:
    return any(fnmatchcase(token, pattern) for token in tokens)


def _satisfied(alternatives: tuple[frozenset[str], ...], tokens: list[str]) -> Optional[frozenset[str]]:
    for alternative in alternatives:
        if alternative and all(_matches(pattern, tokens) for pattern in alternative):
            return alternative
    return None


def score_route(
    expectation: RoutingExpectation,
    receipts: Iterable[Receipt],
    run_finished: bool,
    window_size: int = DEFAULT_WINDOW_SIZE,
) -> RoutingVerdict:
    """Score the first routing decisions of one run.

    ``run_finished`` says the task reached a terminal state, so a short window is all the routing there will ever be.
    """
    window = substantive_window(with_implied_loads(receipts), window_size)
    per_call: list[tuple[str, ...]] = []
    carried: tuple[str, ...] = ()
    for receipt in window:
        if receipt.implied:
            carried += tokens_for(receipt)
            continue
        per_call.append(carried + tokens_for(receipt))
        carried = ()
    tokens = [token for call in per_call for token in call]
    route = tuple(tokens)
    first_call = per_call[0] if per_call else ()
    load_calls = sum(1 for receipt in window if receipt.service == "direct_tool" and receipt.method == "load_tool_family" and not receipt.implied)
    window_full = sum(1 for receipt in window if not receipt.implied) >= window_size
    complete = window_full or run_finished

    def verdict(label: str, reason: str, hits: tuple[str, ...] = ()) -> RoutingVerdict:
        return RoutingVerdict(label, reason, route, first_call, load_calls, sum(1 for receipt in window if not receipt.implied), hits)

    if expectation.expect_no_tools:
        if window:
            return verdict(FAIL, "the model used tools for a prompt it should answer directly", tuple(route))
        return verdict(PASS, "answered directly") if run_finished else verdict(INCOMPLETE, "no answer yet")

    hits = tuple(pattern for pattern in expectation.forbidden if _matches(pattern, tokens))
    if hits:
        return verdict(FAIL, "forbidden route taken: " + ", ".join(hits), hits)
    if _satisfied(expectation.preferred, tokens) is not None:
        return verdict(PASS, "preferred route")
    if _satisfied(expectation.acceptable, tokens) is not None:
        return verdict(PASS_ALT, "acceptable but not preferred route")
    if not complete:
        return verdict(INCOMPLETE, "the run had not finished and the routing window was not yet full")
    if not window and expectation.answerable_from_context:
        return verdict(PASS, "answered from the context already in the prompt")
    if not window:
        return verdict(FAIL, "the model answered without using any tool")
    return verdict(FAIL, "no preferred or acceptable route in the first calls")
