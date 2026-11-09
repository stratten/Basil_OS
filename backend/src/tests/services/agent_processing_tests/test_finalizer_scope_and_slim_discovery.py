"""Guards for two small-model fixes: the finalizer now sees each step's input so it can check the stated scope, and the slim external_catalog description stays at its original wording (a longer discovery steer was measured to make Qwen3.5-4B loop, so the failure is handled in code instead)."""

from __future__ import annotations

from api.services.agent_processing.lifecycle.finalization.evaluation import (
    MAX_STEP_INPUT_CHARS,
    MAX_STEPS_METADATA_CHARS,
    build_evaluation_prompt,
    format_steps_metadata,
)
from api.services.agent_processing.tools.external_services.external_catalog import descriptions as external_catalog_descriptions

# The slim description is 1,964 characters. The ceiling leaves room for small wording fixes; every character is prefilled on every local-model call.
SLIM_DESCRIPTION_CHAR_CEILING = 2_100


def _prompt(steps):
    return build_evaluation_prompt(
        original_prompt="List the sender and subject of my 3 newest inbox messages.",
        self_assessment=None,
        full_agent_output="Here are your three newest inbox messages.",
        max_output_chars=20000,
        steps=steps,
        tool_error_history=None,
        evaluation_context=None,
    )


def _search_step(arguments):
    return {
        "service": "external_catalog",
        "method": "invoke",
        "success": True,
        "tool_input": {"action": "call_tool", "connection_id": "abc", "tool_name": "search_threads", "arguments": arguments},
        "result": {"threads": 3},
    }


def test_step_summary_shows_the_input_the_agent_sent():
    summary = format_steps_metadata([_search_step({"query": "in:inbox", "pageSize": 3})])
    assert "input=" in summary
    assert "in:inbox" in summary
    assert summary.index("input=") < summary.index("result=")


def test_step_summary_makes_a_missing_scope_visible():
    summary = format_steps_metadata([_search_step("{\"tool_name\": \"search_threads\", \"connection_id\": \"abc\"}")])
    assert "input=" in summary
    assert "in:inbox" not in summary


def test_step_summary_has_no_input_field_when_the_step_has_no_input():
    summary = format_steps_metadata([{"service": "file_service", "method": "read_file", "success": True, "result": "ok"}])
    assert "input=" not in summary


def test_step_input_is_clipped_so_a_large_write_cannot_bloat_the_prompt():
    summary = format_steps_metadata(
        [{"service": "file_service", "method": "write_text_file", "success": True, "tool_input": {"content": "z" * 50_000}, "result": "ok"}]
    )
    assert "z" * (MAX_STEP_INPUT_CHARS + 50) not in summary
    assert "..." in summary


def test_step_input_with_unserializable_keys_does_not_break_the_finalizer():
    summary = format_steps_metadata([{"service": "a", "method": "b", "success": True, "tool_input": {(1, 2): object()}}])
    assert "input=" in summary


def test_steps_metadata_stays_bounded_with_inputs_present():
    steps = [
        {"service": "file_service", "method": "read_file", "success": True, "tool_input": {"path": "p" * 5000}, "result": "x" * 50_000}
        for _ in range(500)
    ]
    summary = format_steps_metadata(steps)
    assert len(summary) <= MAX_STEPS_METADATA_CHARS + 200
    assert "more step(s) omitted" in summary


def test_prompt_carries_the_scope_check_inside_the_evaluation_guidelines():
    prompt = _prompt([_search_step({"query": "in:inbox", "pageSize": 3})])
    guidelines = prompt[prompt.index("EVALUATION GUIDELINES:") : prompt.index("failure_basis (REQUIRED)")]
    assert "SCOPE CHECK" in guidelines
    assert "input=" in guidelines
    assert "should_retry=true" in guidelines[guidelines.index("SCOPE CHECK") :]


def test_scope_check_does_not_license_downgrades_on_a_guess():
    prompt = _prompt([])
    scope_check = prompt[prompt.index("SCOPE CHECK") : prompt.index("If output ends mid-item")]
    assert "do not downgrade the outcome on a guess" in scope_check
    assert "no step shows an input= field at all" in scope_check


def test_scope_check_names_the_result_header_and_the_unscoped_signals():
    prompt = _prompt([])
    scope_check = prompt[prompt.index("SCOPE CHECK") : prompt.index("If output ends mid-item")]
    assert "for 'all mail'" in scope_check
    assert "carries no query, filter, label, folder, or date argument" in scope_check
    assert "quoted string" in scope_check
    assert "does not make them so" in scope_check


def test_the_trace_the_finalizer_reads_includes_the_unscoped_call():
    prompt = _prompt([_search_step("{\"tool_name\": \"search_threads\"}")])
    steps_block = prompt[prompt.index("EXECUTION STEPS METADATA") : prompt.index("TOOL ERROR HISTORY")]
    assert "input={" in steps_block
    assert "in:inbox" not in steps_block


def test_slim_description_does_not_carry_the_retired_discovery_steer():
    slim = external_catalog_descriptions.SLIM_DESCRIPTION
    for retired in ("never guess a tool name", "copy connection_id exactly", "such as the inbox", "never repeat a call that already returned"):
        assert retired not in slim


def test_slim_description_keeps_its_earlier_guidance():
    slim = external_catalog_descriptions.SLIM_DESCRIPTION
    for fragment in ("reformulate", "structured/exact parameters", "permission_denied", "connect_server", "connect_with_token", "tool_name is a FIELD"):
        assert fragment in slim


def test_slim_description_stays_under_the_ceiling():
    assert len(external_catalog_descriptions.SLIM_DESCRIPTION) < SLIM_DESCRIPTION_CHAR_CEILING


def test_the_full_description_is_unchanged_by_the_slim_rule():
    full = external_catalog_descriptions.build_full_external_catalog_description("**CURRENT CONNECTIONS:**\n- Example (connection_id=1)")
    assert "never guess a tool name" not in full


def test_scope_check_does_not_accept_an_assumed_after_the_fact_filter():
    prompt = _prompt([])
    scope_check = prompt[prompt.index("SCOPE CHECK") : prompt.index("If output ends mid-item")]
    assert "your own belief that the agent must have filtered the results afterward" in scope_check
    assert "only when a step shows it" in scope_check
    assert "say which step in your reasoning" in scope_check
