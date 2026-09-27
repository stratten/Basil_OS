"""Durable, task-chain-scoped work-ledger orchestration."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_work.records import (
    CLAIMABLE_ITEM_STATUSES,
)
from api.services.agent_processing.shared.material_operation_receipts import (
    MaterialOperationEnvelope,
    extract_material_operation_envelope,
)

from .ledger_json import sanitize_ledger_email_list
from .work_ledger_capture import capture_records, capture_scope, normalize_tool_result


class AgentWorkLedgerService:
    """Coordinates durable work sessions, captured tool evidence, and handoffs."""

    def __init__(self, knowledge_service) -> None:
        self._knowledge_service = knowledge_service
        self._sessions = knowledge_service.agent_work_session_repository
        self._entities = knowledge_service.agent_work_entity_repository
        self._events = knowledge_service.agent_work_event_repository
        self._receipts = knowledge_service.agent_work_receipt_repository

    @staticmethod
    def root_task_id(context: Optional[Dict[str, Any]]) -> Optional[str]:
        context = context or {}
        return context.get("root_task_id") or context.get("agent_task_id")

    async def ensure_session(
        self,
        *,
        context: Optional[Dict[str, Any]],
        goal: Optional[str] = None,
        collection_type: str = "agent_work",
        scope: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        context = context or {}
        root_task_id = self.root_task_id(context)
        if not root_task_id:
            return None
        return await self._sessions.get_or_create_root_session(
            agent_task_id=context.get("agent_task_id"),
            root_task_id=str(root_task_id),
            goal=goal or context.get("user_agent_task") or "Agent work",
            collection_type=collection_type,
            scope=scope or {},
        )

    @staticmethod
    def _material_operation_from_payload(
        payload: Any,
    ) -> Optional[MaterialOperationEnvelope]:
        envelope = extract_material_operation_envelope(payload)
        if envelope:
            return envelope
        if isinstance(payload, dict):
            return extract_material_operation_envelope(payload.get("result"))
        outcome_review = getattr(payload, "outcome_review", None)
        return extract_material_operation_envelope(outcome_review)

    async def _capture_material_operation(
        self,
        *,
        session: Dict[str, Any],
        context: Optional[Dict[str, Any]],
        service: str,
        method: str,
        envelope: MaterialOperationEnvelope,
        receipt_key: Optional[str],
    ) -> Dict[str, Any]:
        persisted_receipts = []
        task_id = (context or {}).get("agent_task_id")
        for index, receipt in enumerate(envelope.receipts):
            entity = await self._entities.upsert_entity(
                session_id=session["id"],
                entity_type=receipt.entity.entity_type,
                source_system=receipt.entity.source_system,
                source_scope=receipt.entity.source_scope,
                external_id=receipt.entity.external_id,
                metadata={},
            )
            await self._events.add_event(
                session_id=session["id"],
                item_id=entity["id"],
                agent_task_id=task_id,
                event_kind="material_operation_capture",
                payload={
                    "entity": receipt.entity.to_dict(),
                    "execution_state": receipt.execution_state,
                    "verification_status": receipt.verification_status,
                },
            )
            persisted_receipts.append(
                await self._receipts.add_receipt(
                    session_id=session["id"],
                    item_id=entity["id"],
                    agent_task_id=task_id,
                    service=service,
                    method=method,
                    receipt_key=(
                        f"{receipt_key}:entity:{index}"
                        if receipt_key
                        else None
                    ),
                    requested_effect=receipt.requested_effect,
                    observed_postcondition=receipt.observed_postcondition,
                    execution_state=receipt.execution_state,
                    verification_status=receipt.verification_status,
                    evidence=receipt.evidence,
                    discrepancy=receipt.discrepancy,
                    material_write=True,
                )
            )
        return {
            "session": session,
            "receipt": persisted_receipts[0],
            "receipts": persisted_receipts,
            "item_count": len(envelope.receipts),
        }

    async def resolve_session(
        self,
        *,
        context: Optional[Dict[str, Any]],
        session_id: Optional[str] = None,
        create: bool = False,
        goal: Optional[str] = None,
        collection_type: str = "agent_work",
    ) -> Optional[Dict[str, Any]]:
        root_task_id = self.root_task_id(context)
        if not root_task_id:
            return None
        if session_id:
            session = await self._sessions.get_session(session_id)
            if not session or session.get("root_task_id") != str(root_task_id):
                raise ValueError("Work session is not accessible from this task chain.")
            return session
        session = await self._sessions.get_latest_session_for_root(str(root_task_id))
        return session or (
            await self.ensure_session(
                context=context, goal=goal, collection_type=collection_type,
            )
            if create else None
        )

    async def capture_tool_result(
        self,
        *,
        context: Optional[Dict[str, Any]],
        service: str,
        method: str,
        parameters: Optional[Dict[str, Any]],
        result: Any,
        error: Optional[Any] = None,
        receipt_key: Optional[str] = None,
        evidence_source: str = "raw_service",
        opaque_evidence: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Persist evidence without changing tool output or failure semantics."""
        payload = normalize_tool_result(result)
        captured_scope = capture_scope(payload)
        session = await self.ensure_session(
            context=context,
            collection_type=service,
            scope=captured_scope,
        )
        if not session:
            return None
        if captured_scope:
            session = await self._sessions.update_scope(
                session["id"],
                {**(session.get("scope") or {}), **captured_scope},
            ) or session
        material_operation = self._material_operation_from_payload(payload)
        if material_operation:
            return await self._capture_material_operation(
                session=session,
                context=context,
                service=service,
                method=method,
                envelope=material_operation,
                receipt_key=receipt_key or (context or {}).get("tool_call_id"),
            )
        records = capture_records(payload, source_system=service)
        captured_entities: Dict[str, Dict[str, Any]] = {}
        if records:
            for record in records:
                entity = await self._entities.upsert_entity(
                    session_id=session["id"],
                    entity_type=record.entity_type,
                    source_system=record.source_system,
                    source_scope={},
                    external_id=record.external_id,
                    metadata=record.metadata,
                    identity_quality="best_effort_capture",
                )
                captured_entities[record.external_id] = entity
                await self._events.add_event(
                    session_id=session["id"],
                    item_id=entity["id"],
                    agent_task_id=(context or {}).get("agent_task_id"),
                    event_kind="discovery_capture",
                    payload={
                        "external_id": record.external_id,
                        "entity_type": record.entity_type,
                        "source_system": record.source_system,
                        "identity_quality": "best_effort_capture",
                    },
                )
        success = getattr(result, "success", None)
        if success is None and isinstance(payload, dict):
            success = payload.get("success")
        execution_state = "succeeded" if success is not False and not error else "failed"
        result_payload = payload.get("result") if isinstance(payload, dict) else payload
        verification_status = "unverified"
        if isinstance(result_payload, dict):
            verification_status = str(
                result_payload.get("verification_status")
                or result_payload.get("outcome_verification_status")
                or verification_status
            ).lower()
        if verification_status not in self._receipts.VERIFICATION_STATUSES:
            verification_status = "not_applicable" if execution_state == "succeeded" else "failed"
        if not records and execution_state == "succeeded" and verification_status == "unverified":
            verification_status = "not_applicable"
        if hasattr(result_payload, "coverage_metadata"):
            receipt = await self._receipts.add_receipt(
                session_id=session["id"],
                item_id=None,
                agent_task_id=(context or {}).get("agent_task_id"),
                service=service,
                method=method,
                receipt_key=receipt_key or (context or {}).get("tool_call_id"),
                requested_effect={"parameters": parameters or {}, "material_write": False},
                observed_postcondition={},
                execution_state=execution_state,
                verification_status=verification_status,
                evidence=(
                    opaque_evidence
                    if opaque_evidence is not None
                    else {
                        "source": evidence_source,
                        "result": sanitize_ledger_email_list(result_payload),
                    }
                ),
                discrepancy={"error": str(error)} if error else {},
            )
            return {
                "session": session,
                "receipt": receipt,
                "receipts": [receipt],
                "item_count": len(records),
            }

        receipts = []
        for record in records or [None]:
            entity = captured_entities.get(record.external_id) if record else None
            record_key = receipt_key or (context or {}).get("tool_call_id")
            if record_key and record:
                record_key = f"{record_key}:{record.external_id}"
            receipts.append(await self._receipts.add_receipt(
                session_id=session["id"],
                item_id=entity["id"] if entity else None,
                agent_task_id=(context or {}).get("agent_task_id"),
                service=service,
                method=method,
                receipt_key=record_key,
                requested_effect={"parameters": parameters or {}, "material_write": False},
                observed_postcondition={},
                execution_state=execution_state,
                verification_status=record.verification_status if record else verification_status,
                evidence=(
                    record.evidence
                    if record and record.evidence
                    else opaque_evidence
                    if opaque_evidence is not None
                    else {"source": evidence_source, "result": result_payload}
                ),
                discrepancy={"error": str(error)} if error else {},
            ))
        return {
            "session": session,
            "receipt": receipts[0],
            "receipts": receipts,
            "item_count": len(records),
        }

    async def handoff(self, *, context: Optional[Dict[str, Any]]) -> str:
        session = await self.resolve_session(context=context)
        if not session:
            return ""
        summary = await self._sessions.summarize(session["id"])
        entities = await self._entities.get_entities(session_id=session["id"])
        material_receipt_counts = (
            await self._receipts.count_material_receipts_by_status(
                session_id=session["id"],
            )
        )
        unresolved_receipts = await self._receipts.get_unresolved_material_receipts(
            session_id=session["id"],
            limit=5,
        )
        unresolved_material_total = (
            material_receipt_counts.get("unverified", 0)
            + material_receipt_counts.get("failed", 0)
        )
        unresolved = {
            status: count for status, count in summary.get("item_counts", {}).items()
            if status in CLAIMABLE_ITEM_STATUSES
        }
        source_scopes = sorted(
            {
                json.dumps(
                    {
                        "entity_type": entity["entity_type"],
                        "source_system": entity["source_system"],
                        "source_scope": entity["source_scope"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                for entity in entities
                if entity["entity_type"] and entity["source_system"]
            }
        )
        return (
            "\n\nWORK LEDGER:\n"
            f"- session_id: {session['id']}\n"
            f"- root_task_id: {session.get('root_task_id')}\n"
            f"- scope: {json.dumps(session.get('scope') or {}, ensure_ascii=False, sort_keys=True)}\n"
            f"- item_counts: {json.dumps(summary.get('item_counts') or {}, sort_keys=True)}\n"
            f"- source_scopes: {json.dumps(source_scopes, ensure_ascii=False)}\n"
            f"- unresolved: {json.dumps(unresolved, sort_keys=True)}\n"
            f"- material_receipt_counts: {json.dumps(material_receipt_counts, sort_keys=True)}\n"
            f"- unresolved_material_receipt_total: {unresolved_material_total}\n"
            f"- unresolved_material_receipts: {json.dumps(receipt_summaries_from_rows(unresolved_receipts), ensure_ascii=False, sort_keys=True)}\n"
            "Use iterative_work with this session_id to query, claim, or update durable work.\n"
        )


def receipt_summaries_from_rows(receipts: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Return compact deterministic handoff receipt summaries without raw evidence."""
    return [
        {
            "id": receipt["id"],
            "item_id": receipt["item_id"],
            "service": receipt["service"],
            "method": receipt["method"],
            "execution_state": receipt["execution_state"],
            "verification_status": receipt["verification_status"],
        }
        for receipt in receipts[:5]
    ]
