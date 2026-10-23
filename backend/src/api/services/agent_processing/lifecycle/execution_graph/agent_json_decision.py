"""Shared helpers for parsing a model's structured JSON decision response.

Both skill selection (`select_relevant_skill`) and the fast-lane intent gate
(`evaluate_fast_lane_intent`) ask the model for a single JSON object and must
tolerate markdown code fences or incidental prose around it. This module is
the single place that tolerance lives.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


def extract_fenced_json_body(response_text: str) -> Optional[str]:
    if not response_text.startswith("```"):
        return None
    first_newline = response_text.find("\n")
    if first_newline == -1:
        return None
    closing_fence = response_text.rfind("```")
    if closing_fence <= first_newline:
        return None
    return response_text[first_newline + 1:closing_fence].strip()


def parse_first_json_object(response_text: str) -> Dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(response_text):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(response_text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise json.JSONDecodeError("No JSON object found", response_text, 0)


def parse_json_object_response(response_text: Any) -> Dict[str, Any]:
    """Parse a model JSON object, tolerating markdown fences or surrounding prose.

    Callers rely on the result being a dict (e.g. ``payload.get(...)``) and
    catch ``json.JSONDecodeError``/``TypeError`` to fall back to a safe
    default. A model can emit syntactically valid JSON that isn't an object
    (``null``, ``true``, ``"a string"``, ``[1, 2]``) -- that must be rejected
    here too, or it reaches callers as a non-dict and raises an unhandled
    ``AttributeError`` instead of hitting their fallback path.
    """
    response_string = "" if response_text is None else str(response_text)
    stripped = response_string.strip()
    if not stripped:
        raise json.JSONDecodeError("Empty response", response_string, 0)

    fenced_body = extract_fenced_json_body(stripped)
    if fenced_body is not None:
        payload = json.loads(fenced_body)
    else:
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = parse_first_json_object(stripped)

    if not isinstance(payload, dict):
        raise json.JSONDecodeError(
            f"Expected a JSON object, got {type(payload).__name__}", stripped, 0
        )
    return payload
