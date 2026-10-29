"""The agent prompt must tell the agent that the user may be editing the same data and that it must not undo their changes."""

from __future__ import annotations

from api.services.agent_processing.lifecycle.execution_graph.system_prompts import AGENT_SYSTEM_PROMPT_TEMPLATE


def _guidance() -> str:
    lines = [line for line in AGENT_SYSTEM_PROMPT_TEMPLATE.splitlines() if line.startswith("- The user may be working in the same mailbox")]
    assert len(lines) == 1
    return lines[0]


def test_the_agent_is_told_the_user_may_change_things_while_it_works():
    guidance = _guidance()
    assert "while you do" in guidance
    assert "possibly the user's own action" in guidance


def test_the_agent_reconciles_to_current_state_instead_of_restoring_what_it_last_saw():
    guidance = _guidance()
    assert "reconcile to the current state" in guidance
    assert "rather than restoring, re-creating, or re-applying" in guidance


def test_the_agent_keeps_the_ability_to_undo_its_own_mistakes():
    guidance = _guidance()
    assert "Reverse a change only when your own earlier call in this task made it and it was a mistake" in guidance


def test_a_refusal_from_a_reversal_tool_is_final_unless_the_user_asked_for_it():
    guidance = _guidance()
    assert "take that as final unless the user explicitly asked for that specific reversal" in guidance
