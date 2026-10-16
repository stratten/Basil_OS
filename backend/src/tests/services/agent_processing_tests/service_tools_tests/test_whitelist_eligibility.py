"""Tests for the deterministic rule that decides which approvals may be remembered."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.core.models.preferences import CommandPattern, ExecutionApprovalMode, ToolExecutionSettings
from api.services.agent_processing.tools.safety.approval_presentation import approval_presentation_fields
from api.services.agent_processing.tools.safety.command_generalization import CommandGeneralizer
from api.services.agent_processing.tools.safety.execution_approval_service import ExecutionApprovalService
from api.services.agent_processing.tools.safety.explanation_gate import (
    EXPLANATION_REQUIRED_STATUS,
    should_request_explanation,
)
from api.services.agent_processing.tools.safety.pattern_matcher import PatternMatcher
from api.services.agent_processing.tools.safety.whitelist_eligibility import (
    assess_whitelist_eligibility,
    normalize_whitelist_advice,
)
from api.services.agent_processing.tools.safety.whitelist_manager import WhitelistManager


@pytest.mark.parametrize(
    "command",
    [
        "bash script.sh",
        "bash",
        "bash -c",
        "sh -lc",
        "zsh /tmp/run.sh",
        "python3 tool.py",
        "python3 -c print(1)",
        "python3.11 -m pytest",
        "/usr/bin/python3 tool.py",
        "node build.js",
        "ruby x.rb",
        "perl -e print",
        "php -r echo",
        "lua x.lua",
        "osascript -e beep",
        "swift main.swift",
        "env FOO=bar git status",
        "sudo ls",
        "xargs rm",
        "nohup sleep 100",
        "exec ls",
        "eval ls",
        "time ls",
        "open /Applications/Calculator.app",
    ],
)
def test_denylisted_commands_can_never_be_remembered(command: str) -> None:
    pattern = CommandGeneralizer().generalize_command(command)

    eligibility = assess_whitelist_eligibility(command, pattern)

    assert eligibility.eligible is False
    assert eligibility.reason


@pytest.mark.parametrize("command", ["git status", "ls -la", "rg needle src", "du -sh /tmp", "poetry run pytest", "bash -lc git status"])
def test_ordinary_commands_can_be_remembered(command: str) -> None:
    pattern = CommandGeneralizer().generalize_command(command)

    assert assess_whitelist_eligibility(command, pattern).eligible is True


def test_a_shell_wrapper_around_an_interpreter_is_not_a_loophole() -> None:
    assert assess_whitelist_eligibility("bash -lc python3 -c x", "bash -lc python3 -c").eligible is False


def test_unparseable_and_empty_patterns_are_not_eligible() -> None:
    assert assess_whitelist_eligibility("echo 'unterminated", "echo 'unterminated").eligible is False
    assert assess_whitelist_eligibility("", "").eligible is False


@pytest.mark.parametrize("execution_type", ["applescript", "browser_foreground_control"])
def test_script_and_automation_approvals_are_never_remembered(execution_type: str) -> None:
    eligibility = assess_whitelist_eligibility("AppleScript: tidy", "AppleScript:", execution_type=execution_type)

    assert eligibility.eligible is False
    assert "reviewed every time" in eligibility.reason


def test_advice_is_downgraded_but_never_upgraded() -> None:
    eligible = assess_whitelist_eligibility("git status", "git status")
    ineligible = assess_whitelist_eligibility("python3 x.py", "python3")

    kept = normalize_whitelist_advice({"recommend": True, "reason": "Read-only."}, eligible, purpose="Shows status.")
    downgraded = normalize_whitelist_advice({"recommend": True, "reason": "Safe."}, ineligible, purpose="Runs it.")
    never_upgraded = normalize_whitelist_advice({"recommend": False, "reason": "Writes files."}, eligible, purpose="Writes.")

    assert kept == {"recommend": True, "reason": "Read-only.", "downgraded": False}
    assert downgraded["recommend"] is False and downgraded["downgraded"] is True and downgraded["reason"] == ineligible.reason
    assert never_upgraded == {"recommend": False, "reason": "Writes files.", "downgraded": False}


@pytest.mark.parametrize(
    "raw",
    [None, "yes", {"recommend": "maybe", "reason": "x"}, {"recommend": True}, {"recommend": True, "reason": "  "}, {"reason": "x"}],
)
def test_malformed_advice_is_dropped(raw) -> None:
    assert normalize_whitelist_advice(raw, assess_whitelist_eligibility("git status", "git status"), purpose="Shows status.") is None


def test_advice_without_an_explanation_is_dropped_and_model_objects_are_accepted() -> None:
    eligible = assess_whitelist_eligibility("git status", "git status")
    advice = SimpleNamespace(model_dump=lambda: {"recommend": "yes", "reason": "Read-only."})

    assert normalize_whitelist_advice({"recommend": True, "reason": "x"}, eligible, purpose=None) is None
    assert normalize_whitelist_advice(advice, eligible, purpose="Shows status.")["recommend"] is True


def test_presentation_marks_a_missing_explanation_and_strips_advice() -> None:
    fields = approval_presentation_fields(
        "cargo build",
        "cargo build",
        {"purpose_required": True, "whitelist_advice": {"recommend": True, "reason": "Fine."}, "script_path": "/tmp/x.sh"},
    )

    assert fields["purpose_missing"] is True
    assert "purpose" not in fields
    assert fields["whitelist"] == {"eligible": True, "reason": "", "advice": None}
    assert fields["script_path"] == "/tmp/x.sh"


def test_presentation_carries_the_explanation_and_the_downgraded_advice() -> None:
    fields = approval_presentation_fields(
        "python3 run.py",
        "python3",
        {"purpose": "  Runs the report.  ", "whitelist_advice": {"recommend": True, "reason": "Safe."}, "purpose_required": True},
    )

    assert fields["purpose"] == "Runs the report."
    assert "purpose_missing" not in fields
    assert fields["whitelist"]["eligible"] is False
    assert fields["whitelist"]["advice"]["recommend"] is False


class _PreferenceStore:
    def __init__(self, patterns: list[CommandPattern]) -> None:
        self.preferences = SimpleNamespace(
            tool_execution=ToolExecutionSettings(
                approval_mode=ExecutionApprovalMode.WHITELIST_ONLY,
                whitelisted_commands=patterns,
                auto_approve_read_only=False,
                safe_execution_mode=False,
            )
        )

    def load(self) -> SimpleNamespace:
        return self.preferences

    def save(self, preferences: SimpleNamespace) -> None:
        self.preferences = preferences


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _PreferenceStore:
    preference_store = _PreferenceStore([])
    monkeypatch.setattr("api.core.preferences.preferences_io.load_preferences", preference_store.load)
    monkeypatch.setattr("api.core.preferences.preferences_io.save_preferences", preference_store.save)
    monkeypatch.setattr(
        "api.services.agent_processing.tools.safety.approval_override.load_preferences", preference_store.load
    )
    return preference_store


@pytest.mark.asyncio
async def test_whitelist_manager_refuses_interpreters_and_accepts_ordinary_commands(store: _PreferenceStore) -> None:
    manager = WhitelistManager(CommandGeneralizer(), PatternMatcher())

    with pytest.raises(ValueError, match="python can run any code"):
        await manager.add_to_whitelist("python3 run.py", pattern_type="prefix")
    with pytest.raises(ValueError):
        await manager.update_whitelist_pattern("pattern", "python3", pattern_type="prefix")

    pattern = await manager.add_to_whitelist("git status", pattern_type="prefix")

    assert pattern.pattern == "git"
    assert [p.pattern for p in store.preferences.tool_execution.whitelisted_commands] == ["git"]


def test_stored_patterns_that_can_never_be_remembered_no_longer_approve_commands() -> None:
    matcher = PatternMatcher()
    legacy = CommandPattern(id="legacy", pattern="python3", pattern_type="prefix", description="old")
    narrow = CommandPattern(id="narrow", pattern="git status", pattern_type="prefix", description="ok")

    assert matcher.check_whitelist("python3 evil.py", [legacy]) is None
    assert matcher.check_whitelist("bash -lc python3", [legacy]) is None
    assert matcher.check_whitelist("git status -s", [legacy, narrow]) is narrow


@pytest.mark.asyncio
async def test_missing_explanation_is_requested_once_per_task_and_command_without_prompting(store: _PreferenceStore) -> None:
    service = ExecutionApprovalService()
    service.interactive_manager = SimpleNamespace(request_approval=AsyncMock(return_value=(True, False, "")))
    context = {"agent_task_id": "task-explain-1", "purpose_required": True}

    first = await service.request_approval_with_outcome("cargo build --explain-once", context)
    second = await service.request_approval_with_outcome("cargo build --explain-once", context)

    assert first.approved is False
    assert first.status == EXPLANATION_REQUIRED_STATUS
    assert "`purpose`" in first.reason and "nothing was denied" in first.reason
    assert first.as_legacy_tuple() == (False, False, EXPLANATION_REQUIRED_STATUS)
    assert second.approved is True
    service.interactive_manager.request_approval.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_supplied_explanation_prompts_immediately(store: _PreferenceStore) -> None:
    service = ExecutionApprovalService()
    service.interactive_manager = SimpleNamespace(request_approval=AsyncMock(return_value=(True, False, "")))

    outcome = await service.request_approval_with_outcome(
        "cargo build --explained", {"agent_task_id": "task-explain-2", "purpose_required": True, "purpose": "Builds it."}
    )

    assert outcome.approved is True
    service.interactive_manager.request_approval.assert_awaited_once()


def test_callers_that_do_not_require_an_explanation_are_never_gated() -> None:
    assert should_request_explanation("cargo build", {"agent_task_id": "task-explain-3"}) is False
    assert should_request_explanation("cargo build", {"purpose_required": True}) is False
    assert should_request_explanation("cargo build", {"agent_task_id": "task-explain-3", "purpose_required": True, "purpose": "  "}) is True


def test_shell_tool_schema_accepts_the_explanation_arguments() -> None:
    from api.services.agent_processing.lifecycle.execution_graph.service_tooling.schema_generation import (
        get_explicit_input_model,
    )

    model = get_explicit_input_model("shell_service", "execute_command")
    parsed = model(command="git", purpose="Shows status.", whitelist_advice={"recommend": False, "reason": "Fine either way."})

    assert parsed.purpose == "Shows status."
    assert parsed.whitelist_advice.recommend is False
    assert model(command="git").purpose is None
    with pytest.raises(ValueError):
        model(command="git", whitelist_advice={"recommend": "perhaps", "reason": "x"})


def test_applescript_capabilities_expose_the_explanation_arguments() -> None:
    from api.services.agent_processing.tools.direct_application_interactions.applescript_automation.generic_applescript_service import (
        GenericAppleScriptService,
    )

    capabilities = GenericAppleScriptService().get_service_capabilities()["supported_methods"]

    for method in ("execute_applescript", "generate_and_execute_applescript"):
        assert {"purpose", "whitelist_advice"} <= set(capabilities[method]["parameters"])
