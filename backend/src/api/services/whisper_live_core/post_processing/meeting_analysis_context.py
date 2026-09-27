"""Identity and capability context for meeting analysis prompts.

These helpers give the meeting follow-up planner two pieces of context it was
previously missing:

1. WHO the user is (first-person framing) so named speakers like the user are
   not treated as third parties ("remind <name>") but as the person Basil is
   helping directly.
2. WHAT the agentTask delegate ("Paprika") can actually do, including which
   external integrations (MCP servers such as Speakeasy) are connected, so the
   planner can frame delegated instructions (e.g. a scheduled Salesforce export
   via a connected integration) instead of defaulting every future-dated item
   to a reminder.

All functions are synchronous and side-effect free aside from reading local
preferences (no network, no secrets). They are intentionally defensive: any
failure degrades to an empty/minimal string so analysis never breaks.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from api.core.knowledge.personalization_models import UserProfile

logger = logging.getLogger(__name__)


# Static fallback used only when the dynamic tool-family catalog cannot be
# loaded. Mirrors the capabilities the agentTask delegate exposes today.
_STATIC_CAPABILITY_FALLBACK = (
    "BASIL AGENT CAPABILITIES (the agentTask delegate executes these after the user approves):\n"
    "- Draft emails or messages, but do not claim to send unless the user approves later.\n"
    "- Create reminders, notes, calendar events, or simple app automations through macOS automation.\n"
    "- Help with documents, files, summaries, searches, and research.\n"
    "- Help with project or developer work through approved file/shell workflows.\n"
    "- Run autonomous work at a future time via its scheduling capability.\n"
    "- Ask for missing information when a task lacks recipients, dates, file names, permissions, or target apps."
)


def format_user_identity_block(profile: Optional[UserProfile]) -> str:
    """Render a first-person identity block for the analysis prompt.

    Returns an empty string when no profile (or no usable identity fields)
    exist, so the prompt simply omits the section.
    """
    if profile is None:
        return ""

    name = (profile.preferred_name or profile.full_name or "").strip()

    role_parts = []
    if profile.job_title:
        role_parts.append(profile.job_title.strip())
    if profile.company_name:
        role_parts.append(f"at {profile.company_name.strip()}")
    role_clause = (" " + " ".join(role_parts)) if role_parts else ""

    # Nothing useful to say about identity.
    if not name and not role_clause:
        return ""

    subject = name if name else "the user"

    lines = ["USER IDENTITY (read this first):"]
    lines.append(
        f"- This transcript was recorded by {subject}{role_clause}. "
        f"You are assisting {subject} directly."
    )
    lines.append(
        f"- When a speaker label in the transcript refers to {subject}, that "
        f"speaker IS the user you are helping - not a third party."
    )
    lines.append(
        f"- Frame help as actions Basil performs FOR {subject} (e.g. 'draft the "
        f"email', 'schedule the export'), never as reminders telling {subject} "
        f"to do something themselves when Basil can do it."
    )
    lines.append(
        f"- In every user-facing explanation or summary, address {subject} "
        f"directly in the second person (\"you\", \"your\") rather than describing "
        f"{subject} in the third person."
    )
    if profile.email:
        lines.append(f"- The user's email address is {profile.email.strip()}.")

    return "\n".join(lines)


def _format_speaker_attribution(
    *,
    member_sources: Optional[List[Tuple[str, bool]]] = None,
    single_source: Optional[str] = None,
) -> str:
    """Bind the user's own audio track to the second person in the transcript.

    The transcript never contains the user's name; speaker labels are derived
    from each recording's audio source. This block tells the model which label
    is the user's own speech so it stops treating the user as a third party.

    Args:
        member_sources: For multi-track meetings, ``(source_label, is_microphone)``
            tuples in transcript order. The microphone member is the user.
        single_source: For single-track meetings, that lone recording's
            ``audio_source``.

    Returns an empty string whenever the user's track cannot be identified (a
    multi-track meeting with no microphone member, or a single non-microphone
    track), so the prompt omits the binding rather than guessing.
    """
    if member_sources:
        mic_label = next(
            (source for source, is_microphone in member_sources if is_microphone),
            None,
        )
        if not mic_label:
            return ""

        other_labels = [
            source
            for source, is_microphone in member_sources
            if not is_microphone and source != mic_label
        ]

        lines = ["SPEAKER ATTRIBUTION (who is who in this transcript):"]
        lines.append(
            f"- Your own speech is labeled \"{mic_label}\" (every line that begins "
            f"with \"{mic_label}\"). That speaker is you - the person being assisted."
        )
        if other_labels:
            lines.append(
                f"- The other participants speak under: {', '.join(other_labels)}. "
                f"They are the people you met with, not you."
            )
        lines.append(
            "- Attribute anything you said or agreed to in the second person "
            "(\"you said\", \"you agreed to\"), and attribute the other labels to "
            "the other participants."
        )
        return "\n".join(lines)

    if (single_source or "").strip().lower() == "microphone":
        return (
            "SPEAKER ATTRIBUTION (who is who in this transcript):\n"
            "- This is your own microphone recording, so you are the primary "
            "speaker. Any other speaker labels are people who were present with "
            "you.\n"
            "- Attribute your own statements to yourself in the second person "
            "(\"you said\", \"you agreed to\")."
        )

    return ""


def build_identity_block(
    profile: Optional[UserProfile],
    *,
    member_sources: Optional[List[Tuple[str, bool]]] = None,
    single_source: Optional[str] = None,
) -> str:
    """Compose the user identity block with the speaker-attribution binding.

    Combines :func:`format_user_identity_block` (who the user is, second-person
    framing) with :func:`_format_speaker_attribution` (which transcript label is
    the user). Either part may be empty; whichever parts exist are joined with a
    blank line so every analysis mode receives consistent context.
    """
    identity = format_user_identity_block(profile)
    attribution = _format_speaker_attribution(
        member_sources=member_sources,
        single_source=single_source,
    )
    return "\n\n".join(part for part in (identity, attribution) if part)


def build_capability_digest(*, preferences: object = None) -> str:
    """Build a prompt-ready digest of what the agentTask delegate can do.

    Consumes the SAME canonical thin-definition surface the agent task runner
    routes on (:func:`render_family_routing_catalog`, including per-family
    ``when_to_load``/``routing_hints``/``examples`` and the live connected
    services), composed with the secret-free connection capability inventory
    and an explicit note about scheduled delegated work. The planner therefore
    sees exactly what the runner can do, not a lossy paraphrase. Falls back to a
    static capability list only if the catalog cannot be loaded.
    """
    lines = [
        "BASIL AGENT CAPABILITIES (the agentTask delegate, which executes a "
        "proposal after the user approves it):"
    ]

    try:
        from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_family_catalog import (
            render_family_routing_catalog,
        )

        family_catalog = render_family_routing_catalog()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not load tool-family catalog for meeting analysis digest: %s", exc)
        return _STATIC_CAPABILITY_FALLBACK

    if not family_catalog or not family_catalog.strip():
        return _STATIC_CAPABILITY_FALLBACK

    lines.append(family_catalog)

    try:
        from api.services.agent_processing.tools.external_services.external_connection_inventory import (
            render_connection_inventory_for_description,
        )

        if preferences is not None:
            connection_block = render_connection_inventory_for_description(preferences=preferences)
        else:
            connection_block = render_connection_inventory_for_description()
        if connection_block:
            lines.append("")
            lines.append(connection_block)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not load connection inventory for meeting analysis digest: %s", exc)

    lines.append("")
    lines.append(
        "SCHEDULING: When a useful follow-up should happen at a specific future "
        "time AND maps to a capability or connected integration above, do not "
        "downgrade it to a reminder. Frame it as a scheduled delegated agent "
        "task: state the date/time (with timezone), the concrete action, and "
        "that the agent should perform and monitor it (e.g. via a connected "
        "integration such as Salesforce through Speakeasy when present)."
    )

    return "\n".join(lines)
