"""Tests for meeting-analysis identity + capability context (Phase 1A).

Covers the first-person identity block, the capability digest fallback, and
the prompt-builder wiring that injects both into the analysis prompts.
"""

from types import SimpleNamespace

from api.core.knowledge.personalization_models import UserProfile
from api.services.whisper_live_core.post_processing.meeting_analysis_context import (
    build_capability_digest,
    build_identity_block,
    format_user_identity_block,
    _format_speaker_attribution,
    _STATIC_CAPABILITY_FALLBACK,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_prompts import (
    MeetingAnalysisPromptBuilder,
)


# --- format_user_identity_block ------------------------------------------------

def test_identity_block_uses_preferred_name_and_role() -> None:
    profile = UserProfile(
        full_name="Stratten Waldt",
        preferred_name="Stratten",
        email="stratten@example.com",
        job_title="Founder",
        company_name="Basil",
    )

    block = format_user_identity_block(profile)

    assert "Stratten" in block
    assert "Founder at Basil" in block
    # First-person framing instructions present.
    assert "assisting Stratten directly" in block
    assert "IS the user you are helping" in block
    assert "never as reminders" in block
    assert "stratten@example.com" in block


def test_identity_block_falls_back_to_full_name_when_no_preferred() -> None:
    profile = UserProfile(full_name="Stratten Waldt")
    block = format_user_identity_block(profile)
    assert "Stratten Waldt" in block


def test_identity_block_handles_role_only_profile() -> None:
    profile = UserProfile(job_title="Engineer")
    block = format_user_identity_block(profile)
    # No name, but a role exists -> uses generic subject and still renders.
    assert "the user" in block
    assert "Engineer" in block


def test_identity_block_empty_for_none_profile() -> None:
    assert format_user_identity_block(None) == ""


def test_identity_block_empty_for_blank_profile() -> None:
    # A profile with no usable identity fields produces no block.
    assert format_user_identity_block(UserProfile()) == ""


def test_identity_block_includes_second_person_directive() -> None:
    # The block must instruct second-person addressing while keeping the
    # existing third-person context lines intact.
    block = format_user_identity_block(UserProfile(preferred_name="Stratten"))
    assert "second person" in block
    assert '"you", "your"' in block
    assert "assisting Stratten directly" in block


# --- _format_speaker_attribution -----------------------------------------------

def test_speaker_attribution_multi_track_binds_microphone_label() -> None:
    block = _format_speaker_attribution(
        member_sources=[("Microphone", True), ("Zoom", False)],
    )
    assert "SPEAKER ATTRIBUTION" in block
    # The microphone source label is bound to the user as "you".
    assert '"Microphone"' in block
    assert "That speaker is you" in block
    # The non-microphone source is framed as the other participants.
    assert "Zoom" in block
    assert "second person" in block


def test_speaker_attribution_uses_actual_source_label_not_hardcoded() -> None:
    # When the mic member's audio_source is a custom string, that exact label is
    # bound (proves we thread the real label rather than hardcoding "Microphone").
    block = _format_speaker_attribution(
        member_sources=[("Built-in Mic", True), ("System Audio", False)],
    )
    assert '"Built-in Mic"' in block
    assert "System Audio" in block


def test_speaker_attribution_multi_track_without_microphone_is_empty() -> None:
    # No microphone member -> the user's track cannot be identified -> no block.
    block = _format_speaker_attribution(
        member_sources=[("Zoom", False), ("System Audio", False)],
    )
    assert block == ""


def test_speaker_attribution_single_track_microphone_is_hedged() -> None:
    block = _format_speaker_attribution(single_source="Microphone")
    assert "SPEAKER ATTRIBUTION" in block
    assert "your own microphone recording" in block
    assert "primary speaker" in block


def test_speaker_attribution_single_track_microphone_is_case_insensitive() -> None:
    block = _format_speaker_attribution(single_source="  microphone ")
    assert "your own microphone recording" in block


def test_speaker_attribution_single_track_non_microphone_is_empty() -> None:
    assert _format_speaker_attribution(single_source="Zoom") == ""


def test_speaker_attribution_single_track_unknown_source_is_empty() -> None:
    # Legacy meetings with no audio_source must not get a guessed binding.
    assert _format_speaker_attribution(single_source=None) == ""


def test_speaker_attribution_no_sources_is_empty() -> None:
    assert _format_speaker_attribution() == ""


# --- build_identity_block ------------------------------------------------------

def test_build_identity_block_combines_identity_and_attribution() -> None:
    profile = UserProfile(preferred_name="Stratten", job_title="Developer")
    block = build_identity_block(
        profile,
        member_sources=[("Microphone", True), ("Zoom", False)],
    )
    # Identity part present.
    assert "USER IDENTITY (read this first):" in block
    assert "Stratten" in block
    # Attribution part present and bound to the mic label.
    assert "SPEAKER ATTRIBUTION" in block
    assert '"Microphone"' in block


def test_build_identity_block_identity_only_when_no_usable_sources() -> None:
    # A multi-track meeting with no microphone member yields identity only.
    profile = UserProfile(preferred_name="Stratten")
    block = build_identity_block(
        profile,
        member_sources=[("Zoom", False), ("System Audio", False)],
    )
    assert "USER IDENTITY (read this first):" in block
    assert "SPEAKER ATTRIBUTION" not in block


def test_build_identity_block_attribution_only_when_no_profile() -> None:
    # No profile but a mic-only single track still binds the user's track.
    block = build_identity_block(None, single_source="Microphone")
    assert "USER IDENTITY (read this first):" not in block
    assert "SPEAKER ATTRIBUTION" in block


def test_build_identity_block_empty_when_nothing_known() -> None:
    assert build_identity_block(None) == ""


# --- build_capability_digest ---------------------------------------------------

def test_capability_digest_includes_families_and_scheduling() -> None:
    digest = build_capability_digest()

    assert "BASIL AGENT CAPABILITIES" in digest
    # The digest must consume the SAME canonical thin-definition surface the
    # runner routes on, including per-family routing detail (not a name+purpose
    # paraphrase). render_family_routing_catalog emits a "When to load:" clause.
    assert "Available tool families for first-pass routing:" in digest
    assert "When to load:" in digest
    # Scheduling guidance must always be present so future-dated items are
    # framed as delegated scheduled tasks rather than reminders.
    assert "SCHEDULING:" in digest
    assert "scheduled delegated agent" in digest


def test_capability_digest_surfaces_connection_capability(monkeypatch) -> None:
    from api.services.agent_processing.tools.external_services import (
        external_connection_inventory,
    )

    fake_preferences = SimpleNamespace(
        connections=SimpleNamespace(
            mcp_connections=[
                SimpleNamespace(
                    id="speakeasy-id",
                    friendly_name="Speakeasy - Custom",
                    server_url="https://app.speakeasy.is/mcp",
                    enabled=True,
                    server_name="salesforce-mcp",
                    server_instructions="Read and write Salesforce records.",
                    cached_tools=[
                        SimpleNamespace(name="sf_query", description="Query Salesforce records."),
                    ],
                ),
            ]
        )
    )
    monkeypatch.setattr(external_connection_inventory, "_load_preferences", lambda: fake_preferences)

    digest = build_capability_digest()

    assert "**CURRENT CONNECTIONS:**" in digest
    assert "server: salesforce-mcp" in digest
    assert "sf_query: Query Salesforce records." in digest


def test_capability_digest_falls_back_when_catalog_unavailable(monkeypatch) -> None:
    # Force the tool-family catalog import to raise so the static fallback path
    # is exercised.
    import builtins

    real_import = builtins.__import__

    def _raising_import(name, *args, **kwargs):
        if "tool_family_catalog" in name:
            raise ImportError("simulated catalog failure")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _raising_import)

    digest = build_capability_digest()
    assert digest == _STATIC_CAPABILITY_FALLBACK


