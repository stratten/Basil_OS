"""Schema-aware normalization for agent tool-call inputs.

Local models sometimes serialize structured tool arguments one layer too deep,
for example passing ``'["browser"]'`` where a schema expects ``list[str]``.
This module repairs those unambiguous shape errors before Pydantic validation
without performing semantic aliasing or fuzzy correction.
"""

from __future__ import annotations

import json
from functools import partial
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


_MAX_REPORTED_ERRORS = 6
_MAX_REPORTED_MESSAGE_CHARS = 160
_MAX_LISTED_FIELD_NAMES = 20
_MISPLACED_FIELD_SEARCH_DEPTH = 2


def _json_schema_of(args_schema: Any) -> dict[str, Any] | None:
    """Return the JSON schema the model was shown for a tool, or None when it cannot be read."""

    try:
        if isinstance(args_schema, dict):
            return args_schema
        if isinstance(args_schema, type) and issubclass(args_schema, BaseModel):
            return args_schema.model_json_schema()
    except Exception:
        return None
    return None


def _resolve_object_schema(schema: Any, definitions: dict[str, Any]) -> dict[str, Any] | None:
    """Follow a ``$ref`` or the single non-null ``anyOf`` branch to an object schema that has properties."""

    if not isinstance(schema, dict):
        return None
    reference = schema.get("$ref")
    if isinstance(reference, str):
        return _resolve_object_schema(definitions.get(reference.rsplit("/", 1)[-1]), definitions)
    branches = schema.get("anyOf")
    if isinstance(branches, list):
        non_null = [branch for branch in branches if isinstance(branch, dict) and branch.get("type") != "null"]
        return _resolve_object_schema(non_null[0], definitions) if len(non_null) == 1 else None
    return schema if isinstance(schema.get("properties"), dict) else None


def _object_schema_at(root: dict[str, Any], path: tuple[Any, ...]) -> dict[str, Any] | None:
    definitions = root.get("$defs") if isinstance(root.get("$defs"), dict) else {}
    current = _resolve_object_schema(root, definitions)
    for part in path:
        if current is None or not isinstance(part, str):
            return None
        current = _resolve_object_schema(current["properties"].get(part), definitions)
    return current


def _describe_accepted_fields(object_schema: dict[str, Any]) -> str:
    required = set(object_schema.get("required") or ())
    names = [f"{name} (required)" if name in required else name for name in object_schema["properties"]]
    if len(names) > _MAX_LISTED_FIELD_NAMES:
        names = names[:_MAX_LISTED_FIELD_NAMES] + ["and more"]
    return ", ".join(names)


def _find_objects_accepting(
    root: dict[str, Any],
    field_name: str,
    exclude_path: tuple[Any, ...],
) -> list[tuple[str, ...]]:
    """Return the object paths, other than ``exclude_path``, whose schema has a property called ``field_name``."""

    definitions = root.get("$defs") if isinstance(root.get("$defs"), dict) else {}
    found: list[tuple[str, ...]] = []

    def walk(schema: dict[str, Any], path: tuple[str, ...], depth: int) -> None:
        if path != exclude_path and field_name in schema["properties"]:
            found.append(path)
        if depth >= _MISPLACED_FIELD_SEARCH_DEPTH:
            return
        for name, child in schema["properties"].items():
            resolved = _resolve_object_schema(child, definitions)
            if resolved is not None:
                walk(resolved, path + (name,), depth + 1)

    top = _resolve_object_schema(root, definitions)
    if top is not None:
        walk(top, (), 0)
    return found


def _format_location(path: tuple[Any, ...]) -> str:
    return f"inside {'.'.join(str(part) for part in path)}" if path else "at the top level"


def _format_validation_details(error: Any, args_schema: Any) -> str:
    """Say why each argument was rejected and, where the schema allows, what is accepted instead.

    Reports Pydantic's own reason and the accepted field names only. It never repeats the rejected values, because a rejected value can hold user text.
    """

    try:
        errors = list(error.errors())
    except Exception:
        return ""
    if not errors:
        return ""

    reasons = []
    for item in errors[:_MAX_REPORTED_ERRORS]:
        location = ".".join(str(part) for part in item.get("loc") or ()) or "<root>"
        message = str(item.get("msg") or item.get("type") or "invalid").strip()
        reasons.append(f"{location}: {message[:_MAX_REPORTED_MESSAGE_CHARS]}")
    if len(errors) > _MAX_REPORTED_ERRORS:
        reasons.append(f"{len(errors) - _MAX_REPORTED_ERRORS} more")
    details = "Reasons: " + "; ".join(reasons) + ". "

    root = _json_schema_of(args_schema)
    if root is None:
        return details

    advised_parents: set[tuple[Any, ...]] = set()
    for item in errors[:_MAX_REPORTED_ERRORS]:
        if item.get("type") != "extra_forbidden":
            continue
        location = tuple(item.get("loc") or ())
        if not location or not isinstance(location[-1], str):
            continue
        parent, field_name = location[:-1], location[-1]
        parent_schema = _object_schema_at(root, parent)
        if parent_schema is None:
            continue
        homes = _find_objects_accepting(root, field_name, parent)
        if homes:
            places = " or ".join(_format_location(home) for home in homes)
            details += f"{field_name} is not accepted {_format_location(parent)} but is accepted {places}. "
        if parent not in advised_parents:
            advised_parents.add(parent)
            details += f"Accepted fields {_format_location(parent)}: {_describe_accepted_fields(parent_schema)}. "
    return details


def format_tool_validation_error(error: Any, args_schema: Any = None) -> str:
    """Turn a tool-argument ``ValidationError`` into actionable agent feedback.

    LangChain calls this (via a tool's ``handle_validation_error``) instead of
    re-raising when argument validation fails. Returning a string makes the
    failure a recoverable tool observation the agent can correct and retry,
    rather than an uncaught exception that crashes the whole run.

    The text starts with ``Tool input validation failed for field(s): <fields>. ``
    because the repetition guard reads the field list from that exact prefix.
    ``args_schema`` is the tool's schema; when given, the message also names the
    accepted fields and says where a misplaced field belongs.
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
        + _format_validation_details(error, args_schema)
        + "Pass each argument as a native JSON value (for object arguments send a "
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
        tool.handle_validation_error = partial(format_tool_validation_error, args_schema=tool.args_schema)
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

    if container_origin in {list, tuple} and _is_object_sequence_annotation(container_args):
        # A list of objects (for example the setup assistant's session agenda items) arrives as a
        # JSON string when a local model quotes the whole array. Pydantic still validates every item.
        if parsed_successfully:
            return parsed_value if isinstance(parsed_value, list) else value
        return value

    if container_origin is dict or container_origin is BaseModel:
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
    # A nested model field (for example whitelist_advice) is object-shaped like a dict, so a
    # double-serialized JSON object is repaired the same way. Pydantic still validates the fields.
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return BaseModel, args
    return None


def _is_string_sequence_annotation(container_origin: Any, container_args: tuple[Any, ...]) -> bool:
    if container_origin is tuple:
        return bool(container_args) and container_args[0] is str
    return bool(container_args) and container_args[0] is str


def _is_object_sequence_annotation(container_args: tuple[Any, ...]) -> bool:
    """True for ``list[SomeModel]`` and ``list[dict[...]]``, where every item is object-shaped."""

    if not container_args:
        return False
    item_annotation = container_args[0]
    item_origin = get_origin(item_annotation) or item_annotation
    return item_origin is dict or (
        isinstance(item_annotation, type) and issubclass(item_annotation, BaseModel)
    )


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
