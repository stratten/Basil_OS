"""The agent prompt must steer Gmail mailbox changes toward a connected Gmail connection without forbidding the Mail app."""

from __future__ import annotations

from api.services.agent_processing.lifecycle.execution_graph.system_prompts import AGENT_SYSTEM_PROMPT_TEMPLATE


def _email_guidance() -> str:
    lines = [line for line in AGENT_SYSTEM_PROMPT_TEMPLATE.splitlines() if line.startswith("- For email operations")]
    assert len(lines) == 1
    return lines[0]


def test_gmail_connection_is_named_as_a_faster_route_for_mailbox_changes():
    guidance = _email_guidance()
    assert "connected Gmail connection" in guidance
    assert "external_catalog" in guidance
    assert "unlabel_thread" in guidance
    assert "take over Mail's windows" in guidance


def test_the_guidance_keeps_the_mail_app_available_and_allows_mixing_routes():
    guidance = _email_guidance()
    assert "email_service tools (the Mail app) are the general default" in guidance
    assert "mix routes" in guidance
    assert "drafts in Mail" in guidance
    assert "do not abandon either route" in guidance


def test_the_guidance_does_not_forbid_any_route():
    guidance = _email_guidance().lower()
    for forbidden in ("never use email_service", "never use the mail app", "must use the gmail connection", "only use the gmail connection"):
        assert forbidden not in guidance
