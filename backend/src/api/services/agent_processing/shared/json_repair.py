"""Robust JSON extraction and repair helpers for LLM responses."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _sanitize_for_json(text: str) -> str:
    """
    Strip Unicode that can break downstream JSON parsing.

    This intentionally mirrors the legacy formatting utility behavior for
    responses coming back from LLMs.
    """
    if not text or not isinstance(text, str):
        return str(text) if text else ""

    result = ""
    for char in text:
        ascii_code = ord(char)
        if 32 <= ascii_code <= 126:
            result += char
        elif ascii_code in (9, 10, 13):
            result += char

    result = re.sub(r" +", " ", result)
    result = re.sub(r"\n +", "\n", result)
    result = re.sub(r" +\n", "\n", result)
    result = re.sub(r"\n\n+", "\n\n", result)

    return result.strip()


def robust_json_loads(response: str) -> Any:
    """Parse JSON response with robust error handling and escape character fixing."""
    # Comprehensive Unicode sanitization for JSON compatibility
    response = _sanitize_for_json(response)

    # Enhanced JSON parsing with multiple fallback strategies
    parsing_strategies = [
        # Strategy 1: Direct parsing
        lambda r: json.loads(r),

        # Strategy 2: LLM response pattern recognition
        lambda r: _extract_llm_json_blocks(r),

        # Strategy 3: Bracket-balanced JSON extraction
        lambda r: _extract_balanced_json(r),

        # Strategy 4: Progressive chunk parsing for large responses
        lambda r: _parse_large_json_chunks(r),

        # Strategy 5: Extract JSON pattern (prioritize arrays since many responses are arrays)
        lambda r: json.loads(re.search(r"\[.*\]", r, re.DOTALL).group(0)),
        lambda r: json.loads(re.search(r"\{.*\}", r, re.DOTALL).group(0)),

        # Strategy 6: Fix common escape character issues
        lambda r: json.loads(fix_json_escape_issues(r)),

        # Strategy 7: Extract and fix JSON pattern (arrays first)
        lambda r: json.loads(fix_json_escape_issues(re.search(r"\[.*\]", r, re.DOTALL).group(0))),
        lambda r: json.loads(fix_json_escape_issues(re.search(r"\{.*\}", r, re.DOTALL).group(0))),

        # Strategy 8: Remove markdown code blocks and try again
        lambda r: json.loads(re.sub(r"```json\s*(.*?)\s*```", r"\1", r, flags=re.DOTALL)),
    ]

    for i, strategy in enumerate(parsing_strategies, 1):
        try:
            result = strategy(response)
            if result:  # Successfully parsed
                logger.info(f"JSON parsed successfully using strategy {i}")
                return result
        except (json.JSONDecodeError, AttributeError, TypeError) as e:
            logger.debug(f"Strategy {i} failed: {e}")
            continue

    # All strategies failed
    logger.warning(f"All JSON parsing strategies failed for response length {len(response)}")
    logger.debug(f"Failed response preview: {response[:500]}...")
    return None


def _extract_llm_json_blocks(text: str) -> Any:
    """Extract JSON from LLM responses that mix explanation with JSON code blocks."""
    # Pattern 1: Extract from markdown code blocks
    markdown_patterns = [
        r"```json\s*(.*?)\s*```",
        r"```\s*([\[\{].*?[\]\}])\s*```",
    ]

    for pattern in markdown_patterns:
        matches = re.findall(pattern, text, re.DOTALL)
        for match in matches:
            try:
                return json.loads(match.strip())
            except json.JSONDecodeError:
                continue

    # Pattern 2: Extract from "Here's the JSON:" style responses
    json_intro_pattern = r"(?:here's|here is|json|response).*?:\s*([\[\{].*?[\]\}])"
    match = re.search(json_intro_pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Pattern 3: Find the largest JSON-like structure
    return _extract_balanced_json(text)


def _extract_balanced_json(text: str) -> Any:
    """Extract JSON using bracket balancing instead of greedy regex."""
    # Find all potential JSON start positions
    start_chars = ["{", "["]

    for start_char in start_chars:
        end_char = "}" if start_char == "{" else "]"

        # Find all start positions
        start_positions = [i for i, char in enumerate(text) if char == start_char]

        for start_pos in start_positions:
            # Balance brackets from this position
            bracket_count = 0
            in_string = False
            escape_next = False

            for i in range(start_pos, len(text)):
                char = text[i]

                if escape_next:
                    escape_next = False
                    continue

                if char == "\\":
                    escape_next = True
                    continue

                if char == '"' and not escape_next:
                    in_string = not in_string
                    continue

                if not in_string:
                    if char == start_char:
                        bracket_count += 1
                    elif char == end_char:
                        bracket_count -= 1

                        # Found balanced brackets
                        if bracket_count == 0:
                            json_candidate = text[start_pos:i + 1]
                            try:
                                return json.loads(json_candidate)
                            except json.JSONDecodeError:
                                break  # Try next start position

    return None


def extract_balanced_json(text: str) -> Any:
    """Public entry point for bracket-balanced extraction.

    Callers that must preserve non-ASCII prose use this instead of
    robust_json_loads, whose sanitizer strips characters outside ASCII
    32-126 and would corrupt narrative text.
    """
    return _extract_balanced_json(text)


def _parse_large_json_chunks(text: str) -> Any:
    """Parse large JSON responses by breaking them into manageable chunks."""
    # If response is not that large, don't chunk
    if len(text) < 3000:
        return None

    # Try to find natural breaking points for large responses.
    object_boundaries = []

    # Find object separators in arrays
    separator_pattern = r"\},\s*\{"
    matches = re.finditer(separator_pattern, text)
    for match in matches:
        object_boundaries.append(match.start() + 1)  # Position after the comma

    if object_boundaries:
        # Try to parse the first part to see if it's a valid array start
        # Then progressively add more objects
        for boundary in object_boundaries[:3]:  # Try first few boundaries
            chunk = text[:boundary + 1] + "]"  # Close the array
            # Fix the chunk by ensuring it starts with '['
            if not chunk.strip().startswith("["):
                # Find the array start
                array_start = text.find("[")
                if array_start >= 0:
                    chunk = text[array_start:boundary + 1] + "]"

            try:
                result = json.loads(chunk)
                if isinstance(result, list) and len(result) > 0:
                    return result
            except json.JSONDecodeError:
                continue

    # If chunking fails, try extracting just the first complete object/array
    return _extract_first_complete_json(text)


def _extract_first_complete_json(text: str) -> Any:
    """Extract the first complete JSON object or array from text."""
    # Find the first '[' or '{'
    for start_char in ["[", "{"]:
        start_pos = text.find(start_char)
        if start_pos >= 0:
            # Use bracket balancing to find the end
            end_char = "]" if start_char == "[" else "}"
            bracket_count = 0
            in_string = False
            escape_next = False

            for i in range(start_pos, len(text)):
                char = text[i]

                if escape_next:
                    escape_next = False
                    continue

                if char == "\\":
                    escape_next = True
                    continue

                if char == '"' and not escape_next:
                    in_string = not in_string
                    continue

                if not in_string:
                    if char == start_char:
                        bracket_count += 1
                    elif char == end_char:
                        bracket_count -= 1

                        if bracket_count == 0:
                            json_candidate = text[start_pos:i + 1]
                            try:
                                return json.loads(json_candidate)
                            except json.JSONDecodeError:
                                break

    return None


def fix_json_escape_issues(text: str) -> str:
    """Fix common JSON escape character issues in LLM responses."""
    # Fix invalid escape sequences that LLMs commonly produce
    fixes = [
        # Fix invalid \escape sequences (keep valid ones)
        (r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r"\\\\"),

        # Fix unescaped quotes in strings
        (r'(?<!\\)"(?=[^,\]\}:])', r'\\"'),

        # Fix trailing commas in JSON
        (r",(\s*[\]\}])", r"\1"),

        # Fix single quotes to double quotes (but be careful with apostrophes)
        (r"'([^']*)'(\s*:)", r'"\1"\2'),
    ]

    fixed_text = text
    for pattern, replacement in fixes:
        try:
            fixed_text = re.sub(pattern, replacement, fixed_text)
        except Exception as e:
            logger.debug(f"JSON fix pattern failed: {e}")
            continue

    return fixed_text
