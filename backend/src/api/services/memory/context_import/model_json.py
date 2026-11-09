"""Reading the JSON a model returns, which small local models often wrap in fences, thinking blocks or prose."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


class ModelJsonError(ValueError):
    """The model's answer held no JSON object that could be read."""


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

# Some local models write their reasoning in the answer itself, outside any think tags, and only then give the JSON. Asking for the JSON alone, and asking again more firmly after an unreadable answer, keeps that from using the whole output budget.
JSON_ONLY_INSTRUCTION = " Do not write out your reasoning, drafts or checks. Your whole reply is the JSON object, so its first character is an opening brace."
RETRY_REMINDER = "That answer could not be read. Reply again with only the JSON object: no explanation, no reasoning, no drafts, and no code fence."


def retry_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """The same request with a firm reminder at the end, so a second try is not a repeat of the first."""
    return [*messages, {"role": "user", "content": RETRY_REMINDER}]


def _last_object(text: str) -> Optional[Dict[str, Any]]:
    """The last complete top-level JSON object in ``text``, which is the final answer when the model reasoned first and drafted JSON along the way."""
    decoder = json.JSONDecoder()
    found: Optional[Dict[str, Any]] = None
    index = text.find("{")
    while index != -1:
        try:
            value, end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            index = text.find("{", index + 1)
            continue
        if isinstance(value, dict):
            found = value
        index = text.find("{", end)
    return found


def parse_model_json(text: str) -> Dict[str, Any]:
    """Return the JSON object in ``text``. Raises ModelJsonError when there is none."""
    candidate = _THINK_BLOCK.sub("", text or "").strip()
    fenced = _FENCE.search(candidate)
    if fenced:
        try:
            fenced_value = json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            fenced_value = None
        if isinstance(fenced_value, dict):
            return fenced_value
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        if "{" not in candidate:
            raise ModelJsonError("The model's answer had no JSON object.") from None
        last = _last_object(candidate)
        if last is None:
            raise ModelJsonError("The model's answer was not valid JSON.") from None
        return last
    if not isinstance(value, dict):
        raise ModelJsonError("The model's answer was not a JSON object.")
    return value
