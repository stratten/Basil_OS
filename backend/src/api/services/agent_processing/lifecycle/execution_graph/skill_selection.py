"""Agent-owned saved-skill selection.

This module asks the agent model whether one saved skill should be loaded in
full before execution. The relevance decision is made by the model judging the
catalog metadata semantically; the backend never matches skills heuristically.
It only presents the catalog, validates the model's chosen slug against the
known catalog, and reports the selection.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from .agent_json_decision import parse_json_object_response as _parse_json_object_response
from .agent_model_caller import call_agent_model_with_messages

logger = logging.getLogger(__name__)

# Keep the decision cheap: this is a single non-streaming classification call.
_DECISION_MAX_TOKENS = 400


@dataclass(frozen=True)
class SkillSelection:
    """The agent's decision about which saved skill (if any) to load."""

    slug: Optional[str]
    reason: str


def _catalog_listing(catalog_entries: Sequence[Any]) -> str:
    """Render catalog entries as a compact, model-readable listing."""
    lines: List[str] = []
    for entry in catalog_entries:
        triggers = list(getattr(entry, "triggers", []) or [])
        triggers_text = "; ".join(triggers) if triggers else "(none)"
        lines.append(
            f"- slug: {entry.slug}\n"
            f"  title: {entry.title}\n"
            f"  when_to_use: {entry.when_to_use}\n"
            f"  triggers: {triggers_text}"
        )
    return "\n".join(lines)


def _normalize_slug(raw_slug: Any) -> Optional[str]:
    """Coerce a model-provided slug into a clean string, or None."""
    if raw_slug is None:
        return None
    slug = str(raw_slug).strip()
    if not slug or slug.lower() in {"null", "none", ""}:
        return None
    return slug


async def select_relevant_skill(
    model: Any,
    user_request: str,
    catalog_entries: Sequence[Any],
) -> SkillSelection:
    """Ask the agent model whether one saved skill should be loaded for this request.

    Returns a SkillSelection whose slug is either a validated catalog slug or None.
    Any failure (no model, bad JSON, hallucinated slug) resolves to no selection.
    """
    if not catalog_entries:
        return SkillSelection(slug=None, reason="No saved skills are available.")

    if model is None:
        return SkillSelection(slug=None, reason="No reasoning model available for skill selection.")

    known_slugs = {entry.slug for entry in catalog_entries}
    listing = _catalog_listing(catalog_entries)

    system_message = (
        "You decide whether one of the user's saved skills should be loaded in full "
        "before you begin working on their request. A saved skill is a reusable "
        "procedure the user previously approved. Judge relevance semantically from the "
        "catalog metadata (title, when_to_use, triggers); do not rely on literal word "
        "overlap. Choose at most ONE skill whose full procedure should be loaded, or "
        "choose none if no saved skill is clearly relevant. Loading a skill is optional "
        "and additive; you will still be able to search and load other skills later.\n\n"
        "Respond with ONLY a JSON object and no other text, in exactly this shape:\n"
        '{"slug": "<one catalog slug, or null>", "reason": "<one short sentence>"}'
    )

    user_message = (
        f"USER REQUEST:\n{user_request}\n\n"
        f"SAVED SKILL CATALOG:\n{listing}\n\n"
        "Pick the single most relevant saved skill to load now, or null if none clearly applies."
    )

    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]

    response_text = await call_agent_model_with_messages(
        model,
        messages,
        enable_web_search=False,
        max_tokens=_DECISION_MAX_TOKENS,
    )

    try:
        payload = _parse_json_object_response(response_text)
    except (TypeError, json.JSONDecodeError) as exc:
        preview = (str(response_text) or "").strip().replace("\n", "\\n")[:240]
        logger.info(
            "Skill selection returned non-JSON; treating as no selection. error=%s preview=%r",
            exc,
            preview,
        )
        return SkillSelection(slug=None, reason="Model response was not valid JSON.")

    reason = str(payload.get("reason") or "").strip() or "No reason provided."
    slug = _normalize_slug(payload.get("slug"))

    if slug is None:
        return SkillSelection(slug=None, reason=reason)

    if slug not in known_slugs:
        logger.info(
            "Skill selection returned unknown slug %r; treating as no selection.",
            slug,
        )
        return SkillSelection(slug=None, reason=f"Model selected unknown skill '{slug}'.")

    return SkillSelection(slug=slug, reason=reason)
