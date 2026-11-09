"""Turns the backend log into an excerpt that is safe to hand to someone else.

The backend log carries window titles, captured activity, message text and request dumps, none of which may leave the user's Mac in a problem report.
The excerpt therefore uses an allow-list: a line is kept only when it comes from a model, runtime or download module, or names a native model-runtime fault.
A deny-list then removes anything that looks like content, and every kept line is scrubbed of paths, emails and secrets and cut to a fixed length.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Optional

MAX_EXCERPT_LINES = 300
MAX_LINE_CHARS = 300
MAX_BYTES_READ = 4 * 1024 * 1024

ALLOWED_LOGGER_PREFIXES = (
    "api.core.models.reasoning",
    "api.core.models.model_download",
    "api.core.models.models_registry",
    "api.core.models.gpu_manager",
    "api.core.runtime",
    "api.core.services.model_service",
    "api.routes.onboarding",
    "api.routes.model_routes",
    "api.services.transcription",
    "api.services.setup_assistant",
    "api.services.agent_processing.lifecycle.execution_graph.llama_cpp",
)

NATIVE_FAULT_PATTERN = re.compile(
    r"llama_decode|llama_cpp|n_ctx|ggml|kIOGPU|out of memory|MemoryError|MLX|mlx_lm",
    re.IGNORECASE,
)

DENY_PATTERN = re.compile(
    r"request_dump|Text message received|messages=|tools=|prompt|content[=:]|\"role\"|window[_ ]title|SQLITE|activity|\btranscripts?\b|user_message|query=|snippet|subject|body=|e-?mail",
    re.IGNORECASE,
)

_LOGGER_PATTERNS = (
    re.compile(r"^(?:DEBUG|INFO|WARNING|ERROR|CRITICAL):([\w.]+):"),
    re.compile(r"^\d{4}-\d{2}-\d{2} [\d:,]+ - ([\w.]+) - (?:DEBUG|INFO|WARNING|ERROR|CRITICAL) - "),
)

_EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[^\s\"',;]+")
_SECRET_PATTERNS = (
    re.compile(r"(?i)(token|api[_-]?key|authorization|secret|password)([\"'\s:=]+)[^\s\"',;]+"),
    re.compile(r"\b(?:sk|pk|rk|ghp|gho|xox[abp])[-_][A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?=[A-Za-z0-9+=]*\d)(?=[A-Za-z0-9+=]*[A-Za-z])[A-Za-z0-9+=]{40,}\b"),
)


def _logger_name(line: str) -> Optional[str]:
    for pattern in _LOGGER_PATTERNS:
        match = pattern.match(line)
        if match:
            return match.group(1)
    return None


def scrub_line(line: str, home: Optional[str] = None) -> str:
    """Remove the home path, emails and secret-looking values from one line, and cut it to ``MAX_LINE_CHARS``."""
    scrubbed = line.rstrip("\r\n")
    home_text = home if home is not None else str(Path.home())
    if home_text and home_text != "/":
        scrubbed = scrubbed.replace(home_text, "~")
    scrubbed = _EMAIL_PATTERN.sub("[email]", scrubbed)
    scrubbed = _BEARER_PATTERN.sub("Bearer [redacted]", scrubbed)
    scrubbed = _SECRET_PATTERNS[0].sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", scrubbed)
    for pattern in _SECRET_PATTERNS[1:]:
        scrubbed = pattern.sub("[redacted]", scrubbed)
    if len(scrubbed) > MAX_LINE_CHARS:
        scrubbed = scrubbed[:MAX_LINE_CHARS] + " [cut]"
    return scrubbed


def _is_allowed(line: str, previous_kept: bool) -> bool:
    logger_name = _logger_name(line)
    if logger_name is not None:
        if any(logger_name == prefix or logger_name.startswith(prefix + ".") for prefix in ALLOWED_LOGGER_PREFIXES):
            return True
        return bool(NATIVE_FAULT_PATTERN.search(line))
    if NATIVE_FAULT_PATTERN.search(line):
        return True
    # A traceback or wrapped message belongs to the line before it, so it is kept only when that line was kept.
    return previous_kept and (line.startswith((" ", "\t", "Traceback")) or bool(re.match(r"^[A-Za-z_.]+(Error|Exception)\b", line)))


def redact_log_lines(lines: Iterable[str], home: Optional[str] = None) -> List[str]:
    """Keep only the allow-listed lines, drop any that look like content, scrub the rest, and return at most ``MAX_EXCERPT_LINES`` of the latest."""
    kept: List[str] = []
    previous_kept = False
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line.strip():
            previous_kept = False
            continue
        allowed = _is_allowed(line, previous_kept) and not DENY_PATTERN.search(line)
        previous_kept = allowed
        if allowed:
            kept.append(scrub_line(line, home))
    return kept[-MAX_EXCERPT_LINES:]


def read_log_tail_lines(path: Path, max_bytes: int = MAX_BYTES_READ) -> List[str]:
    """The last ``max_bytes`` of a log file as lines, or an empty list when it cannot be read. A cut first line is dropped."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            start = max(0, size - max_bytes)
            handle.seek(start)
            data = handle.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    if start > 0 and lines:
        lines = lines[1:]
    return lines


def redacted_log_excerpt(path: Path, home: Optional[str] = None) -> str:
    """The redacted excerpt for one log file as text. The result says so when nothing relevant was found."""
    kept = redact_log_lines(read_log_tail_lines(path), home)
    if not kept:
        return "No model, runtime or download lines were found in the recent log.\n"
    return "\n".join(kept) + "\n"
