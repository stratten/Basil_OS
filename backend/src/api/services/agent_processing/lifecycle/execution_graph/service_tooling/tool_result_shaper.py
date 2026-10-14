"""Trim the tool-result envelope before it enters the agent's conversation.

The model already knows what it asked for, so the envelope drops echoed input and duplicated payloads.
Everything downstream that reads the envelope (file extraction, ledger capture, synthesis) keeps the fields it uses.
"""

from __future__ import annotations

from typing import Any, Dict

# Keys that downstream file extraction reads from parameters_used; everything else the model supplied is not echoed back
_PARAMETER_KEYS_KEPT = ("file_path", "path", "output_path", "action", "operation")
# Redaction placeholders are tiny and record that content was withheld, so they stay
_REDACTION_PREFIX = "<redacted"
_ECHOED_SCRIPT_KEY = "script_content"
_STUB_DATA_KEYS = frozenset({"summary", "result_type", "result_count", "execution_time_ms"})


def _without_echoed_scripts(value: Any) -> Any:
    """Return ``value`` with every nested ``script_content`` removed, copying only the containers it has to change."""
    if isinstance(value, dict):
        return {
            key: _without_echoed_scripts(item)
            for key, item in value.items()
            if key != _ECHOED_SCRIPT_KEY
        }
    if isinstance(value, list):
        return [_without_echoed_scripts(item) for item in value]
    return value


def _slim_parameters(parameters: Any) -> Any:
    """Keep only path and action hints from the echoed parameters; None when nothing useful remains."""
    if not isinstance(parameters, dict):
        return None
    kept: Dict[str, Any] = {key: parameters[key] for key in _PARAMETER_KEYS_KEPT if key in parameters}
    for key, value in parameters.items():
        if isinstance(value, str) and value.startswith(_REDACTION_PREFIX):
            kept[key] = value
    context_data = parameters.get("context_data")
    if isinstance(context_data, dict):
        slim_context = {key: context_data[key] for key in _PARAMETER_KEYS_KEPT if key in context_data}
        if slim_context:
            kept["context_data"] = slim_context
    return kept or None


def _is_stub_data(data: Any) -> bool:
    return isinstance(data, dict) and bool(data) and set(data).issubset(_STUB_DATA_KEYS)


def shape_tool_envelope(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Return a trimmed copy of a service-tool envelope; the input is not modified."""
    shaped = dict(envelope)
    shaped.pop("execution_time", None)

    slim = _slim_parameters(shaped.pop("parameters_used", None))
    if slim is not None:
        shaped["parameters_used"] = slim

    if "result" in shaped:
        shaped["result"] = _without_echoed_scripts(shaped["result"])
    if "data" in shaped:
        data = _without_echoed_scripts(shaped["data"])
        if data is None or data == shaped.get("result") or _is_stub_data(data):
            shaped.pop("data")
        else:
            shaped["data"] = data
    return shaped
