"""Serialization helpers for agent processing data structures."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from typing import Any

logger = logging.getLogger(__name__)


def convert_to_serializable_dict(obj: Any) -> Any:
    """
    Convert any object to JSON-serializable format.

    Handles dataclasses, complex objects, nested structures, and edge cases
    that may cause JSON serialization failures.
    """
    try:
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, list):
            return [convert_to_serializable_dict(item) for item in obj]
        if isinstance(obj, dict):
            return {key: convert_to_serializable_dict(value) for key, value in obj.items()}
        if is_dataclass(obj):
            # Handle dataclasses first (like EmailSearchCriteria)
            return convert_to_serializable_dict(asdict(obj))
        if hasattr(obj, "__dict__"):
            # Convert objects with __dict__ to dictionaries
            result = {}
            for key, value in obj.__dict__.items():
                if not key.startswith("_"):  # Skip private attributes
                    result[key] = convert_to_serializable_dict(value)
            return result
        # For other objects, convert to string representation
        return str(obj)

    except Exception as e:
        logger.warning(f"Failed to convert object {type(obj)} to serializable format: {e}")
        return f"<{type(obj).__name__} object - conversion failed>"


def safe_json_dumps(obj: Any, indent: int = None) -> str:
    """
    Safely convert any object to JSON string with automatic serialization.

    Args:
        obj: Object to convert to JSON
        indent: JSON indentation level

    Returns:
        JSON string representation
    """
    try:
        serializable_obj = convert_to_serializable_dict(obj)
        return json.dumps(serializable_obj, indent=indent)
    except Exception as e:
        logger.error(f"Failed to convert object to JSON: {e}")
        return f'{{"error": "Failed to serialize object: {str(e)}"}}'


def safe_json_loads(json_str: str) -> Any:
    """
    Safely parse JSON string with error handling.

    Args:
        json_str: JSON string to parse

    Returns:
        Parsed object or None if parsing fails
    """
    try:
        return json.loads(json_str) if json_str else None
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}")
        return None
