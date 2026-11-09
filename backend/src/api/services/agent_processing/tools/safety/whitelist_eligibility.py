"""Deterministic decision about whether an approved command may be remembered.

One function decides, and it is enforced in three places: the approval event (so the card hides the checkbox), the approval response (so a forged ``remember`` is dropped), and ``WhitelistManager.add_to_whitelist`` (so no caller can store the pattern). Stored patterns that fail the check are also skipped when matching, so an old entry cannot approve arbitrary code.
"""

import shlex
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from .command_words import (
    SHELL_WRAPPERS,
    effective_command,
    is_shell_wrapper,
    normalized_command_name,
    pattern_words,
)

__all__ = ["SHELL_WRAPPERS", "is_shell_wrapper", "normalized_command_name"]

INTERPRETERS = frozenset({"python", "python3", "node", "ruby", "perl", "php", "lua", "osascript", "swift"})

INDIRECTION_COMMANDS = frozenset({"env", "sudo", "xargs", "nohup", "exec", "eval", "time", "open"})

# Only plain shell commands can be remembered; script and automation approvals are always reviewed again.
REMEMBERABLE_EXECUTION_TYPE = "shell"

MAX_ADVICE_REASON_CHARS = 500
MAX_PURPOSE_CHARS = 1000

# A connected-tool call is described to the approval service as `mcp:<connection name>:<tool>(<arguments>)`. As a command pattern that text either carries one call's arguments (and never matches again) or shrinks to the first word of the connection's name (and covers every tool on it), so connected tools are remembered per tool through the connection's tool policy instead.
CONNECTED_TOOL_COMMAND_PREFIX = "mcp:"
CONNECTED_TOOL_ASK_REASON = "This tool is set to ask before it runs"
CONNECTED_TOOL_REMEMBER_REASON = "A connected tool cannot be remembered as a command pattern, because the pattern would cover every tool on that connection. Set this tool to Always allow in Settings → Connections instead."


def is_connected_tool_command(text: str) -> bool:
    """True when the text is the synthetic command Basil builds for a connected-tool call, or a pattern derived from it."""
    return text.lstrip().startswith(CONNECTED_TOOL_COMMAND_PREFIX)

# Tools with many unrelated subcommands, some of which delete, publish, or send data. Remembering only the bare name would approve all of them, so a specific form (git status, gh gist view) is required instead.
BROAD_ONLY_COMMANDS = frozenset({
    "git", "gh", "docker", "kubectl", "helm", "terraform", "aws", "gcloud", "az",
    "curl", "wget", "ssh", "scp", "sftp", "rsync", "nc", "ncat",
    "brew", "npm", "npx", "yarn", "pnpm", "pip", "cargo", "make",
})


@dataclass(frozen=True)
class WhitelistEligibility:
    """Whether a pattern may be remembered, with a plain-language reason when it may not."""

    eligible: bool
    reason: str = ""


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
    enforce_specificity: bool = True,
) -> WhitelistEligibility:
    """Decide whether the pattern chosen for ``command`` may ever be remembered.

    ``enforce_specificity`` additionally refuses a bare name such as ``git`` or ``gh`` that would approve every subcommand. It applies when a pattern is chosen for the user; it is switched off when re-checking a stored pattern (so an older entry keeps working and is only flagged as broad) and for a pattern the user typed themselves.
    """
    if execution_type != REMEMBERABLE_EXECUTION_TYPE:
        return WhitelistEligibility(False, "Scripts and app automation are reviewed every time, so this choice cannot be remembered.")

    if is_connected_tool_command(command) or is_connected_tool_command(generalized_pattern or ""):
        return WhitelistEligibility(False, CONNECTED_TOOL_REMEMBER_REASON)

    if effective_command(command).chained:
        return WhitelistEligibility(
            False,
            "This command chains, pipes, redirects, or substitutes other commands, so Basil asks every time instead of remembering it.",
        )

    pattern = generalized_pattern if generalized_pattern is not None else command
    eligibility = _assess_pattern(pattern)
    if eligibility.eligible and enforce_specificity:
        return _assess_specificity(pattern)
    return eligibility


def _assess_specificity(pattern: str) -> WhitelistEligibility:
    words = pattern_words(pattern)
    if words is not None and len(words) == 1:
        name = normalized_command_name(words[0])
        if name in BROAD_ONLY_COMMANDS:
            return WhitelistEligibility(
                False,
                f"Remembering only {name} would approve every {name} command, so Basil asks every time unless the agent names a specific form such as {name} followed by its subcommand.",
            )
    return WhitelistEligibility(True)


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
