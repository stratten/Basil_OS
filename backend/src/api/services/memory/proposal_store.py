"""Unified storage for user-reviewable memory and skill proposals."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from api.core.config.api_settings import settings
from api.services.memory.memory_evaluator import MemoryProposal
from api.services.skills.skill_evaluator import SkillProposal


logger = logging.getLogger(__name__)
PROPOSAL_STORE_FILE_NAME = "proposal_store.json"


def union_preserving_order(existing: Optional[List[str]], incoming: Optional[List[str]]) -> List[str]:
    """Union two string lists, keeping existing order first then new entries."""
    seen: Dict[str, None] = {}
    for value in list(existing or []) + list(incoming or []):
        text = str(value).strip()
        if text and text not in seen:
            seen[text] = None
    return list(seen.keys())


# Backwards-compatible private alias for in-module call sites.
_union_preserving_order = union_preserving_order


@dataclass(frozen=True)
class MemoryProposalRecord:
    id: str
    target_file_name: str
    entry: str
    why: str
    confidence: str
    source: str
    created_at: str
    status: str = "pending"
    updated_at: Optional[str] = None
    reviewed_at: Optional[str] = None


@dataclass(frozen=True)
class SkillCandidateRecord:
    id: str
    title: str
    when_to_use: str
    triggers: List[str]
    procedure_markdown: str
    expected_result: str
    source_task_ids: List[str]
    source: str
    created_at: str
    status: str = "pending"
    updated_at: Optional[str] = None
    reviewed_at: Optional[str] = None
    enhances_skill_slug: Optional[str] = None
    observation_count: int = 1
    approved_skill_slug: Optional[str] = None


def _skill_candidate_from_record(record: Dict[str, Any]) -> SkillCandidateRecord:
    """Reconstruct a candidate, backfilling observation_count for legacy records.

    Records persisted before the recurrence counter existed have no
    ``observation_count`` key; derive it from the distinct source task ids so
    the materialized field always equals the count of unique observations.
    """
    updates: Dict[str, Any] = {}
    if "observation_count" not in record:
        updates["observation_count"] = len(
            union_preserving_order(None, record.get("source_task_ids"))
        )
    if "approved_skill_slug" not in record:
        updates["approved_skill_slug"] = None
    if updates:
        record = {**record, **updates}
    return SkillCandidateRecord(**record)


class ProposalStore:
    """JSON-backed proposal queue for Settings and evaluator workers."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or settings.STORAGE_DIR / "memory" / PROPOSAL_STORE_FILE_NAME

    def enqueue_memory_proposals(
        self,
        proposals: List[MemoryProposal],
        *,
        source: str,
    ) -> List[MemoryProposalRecord]:
        store = self._read_store()
        created_at = datetime.now(timezone.utc).isoformat()
        records = [
            MemoryProposalRecord(
                id=f"memory-proposal-{uuid.uuid4().hex}",
                target_file_name=proposal.target_file,
                entry=proposal.observation,
                why=proposal.why,
                confidence=proposal.confidence,
                source=source,
                created_at=created_at,
            )
            for proposal in proposals
        ]
        store["memory_proposals"].extend(asdict(record) for record in records)
        self._write_store(store)
        return records

    def enqueue_skill_candidates(
        self,
        proposals: List[SkillProposal],
        *,
        source: str,
    ) -> List[SkillCandidateRecord]:
        store = self._read_store()
        created_at = datetime.now(timezone.utc).isoformat()
        records = [
            SkillCandidateRecord(
                id=f"skill-candidate-{uuid.uuid4().hex}",
                title=proposal.title,
                when_to_use=proposal.when_to_use,
                triggers=proposal.triggers,
                procedure_markdown=proposal.procedure_markdown,
                expected_result=proposal.expected_result,
                source_task_ids=proposal.source_task_ids,
                source=source,
                created_at=created_at,
                enhances_skill_slug=getattr(proposal, "enhances_skill_slug", None),
                observation_count=len(union_preserving_order(None, proposal.source_task_ids)),
            )
            for proposal in proposals
        ]
        store["skill_candidates"].extend(asdict(record) for record in records)
        self._write_store(store)
        return records

    def list_pending_memory_proposals(self) -> List[MemoryProposalRecord]:
        return [
            MemoryProposalRecord(**record)
            for record in self._read_store()["memory_proposals"]
            if record.get("status") == "pending"
        ]

    def list_pending_skill_candidates(self) -> List[SkillCandidateRecord]:
        return [
            _skill_candidate_from_record(record)
            for record in self._read_store()["skill_candidates"]
            if record.get("status") == "pending"
        ]

    def get_memory_proposal(self, proposal_id: str) -> MemoryProposalRecord:
        for record in self._read_store()["memory_proposals"]:
            if record.get("id") == proposal_id:
                return MemoryProposalRecord(**record)
        raise ValueError(f"Proposal '{proposal_id}' was not found.")

    def get_skill_candidate(self, candidate_id: str) -> SkillCandidateRecord:
        for record in self._read_store()["skill_candidates"]:
            if record.get("id") == candidate_id:
                return _skill_candidate_from_record(record)
        raise ValueError(f"Skill candidate '{candidate_id}' was not found.")

    def update_memory_proposal_entry(
        self,
        proposal_id: str,
        *,
        target_file_name: str,
        entry: str,
    ) -> MemoryProposalRecord:
        store = self._read_store()
        for record in store["memory_proposals"]:
            if record.get("id") == proposal_id:
                record["target_file_name"] = target_file_name
                record["entry"] = entry
                record["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._write_store(store)
                return MemoryProposalRecord(**record)
        raise ValueError(f"Proposal '{proposal_id}' was not found.")

    def update_skill_candidate(
        self,
        candidate_id: str,
        *,
        title: str,
        when_to_use: str,
        triggers: List[str],
        procedure_markdown: str,
    ) -> SkillCandidateRecord:
        store = self._read_store()
        for record in store["skill_candidates"]:
            if record.get("id") == candidate_id:
                record["title"] = title
                record["when_to_use"] = when_to_use
                record["triggers"] = triggers
                record["procedure_markdown"] = procedure_markdown
                record["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._write_store(store)
                return _skill_candidate_from_record(record)
        raise ValueError(f"Skill candidate '{candidate_id}' was not found.")

    def replace_skill_candidate_content(
        self,
        candidate_id: str,
        *,
        title: str,
        when_to_use: str,
        triggers: List[str],
        procedure_markdown: str,
        expected_result: str,
        source_task_ids: List[str],
    ) -> SkillCandidateRecord:
        """Replace a pending candidate's content in place with a model-merged result.

        Used when the evaluator folds a new task into an existing pending
        candidate. The candidate stays pending; triggers and source_task_ids are
        defensively unioned with the existing record so nothing is dropped.
        """
        store = self._read_store()
        for record in store["skill_candidates"]:
            if record.get("id") == candidate_id:
                record["title"] = title
                record["when_to_use"] = when_to_use
                record["triggers"] = _union_preserving_order(record.get("triggers"), triggers)
                record["procedure_markdown"] = procedure_markdown
                record["expected_result"] = expected_result
                record["source_task_ids"] = _union_preserving_order(
                    record.get("source_task_ids"), source_task_ids
                )
                record["observation_count"] = len(record["source_task_ids"])
                record["status"] = "pending"
                record["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._write_store(store)
                return _skill_candidate_from_record(record)
        raise ValueError(f"Skill candidate '{candidate_id}' was not found.")

    def mark_memory_proposal_status(self, proposal_id: str, status: str) -> MemoryProposalRecord:
        return MemoryProposalRecord(**self._mark_status("memory_proposals", proposal_id, status))

    def mark_skill_candidate_status(self, candidate_id: str, status: str) -> SkillCandidateRecord:
        return _skill_candidate_from_record(
            self._mark_status("skill_candidates", candidate_id, status)
        )

    def mark_skill_candidate_approved(
        self,
        candidate_id: str,
        approved_skill_slug: str,
    ) -> SkillCandidateRecord:
        """Persist the saved skill created by one approved candidate."""
        store = self._read_store()
        for record in store["skill_candidates"]:
            if record.get("id") != candidate_id:
                continue
            existing_slug = record.get("approved_skill_slug")
            if record.get("status") == "approved" and existing_slug == approved_skill_slug:
                return _skill_candidate_from_record(record)
            if record.get("status") != "pending":
                raise ValueError(
                    f"Skill candidate '{candidate_id}' was already reviewed."
                )
            record["status"] = "approved"
            record["approved_skill_slug"] = approved_skill_slug
            record["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            self._write_store(store)
            return _skill_candidate_from_record(record)
        raise ValueError(f"Skill candidate '{candidate_id}' was not found.")

    def _mark_status(self, collection_name: str, record_id: str, status: str) -> Dict[str, Any]:
        if status not in {"approved", "declined"}:
            raise ValueError(f"Unsupported proposal status: {status}")
        store = self._read_store()
        for record in store[collection_name]:
            if record.get("id") == record_id:
                record["status"] = status
                record["reviewed_at"] = datetime.now(timezone.utc).isoformat()
                self._write_store(store)
                return record
        raise ValueError(f"Proposal '{record_id}' was not found.")

    def _read_store(self) -> Dict[str, List[Dict[str, Any]]]:
        if not self.path.exists():
            return self._empty_store()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return {
                "memory_proposals": list(payload.get("memory_proposals") or []),
                "skill_candidates": list(payload.get("skill_candidates") or []),
            }
        except Exception:
            logger.exception("Failed to read proposal store")
            return self._empty_store()

    def _write_store(self, payload: Dict[str, List[Dict[str, Any]]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temporary_path.replace(self.path)

    def _empty_store(self) -> Dict[str, List[Dict[str, Any]]]:
        return {
            "memory_proposals": [],
            "skill_candidates": [],
        }


_proposal_store_singleton: Optional[ProposalStore] = None


def get_proposal_store() -> ProposalStore:
    global _proposal_store_singleton
    if _proposal_store_singleton is None:
        _proposal_store_singleton = ProposalStore()
    return _proposal_store_singleton
