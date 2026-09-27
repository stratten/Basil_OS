"""Regression tests for staged-tool routing before checkpoints."""

from __future__ import annotations

import logging

import pytest

from api.services.agent_processing.lifecycle.execution_graph import system_prompts
from api.services.agent_processing.lifecycle.execution_graph.system_prompts import (
    AGENT_SYSTEM_PROMPT_TEMPLATE,
)
from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import (
    SLIM_DESCRIPTION,
    request_user_input,
)


def test_system_prompt_requires_tool_inspection_before_user_checkpoint():
    prompt = AGENT_SYSTEM_PROMPT_TEMPLATE

    assert "Do not ask the user for information that available tools can determine" in prompt
    assert "load that family and inspect first" in prompt
    assert "load the `browser` tool family before asking whether a website or browser tab is open" in prompt
    assert "browser_tabs first" in prompt
    assert "authorize_target" in prompt
    assert "resolve_target_authorization" in prompt
    assert "Never treat a checkpoint response as authorization until resolve_target_authorization returns authorized." in prompt


def test_request_user_input_preserves_bounded_checkpoint_identity():
    from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import (
        CheckpointRequest,
        _validate_checkpoint_extensions,
    )

    with pytest.raises(ValueError, match="metadata must not exceed"):
        _validate_checkpoint_extensions(
            "auth-1",
            {"source": "provider_target_authorization", "payload": "x" * 3000},
        )

    with pytest.raises(CheckpointRequest) as exc_info:
        request_user_input.invoke(
            {
                "prompt": "Choose a target",
                "input_type": "choice",
                "options": ["A", "B"],
                "checkpoint_id": "auth-1",
                "metadata": {
                    "source": "provider_target_authorization",
                    "authorization_id": "auth-1",
                    "cancel_value": "target-cancel:1",
                },
            }
        )

    assert exc_info.value.checkpoint_data["checkpoint_id"] == "auth-1"
    assert exc_info.value.checkpoint_data["metadata"]["source"] == "provider_target_authorization"
    assert exc_info.value.checkpoint_data["input_type"] == "choice"


def test_checkpoint_tool_description_discourages_inspectable_state_questions():
    full_description = request_user_input.description or ""

    assert "Do not use this tool to ask for information that available tools can" in full_description
    assert "load and use those" in full_description
    assert "do not use for state that tools can inspect" in SLIM_DESCRIPTION


def test_system_prompt_section_telemetry_tracks_assembled_prompt(monkeypatch, caplog):
    working_memory_context = "\n\nWORKING MEMORY:\nnone\n"
    skill_catalog_context = "\n\nSAVED SKILL CATALOG:\nnone\n"
    screen_context_context = "\n\nSCREEN CONTEXT:\nnone\n"
    preloaded_skill_section = "\n\nSELECTED SAVED SKILL:\nbody\n"
    custom_instructions_section = "\n\nCUSTOM INSTRUCTIONS:\nbe terse\n"

    monkeypatch.setattr(
        system_prompts,
        "build_working_memory_prompt_section",
        lambda: working_memory_context,
    )
    monkeypatch.setattr(
        system_prompts,
        "build_skill_catalog_prompt_section",
        lambda: skill_catalog_context,
    )
    monkeypatch.setattr(
        system_prompts,
        "build_screen_context_prompt_section",
        lambda: screen_context_context,
    )

    with caplog.at_level(logging.INFO, logger=system_prompts.logger.name):
        prompt = system_prompts.get_agent_system_prompt(
            user_profile_context="Test User",
            custom_instructions_section=custom_instructions_section,
            preloaded_skill_section=preloaded_skill_section,
        )

    telemetry = system_prompts.get_last_prompt_section_telemetry()
    expected_base_chars = len(prompt) - (
        len(custom_instructions_section)
        + len(working_memory_context)
        + len(skill_catalog_context)
        + len(screen_context_context)
        + len(preloaded_skill_section)
    )

    assert telemetry["base_chars"] == expected_base_chars
    assert telemetry["custom_instructions_chars"] == len(custom_instructions_section)
    assert telemetry["working_memory_chars"] == len(working_memory_context)
    assert telemetry["skill_catalog_chars"] == len(skill_catalog_context)
    assert telemetry["screen_context_chars"] == len(screen_context_context)
    assert telemetry["preloaded_skill_chars"] == len(preloaded_skill_section)
    assert telemetry["total_chars"] == len(prompt)
    assert telemetry["total_tokens_est"] == len(prompt) // 4
    assert "[AgentTelemetry] prompt-sections" in caplog.text
