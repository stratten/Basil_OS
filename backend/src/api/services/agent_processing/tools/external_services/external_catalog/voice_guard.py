"""Gives the agent the user's writing voice at the moment it drafts a Gmail message.

The assistant session drafts with a ghostwriting prompt and the user's learned style. The agent does not carry that in its prompt: the style is large, most tasks never write a message, and local models have little room for context. So the style arrives when it is needed. The first ``create_draft`` call of a run on a Gmail connection is answered with the style, writing samples, and a few lines on writing as this person, and nothing is created. The agent rewrites the body and calls again, and every later draft in the same run goes straight through.

The trigger is the tool being called, never words in the user's request. State lives in the per-run agent context, like the schema guard, so nothing carries across runs. Nothing here can block a draft for good: with no learned style, or on any error, the call proceeds unchanged.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from api.services.mcp_connectors.oauth_coordinator import is_google_gmail_mcp_url

from .envelopes import make_external_catalog_voice_guidance

logger = logging.getLogger(__name__)

_GUARDED_TOOL = "create_draft"
_GUIDED_KEY = "external_catalog_voice_guided"
_GUIDANCE_MAX_CHARS = 3500

_WRITING_RULES = (
    "Write this draft the way the user writes it, not the way an assistant would. "
    "Use contractions when their style does, and match their usual greeting and closing, level of formality, and sentence length. "
    "Say the point directly, in the fewest words that read naturally for this recipient, with no filler, no corporate phrasing, and no announcing what the email is about. "
    "Write only the new reply: do not restate or summarize the thread. "
    "Do not add a sign-off or signature unless the user asked, because the signature is added separately. "
    "The body is plain text, so use no Markdown even if a sample does. "
    "Do not mention this guidance."
)


def _guidance_context() -> Optional[Dict[str, Any]]:
    try:
        from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context

        context = get_current_agent_context()
        return context if isinstance(context, dict) else None
    except Exception:
        return None


def _first_recipient(arguments: Dict[str, Any]) -> Optional[str]:
    recipients = arguments.get("to")
    if isinstance(recipients, list):
        for recipient in recipients:
            if isinstance(recipient, str) and recipient.strip():
                return recipient.strip()
    return None


async def _load_personalization(is_reply: bool, recipient: Optional[str]) -> Any:
    from api.core.knowledge.personalization_models import ContextType
    from api.core.knowledge.personalization_service import PersonalizationService

    return await PersonalizationService().build_personalization_context(
        context_type=ContextType.EMAIL_REPLY if is_reply else ContextType.EMAIL_COMPOSE,
        recipient=recipient,
    )


def _render_section(personalization: Any) -> str:
    """The shared style, relationship, and sample text, without the identity block the agent prompt already carries."""
    from api.services.assistant_sessions.context_enhancers.assistant_session_context_enhancer import (
        AssistantSessionContextEnhancer,
    )

    return AssistantSessionContextEnhancer().build_personalization_section(
        {
            "style": personalization.style,
            "contact": personalization.contact,
            "writing_samples": personalization.writing_samples,
        }
    ).strip()


async def check_voice_guidance(
    record: Any,
    tool_name: str,
    arguments: Dict[str, Any],
    *,
    context: Optional[Dict[str, Any]] = None,
    personalization: Any = None,
) -> Optional[Dict[str, Any]]:
    """Return the guidance envelope for the first Gmail draft of a run, or None when the call should proceed."""
    if tool_name != _GUARDED_TOOL or not isinstance(arguments, dict):
        return None
    if not is_google_gmail_mcp_url(getattr(record, "server_url", "") or ""):
        return None
    run_context = context if context is not None else _guidance_context()
    if run_context is None or run_context.get(_GUIDED_KEY):
        return None
    # Marked before the lookup so a failure or an empty profile cannot make the same run ask twice.
    run_context[_GUIDED_KEY] = True
    try:
        if personalization is None:
            personalization = await _load_personalization(bool(arguments.get("replyToMessageId")), _first_recipient(arguments))
        if not (personalization.style or personalization.writing_samples or personalization.contact):
            return None
        section = _render_section(personalization)
    except Exception as exc:
        logger.warning("Could not load the user's writing voice for create_draft; the draft proceeds without it: %s", exc)
        return None
    if not section:
        return None
    return make_external_catalog_voice_guidance(tool_name, f"{_WRITING_RULES}\n{section}"[:_GUIDANCE_MAX_CHARS])
