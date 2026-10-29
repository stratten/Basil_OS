"""Unit coverage for the shared American-spelling policy used by the codemod and the checker."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "spelling"))

from spelling_policy import (  # noqa: E402
    BRITISH_TO_AMERICAN,
    americanize_text,
    americanize_token,
    compound_identifier_collisions,
    find_violations,
    is_protected_path,
    is_scannable_path,
)


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("cancelled", "canceled"),
        ("Cancelled", "Canceled"),
        ("CANCELLED", "CANCELED"),
        ("cancelling", "canceling"),
        ("Cancelling", "Canceling"),
        ("behaviour", "behavior"),
        ("normalised", "normalized"),
        ("grey", "gray"),
        ("queueing", "queuing"),
        ("acknowledgement", "acknowledgment"),
        ("analyse", "analyze"),
        ("labelled", "labeled"),
        ("relabelled", "relabeled"),
    ],
)
def test_americanize_token_preserves_case(token: str, expected: str) -> None:
    assert americanize_token(token) == expected


@pytest.mark.parametrize(
    "token",
    ["cancellation", "cancellable", "Cancellables", "dialogue", "analyses", "afterwards", "forwards", "promise", "exercise", "controlled"],
)
def test_intentional_spellings_are_not_mapped(token: str) -> None:
    assert americanize_token(token) is None


def test_replacement_map_has_no_identity_or_intentional_keys() -> None:
    for british, american in BRITISH_TO_AMERICAN.items():
        assert british != american
        assert british == british.lower()
    for kept in ("cancellation", "cancellable", "dialogue", "analyses"):
        assert kept not in BRITISH_TO_AMERICAN


def test_identifiers_are_rewritten_inside_compound_names() -> None:
    text = "is_cancelled = isCancelling or AGENT_TASK_CANCELLED or _normalise(value)\n"
    americanized, findings = americanize_text("backend/example.py", text)
    assert americanized == "is_canceled = isCanceling or AGENT_TASK_CANCELED or _normalize(value)\n"
    assert [finding.token for finding in findings] == ["cancelled", "Cancelling", "CANCELLED", "normalise"]


def test_python_external_tokens_are_protected() -> None:
    text = "except asyncio.CancelledError:\n    if not task.cancelled():\n        status = 'cancelled'\n"
    americanized, _ = americanize_text("backend/example.py", text)
    assert americanized == "except asyncio.CancelledError:\n    if not task.cancelled():\n        status = 'canceled'\n"


def test_swift_platform_tokens_are_protected_but_own_properties_are_renamed() -> None:
    text = (
        "if Task.isCancelled || pending.isCancelled || isCancelled { }\n"
        "case .cancelled:\n"
        "let marker = NSTextList(markerFormat: .disc, options: 0)\n"
    )
    americanized, _ = americanize_text("client/Sources/Example.swift", text)
    assert americanized == (
        "if Task.isCancelled || pending.isCancelled || isCanceled { }\n"
        "case .cancelled:\n"
        "let marker = NSTextList(markerFormat: .disc, options: 0)\n"
    )


def test_member_access_is_renamed_outside_swift() -> None:
    americanized, _ = americanize_text("web-components/Example/src/state.ts", "if (state.isCancelled && result.cancelled) {}\n")
    assert americanized == "if (state.isCanceled && result.canceled) {}\n"


def test_dom_and_protocol_values_are_protected() -> None:
    text = (
        '<div aria-labelledby="title" />\n'
        '{"stopReason": "cancelled"}\n'
        'assert update["stopReason"] == "cancelled"\n'
        'if params["update"].get("stopReason") == "cancelled":\n'
        'if stop_reason == "cancelled":\n'
    )
    americanized, findings = americanize_text("web-components/Example/src/view.tsx", text)
    assert americanized == text
    assert findings == []


def test_line_anchors_protect_external_normalizer_inputs() -> None:
    relpath = "backend/src/api/core/models/reasoning/streaming_contract.py"
    text = '    if reason in {"cancelled", "canceled"}:\n        return "cancelled"\n'
    americanized, _ = americanize_text(relpath, text)
    assert americanized == '    if reason in {"cancelled", "canceled"}:\n        return "canceled"\n'


def test_line_anchor_keeps_discussion_abbreviation() -> None:
    relpath = "backend/src/api/services/agent_processing/lifecycle/submission/agent_task_submission_service.py"
    text = '        cmd_id = agent_task_id or f"disc_{root_task_id[:8]}_{int(time.time())}"\n'
    americanized, findings = americanize_text(relpath, text)
    assert americanized == text
    assert findings == []


def test_rewrite_is_idempotent_and_line_preserving() -> None:
    text = "a cancelled\r\nb behaviour\nc grey\n"
    once, _ = americanize_text("docs/example.md", text)
    twice, findings = americanize_text("docs/example.md", once)
    assert once == "a canceled\r\nb behavior\nc gray\n"
    assert twice == once
    assert findings == []


def test_find_violations_reports_unmapped_cancel_forms_with_positions() -> None:
    violations = find_violations("docs/example.md", "ok\nThe job was uncancelled and Cancelled.\n")
    assert [(v.line, v.column, v.token, v.replacement) for v in violations] == [
        (2, 15, "cancelled", None),
        (2, 29, "Cancelled", "Canceled"),
    ]


def test_find_violations_is_empty_for_protected_content() -> None:
    assert find_violations("backend/example.py", "except asyncio.CancelledError:\n    pass\n") == []


def test_compound_identifier_collisions_are_reported() -> None:
    original = "is_cancelled = 1\nis_canceled = 2\nplain cancelled canceled\n"
    americanized, _ = americanize_text("backend/example.py", original)
    assert compound_identifier_collisions(original, americanized) == [("is_cancelled", "is_canceled")]


@pytest.mark.parametrize(
    ("relpath", "protected"),
    [
        ("backend/src/api/services/whisper_live_core/whisper/normalizers/english.json", True),
        ("client/Sources/Resources/SetupAssistantWebAssets/src/entries/setup-assistant.html", True),
        ("client/Sources/Resources/ScheduledRunMiniPanelAssets/assets/index.js", True),
        ("web-components/BasilBoard/node_modules/react/index.js", True),
        ("poetry.lock", True),
        ("NOTICE", True),
        ("scripts/spelling/spelling_policy.py", True),
        ("backend/src/api/core/models/model_invocation.py", False),
        ("web-components/BasilBoard/src/todos/TodoWorkerStatusCard.tsx", False),
    ],
)
def test_protected_paths(relpath: str, protected: bool) -> None:
    assert is_protected_path(relpath) is protected


def test_scannable_paths_are_text_sources_only() -> None:
    assert is_scannable_path("client/Sources/App/Example.swift")
    assert is_scannable_path("docs/development.md")
    assert not is_scannable_path("client/Sources/Resources/icon.png")
    assert not is_scannable_path("poetry.lock")