# --- prompt-builder wiring -----------------------------------------------------

def _base_metadata() -> dict:
    return {
        "name": "Quarterly Sync",
        "purpose": "Plan the quarter",
        "participants": ["Stratten", "Alex"],
        "duration": 600.0,
        "speaker_count": 2,
    }


def test_suggested_actions_prompt_injects_identity_and_digest() -> None:
    builder = MeetingAnalysisPromptBuilder()
    metadata = _base_metadata()
    metadata["identity_block"] = "USER IDENTITY (read this first):\n- This transcript was recorded by Stratten."
    metadata["capability_digest"] = "BASIL AGENT CAPABILITIES (custom digest):\n- external: connect things."

    prompt = builder.build_suggested_actions_prompt(
        transcript="[00:00] Stratten: Let's export the data.",
        meeting_metadata=metadata,
        action_items=[],
        custom_instructions=None,
    )

    assert "USER IDENTITY (read this first):" in prompt
    assert "BASIL AGENT CAPABILITIES (custom digest):" in prompt
    # New capability type and durable candidate schema must be present.
    assert "scheduled_agent_task" in prompt
    assert '"disposition": "todo_candidate"' in prompt


def test_metadata_section_omits_identity_when_absent() -> None:
    builder = MeetingAnalysisPromptBuilder()
    # No identity_block key -> section must not start with an identity header.
    section = builder._build_metadata_section(_base_metadata())
    assert section.startswith("MEETING CONTEXT:")
    assert "USER IDENTITY" not in section


def test_prompt_builder_has_no_fixed_transcript_cutoff() -> None:
    builder = MeetingAnalysisPromptBuilder()
    assert not hasattr(builder, "max_transcript_length")
    assert not hasattr(builder, "truncate_transcript_if_needed")


def test_suggested_actions_prompt_uses_static_capabilities_without_digest() -> None:
    builder = MeetingAnalysisPromptBuilder()
    prompt = builder.build_suggested_actions_prompt(
        transcript="[00:00] Stratten: hello",
        meeting_metadata=_base_metadata(),
        action_items=[],
        custom_instructions=None,
    )
    # Falls back to the static capability list when no digest is supplied.
    assert "KNOWN BASIL CAPABILITIES:" in prompt


def test_suggested_actions_prompt_scopes_second_person_to_user_facing_field() -> None:
    builder = MeetingAnalysisPromptBuilder()
    prompt = builder.build_suggested_actions_prompt(
        transcript="[00:00] Stratten: hello",
        meeting_metadata=_base_metadata(),
        action_items=[],
        custom_instructions=None,
    )
    # why_basil_can_help is addressed to the user in the second person...
    assert '"why_basil_can_help" addressed to the user in the second person' in prompt
    # ...while suggested_agent_task stays a self-contained delegate instruction.
    assert 'When execution_mode is "agent_assisted", make suggested_agent_task a self-contained instruction' in prompt
    assert 'do NOT use "you" because a separate delegate has no chat context.' in prompt
