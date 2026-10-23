"""LangChain StructuredTool registration for setup-agent tools."""

from __future__ import annotations

from typing import List

from langchain_core.tools import StructuredTool

from .schemas import (
    SetupAddArtifactRowInput,
    SetupCloseArtifactInput,
    SetupDiscoverWritingSampleCandidatesInput,
    SetupEmptyInput,
    SetupMarkAgendaItemInput,
    SetupNarrateProgressInput,
    SetupNoteObservationInput,
    SetupOpenArtifactInput,
    SetupPeekRecentInboxEmailsInput,
    SetupProposeConsentReceiptInput,
    SetupProposeMutationInput,
    SetupProposeSessionAgendaInput,
    SetupProposeWrapUpInput,
    SetupPullInboxEmailForDillInput,
    SetupRequestAgendaItemConfirmationInput,
    SetupSayInput,
    SetupSetChipsInput,
    SetupShowVisualInput,
)


def _format_setup_tool_validation_error(error: Exception) -> str:
    """Turn a tool-argument validation failure into a corrective observation.

    Returned to the model as the tool result (with error status) instead ofraising, so a single malformed argument — e.g. an over-length agenda
    ``intent`` — makes the model retry with fixed arguments rather than aborting the whole setup turn. The raw pydantic detail is included so the
    model knows exactly which field and constraint to correct.
    """

    return (
        "Your tool call was rejected because its arguments failed validation, "
        "and NOTHING was applied. Read the constraint violations below, fix the "
        "offending argument(s), and call the tool again with corrected values:\n"
        f"{error}"
    )


