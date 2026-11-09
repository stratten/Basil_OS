"""Every mutating route has a decided relationship to agent control, and the deferred set can only shrink."""

from collections import Counter

import pytest
from fastapi import FastAPI

from api.services.app_control.route_classification import (
    DEFERRED,
    DEFERRED_BASELINE,
    DISPOSITIONS,
    EXISTING_TOOL,
    MUTATING_METHODS,
    ROUTE_RULES,
    classify_route,
)


@pytest.fixture(scope="module")
def mutating_routes():
    from api.routes.registry import build_ordered_application_routers

    app = FastAPI()
    for router in build_ordered_application_routers():
        app.include_router(router)
    found = []
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            if method.upper() in MUTATING_METHODS:
                found.append((method.upper(), path))
    assert len(found) > 200, "the route table looks incomplete"
    return found


def test_every_mutating_route_is_classified(mutating_routes):
    unclassified = [f"{method} {path}" for method, path in mutating_routes if classify_route(method, path) is None]
    assert not unclassified, "Decide how an agent relates to these routes by adding a rule in app_control/route_classification.py:\n" + "\n".join(unclassified)


def test_no_rule_is_dead(mutating_routes):
    reached = {id(classify_route(method, path)) for method, path in mutating_routes}
    dead = [rule.pattern for rule in ROUTE_RULES if id(rule) not in reached]
    assert not dead, f"These rules are shadowed by earlier rules or match no route: {dead}"


def test_rules_are_well_formed():
    for rule in ROUTE_RULES:
        assert rule.disposition in DISPOSITIONS
        assert rule.reason.strip()
        if rule.disposition == DEFERRED:
            assert rule.domain
        assert (rule.disposition == EXISTING_TOOL) == bool(rule.tool)


def test_existing_tool_rules_name_a_tool_that_exists():
    from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_family_catalog import CORE_TOOL_NAMES, FAMILY_DEFINITIONS

    known = set(CORE_TOOL_NAMES) | {name for family in FAMILY_DEFINITIONS for name in family.tool_names}
    for rule in ROUTE_RULES:
        if rule.disposition == EXISTING_TOOL:
            assert rule.tool in known, f"{rule.pattern} names an unknown tool {rule.tool}"


def test_deferred_routes_match_the_baseline_and_can_only_shrink(mutating_routes):
    counts = Counter()
    for method, path in mutating_routes:
        rule = classify_route(method, path)
        if rule is not None and rule.disposition == DEFERRED:
            counts[rule.domain] += 1
    grown = {domain: count for domain, count in counts.items() if count > DEFERRED_BASELINE.get(domain, 0)}
    assert not grown, f"Deferred routes grew in {grown}. Decide the new routes (a rule other than deferred) instead of raising the baseline."
    shrunk = {domain: count for domain, count in counts.items() if count < DEFERRED_BASELINE.get(domain, 0)}
    assert not shrunk, f"Lower DEFERRED_BASELINE to {shrunk} so the gain cannot be lost."


def test_the_credential_and_approval_routes_are_never_deferred_or_registry(mutating_routes):
    sensitive_words = ("api_keys", "/auth", "oauth", "manual_token", "whitelist", "approval", "workspace-grants", "sensitive")
    for method, path in mutating_routes:
        if any(word in path for word in sensitive_words):
            rule = classify_route(method, path)
            assert rule.disposition not in {DEFERRED, "registry"}, f"{method} {path} is {rule.disposition}"
