"""Agent task title generation helpers."""

import re

_AGENT_TASK_PREFIX_PATTERN = re.compile(
    r'^(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?|'
    r'(?:please\s+)?(?:help\s+(?:me|us)\s+(?:to\s+)?)?|'
    r'i(?:\'d|\s+would)\s+like\s+(?:you\s+)?to\s+|'
    r'i\s+(?:want|need)\s+(?:you\s+)?to\s+|'
    r'go\s+ahead\s+and\s+|'
    r'please\s+)',
    re.IGNORECASE,
)


def generate_heuristic_title(agent_task_text: str, max_length: int = 50) -> str:
    """Strip conversational prefixes and return a concise title."""
    text = agent_task_text.strip()
    text = _AGENT_TASK_PREFIX_PATTERN.sub('', text).strip()
    if not text:
        text = agent_task_text.strip()
    text = text[0].upper() + text[1:] if text else text
    if len(text) <= max_length:
        return text
    truncated = text[:max_length].rsplit(' ', 1)[0]
    return truncated + '...' if truncated != text else text
