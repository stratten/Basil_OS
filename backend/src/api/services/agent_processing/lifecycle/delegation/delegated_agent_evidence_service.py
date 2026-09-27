"""Derive bounded parent-owned report cards from delegated-agent evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class DelegatedAgentEvidenceService:
    """Read one owned run without creating another durable report-card authority."""

    def __init__(self, *, delegated_agent_repository: Any, evidence_repository: Any) -> None:
        self._runs = delegated_agent_repository
        self._evidence = evidence_repository

    async def build_parent_report_card(
        self, *, parent_agent_task_id: str, delegated_agent_run_id: str
    ) -> dict[str, Any]:
        run = await self._runs.get_run(delegated_agent_run_id)
        if run is None or run["parent_agent_task_id"] != parent_agent_task_id:
            raise ValueError("delegated child is not owned by this parent")
        page = await self._evidence.list_evidence_for_run(
            delegated_agent_run_id=delegated_agent_run_id,
            limit=24,
        )
        aggregate = await self._evidence.get_report_card_aggregate(delegated_agent_run_id)
        items = page["items"]
        claims = [
            {
                "evidence_id": item["id"],
                "kind": item["kind"],
                "provenance": item["provenance"],
                "verification_state": item["verification_state"],
                "summary": item["summary"],
            }
            for item in items[-6:]
        ]
        artifacts = [
            {
                "evidence_id": item["id"],
                "kind": item["kind"],
                "artifact_locator": item["artifact_locator"],
                "provenance": item["provenance"],
                "verification_state": item["verification_state"],
            }
            for item in items
            if item["artifact_locator"] is not None
        ][-6:]
        return {
            "delegated_agent_run_id": run["id"],
            "run_status": run["status"],
            "run_revision": run["revision"],
            "capture_state": "available" if aggregate["evidence_count"] else "unavailable",
            "evidence_count": aggregate["evidence_count"],
            "latest_summary": aggregate["latest_summary"],
            "verification_state": aggregate["verification_state"],
            "claims": claims,
            "artifacts": artifacts,
            "next_after_sequence": page["next_after_sequence"],
        }

    async def build_parent_report_cards(self, *, parent_agent_task_id: str) -> list[dict[str, Any]]:
        """Return compact derived cards for every delegated run owned by one parent."""
        runs = await self._runs.list_runs_for_parent(parent_agent_task_id)
        cards: list[dict[str, Any]] = []
        for run in runs:
            report = await self.build_parent_report_card(
                parent_agent_task_id=parent_agent_task_id,
                delegated_agent_run_id=str(run["id"]),
            )
            cards.append(
                {
                    "delegated_agent_run_id": report["delegated_agent_run_id"],
                    "run_status": report["run_status"],
                    "run_revision": report["run_revision"],
                    "capture_state": report["capture_state"],
                    "evidence_count": report["evidence_count"],
                    "latest_summary": report["latest_summary"],
                    "verification_state": report["verification_state"],
                }
            )
        return cards

    async def build_parent_supervision_snapshot(
        self, *, parent_agent_task_id: str, delegated_agent_run_id: str, capture_state: str
    ) -> dict[str, Any]:
        if capture_state not in {"available", "unavailable"}:
            raise ValueError("capture_state is unsupported")
        report = await self.build_parent_report_card(
            parent_agent_task_id=parent_agent_task_id,
            delegated_agent_run_id=delegated_agent_run_id,
        )
        return {
            "delegated_agent_run_id": report["delegated_agent_run_id"],
            "run_status": report["run_status"],
            "run_revision": report["run_revision"],
            "capture_state": "unavailable" if capture_state == "unavailable" else report["capture_state"],
            "evidence_count": report["evidence_count"],
            "latest_summary": report["latest_summary"],
            "claims": report["claims"],
            "artifacts": [
                {
                    "evidence_id": artifact["evidence_id"],
                    "kind": artifact["kind"],
                    "provenance": artifact["provenance"],
                    "verification_state": artifact["verification_state"],
                }
                for artifact in report["artifacts"]
            ],
            "next_after_sequence": report["next_after_sequence"],
        }

    async def inspect_parent_evidence(
        self,
        *,
        parent_agent_task_id: str,
        delegated_agent_run_id: str,
        evidence_id: str | None,
        after_sequence: int | None,
        limit: int,
    ) -> dict[str, Any]:
        run = await self._runs.get_run(delegated_agent_run_id)
        if run is None or run["parent_agent_task_id"] != parent_agent_task_id:
            raise ValueError("delegated child is not owned by this parent")
        if evidence_id is not None:
            evidence = await self._evidence.get_evidence_for_parent(
                parent_agent_task_id=parent_agent_task_id,
                delegated_agent_run_id=delegated_agent_run_id,
                evidence_id=evidence_id,
            )
            if evidence is None:
                raise ValueError("evidence is not owned by this parent")
            items = [self._inspection_item(evidence)]
            next_after_sequence = None
        else:
            page = await self._evidence.list_evidence_for_run(
                delegated_agent_run_id=delegated_agent_run_id,
                after_sequence=after_sequence,
                limit=limit,
            )
            items = [self._inspection_item(item) for item in page["items"]]
            next_after_sequence = page["next_after_sequence"]
        return {
            "delegated_agent_run_id": run["id"],
            "run_status": run["status"],
            "items": items,
            "next_after_sequence": next_after_sequence,
        }

    @staticmethod
    def _inspection_item(evidence: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "evidence_id": evidence["id"],
            "sequence": evidence["sequence"],
            "source": evidence["source"],
            "kind": evidence["kind"],
            "provenance": evidence["provenance"],
            "verification_state": evidence["verification_state"],
            "summary": evidence["summary"],
            "structured_data": evidence["structured_data"],
            "created_at": evidence["created_at"],
        }
