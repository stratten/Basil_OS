"""Submission entrypoints for AgentTask lifecycle."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional


class AgentTaskSubmissionService:
    """Creates AgentTask records and starts routing/processing."""

    def __init__(
        self,
        *,
        db_service: Any,
        screen_context_service: Any,
        routing_service: Any,
        processing_service: Any,
        is_canceled: Optional[Callable[[str], bool]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.db_service = db_service
        self.screen_context_service = screen_context_service
        self.routing_service = routing_service
        self.processing_service = processing_service
        self._is_canceled = is_canceled or (lambda _agent_task_id: False)
        self.logger = logger or logging.getLogger(__name__)
        self._delegated_agent_runs = getattr(db_service, "delegated_agent_repository", None)

    async def reserve_delegated_agent_task(
        self,
        *,
        agent_task: str,
        child_agent_task_id: str,
        root_task_id: str,
        parent_agent_task_id: str,
        chain_sequence_number: int,
        session_type: str,
        accumulated_artifacts: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Persist the canonical child row without starting routing or capture."""

        if not all(isinstance(value, str) and value.strip() for value in (agent_task, child_agent_task_id, root_task_id, parent_agent_task_id, session_type)):
            raise ValueError("delegated child identity and task fields must be nonblank")
        await self.db_service.store_agent_task(
            agent_task_id=child_agent_task_id,
            original_prompt=agent_task,
            transcribed_prompt=agent_task,
            display_prompt_markdown=None,
            status="routing",
            app_name=None,
            window_title=None,
            screen_text=None,
            screen_capture_path=None,
            root_task_id=root_task_id,
            previous_task_id=parent_agent_task_id,
            chain_sequence_number=chain_sequence_number,
            session_type=session_type,
            accumulated_artifacts=dict(accumulated_artifacts),
            origin_type=None,
            origin_id=None,
        )
        return {"success": True, "agent_task_id": child_agent_task_id, "status": "routing", "reserved": True}

    async def dispatch_reserved_delegated_agent_task(
        self,
        *,
        child_agent_task_id: str,
        root_task_id: str,
        parent_agent_task_id: str,
    ) -> Dict[str, Any]:
        """Start deferred capture only after generic admission commits exactly once."""

        if self._delegated_agent_runs is None:
            raise RuntimeError("delegated-agent repository is unavailable")
        reservation = await self._delegated_agent_runs.mark_reservation_dispatched(child_agent_task_id)
        try:
            asyncio.ensure_future(
                self._capture_and_persist_screen_context(
                    agent_task_id=child_agent_task_id,
                    pre_captured_screenshot=None,
                    root_task_id=root_task_id,
                    previous_task_id=parent_agent_task_id,
                )
            )
        except Exception:
            await self._delegated_agent_runs.mark_reservation_dispatch_failed(child_agent_task_id)
            run = await self._delegated_agent_runs.get_run_for_child(child_agent_task_id)
            if run is not None and run["status"] not in {"settled", "failed", "canceled"}:
                await self._delegated_agent_runs.record_outcome(
                    delegated_agent_run_id=str(run["id"]),
                    expected_revision=int(run["revision"]),
                    transport_state="dispatch",
                    executor_result_state="failed",
                    evidence_state="unavailable",
                    summary="Delegated child dispatch failed before routing started.",
                    receipt_references=[],
                    terminal_status="failed",
                )
            raise
        return {"success": True, "agent_task_id": child_agent_task_id, "status": "routing", "reservation": reservation}

    async def process_agent_task(
        self,
        agent_task: str,
        display_prompt_markdown: Optional[str] = None,
        pre_captured_screenshot: Dict[str, Any] = None,
        agent_task_id: str = None,
        synchronous: bool = False,
        chain_context: Dict[str, Any] = None,
        reference_paths: Optional[List[str]] = None,
        model_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        provider_target: Optional[Dict[str, Any]] = None,
        origin_type: Optional[str] = None,
        origin_id: Optional[str] = None,
        todo_workspace_context: Optional[Dict[str, Any]] = None,
        todo_worker_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Process a new AgentTask using event-driven or synchronous architecture."""
        if not agent_task_id:
            agent_task_id = str(uuid.uuid4())

        # Anchor for the critical-path timer: entry -> 'routing' set. On the async
        # path this excludes screen capture (now deferred), so the logged span
        # quantifies how quickly the task reaches routing/execution.
        _submit_started = time.monotonic()

        self.logger.info("🎯 Processing new agent_task via orchestrator: %r (ID: %s)", agent_task, agent_task_id)
        if chain_context:
            self.logger.info(
                "🔗 Chain context: root=%s, sequence=%s",
                chain_context.get("root_task_id"),
                chain_context.get("chain_sequence_number"),
            )

        try:
            artifacts = chain_context.get("accumulated_artifacts", {}) if chain_context else {}
            if provider_target:
                artifacts["provider_target"] = provider_target
            if reference_paths:
                artifacts["reference_paths"] = reference_paths
            if model_id:
                artifacts["model_id"] = model_id
            if conversation_id:
                artifacts["conversation_id"] = conversation_id
            if todo_workspace_context:
                artifacts["todo_workspace_context"] = todo_workspace_context
            if todo_worker_context is not None:
                artifacts["todo_worker_context"] = todo_worker_context

            await self.db_service.store_agent_task(
                agent_task_id=agent_task_id,
                original_prompt=agent_task,
                transcribed_prompt=agent_task,
                display_prompt_markdown=display_prompt_markdown,
                status="capturing",
                app_name=None,
                window_title=None,
                screen_text=None,
                screen_capture_path=None,
                root_task_id=(
                    chain_context.get("root_task_id")
                    if chain_context
                    else (agent_task_id if provider_target else None)
                ),
                previous_task_id=chain_context.get("previous_task_id") if chain_context else None,
                chain_sequence_number=chain_context.get("chain_sequence_number", 0) if chain_context else 0,
                session_type=chain_context.get("session_type") if chain_context else None,
                accumulated_artifacts=artifacts if artifacts else None,
                origin_type=origin_type,
                origin_id=origin_id,
            )

            if self._is_canceled(agent_task_id):
                await self.db_service.update_agent_task_status(
                    agent_task_id=agent_task_id,
                    status="canceled",
                    result_data={
                        "canceled": True,
                        "cancellation_reason": "User canceled",
                        "canceled_at": datetime.utcnow().isoformat(),
                    },
                )
                self.logger.info(
                    "🛑 Persisted preemptively canceled agent_task %s as terminal",
                    agent_task_id,
                )
                return {
                    "success": False,
                    "agent_task_id": agent_task_id,
                    "status": "canceled",
                    "message": "Task canceled",
                }

            asyncio.ensure_future(self.routing_service.generate_agent_task_title(agent_task_id, agent_task))

            root_task_id = chain_context.get("root_task_id") if chain_context else None
            previous_task_id = chain_context.get("previous_task_id") if chain_context else None

            if synchronous:
                # Synchronous path keeps blocking capture so the fully-assembled
                # context (incl. screen_text) is available to _process_synchronously.
                await self.routing_service.send_progress_update(
                    "Reading screen context",
                    "started",
                    "Extracting text from the current screen...",
                    agent_task_id=agent_task_id,
                    root_task_id=root_task_id,
                    previous_task_id=previous_task_id,
                )
                try:
                    context = await self.capture_screen_context(pre_captured_screenshot)
                except Exception as capture_error:
                    self.logger.warning("Screen context capture failed; continuing without OCR context: %s", capture_error)
                    context = {}

                if reference_paths:
                    context["reference_paths"] = reference_paths
                    self.logger.info("📂 Including %s reference paths in agent-task context", len(reference_paths))

                screen_text = context.get("screen_text") or ""
                app_name = context.get("active_app")
                window_title = context.get("window_title")
                await self.db_service.update_agent_task_screen_context(
                    agent_task_id=agent_task_id,
                    screen_text=screen_text,
                    app_name=app_name,
                    window_title=window_title,
                    screen_capture_path=context.get("screenshot_path"),
                )
                if screen_text:
                    screen_details = f"Read {len(screen_text):,} characters from {app_name or 'the current app'}."
                else:
                    screen_details = "Screen text was unavailable; continuing with the agent task text."
                await self.routing_service.send_progress_update(
                    "Reading screen context",
                    "completed",
                    screen_details,
                    agent_task_id=agent_task_id,
                    root_task_id=root_task_id,
                    previous_task_id=previous_task_id,
                )
                await self.db_service.update_agent_task_status(
                    agent_task_id=agent_task_id,
                    status="routing",
                )
                return await self._process_synchronously(agent_task_id, agent_task, context)

            # Async path: capture screen OFF the critical path so agent execution
            # starts immediately. The captured text is written back to this task's
            # own row when OCR finishes; the agent pulls it via
            # recall_agent_tasks(scope='screen') only if the request needs it.
            asyncio.ensure_future(
                self._capture_and_persist_screen_context(
                    agent_task_id=agent_task_id,
                    pre_captured_screenshot=pre_captured_screenshot,
                    root_task_id=root_task_id,
                    previous_task_id=previous_task_id,
                )
            )

            await self.db_service.update_agent_task_status(
                agent_task_id=agent_task_id,
                status="routing",
            )
            self.logger.info(
                "TIMING critical_path submit->routing=%.1fms agent_task_id=%s "
                "(screen capture deferred off critical path)",
                (time.monotonic() - _submit_started) * 1000.0,
                agent_task_id,
            )

            return {
                "success": True,
                "agent_task_id": agent_task_id,
                "status": "routing",
                "message": "Task received and being processed...",
                "context": {
                    "app": "pending",
                    "has_screen_text": False,
                },
            }

        except Exception as exc:
            self.logger.error("Error in orchestrator processing: %s", exc, exc_info=True)
            return {
                "success": False,
                "agent_task_id": agent_task_id,
                "status": "failed",
                "error": str(exc),
                "message": "Failed to process agent_task. Please try again.",
            }

    async def add_clarification(
        self,
        agent_task_id: str,
        clarification_text: str,
    ) -> Dict[str, Any]:
        """Add clarification to an existing AgentTask."""
        self.logger.info("🎯 Adding clarification to agent_task %s: %r", agent_task_id, clarification_text)
        try:
            await self.db_service.add_agent_task_clarification(
                agent_task_id=agent_task_id,
                clarification_text=clarification_text,
            )
            return {
                "success": True,
                "agent_task_id": agent_task_id,
                "status": "clarification_added",
                "message": "Clarification received and being processed...",
            }
        except Exception as exc:
            self.logger.error("Error adding clarification: %s", exc, exc_info=True)
            return {
                "success": False,
                "agent_task_id": agent_task_id,
                "error": str(exc),
                "message": "Failed to process clarification. Please try again.",
            }

    async def capture_screen_context(self, pre_captured_screenshot: Dict[str, Any] = None) -> Dict[str, Any]:
        """Capture current screen context through the dedicated service."""
        return await self.screen_context_service.capture_screen_context(pre_captured_screenshot)

    async def _capture_and_persist_screen_context(
        self,
        *,
        agent_task_id: str,
        pre_captured_screenshot: Dict[str, Any] = None,
        root_task_id: Optional[str] = None,
        previous_task_id: Optional[str] = None,
    ) -> None:
        """Background OCR + write-back for the async submission path.

        Runs off the critical path. ALWAYS writes screen_text as a string
        (empty on failure) so a NULL screen_text unambiguously means
        'capture still running' for recall(scope='screen').

        Intentionally emits NO user-facing progress updates: this runs
        concurrently with agent execution, so a "Reading screen context"
        chip would appear out of order in the activity feed. The result is
        surfaced only on demand via recall_agent_tasks(scope='screen').
        The root/previous task ids are retained for logging/tracing context.
        """
        context: Dict[str, Any] = {}
        _capture_started = time.monotonic()
        try:
            context = await self.capture_screen_context(pre_captured_screenshot)
        except Exception as capture_error:
            self.logger.warning("Async screen context capture failed; persisting empty screen text: %s", capture_error)
            context = {}
        capture_ms = (time.monotonic() - _capture_started) * 1000.0

        screen_text = context.get("screen_text") or ""
        app_name = context.get("active_app")
        window_title = context.get("window_title")
        try:
            await self.db_service.update_agent_task_screen_context(
                agent_task_id=agent_task_id,
                screen_text=screen_text,
                app_name=app_name,
                window_title=window_title,
                screen_capture_path=context.get("screenshot_path"),
            )
        except Exception as persist_error:
            self.logger.error("Failed to persist async screen context for %s: %s", agent_task_id, persist_error)
            return

        self.logger.info(
            "TIMING background screen capture=%.1fms; persisted %s chars from %s "
            "for %s (this duration was kept OFF the critical path)",
            capture_ms,
            len(screen_text),
            app_name or "unknown app",
            agent_task_id,
        )

    async def _process_synchronously(
        self,
        agent_task_id: str,
        agent_task: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        self.logger.info("Processing agent_task %s synchronously", agent_task_id)
        await self.routing_service.perform_routing(agent_task_id)

        agent_task_record = await self.db_service.get_agent_task(agent_task_id)
        if agent_task_record and agent_task_record.status == "processing":
            await self.processing_service.perform_processing(agent_task_id)

            final_agent_task = await self.db_service.get_agent_task(agent_task_id)
            if final_agent_task:
                operation_parameters = final_agent_task.operation_parameters or {}
                return {
                    "success": final_agent_task.status == "completed",
                    "agent_task_id": agent_task_id,
                    "status": final_agent_task.status,
                    "message": (
                        "Task processed successfully"
                        if final_agent_task.status == "completed"
                        else "Task processing failed"
                    ),
                    "operation": operation_parameters.get("operation"),
                    "confidence": operation_parameters.get("confidence", 0.9),
                    "reasoning": operation_parameters.get("reasoning", "AgentTask processed"),
                    "data": {"transcribed_prompt": agent_task},
                    "context": {
                        "app": context.get("active_app", "Unknown"),
                        "has_screen_text": len(context.get("screen_text", "")) > 0,
                    },
                }

        return {
            "success": False,
            "agent_task_id": agent_task_id,
            "status": "failed",
            "message": "Synchronous processing failed",
            "error": "Unable to complete processing",
        }


__all__ = ["AgentTaskSubmissionService"]
