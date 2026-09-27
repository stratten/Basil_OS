"""Schema-aware normalization for agent tool-call inputs.

Local models sometimes serialize structured tool arguments one layer too deep,
for example passing ``'["browser"]'`` where a schema expects ``list[str]``.
This module repairs those unambiguous shape errors before Pydantic validation
without performing semantic aliasing or fuzzy correction.
"""

from __future__ import annotations

import json
from types import UnionType
from typing import Any, Iterable, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, model_validator


_NORMALIZED_SCHEMA_MARKER = "__basil_tool_input_normalized__"
_NORMALIZED_SCHEMA_CACHE: dict[type[BaseModel], type[BaseModel]] = {}


class ToolInputNormalizationMixin(BaseModel):
    """Pydantic mixin that normalizes raw tool-call mappings before validation."""

    @model_validator(mode="before")
    @classmethod
    def normalize_tool_input_shapes(cls, raw_input: Any) -> Any:
        return _normalize_input_mapping(raw_input, cls)


def create_normalized_args_schema(
    args_schema: type[BaseModel] | None,
) -> type[BaseModel] | None:
    """Return an args schema subclass with tool-input normalization enabled."""

    if args_schema is None:
        return None
    if getattr(args_schema, _NORMALIZED_SCHEMA_MARKER, False):
        return args_schema
    if not isinstance(args_schema, type) or not issubclass(args_schema, BaseModel):
        return args_schema

    cached_schema = _NORMALIZED_SCHEMA_CACHE.get(args_schema)
    if cached_schema is not None:
        return cached_schema

    normalized_schema = type(
        args_schema.__name__,
        (ToolInputNormalizationMixin, args_schema),
        {
            "__module__": args_schema.__module__,
            _NORMALIZED_SCHEMA_MARKER: True,
            "model_config": ConfigDict(title=args_schema.__name__),
        },
    )
    normalized_schema.model_rebuild(force=True)
    _NORMALIZED_SCHEMA_CACHE[args_schema] = normalized_schema
    return normalized_schema


def _format_malformed_shell_args_guidance(error: Any) -> str | None:
    try:
        errors = error.errors()
    except Exception:
        return None

    for item in errors:
        location = tuple(item.get("loc") or ())
        raw_value = item.get("input")
        if location != ("args",) or not isinstance(raw_value, str):
            continue
        stripped = raw_value.strip()
        if not stripped.startswith("["):
            continue
        return (
            " The shell args value looks like malformed JSON text. Send args as a native JSON array of strings, for example "
            "{\"command\": \"bash\", \"args\": [\"-lc\", \"printf '%s\\n' hello\"]}, not a quoted JSON array. "
            "Do not repair this by stripping non-ASCII characters. If the task is writing a text file, call file_service_write_text_file with direct content instead of shell redirection."
        )
    return None


def format_tool_validation_error(error: Any) -> str:
    """Turn a tool-argument ``ValidationError`` into actionable agent feedback.

    LangChain calls this (via a tool's ``handle_validation_error``) instead of
    re-raising when argument validation fails. Returning a string makes the
    failure a recoverable tool observation the agent can correct and retry,
    rather than an uncaught exception that crashes the whole run.
    """

    try:
        fields = ", ".join(
            ".".join(str(loc) for loc in err.get("loc", ())) or "<root>"
            for err in error.errors()
        )
    except Exception:
        fields = "<unknown>"
    shell_guidance = _format_malformed_shell_args_guidance(error)
    return (
        f"Tool input validation failed for field(s): {fields}. "
        "Pass each argument as a native JSON value (for object arguments send a "
        "JSON object, not a quoted JSON string), then call the tool again."
        + (shell_guidance or "")
    )


def normalize_structured_tool_args_schema(tool: Any) -> Any:
    """Normalize a LangChain StructuredTool's args schema in place."""

    args_schema = getattr(tool, "args_schema", None)
    normalized_schema = create_normalized_args_schema(args_schema)
    if normalized_schema is not None and normalized_schema is not args_schema:
        tool.args_schema = normalized_schema
    if not getattr(tool, "handle_validation_error", None):
        tool.handle_validation_error = format_tool_validation_error
    return tool


def normalize_structured_tool_args_schemas(tools: Iterable[Any]) -> list[Any]:
    """Normalize each tool args schema and return a concrete tool list."""

    return [normalize_structured_tool_args_schema(tool) for tool in tools]


def _normalize_input_mapping(raw_input: Any, schema_model: type[BaseModel]) -> Any:
    if not isinstance(raw_input, dict):
        return raw_input

    model_fields = getattr(schema_model, "model_fields", {})
    normalized_input = dict(raw_input)
    for field_name, field_info in model_fields.items():
        if field_name not in normalized_input:
            continue
        normalized_input[field_name] = _normalize_value_for_annotation(
            normalized_input[field_name],
            getattr(field_info, "annotation", Any),
        )
    return normalized_input


def _normalize_value_for_annotation(value: Any, annotation: Any) -> Any:
    if not isinstance(value, str):
        return value

    structured_annotation = _structured_annotation(annotation)
    if structured_annotation is None:
        return value

    container_origin, container_args = structured_annotation
    text = value.strip()
    if not text:
        return value

    parsed_value, parsed_successfully = _structured_json_parse(text)

    if container_origin in {list, set, tuple} and _is_string_sequence_annotation(
        container_origin,
        container_args,
    ):
        if parsed_successfully:
            if isinstance(parsed_value, list):
                return parsed_value
            return value
        if text.startswith("[") or text.startswith("{"):
            return value
        parts = [part.strip() for part in text.split(",") if part.strip()]
        return parts if parts else value

    if container_origin is dict:
        if parsed_successfully and isinstance(parsed_value, dict):
            return parsed_value
        return value

    return value


def _structured_annotation(annotation: Any) -> tuple[Any, tuple[Any, ...]] | None:
    annotation = _unwrap_optional_annotation(annotation)
    origin = get_origin(annotation) or annotation
    args = get_args(annotation)

    if origin in {list, set, tuple, dict}:
        return origin, args
    return None


def _is_string_sequence_annotation(container_origin: Any, container_args: tuple[Any, ...]) -> bool:
    if container_origin is tuple:
        return bool(container_args) and container_args[0] is str
    return bool(container_args) and container_args[0] is str


def _unwrap_optional_annotation(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin not in {Union, UnionType}:
        return annotation

    non_none_args = [
        arg for arg in get_args(annotation)
        if arg is not type(None)
    ]
    for arg in non_none_args:
        if _structured_annotation(arg) is not None:
            return arg
    return annotation


def _structured_json_parse(text: str) -> tuple[Any, bool]:
    # strict=False lets models' large text fields survive: it permits raw
    # control characters (newlines/tabs) inside JSON string values, which
    # strict parsing rejects. It does not make otherwise-malformed JSON
    # (e.g. unescaped quotes) parse.
    try:
        return json.loads(text, strict=False), True
    except json.JSONDecodeError:
        return None, False
