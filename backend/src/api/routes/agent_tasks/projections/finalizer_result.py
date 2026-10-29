"""Finalizer-result selection helpers shared by Agent Task route projections."""

from typing import Any, Dict, Mapping, Optional


def get_finalizer_envelope(result_data: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the finalizer envelope across historical and current storage shapes."""
    for key in ("finalizer_result", "final_envelope"):
        candidate = result_data.get(key)
        if isinstance(candidate, dict):
            return candidate

    nested_data = result_data.get("data")
    if isinstance(nested_data, dict):
        candidate = nested_data.get("final_envelope") or nested_data.get("finalizer_result")
        if isinstance(candidate, dict):
            return candidate

    return None
