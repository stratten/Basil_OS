"""Capture bounded parser-normalized ACP facts into the delegated evidence ledger."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

MAX_CAPTURE_SUMMARY_BYTES = 1_200
MAX_CAPTURE_LOCATORS = 6
MAX_CAPTURE_USAGE_FIELDS = 16


def _bounded_text(value: object, maximum_bytes: int = MAX_CAPTURE_SUMMARY_BYTES) -> str:
    text = str(value or "").strip()
    encoded = text.encode("utf-8", errors="replace")
    return encoded[:maximum_bytes].decode("utf-8", errors="ignore").strip()


def _event_key(prefix: str, value: object) -> str:
    digest = hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()
    return f"{prefix}:{digest}"


def _activity_event_key(
    *,
    entry_id: str,
    activity_kind: str,
    summary: str,
    structured_data: Mapping[str, Any],
    locations: Sequence[str],
) -> str:
    snapshot = {
        "activity_kind": activity_kind[:96],
        "entry_id": entry_id,
        "locations": list(locations),
        "structured_data": dict(structured_data),
        "summary": summary,
    }
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _event_key("activity", encoded)


def _safe_usage(value: object) -> dict[str, int | float]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key)[:64]: item
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))[:MAX_CAPTURE_USAGE_FIELDS]
        if isinstance(item, (int, float)) and not isinstance(item, bool)
    }


def _safe_locations(metadata: Mapping[str, Any]) -> list[str]:
    raw = metadata.get("provider_locations")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    return [item for item in raw[:MAX_CAPTURE_LOCATORS] if isinstance(item, str) and item]


class DelegatedAgentEvidenceCaptureService:
    """Append safe activity and terminal facts without affecting the ACP turn lifecycle."""

    def __init__(self, *, evidence_repository: Any) -> None:
        self._evidence = evidence_repository
        self._capture_failures: set[tuple[str, str]] = set()

    async def capture_activity(
        self,
        *,
        delegated_agent_run_id: str,
        delegated_agent_turn_id: str,
        entry: Mapping[str, Any],
    ) -> None:
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), Mapping) else {}
        activity_kind = metadata.get("provider_activity_kind")
        entry_id = entry.get("id")
        if not isinstance(activity_kind, str) or not isinstance(entry_id, str) or not entry_id:
            return
        if metadata.get("raw_detail") is True:
            return
        summary = _bounded_text(entry.get("summary") or entry.get("content"))
        if not summary:
            return
        structured_data = {
            "entry_type": str(entry.get("type") or "step")[:96],
            "tool_kind": metadata.get("tool_kind"),
            "tool_status": metadata.get("tool_status"),
            "provider_state": metadata.get("provider_state"),
            "provider_stop_reason": metadata.get("provider_stop_reason"),
        }
        locations = _safe_locations(metadata)
        try:
            await self._evidence.append_evidence(
                delegated_agent_run_id=delegated_agent_run_id,
                delegated_agent_turn_id=delegated_agent_turn_id,
                source_event_key=_activity_event_key(
                    entry_id=entry_id,
                    activity_kind=activity_kind,
                    summary=summary,
                    structured_data=structured_data,
                    locations=locations,
                ),
                source="provider_activity",
                kind=activity_kind[:96],
                provenance="provider_reported",
                verification_state="not_applicable",
                summary=summary,
                structured_data=structured_data,
            )
            for locator in locations:
                await self._evidence.append_evidence(
                    delegated_agent_run_id=delegated_agent_run_id,
                    delegated_agent_turn_id=delegated_agent_turn_id,
                    source_event_key=_event_key("activity-artifact", f"{entry_id}:{locator}"),
                    source="provider_activity",
                    kind="artifact_locator",
                    provenance="provider_reported",
                    verification_state="pending",
                    summary=f"Provider reported workspace artifact: {locator}",
                    structured_data={"activity_kind": activity_kind[:96]},
                    artifact_locator=locator,
                )
        except Exception:
            await self._record_capture_unavailable(
                delegated_agent_run_id=delegated_agent_run_id,
                delegated_agent_turn_id=delegated_agent_turn_id,
                source_event_key=_event_key("activity-capture-failure", entry_id),
            )

    async def capture_terminal_response(
        self,
        *,
        delegated_agent_run_id: str,
        delegated_agent_turn_id: str,
        response: Mapping[str, Any],
    ) -> None:
        stop_reason = _bounded_text(response.get("stopReason"), 200) or "unknown"
        try:
            await self._evidence.append_evidence(
                delegated_agent_run_id=delegated_agent_run_id,
                delegated_agent_turn_id=delegated_agent_turn_id,
                source_event_key=_event_key("terminal", delegated_agent_turn_id),
                source="provider_terminal_response",
                kind="turn_terminal_response",
                provenance="provider_reported",
                verification_state="not_applicable",
                summary=f"Provider completed this turn with stop reason: {stop_reason}.",
                structured_data={"stop_reason": stop_reason, "usage": _safe_usage(response.get("usage"))},
            )
        except Exception:
            await self._record_capture_unavailable(
                delegated_agent_run_id=delegated_agent_run_id,
                delegated_agent_turn_id=delegated_agent_turn_id,
                source_event_key=_event_key("terminal-capture-failure", delegated_agent_turn_id),
            )

    def capture_state(self, *, delegated_agent_run_id: str) -> str:
        return "unavailable" if any(run_id == delegated_agent_run_id for run_id, _ in self._capture_failures) else "available"

    async def _record_capture_unavailable(
        self,
        *,
        delegated_agent_run_id: str,
        delegated_agent_turn_id: str,
        source_event_key: str,
    ) -> None:
        self._capture_failures.add((delegated_agent_run_id, delegated_agent_turn_id))
        try:
            await self._evidence.append_evidence(
                delegated_agent_run_id=delegated_agent_run_id,
                delegated_agent_turn_id=delegated_agent_turn_id,
                source_event_key=source_event_key,
                source="provider_activity",
                kind="capture_unavailable",
                provenance="unavailable",
                verification_state="unavailable",
                summary="Basil could not durably capture one bounded provider activity fact.",
                structured_data={},
            )
        except Exception:
            return
