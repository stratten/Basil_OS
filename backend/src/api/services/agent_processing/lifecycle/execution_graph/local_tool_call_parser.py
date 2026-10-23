"""Parsers for local-model tool calls emitted as text or llama.cpp structures."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from api.core.models.reasoning.model_runtime_profile import (
    TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS,
    TOOL_CALL_FORMAT_JSON_TOOL_CALL,
)

logger = logging.getLogger(__name__)

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_FUNCTION_TAG_RE = re.compile(
    r"<function=([^\s>]+)>\s*(.*?)\s*</function>", re.DOTALL
)
_PARAMETER_TAG_RE = re.compile(
    r"<parameter=([^\s>]+)>\s*(.*?)\s*</parameter>", re.DOTALL
)
# A stray, unmatched <tool_call>/</tool_call> tag left over from a model that
# dropped the opening (or closing) half of the wrapper around an otherwise
# well-formed <function=...> block. Stripped only after that block has
# already been recovered below -- this targets the exact wrapper tag, not
# free prose.
_STRAY_TOOL_CALL_TAG_RE = re.compile(r"</?tool_call>", re.IGNORECASE)


def safe_parse_json(
    json_str: str, context: str = ""
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not json_str or json_str.strip() == "":
        return {}, None

    original_str = json_str

    try:
        return json.loads(json_str), None
    except json.JSONDecodeError:
        pass

    try:
        fixed = re.sub(r",\s*([}\]])", r"\1", json_str)
        if "'" in fixed and '"' not in fixed:
            fixed = fixed.replace("'", '"')
        result = json.loads(fixed)
        logger.warning("JSON repair (trailing commas/quotes) succeeded for %s", context)
        return result, None
    except json.JSONDecodeError:
        pass

    try:
        start = json_str.find("{")
        end = json_str.rfind("}")
        if start != -1 and end != -1 and end > start:
            extracted = json_str[start : end + 1]
            result = json.loads(extracted)
            logger.warning("JSON repair (extraction) succeeded for %s", context)
            return result, None
    except json.JSONDecodeError:
        pass

    try:
        open_braces = json_str.count("{") - json_str.count("}")
        open_brackets = json_str.count("[") - json_str.count("]")
        if open_braces > 0 or open_brackets > 0:
            truncated = re.sub(r',\s*"[^"]*"?\s*:?\s*$', "", json_str)
            truncated += "}" * open_braces + "]" * open_brackets
            result = json.loads(truncated)
            logger.warning("JSON repair (truncation fix) succeeded for %s", context)
            return result, None
    except json.JSONDecodeError:
        pass

    repaired, repair_err = _repair_unescaped_quotes(json_str, context)
    if repaired is not None:
        return repaired, None
    if repair_err:
        logger.debug("Progressive quote repair also failed for %s: %s", context, repair_err)

    error_preview = original_str[:100] + "..." if len(original_str) > 100 else original_str
    error_msg = f"Failed to parse JSON after all repair attempts. Preview: {error_preview}"
    logger.error("JSON parse failed for %s: %s", context, error_msg)
    return None, error_msg


def parse_structured_tool_calls(
    response_data: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], List[str]]:
    tool_calls = []
    parse_errors = []

    if "choices" not in response_data or not response_data["choices"]:
        return tool_calls, parse_errors

    message = response_data["choices"][0].get("message", {})
    raw_tool_calls = message.get("tool_calls", [])

    for tc in raw_tool_calls:
        if tc.get("type") != "function":
            continue

        func = tc.get("function", {})
        tool_name = func.get("name", "unknown")
        arguments_str = func.get("arguments", "{}")

        if isinstance(arguments_str, dict):
            parsed_args = arguments_str
            error = None
        else:
            parsed_args, error = safe_parse_json(
                arguments_str, context=f"tool '{tool_name}'"
            )

        if error:
            parse_errors.append(f"Tool '{tool_name}': {error}")
            logger.warning(
                "Skipping malformed tool call '%s' - will request retry. Raw args: %s",
                tool_name,
                str(arguments_str)[:200],
            )
            continue

        tool_calls.append(
            {
                "id": tc.get("id", f"call_{len(tool_calls)}"),
                "name": tool_name,
                "args": _strip_reasoning_from_value(parsed_args or {}),
            }
        )

    return tool_calls, parse_errors


def extract_text_tool_calls(
    content: str, tool_call_format: str
) -> Tuple[List[Dict[str, Any]], str]:
    """Parse text tool calls using the registry-selected local format."""
    raw_blocks = _TOOL_CALL_RE.findall(content)
    if raw_blocks:
        tool_calls: List[Dict[str, Any]] = []
        for i, block in enumerate(raw_blocks):
            parsed_call = _parse_text_tool_call_block(block, i, tool_call_format)
            if parsed_call is not None:
                tool_calls.append(parsed_call)

        cleaned = _TOOL_CALL_RE.sub("", content)
        cleaned = strip_think_sections(cleaned)

        logger.info(
            "Extracted %s tool call(s) from text content (%s raw blocks, format=%s)",
            len(tool_calls),
            len(raw_blocks),
            tool_call_format,
        )
        return tool_calls, cleaned

    if tool_call_format == TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS:
        recovered = _extract_bare_function_tag_tool_calls(content)
        if recovered is not None:
            return recovered

    return [], strip_think_sections(content)


def _extract_bare_function_tag_tool_calls(
    content: str,
) -> Optional[Tuple[List[Dict[str, Any]], str]]:
    """Recover <function=...>...</function> tool calls emitted without the
    enclosing <tool_call> wrapper (observed from a model that dropped the
    opening wrapper tag but still appended a stray, unmatched closing
    </tool_call> tag). The <function=...> tag itself is the authoritative
    structural signal -- this still parses one specific message format for
    a specific purpose, never free-form prose. Returns None when no bare
    <function=...> block is present, so the caller falls back cleanly."""
    function_matches = list(_FUNCTION_TAG_RE.finditer(content))
    if not function_matches:
        return None

    tool_calls: List[Dict[str, Any]] = []
    for i, match in enumerate(function_matches):
        parsed_call = _parse_function_parameter_tool_call_block(match.group(0), i)
        if parsed_call is not None:
            tool_calls.append(parsed_call)

    cleaned = _FUNCTION_TAG_RE.sub("", content)
    cleaned = _STRAY_TOOL_CALL_TAG_RE.sub("", cleaned)
    cleaned = strip_think_sections(cleaned)

    logger.info(
        "Recovered %s tool call(s) from bare <function=...> tag(s) missing the "
        "<tool_call> wrapper (%s block(s) found)",
        len(tool_calls),
        len(function_matches),
    )
    return tool_calls, cleaned


def strip_think_sections(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


def _strip_leaked_reasoning(text: str) -> str:
    """Remove a complete <think>...</think> block, plus a bare closing tag with
    no matching opener anywhere in the string.

    This model's chat template can inject the opening <think> as an implicit
    generation prefix that is never echoed back in the completion text, while
    the model still emits the literal closing tag itself once it stops
    reasoning -- the same dropped-opening-structural-tag behavior already seen
    on the <tool_call> wrapper (see _STRAY_TOOL_CALL_TAG_RE above). When that
    happens, everything through the orphaned closer is leaked reasoning, not
    part of the tool argument's actual value.
    """
    text = _THINK_RE.sub("", text)
    if "</think>" in text and "<think>" not in text:
        text = text.split("</think>", 1)[1]
    return text.strip()


def _strip_reasoning_from_value(value: Any) -> Any:
    """Recursively apply _strip_leaked_reasoning to every string leaf of a
    parsed tool-call argument value, so a free-text argument (self_assessment,
    standardized_messages, summary_text, or any future field) can't carry the
    model's raw chain-of-thought into a persisted result verbatim."""
    if isinstance(value, str):
        return _strip_leaked_reasoning(value)
    if isinstance(value, list):
        return [_strip_reasoning_from_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _strip_reasoning_from_value(item) for key, item in value.items()}
    return value


