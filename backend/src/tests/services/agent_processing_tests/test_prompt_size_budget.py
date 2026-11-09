"""Guards for the system prompt size reduction: a size ceiling, the steers that must stay in the prompt, and the guidance that moved."""

from __future__ import annotations

import pytest

from api.services.agent_processing.lifecycle.execution_graph.discovery_handoff import DiscoveryHandoff
from api.services.agent_processing.lifecycle.execution_graph.system_prompts import AGENT_SYSTEM_PROMPT_TEMPLATE
from api.services.agent_processing.tools.internal_basil_tools.iterative_work_tool import (
    SLIM_DESCRIPTION as ITERATIVE_SLIM_DESCRIPTION,
    create_iterative_work_tool,
)

# The template was 39,144 characters before the reduction and 30,128 after it. The ceiling leaves room for small
# wording fixes; raising it needs a reason, because every character is paid on every cold call.
# Raised from 31,000 to 31,500 for the one bullet that routes "search or read local text" to the read-only file_service tools: the choice between the shell and a file tool is made before any tool family loads, so the steer cannot live in the tool descriptions.
TEMPLATE_CHAR_CEILING = 31_500

REMOVED_FROM_TEMPLATE = (
    "ITERATIVE WORK STRATEGY:",
    "TOOL FAILURES AND HONESTY:",
    "CHECKPOINTS VS WORK COMPLETE:",
    "INPUT DISCOVERY HANDOFF",
    "- Browser JavaScript automation permission failures",
    "If REFERENCE MATERIALS lists explicit",
)

SECTIONS_THAT_REMAIN = (
    "EXECUTION PRINCIPLES:",
    "ACTION OVER CLARIFICATION (CRITICAL):",
    "FOLLOW-UP AGENT TASK CONTEXT:",
    "FILE SYSTEM RECONNAISSANCE (CRITICAL FOR ACCURACY):",
    "SHELL USAGE RULES (SECURITY & RELIABILITY):",
    "OPTIONAL HELPER TOOLS AND LIBRARIES:",
    "VISION/IMAGE ANALYSIS:",
    "TASK CHECKLIST:",
    "PERMISSION HANDLING:",
    "PROGRESS REPORTING:",
    "SELF-HEALING MICRO-RETRY (OUTCOME-AGNOSTIC):",
    "FILE OPERATION REPORTING:",
    "PATH QUALITY REQUIREMENTS (CRITICAL):",
    "TOOL ETIQUETTE (CROSS-TOOL GUARDRAILS):",
    "CLEANUP REQUIREMENTS (SAFETY-CRITICAL):",
    "CRITICAL SYSTEM INFORMATION:",
    "REFLECTION CHECKPOINT (before you stop this turn):",
    "MATERIAL OUTCOME VERIFICATION",
    "REQUESTING USER INPUT (COLLABORATIVE FLOWS):",
    "BACKEND FINAL ANSWER",
    "LAST-RESORT SCRIPTING FLOOR",
)

STEERS_THAT_MUST_STAY_IN_THE_PROMPT = (
    # Routing decisions that happen before any family loads.
    "load the `browser` tool family before asking whether a website or browser tab is open",
    "browser_tabs first",
    "start with a simple bounded first pass",
    "file_service_edit_text_file",
    "- For email operations",
    "use `external_catalog` with the discover-then-call pattern",
    "reformulate",
    "load the `provider` family",
    "schedule_agent_follow_up",
    # Safety and honesty rules.
    "permission_blocked=true",
    "outcome_unknown",
    "do not treat an unverified empty result as clean success",
    "say so plainly in your handoff",
    "you MUST call `request_user_input` with a clear prompt and then STOP",
    "name where it is saved and which tool call holds its final saved text",
    # Checklist behavior pinned by the checklist tests.
    "one item per record",
    "waiting_user",
    "does not complete an item",
    # Formats the backend parses.
    "STEP_START:",
    "STEP_COMPLETE:",
    "FAIL_NOTE:",
    "Successfully created file '[filename]' at '[path]'",
    "STEP_COMPLETE: Successfully deleted file '[filename]'",
)


def test_template_stays_under_its_size_ceiling():
    assert len(AGENT_SYSTEM_PROMPT_TEMPLATE) <= TEMPLATE_CHAR_CEILING


@pytest.mark.parametrize("text", REMOVED_FROM_TEMPLATE)
def test_relocated_or_deleted_text_is_gone_from_the_template(text):
    assert text not in AGENT_SYSTEM_PROMPT_TEMPLATE


@pytest.mark.parametrize("heading", SECTIONS_THAT_REMAIN)
def test_sections_that_should_remain_are_still_present(heading):
    assert heading in AGENT_SYSTEM_PROMPT_TEMPLATE


@pytest.mark.parametrize("phrase", STEERS_THAT_MUST_STAY_IN_THE_PROMPT)
def test_pre_load_steers_and_parsed_formats_stay_in_the_prompt(phrase):
    assert phrase in AGENT_SYSTEM_PROMPT_TEMPLATE


def test_template_keeps_one_identity_placeholder_and_no_runs_of_blank_lines():
    assert AGENT_SYSTEM_PROMPT_TEMPLATE.count("{user_identity}") == 1
    assert "\n\n\n" not in AGENT_SYSTEM_PROMPT_TEMPLATE


def test_browser_permission_rules_live_in_exactly_one_place():
    assert AGENT_SYSTEM_PROMPT_TEMPLATE.count("foreground_blocked") == 1
    assert AGENT_SYSTEM_PROMPT_TEMPLATE.count("browser_native_input") == 1
    assert "do not open browser settings" in AGENT_SYSTEM_PROMPT_TEMPLATE


def test_ledger_strategy_moved_into_the_iterative_work_description():
    description = create_iterative_work_tool().description
    for phrase in (
        "Strategy:",
        "Do not force batching for small jobs",
        "`iterative_work` is a durable ledger, not the strategy itself",
        "Do not blindly walk backwards from today",
        "ledger every discovered item",
        "not hardcoded string matching",
        "coverage is ambiguous or unresolved",
        "discovered, reviewed, expanded, acted_on, skipped, failed, and unresolved",
    ):
        assert phrase in description


def test_ledger_strategy_essentials_reach_slim_rendering_profiles():
    for phrase in (
        "Do not force batching for small jobs",
        "do not blindly walk backwards from today",
        "Ledger every discovered item",
        "acted_on",
    ):
        assert phrase in ITERATIVE_SLIM_DESCRIPTION


def test_input_discovery_handoff_block_carries_its_own_guidance():
    block = DiscoveryHandoff(prepared_files=(), source_catalog=()).render()
    assert block.startswith("\n\nINPUT DISCOVERY HANDOFF:")
    for phrase in (
        "user-provided files are claims to compare",
        "a record marked primary is its Basil-owned authority",
        "a scheduled calendar event is not proof that an event occurred",
        "rather than silently substituting another source",
    ):
        assert phrase in block
