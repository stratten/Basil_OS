"""Session-history enrichment and result-artifact persistence for workflows."""

import logging
from typing import Any, Dict, Optional

from .session_context_manager import get_session_context_manager
from .workflow_results import WorkflowExecutionResult


class WorkflowSessionContextService:
    """Enrich workflow context and save lightweight result artifacts for follow-ups."""

    def __init__(self, status_notifier=None):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.status_notifier = status_notifier

    async def enrich_context_with_session_history(
        self,
        user_agent_task: str,
        context: Dict[str, Any],
        agent_task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Enrich standalone tasks with recent history or preserve follow-up chain context."""
        try:
            chain_context = context.get("chain_context")
            if chain_context:
                self.logger.info("🔗 This is a follow-up - using chain context only (not general session history)")
                enriched_context = context.copy()
                enriched_context["chain_context"] = chain_context
                self.logger.info(f"🔗 Chain context keys: {list(chain_context.keys())}")
                if self.status_notifier and agent_task_id:
                    await self.status_notifier.send_session_context_info(
                        agent_task_id=agent_task_id,
                        has_recent_context=True,
                        context_count=1,
                    )
                return enriched_context

            session_manager = get_session_context_manager()
            recent_context = session_manager.get_recent_context(count=3)
            last_artifacts = session_manager.get_last_agent_task_artifacts()
            if recent_context:
                enriched_context = context.copy()
                enriched_context["recent_agentTasks"] = recent_context
                enriched_context["last_agentTask_artifacts"] = last_artifacts
                self.logger.info(f"📚 Enriched context with {len(recent_context)} recent agent tasks from session history")
                self.logger.debug(f"   Last artifacts keys: {list(last_artifacts.keys()) if last_artifacts else 'none'}")
                if self.status_notifier and agent_task_id:
                    await self.status_notifier.send_session_context_info(
                        agent_task_id=agent_task_id,
                        has_recent_context=True,
                        context_count=len(recent_context),
                    )
                return enriched_context

            self.logger.debug("📚 No recent agent-task history to enrich context")
            return context
        except Exception as error:
            self.logger.warning(f"⚠️ Failed to enrich context with session history: {error}")
            return context

    def save_agent_task_to_session_context(
        self,
        user_agent_task: str,
        result: WorkflowExecutionResult,
        agent_task_id: Optional[str] = None,
        operation: str = "multi_step_workflow",
        artifacts: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Save a completed agent-task result for future natural-language follow-ups."""
        try:
            session_manager = get_session_context_manager()
            result_summary = f"Completed {result.todos_completed} tasks"
            if artifacts is None:
                artifacts = self._extract_artifacts_from_result(result)
            session_manager.add_agent_task_result(
                agent_task_id=agent_task_id or "unknown",
                agent_task_text=user_agent_task,
                result_summary=result_summary,
                artifacts=artifacts,
                operation=operation,
            )
            self.logger.info(f"💾 Saved agent task to session context: '{user_agent_task[:50]}...'")
        except Exception as error:
            self.logger.warning(f"⚠️ Failed to save agent task to session context: {error}")

    def _extract_artifacts_from_result(self, result: WorkflowExecutionResult) -> Dict[str, Any]:
        """Extract lightweight artifact references from a workflow result."""
        artifacts: Dict[str, Any] = {}
        try:
            if hasattr(result, "final_envelope") and isinstance(result.final_envelope, dict):
                result_payload = result.final_envelope.get("result_payload", {})
                if "files" in result_payload:
                    artifacts["files"] = result_payload["files"]
                if "item_ids" in result_payload:
                    artifacts["item_ids"] = result_payload["item_ids"]

            if result.execution_results:
                for execution_result in result.execution_results:
                    if not isinstance(execution_result, dict):
                        continue
                    for key in ["created_items", "email_ids", "file_paths", "urls", "browser_automation_target"]:
                        if key in execution_result:
                            artifacts[key] = execution_result[key]
                    browser_targets = self._extract_browser_automation_targets(execution_result)
                    if browser_targets:
                        artifacts["browser_automation_targets"] = browser_targets

            self.logger.debug(f"📦 Extracted artifacts: {list(artifacts.keys())}")
        except Exception as error:
            self.logger.warning(f"⚠️ Failed to extract artifacts: {error}")
        return artifacts

    def _extract_browser_automation_targets(self, value: Any) -> list[dict[str, Any]]:
        """Extract JSON-safe browser automation targets from nested tool results."""
        targets: list[dict[str, Any]] = []
        for item in self._walk_values(value):
            if not isinstance(item, dict):
                continue
            target = item.get("browser_automation_target")
            if isinstance(target, dict) and target not in targets:
                targets.append(target)
        return targets

    def _walk_values(self, value: Any):
        yield value
        if isinstance(value, dict):
            for item in value.values():
                yield from self._walk_values(item)
        elif isinstance(value, list):
            for item in value:
                yield from self._walk_values(item)
