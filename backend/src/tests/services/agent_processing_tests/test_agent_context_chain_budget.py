"""Follow-up summaries grow with the budget, and the result summary can be read from outside the assembler."""

from __future__ import annotations

from api.services.agent_processing.lifecycle.planning.agent_context_assembler import (
    AgentContextAssembler,
    extract_result_summary_text,
)


def test_chain_summary_cap_is_the_old_value_at_the_default_scale_and_grows_with_the_budget():
    assembler = AgentContextAssembler()
    assert assembler._chain_summary_chars(None) == 900
    assert assembler._chain_summary_chars(6_400) == 900
    assert assembler._chain_summary_chars(48_000) == 1_200
    assert assembler._chain_summary_chars(160_000) == 4_000
    assert assembler._chain_summary_chars(10_000_000) == 4_000


def _chain(summary: str):
    return {"chain_agentTasks": [{"sequence": 1, "text": "check mail", "status": "completed", "result": {"message": summary}}]}


def test_a_larger_summary_cap_keeps_more_of_a_long_earlier_answer():
    assembler = AgentContextAssembler()
    long_answer = "A" * 3_000
    default = assembler._format_chain_context(_chain(long_answer))
    widened = assembler._format_chain_context(_chain(long_answer), summary_chars=4_000)
    assert "A" * 1_000 not in default
    assert "A" * 3_000 in widened


def test_budget_flows_into_the_follow_up_section_through_assemble():
    assembler = AgentContextAssembler()
    context = {"chain_context": _chain("B" * 3_000), "context_window": 200_000}
    assembled = assembler.assemble(current_request="again", context=context)
    follow_up = next(section for section in assembled.sections if section.name == "FOLLOW UP CONTEXT")
    assert "B" * 3_000 in follow_up.body
    assert assembled.budget_chars == assembler.MAX_INPUT_BUDGET_CHARS


def test_extract_result_summary_text_reads_the_stored_answer_and_clips():
    assert extract_result_summary_text({"summary_text": "All caught up."}) == "All caught up."
    clipped = extract_result_summary_text({"summary_text": "C" * 5_000}, 1_000)
    assert clipped.startswith("C" * 900) and len(clipped) <= 1_000


def test_extract_result_summary_text_returns_none_for_empty_or_missing_results():
    assert extract_result_summary_text(None) is None
    assert extract_result_summary_text({}) is None
    assert extract_result_summary_text({"unrelated": 1}) is None
