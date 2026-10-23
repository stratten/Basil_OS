"""Deterministic decision about whether an approved command may be remembered.

One function decides, and it is enforced in three places: the approval event (so the card hides the checkbox), the approval response (so a forged ``remember`` is dropped), and ``WhitelistManager.add_to_whitelist`` (so no caller can store the pattern). Stored patterns that fail the check are also skipped when matching, so an old entry cannot approve arbitrary code.
"""

import os
import re
import shlex
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

SHELL_WRAPPERS = frozenset({"bash", "sh", "zsh", "fish", "dash", "ksh"})

INTERPRETERS = frozenset({"python", "python3", "node", "ruby", "perl", "php", "lua", "osascript", "swift"})

INDIRECTION_COMMANDS = frozenset({"env", "sudo", "xargs", "nohup", "exec", "eval", "time", "open"})

# Only plain shell commands can be remembered; script and automation approvals are always reviewed again.
REMEMBERABLE_EXECUTION_TYPE = "shell"

MAX_ADVICE_REASON_CHARS = 500
MAX_PURPOSE_CHARS = 1000

_VERSION_SUFFIX = re.compile(r"[\d.]+$")


@dataclass(frozen=True)
class WhitelistEligibility:
    """Whether a pattern may be remembered, with a plain-language reason when it may not."""

    eligible: bool
    reason: str = ""


def normalized_command_name(token: str) -> str:
    """Return the lowercase executable name without its directory or trailing version digits (python3.11 becomes python)."""
    base = os.path.basename(token.strip()).lower()
    stripped = _VERSION_SUFFIX.sub("", base)
    return stripped or base


def is_shell_wrapper(token: str) -> bool:
    return normalized_command_name(token) in SHELL_WRAPPERS


def is_interpreter(token: str) -> bool:
    return normalized_command_name(token) in INTERPRETERS


def _inner_command_of_wrapper(tokens: list[str]) -> Optional[list[str]]:
    """Return the tokens after the wrapper's -c style flag, or None when the wrapper has no inner command."""
    for index in range(1, len(tokens)):
        token = tokens[index]
        if token.startswith("-") and "c" in token:
            inner = tokens[index + 1:]
            return inner or None
        if not token.startswith("-"):
            return None
    return None


def assess_whitelist_eligibility(
    command: str,
    generalized_pattern: Optional[str] = None,
    *,
    execution_type: str = REMEMBERABLE_EXECUTION_TYPE,
) -> WhitelistEligibility:
    """Decide whether the pattern generalized from ``command`` may ever be remembered."""
    if execution_type != REMEMBERABLE_EXECUTION_TYPE:
        return WhitelistEligibility(False, "Scripts and app automation are reviewed every time, so this choice cannot be remembered.")

    pattern = generalized_pattern if generalized_pattern is not None else command
    return _assess_pattern(pattern)


def _assess_pattern(pattern: str) -> WhitelistEligibility:
    try:
        tokens = shlex.split(pattern)
    except ValueError:
        return WhitelistEligibility(False, "Basil could not read this command safely enough to remember it.")
    if not tokens:
        return WhitelistEligibility(False, "There is nothing specific to remember for an empty command.")

    name = normalized_command_name(tokens[0])
    if name in SHELL_WRAPPERS:
        inner = _inner_command_of_wrapper(tokens)
        if inner is None:
            return WhitelistEligibility(False, f"A bare {name} would allow any command or script, so Basil asks every time.")
        return _assess_pattern(" ".join(shlex.quote(token) for token in inner))
    if name in INTERPRETERS:
        return WhitelistEligibility(False, f"{name} can run any code, so Basil asks every time instead of remembering it.")
    if name in INDIRECTION_COMMANDS:
        return WhitelistEligibility(False, f"{name} runs other commands on its behalf, so Basil asks every time instead of remembering it.")
    return WhitelistEligibility(True)


def normalize_purpose(value: Any) -> Optional[str]:
    """Return the agent's explanation as trimmed text, or None when it is missing or blank."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text[:MAX_PURPOSE_CHARS]


def normalize_whitelist_advice(
    raw: Any,
    eligibility: WhitelistEligibility,
    *,
    purpose: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Return the advice the card may show.

    The agent can only argue for remembering. The server downgrades the advice to "no" whenever the pattern is ineligible, and shows no advice at all when the agent gave no explanation or malformed advice.
    """
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    if purpose is None or not isinstance(raw, Mapping):
        return None
    recommend = raw.get("recommend")
    reason = raw.get("reason")
    if isinstance(recommend, str):
        answer = recommend.strip().lower()
        recommend = True if answer in {"yes", "true"} else False if answer in {"no", "false"} else None
    if not isinstance(recommend, bool) or not isinstance(reason, str) or not reason.strip():
        return None
    if recommend and not eligibility.eligible:
        return {"recommend": False, "reason": eligibility.reason, "downgraded": True}
    return {"recommend": recommend, "reason": reason.strip()[:MAX_ADVICE_REASON_CHARS], "downgraded": False}
