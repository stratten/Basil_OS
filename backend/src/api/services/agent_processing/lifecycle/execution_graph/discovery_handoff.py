"""Build one bounded replan handoff after an input artifact is prepared."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Sequence

MAX_PREPARED_FILES = 3
MAX_EXTRACTED_TEXT_CHARS_PER_FILE = 12_000
_PREPARE_TOOL_SUFFIXES = frozenset(
    {
        "detect_and_prepare_current_document",
        "find_file_for_llm",
        "prepare_file_by_path",
    }
)


@dataclass(frozen=True)
class DiscoveryHandoff:
    prepared_files: tuple[dict[str, Any], ...]
    source_catalog: tuple[dict[str, Any], ...]

    def render(self) -> str:
        payload = {
            "prepared_files": list(self.prepared_files),
            "available_local_record_types": list(self.source_catalog),
        }
        return (
            "\n\nINPUT DISCOVERY HANDOFF:\n"
            + json.dumps(payload, ensure_ascii=False)
            + "\nUse the original request and this prepared input to select the relevant "
            "authoritative records before any material write. The record catalog is metadata; "
            "call retrieve_basil_history with browse, search, aggregate, or detail to collect evidence."
        )


def _tool_name(step: Any) -> str:
    if not isinstance(step, tuple) or len(step) < 2:
        return ""
    return str(getattr(step[0], "tool", "") or "")


def _payload_from_observation(observation: Any) -> dict[str, Any]:
    text = observation if isinstance(observation, str) else str(observation)
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    result = data.get("result")
    return result if isinstance(result, dict) else data


def _prepared_file_from_step(step: Any) -> dict[str, Any] | None:
    tool_name = _tool_name(step)
    if not tool_name.startswith("file_service_"):
        return None
    if not any(tool_name.endswith(suffix) for suffix in _PREPARE_TOOL_SUFFIXES):
        return None
    payload = _payload_from_observation(step[1])
    if payload.get("result_kind") != "prepared":
        return None
    file_path = payload.get("file_path")
    extracted_text = payload.get("extracted_text")
    if not isinstance(file_path, str) or not file_path.strip():
        return None
    if not isinstance(extracted_text, str) or not extracted_text.strip():
        return None
    return {
        "file_path": file_path,
        "file_name": str(payload.get("file_name") or ""),
        "file_type": str(payload.get("file_type") or ""),
        "extracted_text": extracted_text[:MAX_EXTRACTED_TEXT_CHARS_PER_FILE],
        "truncated": len(extracted_text) > MAX_EXTRACTED_TEXT_CHARS_PER_FILE,
    }


def build_discovery_handoff(
    intermediate_steps: Sequence[Any],
    source_catalog: Sequence[dict[str, Any]],
) -> DiscoveryHandoff | None:
    prepared_files: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for step in intermediate_steps:
        prepared = _prepared_file_from_step(step)
        if prepared is None:
            continue
        file_path = prepared["file_path"]
        if file_path in seen_paths:
            continue
        seen_paths.add(file_path)
        prepared_files.append(prepared)
        if len(prepared_files) == MAX_PREPARED_FILES:
            break
    if not prepared_files:
        return None
    return DiscoveryHandoff(
        prepared_files=tuple(prepared_files),
        source_catalog=tuple(source_catalog),
    )