def _repair_unescaped_quotes(
    json_str: str, context: str = ""
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Fix unescaped double quotes inside JSON string values."""
    s = json_str.strip()
    start = s.find("{")
    if start == -1:
        return None, "No opening brace"
    s = s[start:]

    decoder = json.JSONDecoder()
    max_attempts = 50

    for attempt in range(max_attempts):
        try:
            result, _ = decoder.raw_decode(s)
            if isinstance(result, dict):
                logger.warning(
                    "JSON progressive quote repair succeeded for %s after %s escape(s)",
                    context,
                    attempt,
                )
                return result, None
            return None, "Parsed but result is not a dict"
        except json.JSONDecodeError as e:
            pos = e.pos
            msg = str(e)

            fixable = (
                "Expecting ',' delimiter" in msg
                or "Expecting ':' delimiter" in msg
                or "Expecting value" in msg
            )
            if fixable:
                quote_pos = s.rfind('"', 0, pos)
                if quote_pos > 0 and s[quote_pos - 1] != "\\":
                    s = s[:quote_pos] + '\\"' + s[quote_pos + 1 :]
                    continue

            if "Unterminated string" in msg and pos < len(s) and s[pos] == '"':
                s = s[:pos] + '\\"' + s[pos + 1 :]
                continue

            return None, f"Non-recoverable JSON error at pos {pos}: {msg[:120]}"

    return None, f"Exceeded {max_attempts} repair attempts"


def _parse_text_tool_call_block(
    block: str, index: int, tool_call_format: str
) -> Optional[Dict[str, Any]]:
    if tool_call_format == TOOL_CALL_FORMAT_FUNCTION_PARAMETER_TAGS:
        return _parse_function_parameter_tool_call_block(block, index)
    if tool_call_format != TOOL_CALL_FORMAT_JSON_TOOL_CALL:
        logger.warning(
            "Unknown text tool-call format '%s'; falling back to %s",
            tool_call_format,
            TOOL_CALL_FORMAT_JSON_TOOL_CALL,
        )
    return _parse_json_tool_call_block(block, index)


def _parse_json_tool_call_block(block: str, index: int) -> Optional[Dict[str, Any]]:
    parsed, error = safe_parse_json(block, context=f"text tool_call block #{index}")
    if error or parsed is None:
        logger.warning("Skipping unparseable <tool_call> block #%s: %s", index, error)
        return None

    name = parsed.get("name", "unknown")
    arguments = parsed.get("arguments", {})
    if isinstance(arguments, str):
        arguments, arg_err = safe_parse_json(
            arguments, context=f"tool_call '{name}' arguments"
        )
        if arg_err or arguments is None:
            logger.warning("Skipping tool_call '%s' - bad arguments: %s", name, arg_err)
            return None

    return {
        "id": f"call_{index}_{name}",
        "name": name,
        "args": _strip_reasoning_from_value(arguments),
    }


def _parse_function_parameter_tool_call_block(
    block: str, index: int
) -> Optional[Dict[str, Any]]:
    function_match = _FUNCTION_TAG_RE.search(block)
    if not function_match:
        logger.warning(
            "Skipping function/parameter <tool_call> block #%s: missing function tag",
            index,
        )
        return None

    tool_name = function_match.group(1).strip()
    function_body = function_match.group(2)
    if not tool_name:
        logger.warning(
            "Skipping function/parameter <tool_call> block #%s: empty function name",
            index,
        )
        return None

    args: Dict[str, Any] = {}
    for parameter_match in _PARAMETER_TAG_RE.finditer(function_body):
        parameter_name = parameter_match.group(1).strip()
        parameter_value = parameter_match.group(2).strip()
        if parameter_name:
            args[parameter_name] = _strip_leaked_reasoning(parameter_value)

    return {
        "id": f"call_{index}_{tool_name}",
        "name": tool_name,
        "args": args,
    }
