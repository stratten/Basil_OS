"""Text formatting helpers for content sent to LLMs."""

from __future__ import annotations

import re


def sanitize_data_for_llm(text: str) -> str:
    """
    UNIVERSAL data sanitization for any content going to LLMs.
    Strips all Unicode characters that could break JSON parsing.
    USE THIS FOR ALL DATA RETRIEVAL OPERATIONS.
    """
    if not text or not isinstance(text, str):
        return str(text) if text else ""

    # NUCLEAR: Strip EVERY non-ASCII character, no exceptions
    # Only keep ASCII 32-126 (printable) + tab(9), newline(10), carriage return(13)
    result = ""
    for char in text:
        ascii_code = ord(char)
        if 32 <= ascii_code <= 126:  # Printable ASCII only
            result += char
        elif ascii_code in (9, 10, 13):  # Essential whitespace only
            result += char
        # EVERYTHING ELSE GETS NUKED - no spaces, no replacements, GONE

    # Clean up any resulting whitespace issues
    result = re.sub(r" +", " ", result)  # Multiple spaces to single
    result = re.sub(r"\n +", "\n", result)  # Spaces after newlines
    result = re.sub(r" +\n", "\n", result)  # Spaces before newlines
    result = re.sub(r"\n\n+", "\n\n", result)  # Multiple newlines to double

    return result.strip()
