"""Choose the language Whisper should decode, from the user's setting and what the loaded checkpoint supports."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)

AUTO_LANGUAGE = "auto"


def _supported_language_codes(model: Any) -> Optional[Set[str]]:
    """Return the language codes a multilingual Whisper checkpoint knows, or None for a checkpoint with no language tokens (English-only models)."""
    generation_config = getattr(model, "generation_config", None)
    lang_to_id = getattr(generation_config, "lang_to_id", None)
    if not lang_to_id:
        return None
    return {str(token).strip("<|>") for token in lang_to_id}


def whisper_language_kwargs(model: Any, language: Optional[str]) -> Dict[str, Any]:
    """Return pipeline call kwargs that pin the decode language, or an empty dict.

    An empty dict means: the setting is unset or automatic, the checkpoint is English-only, or the checkpoint does not know the language. Whisper then detects the language itself, exactly as before.
    """
    if not language:
        return {}
    code = str(language).strip().lower()
    if not code or code == AUTO_LANGUAGE:
        return {}
    supported = _supported_language_codes(model)
    if supported is None:
        logger.info("Whisper checkpoint has no language tokens; ignoring language setting %r", language)
        return {}
    if code not in supported:
        logger.warning("Whisper checkpoint does not support language %r; using automatic detection", language)
        return {}
    return {"generate_kwargs": {"language": code}}
