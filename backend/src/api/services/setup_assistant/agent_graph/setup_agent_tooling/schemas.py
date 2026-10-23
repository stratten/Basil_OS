"""Pydantic input schemas for setup-agent tools."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from api.routes.setup_assistant.models import (
    SetupArtifactKind,
    SetupOrientationTone,
    SetupPrivacyImpact,
    SetupSessionAgendaItemKind,
    SetupSessionAgendaItemSource,
    SetupSessionAgendaItemStatus,
)

SETUP_MESSAGE_DELTA_CHARS = 18
SETUP_MESSAGE_DELTA_DELAY_SECONDS = 0.03


class SetupSuggestionChipInput(BaseModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    message: str = Field(min_length=1)
    preliminary_status_message: Optional[str] = Field(
        default=None,
        max_length=120,
        description=(
            "Optional immediate status line the UI can show as soon as "
            "the user clicks this chip, before the next agent turn streams."
        ),
    )


class SetupNoteObservationInput(BaseModel):
    label: str = Field(min_length=1)
    title: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    tone: SetupOrientationTone = SetupOrientationTone.ready


class SetupNarrateProgressInput(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=120,
        description=(
            "One short first-person status line describing what you are actively "
            "looking at or thinking about right now. Transient; only the most "
            "recent narration is shown."
        ),
    )


class SetupSetChipsInput(BaseModel):
    chips: List[SetupSuggestionChipInput] = Field(default_factory=list, max_length=4)


class SetupProposeMutationInput(BaseModel):
    proposal_id: Optional[str] = None
    title: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    payload: Dict[str, Any] = Field(default_factory=dict)
    privacy_impact: SetupPrivacyImpact = SetupPrivacyImpact.none
    mutates_external_state: bool = False
    required_permissions: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_appearance_settings_payload(self) -> "SetupProposeMutationInput":
        if self.tool_name != "update_basil_settings":
            return self
        settings = self.payload.get("settings")
        ui_updates = settings.get("ui") if isinstance(settings, dict) else None
        if not isinstance(ui_updates, dict):
            return self
        from api.services.setup_assistant.action_execution_service import validate_ui_settings_payload

        validate_ui_settings_payload(ui_updates)
        return self


class SetupProposeConsentReceiptInput(BaseModel):
    proposal_id: Optional[str] = None
    title: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    mutation_tool_name: str = Field(min_length=1)
    mutation_payload: Dict[str, Any] = Field(default_factory=dict)
    privacy_impact: SetupPrivacyImpact = SetupPrivacyImpact.none
    mutates_external_state: bool = False
    required_permissions: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_launch_agent_task_payload(self) -> "SetupProposeConsentReceiptInput":
        # Paprika launches are routed through the native bridge, which requires
        # a non-empty prompt string. Reject malformed receipts at proposal time
        # with a corrective message so the agent self-corrects on the next step
        # instead of letting the user see a "failed" card after they approve.
        #
        # Note: mutation_payload["model_id"] is intentionally NOT required here.
        # The setup runtime auto-stamps it from the current setup-agent model
        # selection so launch-from-setup tasks inherit the same route the setup
        # agent is using (default = free proxy). See _stamp_setup_model_id_for_launch
        # in proposal_tools.py for the stamping path and its hard assertion that
        # guarantees no launch_agent_task receipt reaches the user without a
        # model_id. If the agent wants to explicitly override the route it can
        # still pass mutation_payload["model_id"]; otherwise the runtime fills it.
        if self.mutation_tool_name != "launch_agent_task":
            return self
        prompt_value = self.mutation_payload.get("prompt")
        if not isinstance(prompt_value, str) or not prompt_value.strip():
            raise ValueError(
                "launch_agent_task consent receipts must include "
                "mutation_payload['prompt'] as a non-empty task string. "
                "Ask the user what they want Paprika to do, then re-propose "
                "with the confirmed task embedded as the prompt."
            )
        return self

    @model_validator(mode="after")
    def _validate_appearance_settings_payload(self) -> "SetupProposeConsentReceiptInput":
        # Mirrors the execution-time check in action_execution_service.py so a
        # malformed appearance proposal (bad RGB range, unknown ui key, a font
        # outside the catalog) self-corrects here instead of reaching the user
        # as a receipt that later fails on approval.
        if self.mutation_tool_name != "update_basil_settings":
            return self
        settings = self.mutation_payload.get("settings")
        ui_updates = settings.get("ui") if isinstance(settings, dict) else None
        if not isinstance(ui_updates, dict):
            return self
        from api.services.setup_assistant.action_execution_service import validate_ui_settings_payload

        validate_ui_settings_payload(ui_updates)
        return self


class SetupOpenArtifactInput(BaseModel):
    artifact_id: str = Field(min_length=1)
    kind: SetupArtifactKind
    title: str = Field(min_length=1)
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional artifact context. For prioritized setup paths, include a concise "
            "summary of the value hypothesis and why a side panel is useful."
        ),
    )


class SetupAddArtifactRowInput(BaseModel):
    artifact_id: str = Field(min_length=1)
    row_id: str = Field(min_length=1)
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "One user-value path. Prefer keys: title, why_this_might_matter, "
            "example_use_cases, recommended_next_step, priority, and defer_message."
        ),
    )
    receipt: Optional[SetupProposeConsentReceiptInput] = None


class SetupCloseArtifactInput(BaseModel):
    artifact_id: str = Field(min_length=1)


class SetupSayInput(BaseModel):
    content: str = Field(min_length=1)


class SetupProposeWrapUpInput(BaseModel):
    recap: str = Field(
        min_length=1,
        description=(
            "User-facing recap of what was configured during setup. Should reflect the "
            "actual Facts -> Value hypotheses -> Prioritized paths reasoning, not a generic "
            "all-set message."
        ),
    )
    recommended_next_steps: List[SetupSuggestionChipInput] = Field(
        default_factory=list,
        max_length=4,
        description=(
            "0-4 concrete next-step chips the user can act on. Each chip's message is a "
            "ready-to-send conversation prompt."
        ),
    )
    optional_breadth: Optional[str] = Field(
        default=None,
        description=(
            "Optional one-paragraph note on what Basil capabilities can be deferred. "
            "Leave None when nothing meaningful is being deferred."
        ),
    )


class SetupDiscoverWritingSampleCandidatesInput(BaseModel):
    days_back: int = Field(default=14, ge=1, le=60)
    limit: int = Field(default=25, ge=1, le=50)


class SetupPeekRecentInboxEmailsInput(BaseModel):
    """Input for the metadata-only inbox peek that feeds Dill demo selection.

    The agent calls this first, reads the returned metadata, and decides
    which message is worth using for a Dill reply demo. No bodies are
    fetched at this step; body retrieval happens in the follow-up
    ``pull_inbox_email_for_dill`` call against the chosen id.
    """

    limit: int = Field(
        default=10,
        ge=1,
        le=25,
        description=(
            "How many recent received messages from the primary inbox to "
            "surface as candidates. Metadata only; no bodies are fetched."
        ),
    )


class SetupPullInboxEmailForDillInput(BaseModel):
    """Input for pulling one specific inbox email body for the Dill demo.

    ``email_id`` MUST come from a prior ``peek_recent_inbox_emails`` call
    in the same turn — this tool intentionally has no fallback to
    "most recent" so the agent (not code) decides which message to demo on.
    """

    email_id: str = Field(
        min_length=1,
        description=(
            "The id of the email to pull, as returned by "
            "peek_recent_inbox_emails. Required; this tool will not "
            "improvise a choice."
        ),
    )
    max_excerpt_chars: int = Field(
        default=2000,
        ge=200,
        le=8000,
        description="Hard cap on the returned body excerpt length, in characters.",
    )


class SetupEmptyInput(BaseModel):
    pass


class SetupAgendaItemInput(BaseModel):
    """One entry the agent submits via ``propose_session_agenda``.

    Mirrors ``SetupSessionAgendaItem`` from the route models but lives
    here so the agent-tool input layer doesn't reach across into the
    route schema for what is functionally a tool-input contract.
    Defaults match the seed shape: agent-authored, pending, no
    completion basis yet.
    """

    id: str = Field(
        min_length=1,
        description=(
            "Stable identifier for this agenda item. Reuse catalog ids "
            "verbatim (e.g. 'intro_dill') when keeping a seeded item, "
            "or invent a slug like 'custom_explain_voice_notes' for an "
            "agent-authored addition."
        ),
    )
    title: str = Field(
        min_length=1,
        max_length=80,
        description=(
            "Short, user-facing label that appears in the sidebar. "
            "Action-shaped where natural, e.g. 'Show what Paprika can do'. "
            "Hard cap: at most 80 characters."
        ),
    )
    intent: str = Field(
        min_length=1,
        max_length=480,
        description=(
            "One-sentence rationale shown on hover and used in your own "
            "internal tracking. Phrase it from the user's benefit angle. "
            "Hard cap: at most 480 characters — keep it to a single tight "
            "sentence, since an over-length value rejects the whole call."
        ),
    )
    kind: SetupSessionAgendaItemKind = Field(
        description=(
            "One of: action (changes state), demo (capability showcase), "
            "literacy (UI walkthrough), conversational (discussion item)."
        ),
    )
    source: SetupSessionAgendaItemSource = SetupSessionAgendaItemSource.agent
    status: SetupSessionAgendaItemStatus = SetupSessionAgendaItemStatus.pending
    completion_basis: Optional[str] = None


class SetupProposeSessionAgendaInput(BaseModel):
    """Wholesale replacement of the session agenda."""

    items: List[SetupAgendaItemInput] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Ordered list of agenda items. Capped at 20 so the sidebar "
            "doesn't become a wall of text; trim aggressively."
        ),
    )


class SetupMarkAgendaItemInput(BaseModel):
    """Update the status of a single agenda item."""

    id: str = Field(
        min_length=1,
        description="The agenda item id to update.",
    )
    status: SetupSessionAgendaItemStatus = Field(
        description=(
            "New status: in_progress when you pick the item up, "
            "completed when it's unambiguously done, skipped when the "
            "user opts out, deferred when revisiting later makes sense."
        ),
    )
    completion_basis: Optional[str] = Field(
        default=None,
        max_length=240,
        description=(
            "Short note on why you marked it this way (e.g. 'user "
            "approved Dill receipt and Dill returned a draft'). Captured "
            "for transcripts and debugging; not rendered to the user."
        ),
    )


class SetupRequestAgendaItemConfirmationInput(BaseModel):
    """Ask the user whether a literacy/demo item landed.

    Use this when the item has no observable side-effect to confirm
    completion (literacy walkthroughs, capability demos the user just
    watched). The frontend renders an inline card with Yes / Not quite
    / Skip; the user's response comes back as a system observation so
    you can react in the next turn.
    """

    agenda_item_id: str = Field(
        min_length=1,
        description="The agenda item id this confirmation is about.",
    )
    prompt: str = Field(
        min_length=1,
        max_length=200,
        description=(
            "First-person check, phrased as a sincere question, e.g. "
            "'Did that give you a clear sense of how Paprika could "
            "help you?' Keep it short."
        ),
    )


class SetupShowVisualInput(BaseModel):
    """Surface one inline visual from the curated setup catalog.

    Use this whenever you're working a `literacy` or `demo` agenda
    item that has a paired visual (the `default_visual_id` field
    on the seeded agenda item, or any other matching catalog entry
    listed in the system prompt). Pairs naturally with `say` so
    the conversation gets both the visual and the framing prose at
    once — don't describe the UI in words when you can show it.
    """

    visual_id: str = Field(
        min_length=1,
        description=(
            "Catalog slug from the Setup visuals inventory in the "
            "system prompt (e.g. 'menu_bar_idle_vs_recording'). "
            "Unknown slugs are rejected at the tool boundary; the "
            "tool returns a corrective string listing available ids."
        ),
    )
    caption_override: Optional[str] = Field(
        default=None,
        max_length=240,
        description=(
            "Optional in-the-moment caption that replaces the catalog "
            "default for this one emission. Use sparingly; the catalog "
            "captions are written to be reusable. Useful when you want "
            "to tie the visual to something the user just said."
        ),
    )
