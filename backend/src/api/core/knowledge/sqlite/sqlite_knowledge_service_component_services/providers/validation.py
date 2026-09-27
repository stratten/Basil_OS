"""Validation and JSON helpers shared by provider repositories."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .errors import ProviderRunPersistenceError

SECRET_ARG_FLAGS = (
    "--api-key",
    "--apikey",
    "--token",
    "--secret",
    "--password",
    "--credential",
    "--authorization",
)

SECRET_ARG_PREFIXES = ("sk-", "sk_", "ghp_", "github_pat_")
MAX_DESCRIPTION_LENGTH = 1000
MAX_ROUTING_HINTS = 8
MAX_ROUTING_HINT_LENGTH = 160
MAX_WORKSPACE_LABEL_LENGTH = 120
MAX_AUTHENTICATION_METHOD_ID_LENGTH = 128
ENVIRONMENT_VARIABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")

def _require_nonblank(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderRunPersistenceError(f"{field_name} must be a nonblank string")
    return value.strip()

def _validate_launch_argv(launch_argv: Sequence[str]) -> tuple[str, ...]:
    if isinstance(launch_argv, (str, bytes)) or not isinstance(launch_argv, Sequence):
        raise ProviderRunPersistenceError("launch_argv must be a sequence of strings")
    if not launch_argv:
        raise ProviderRunPersistenceError("launch_argv must contain at least one segment")
    normalized: list[str] = []
    for index, segment in enumerate(launch_argv):
        if not isinstance(segment, str) or not segment.strip():
            raise ProviderRunPersistenceError(
                f"launch_argv segment at index {index} must be a nonblank string"
            )
        _reject_secret_argv_segment(segment)
        normalized.append(segment)
    return tuple(normalized)

def _validate_environment_allowlist(
    environment_allowlist: Sequence[str],
) -> tuple[str, ...]:
    if isinstance(environment_allowlist, (str, bytes)) or not isinstance(
        environment_allowlist,
        Sequence,
    ):
        raise ProviderRunPersistenceError(
            "environment_allowlist must be a sequence of strings"
        )
    normalized: list[str] = []
    for index, name in enumerate(environment_allowlist):
        if not isinstance(name, str) or not name.strip():
            raise ProviderRunPersistenceError(
                f"environment_allowlist entry at index {index} must be a nonblank string"
            )
        cleaned_name = name.strip()
        if not ENVIRONMENT_VARIABLE_NAME_PATTERN.fullmatch(cleaned_name):
            raise ProviderRunPersistenceError(
                f"environment_allowlist entry at index {index} must be an environment variable name"
            )
        normalized.append(cleaned_name)
    return tuple(normalized)

def _validate_optional_description(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProviderRunPersistenceError("description must be a string or null")
    cleaned_value = value.strip()
    if not cleaned_value:
        return None
    if len(cleaned_value) > MAX_DESCRIPTION_LENGTH:
        raise ProviderRunPersistenceError(
            f"description must not exceed {MAX_DESCRIPTION_LENGTH} characters"
        )
    return cleaned_value


def _validate_optional_authentication_method_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProviderRunPersistenceError(
            "authentication_method_id must be a string or null"
        )
    cleaned_value = value.strip()
    if not cleaned_value:
        return None
    if len(cleaned_value) > MAX_AUTHENTICATION_METHOD_ID_LENGTH:
        raise ProviderRunPersistenceError(
            "authentication_method_id must not exceed "
            f"{MAX_AUTHENTICATION_METHOD_ID_LENGTH} characters"
        )
    if any(
        not character.isascii()
        or not character.isprintable()
        or character.isspace()
        or character == ":"
        for character in cleaned_value
    ):
        raise ProviderRunPersistenceError(
            "authentication_method_id must contain printable non-whitespace ASCII characters other than ':'"
        )
    return cleaned_value


def _validate_routing_hints(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ProviderRunPersistenceError("routing_hints must be a sequence of strings")
    if len(values) > MAX_ROUTING_HINTS:
        raise ProviderRunPersistenceError(
            f"routing_hints must contain at most {MAX_ROUTING_HINTS} entries"
        )
    normalized: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            raise ProviderRunPersistenceError(
                f"routing_hints entry at index {index} must be a nonblank string"
            )
        cleaned_value = value.strip()
        if len(cleaned_value) > MAX_ROUTING_HINT_LENGTH:
            raise ProviderRunPersistenceError(
                f"routing_hints entry at index {index} must not exceed {MAX_ROUTING_HINT_LENGTH} characters"
            )
        normalized.append(cleaned_value)
    return tuple(normalized)

def _validate_workspace_label(value: object) -> str:
    label = _require_nonblank(value, "workspace_label")
    if len(label) > MAX_WORKSPACE_LABEL_LENGTH:
        raise ProviderRunPersistenceError(
            f"workspace_label must not exceed {MAX_WORKSPACE_LABEL_LENGTH} characters"
        )
    return label

def _require_nonnegative_revision(value: object, field_name: str = "expected_revision") -> int:
    if type(value) is not int or value < 0:
        raise ProviderRunPersistenceError(f"{field_name} must be a nonnegative integer")
    return value

def _require_absolute_executable_path(value: str) -> str:
    executable_path = Path(value)
    if not executable_path.is_absolute():
        raise ProviderRunPersistenceError("launch_argv[0] must be an absolute executable path")
    if not executable_path.exists():
        raise ProviderRunPersistenceError(
            f"launch_argv[0] does not exist: {executable_path}"
        )
    if not executable_path.is_file():
        raise ProviderRunPersistenceError(
            f"launch_argv[0] is not a regular file: {executable_path}"
        )
    if not os.access(executable_path, os.X_OK):
        raise ProviderRunPersistenceError(
            f"launch_argv[0] is not executable: {executable_path}"
        )
    return str(executable_path)

def _require_absolute_workspace_root(value: str) -> str:
    workspace_root = Path(value)
    if not workspace_root.is_absolute():
        raise ProviderRunPersistenceError(
            "canonical_workspace_root must be an absolute path"
        )
    return str(workspace_root)

def _reject_secret_argv_segment(segment: str) -> None:
    lowered = segment.lower()
    for flag in SECRET_ARG_FLAGS:
        if flag in lowered:
            raise ProviderRunPersistenceError(
                f"launch_argv must not contain secret-bearing flag {flag!r}"
            )
    for prefix in SECRET_ARG_PREFIXES:
        if lowered.startswith(prefix):
            raise ProviderRunPersistenceError(
                f"launch_argv must not contain secret-like value prefix {prefix!r}"
            )

def _json_dump_sequence(values: Sequence[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False)

def _json_dump_object(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=False)

def _json_load_string_sequence(raw: str | None, field_name: str) -> tuple[str, ...]:
    if raw is None:
        raise ProviderRunPersistenceError(f"{field_name} is missing")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderRunPersistenceError(f"{field_name} contains invalid JSON") from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise ProviderRunPersistenceError(f"{field_name} must be a JSON string array")
    return tuple(parsed)

def _json_load_object(raw: str | None, field_name: str) -> dict[str, Any]:
    if raw is None:
        raise ProviderRunPersistenceError(f"{field_name} is missing")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderRunPersistenceError(f"{field_name} contains invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ProviderRunPersistenceError(f"{field_name} must be a JSON object")
    return dict(parsed)
