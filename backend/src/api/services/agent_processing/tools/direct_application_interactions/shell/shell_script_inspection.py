"""Read the script file an interpreter command is about to run, so the user can inspect it before approving.

The text, path, and SHA-256 travel with the approval. The file is hashed again immediately before execution and the run is refused when it no longer matches what the user approved.
"""

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from api.services.agent_processing.tools.safety.whitelist_eligibility import is_interpreter, is_shell_wrapper

logger = logging.getLogger(__name__)

MAX_SCRIPT_BYTES = 256 * 1024

SCRIPT_TOO_LARGE_NOTICE = "This script is larger than 256 KB, so its text is not shown. Only approve it if you trust where it came from."
SCRIPT_UNREADABLE_NOTICE = "This script is not readable text, so its contents are not shown. Only approve it if you trust where it came from."

# Flags after which the next argument is code or a module name rather than a script path.
_INLINE_CODE_FLAGS = frozenset({"-c", "-e", "-E", "-p", "-r", "-m"})


@dataclass(frozen=True)
class ScriptInspection:
    """The script an approved command will run: its text and fingerprint, or a notice explaining why the text is absent."""

    path: str
    content: Optional[str] = None
    sha256: Optional[str] = None
    notice: Optional[str] = None


def _candidate_script_argument(command: str, args: List[str]) -> Optional[str]:
    """Return the argument that names a script file, or None when the command runs inline code."""
    shell_wrapper = is_shell_wrapper(command)
    if not shell_wrapper and not is_interpreter(command):
        return None
    for argument in args:
        if argument == "--":
            continue
        if argument.startswith("-"):
            if shell_wrapper and not argument.startswith("--") and "c" in argument[1:]:
                return None
            if argument in _INLINE_CODE_FLAGS:
                return None
            continue
        return argument
    return None


def _hash_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def inspect_command_script(command: str, args: Optional[List[str]], cwd: Optional[Path]) -> Optional[ScriptInspection]:
    """Return what the user should see for the script this command runs, or None when it runs no script file."""
    candidate = _candidate_script_argument(command, list(args or []))
    if candidate is None:
        return None
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = (cwd or Path.cwd()) / path
    try:
        resolved = path.resolve()
        if not resolved.is_file():
            return None
        if resolved.stat().st_size > MAX_SCRIPT_BYTES:
            return ScriptInspection(path=str(resolved), notice=SCRIPT_TOO_LARGE_NOTICE)
        raw = resolved.read_bytes()
    except OSError as exc:
        logger.debug("Could not read script %s for approval: %s", path, exc)
        return None
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ScriptInspection(path=str(resolved), notice=SCRIPT_UNREADABLE_NOTICE)
    if "\x00" in content:
        return ScriptInspection(path=str(resolved), notice=SCRIPT_UNREADABLE_NOTICE)
    return ScriptInspection(path=str(resolved), content=content, sha256=_hash_text(content))


def script_changed_since_inspection(inspection: ScriptInspection) -> bool:
    """Return True when an inspected script is gone or differs from the text the user approved."""
    if inspection.sha256 is None:
        return False
    try:
        raw = Path(inspection.path).read_bytes()
        return _hash_text(raw.decode("utf-8")) != inspection.sha256
    except (OSError, UnicodeDecodeError):
        return True