def create_setup_agent_tools_for_factory(factory) -> List[StructuredTool]:
    tools = [
        StructuredTool.from_function(
            coroutine=factory.note_setup_observation,
            name="note_observation",
            description="Surface one concrete setup impression as an animated orientation card.",
            args_schema=SetupNoteObservationInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.narrate_setup_progress,
            name="narrate_progress",
            description=(
                "Tell the user what you are looking at or thinking about right now, "
                "in one short first-person line. Use during orientation while you are "
                "reading discovery facts and forming impressions — not for final notes "
                "(use note_observation) or replies (use say). Transient: only the most "
                "recent narration is shown."
            ),
            args_schema=SetupNarrateProgressInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.set_setup_suggestion_chips,
            name="set_chips",
            description=(
                "Replace the next-step chip row. Use chips as optional, non-exclusive "
                "paths the user can pursue, not as a forced single-choice quiz."
            ),
            args_schema=SetupSetChipsInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.propose_setup_mutation,
            name="propose_mutation",
            description="Create a reviewable setup mutation proposal without executing it.",
            args_schema=SetupProposeMutationInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.propose_setup_consent_receipt,
            name="propose_consent_receipt",
            description="Surface a single inline consent receipt for a setup mutation.",
            args_schema=SetupProposeConsentReceiptInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.open_setup_artifact,
            name="open_artifact",
            description=(
                "Open a structured side-panel artifact for several plausible user-value "
                "setup paths, such as Dill email demos, Paprika project workflows, or "
                "optional breadth to revisit later."
            ),
            args_schema=SetupOpenArtifactInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.add_setup_artifact_row,
            name="add_artifact_row",
            description=(
                "Add one outcome-oriented row to an open setup artifact. Each row should "
                "explain why the path may matter to this user, concrete examples, and "
                "the recommended next step."
            ),
            args_schema=SetupAddArtifactRowInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.close_setup_artifact,
            name="close_artifact",
            description="Close or suggest dismissing a setup artifact.",
            args_schema=SetupCloseArtifactInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.say_setup_message,
            name="say",
            description="Send user-visible Basil setup text.",
            args_schema=SetupSayInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.propose_setup_wrap_up,
            name="propose_wrap_up",
            description=(
                "Surface a user-facing setup wrap-up recap with recommended next steps "
                "and optional breadth. Call once, only after Facts -> Value hypotheses "
                "-> Prioritized paths reasoning is complete; never on the first turn."
            ),
            args_schema=SetupProposeWrapUpInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.discover_setup_email_clients,
            name="discover_email_clients",
            description="Read-only discovery of available email clients.",
            args_schema=SetupEmptyInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.discover_setup_connections,
            name="discover_connections",
            description="Read-only discovery of supported setup connections.",
            args_schema=SetupEmptyInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.discover_setup_local_models,
            name="discover_local_models",
            description="Read-only discovery of local setup model recommendations.",
            args_schema=SetupEmptyInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.discover_setup_profile,
            name="discover_user_profile",
            description="Read-only discovery of existing profile setup facts.",
            args_schema=SetupEmptyInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.discover_setup_writing_sample_candidates,
            name="discover_writing_sample_candidates",
            description="Opt-in discovery of sent-email metadata for writing-sample triage.",
            args_schema=SetupDiscoverWritingSampleCandidatesInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.discover_setup_permissions,
            name="discover_permissions",
            description="Read-only discovery of platform permission catalog.",
            args_schema=SetupEmptyInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.peek_recent_inbox_emails,
            name="peek_recent_inbox_emails",
            description=(
                "Read-only: list the most recent received messages in the user's "
                "primary inbox as metadata only (id, sender, subject, "
                "received_at, is_read). No bodies are pulled. Use this to judge "
                "which message is worth demoing Dill on, then call "
                "pull_inbox_email_for_dill with the id you chose. Re-call with a "
                "different limit if nothing in the first batch is worth using."
            ),
            args_schema=SetupPeekRecentInboxEmailsInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.pull_inbox_email_for_dill,
            name="pull_inbox_email_for_dill",
            description=(
                "Fetch one specific inbox email body by id (from a prior "
                "peek_recent_inbox_emails call), sanitize display HTML, and emit "
                "an inline email-context card into the conversation so the user "
                "can see exactly what was pulled. Required step before proposing "
                "a Dill launch_agent_task receipt grounded in a real email; the "
                "returned email_id auto-stamps onto the receipt's source_email_id."
            ),
            args_schema=SetupPullInboxEmailForDillInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.propose_session_agenda,
            name="propose_session_agenda",
            description=(
                "Set or replace the entire session agenda — the curated list "
                "of goals you intend to work through with the user during "
                "setup. Call once early in the conversation phase after "
                "reviewing the catalog seed in the request's agenda_items "
                "field. Keep items you find useful, reshape titles for the "
                "specific user, drop items you judge irrelevant, and add "
                "agent-authored items as needed. Re-call later only when you "
                "want to restructure the remaining work — partial updates "
                "should use mark_agenda_item instead."
            ),
            args_schema=SetupProposeSessionAgendaInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.mark_agenda_item,
            name="mark_agenda_item",
            description=(
                "Update the status of a single agenda item. Call at the "
                "start of a turn with status='in_progress' when you pick "
                "an item up; call with status='completed' when an action "
                "lands, a demo runs successfully, or the user confirms a "
                "literacy item via the inline confirmation card. Use "
                "'skipped' when the user opts out and 'deferred' when "
                "revisiting later makes sense."
            ),
            args_schema=SetupMarkAgendaItemInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.request_agenda_item_confirmation,
            name="request_agenda_item_confirmation",
            description=(
                "Ask the user whether a literacy or demo agenda item "
                "landed for them. Use this whenever completion isn't "
                "observable from a side-effect (e.g. after explaining "
                "what the status bubble colors mean, or after a Dill "
                "demo). Surfaces an inline Yes / Not quite / Skip card; "
                "the user's response comes back as a system observation "
                "so you can react. Do not mark the item completed "
                "yourself when calling this — wait for the user."
            ),
            args_schema=SetupRequestAgendaItemConfirmationInput,
        ),
        StructuredTool.from_function(
            coroutine=factory.show_setup_visual,
            name="show_setup_visual",
            description=(
                "Surface one inline image from the curated Setup "
                "visuals catalog (see the Setup visuals section of "
                "this system prompt for the full inventory). Use "
                "alongside `say` when working a literacy or demo "
                "agenda item that has a paired visual — show the "
                "menu bar icon instead of describing it in words. "
                "`visual_id` must match a catalog slug exactly; "
                "unknown ids are rejected with a corrective response "
                "listing the available ones."
            ),
            args_schema=SetupShowVisualInput,
        ),
    ]
    for tool in tools:
        tool.handle_validation_error = _format_setup_tool_validation_error
    return tools
