import asyncio
import logging
import threading
from typing import Any, Dict, List, Optional, Set

from .agent_task_orchestration import capture_flow
from .agent_task_orchestration import feedback_and_broadcast
from .agent_task_orchestration import frontend_state_queries
from .agent_task_orchestration import lifecycle_gate
from .agent_task_orchestration import resume_control
from .agent_task_orchestration import screenshot_capture

logger = logging.getLogger(__name__)

_WAKE_CAPTURE_SAFETY_TIMEOUT_SECONDS: float = lifecycle_gate.WAKE_CAPTURE_SAFETY_TIMEOUT_SECONDS


class VoiceListenerAgentTaskOrchestrationService:
    def __init__(self, agent_task_capture_service, agent_task_orchestrator, feedback_manager=None, main_service=None):
        """
        Initialize the agent-task orchestration service.

        Args:
            agent_task_capture_service: The agent-task capture service instance
            agent_task_orchestrator: The agent_task orchestrator instance
            feedback_manager: The feedback manager (to be implemented)
            main_service: Reference to main service for delegation
        """
        self.agent_task_capture_service = agent_task_capture_service
        self.agent_task_orchestrator = agent_task_orchestrator
        self.feedback_manager = feedback_manager
        self.main_service = main_service
        self._agent_task_canceled = False
        self._current_screenshot_data = None
        self._operation_state_responses = {}  # Track responses by request_id
        self._widget_state_responses = {}  # Track widget state responses by request_id
        self._operation_state_lock = threading.Lock()
        self._widget_state_lock = threading.Lock()

        # ------------------------------------------------------------------
        # Backend task lifecycle gate.
        #
        # Single source of truth for whether the backend may accept another
        # wake-word capture. The gate is "busy" while ANY of these are held:
        #
        #   wake_capture:<uuid>      Held by orchestration during a wake/hotkey
        #                            capture session. Audio_routes takes over
        #                            this key when /process-audio is called.
        #   transcription:<id>       Held by audio_routes while transcription
        #                            is in flight.
        #   task:<agent_task_id>     Held while a stored agent task is in a
        #                            non-terminal state (routing, processing,
        #                            awaiting_user_input). Released by the
        #                            agent-task event handlers on terminal
        #                            transitions (completed / failed).
        #
        # Wake detection is paused while the gate is busy. When the last key
        # is released, an "idle" coroutine is scheduled on the FastAPI loop to
        # re-enable wake detection. This replaces the previous fixed 10s
        # timeout that resumed the listener mid-task.
        # ------------------------------------------------------------------
        self._lifecycle_lock: threading.Lock = threading.Lock()
        self._active_lifecycle_keys: Set[str] = set()
        self._lifecycle_idle_event: asyncio.Event = asyncio.Event()
        self._lifecycle_idle_event.set()  # Idle initially.
        # The orchestration acquires this key when a wake/hotkey capture
        # begins. It is consumed by audio_routes when /process-audio is
        # invoked, so the gate stays held across the FFmpeg-track end /
        # Swift-upload start gap that previously let wake reopen too early.
        self._active_wake_capture_key: Optional[str] = None

        # Retained for diagnostic latency logging only. The wake-resume
        # decision no longer depends on this signal; resume is controlled by
        # the lifecycle gate above.
        self.processing_started_event: asyncio.Event = asyncio.Event()
        self._capture_handoff_ts: float = 0.0

    def set_agent_task_canceled(self, canceled: bool):
        """Set the agent-task cancellation flag and sync with capture service."""
        self._agent_task_canceled = canceled
        if self.agent_task_capture_service:
            self.agent_task_capture_service.set_agent_task_canceled(canceled)

    def signal_processing_started(self, agent_task_id: str, started_at: float) -> None:
        """
        Called by the agent task state machine when a task transitions to 'processing'.

        We only honor signals from tasks that started AFTER the most recent wake-word
        capture handoff timestamp. This avoids a stale processing-started for an
        earlier task accidentally satisfying the current capture's resume gate.

        Args:
            agent_task_id: The agent task that just entered 'processing' state
            started_at: A monotonic timestamp (time.monotonic()) for when processing began
        """
        try:
            if self.processing_started_event.is_set():
                return
            if self._capture_handoff_ts <= 0.0:
                return
            if started_at < self._capture_handoff_ts:
                logger.debug(
                    f"Ignoring processing_started signal for {agent_task_id}: "
                    f"started_at={started_at:.3f} < capture_handoff_ts={self._capture_handoff_ts:.3f}"
                )
                return
            logger.info(
                f"🟢 processing_started signal received for agent_task {agent_task_id} "
                f"(latency since capture handoff: {(started_at - self._capture_handoff_ts):.2f}s)"
            )
            self.processing_started_event.set()
        except Exception as exc:
            logger.warning(f"signal_processing_started failed for {agent_task_id}: {exc}")

    def _resolve_main_event_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """Return the FastAPI startup loop captured by WakeWordService, if any."""
        return frontend_state_queries.resolve_main_event_loop(self)

    def _schedule_frontend_query(self, query_message: Dict[str, Any], query_name: str) -> bool:
        """Schedule a frontend query from non-event-loop threads."""
        return frontend_state_queries.schedule_frontend_query(self, query_message, query_name)

    def acquire_lifecycle(self, key: str, source: str) -> None:
        """Acquire a lifecycle slot. The backend gate is "busy" while any key is held."""
        lifecycle_gate.acquire_lifecycle(self, key, source)

    def release_lifecycle(self, key: str, reason: str) -> None:
        """Release a lifecycle slot. Triggers wake resume when the gate becomes idle."""
        lifecycle_gate.release_lifecycle(self, key, reason)

    def transfer_lifecycle(self, old_key: str, new_key: str, reason: str) -> None:
        """Atomically swap one lifecycle key for another (e.g., capture -> task)."""
        lifecycle_gate.transfer_lifecycle(self, old_key, new_key, reason)

    def is_lifecycle_busy(self) -> bool:
        return lifecycle_gate.is_lifecycle_busy(self)

    def lifecycle_snapshot(self) -> List[str]:
        return lifecycle_gate.lifecycle_snapshot(self)

    def consume_active_wake_capture_key(self) -> Optional[str]:
        """Atomically retrieve and clear the active wake-capture key."""
        return lifecycle_gate.consume_active_wake_capture_key(self)

    def _sync_idle_event(self, target_idle: bool) -> None:
        """Set or clear the asyncio idle event from any thread."""
        lifecycle_gate.sync_idle_event(self, target_idle)

    def _schedule_idle_resume(self, reason: str) -> None:
        """Schedule wake-detection resume on the main loop after lifecycle becomes idle."""
        lifecycle_gate.schedule_idle_resume(self, reason)

    def _schedule_wake_capture_safety_release(
        self, capture_key: str, timeout: float = _WAKE_CAPTURE_SAFETY_TIMEOUT_SECONDS
    ) -> None:
        """Fallback release of the wake-capture key if no downstream handler takes over."""
        lifecycle_gate.schedule_wake_capture_safety_release(self, capture_key, timeout)

    async def _capture_and_process_agent_task(self, wake_phrase: str):
        """Capture agent_task after wake word and process it through the agent-task pipeline."""
        await capture_flow.capture_and_process_agent_task(self, wake_phrase)

    def _release_local_capture_key_if_owned(
        self, capture_key: str, owned_locally: bool, reason: str
    ) -> None:
        """Release a wake-capture key only if this coroutine still owns it."""
        capture_flow.release_local_capture_key_if_owned(self, capture_key, owned_locally, reason)

    async def _notify_agent_task_started(self):
        """Notify connected WebSocket clients that agent_task capture has started."""
        await feedback_and_broadcast.notify_agent_task_started(self)

    async def _provide_feedback(self, message: str):
        """Provide feedback to the user about agent-task processing."""
        await feedback_and_broadcast.provide_feedback(self, message)

    async def _provide_feedback_from_result(self, result: Dict[str, Any]):
        """Provide feedback based on agent-task processing result."""
        await feedback_and_broadcast.provide_feedback_from_result(self, result)

    async def broadcast(self, message_data: Dict[str, Any]):
        """Broadcast a message to all connected WebSocket clients."""
        await feedback_and_broadcast.broadcast(self, message_data)

    async def _resume_wake_word_detection(self):
        """Resume wake word detection after agent-task processing."""
        await resume_control.resume_wake_word_detection(self)

    async def _resume_listening_if_enabled(self):
        """Resume voice listening if it's enabled by user settings."""
        await resume_control.resume_listening_if_enabled(self)

    def set_current_screenshot_data(self, screenshot_data: Dict[str, Any]):
        """Set the current screenshot data for agent-task processing."""
        screenshot_capture.set_current_screenshot_data(self, screenshot_data)

    def query_frontend_operation_state_sync(self, timeout_seconds: float = 0.2) -> bool:
        """
        Synchronously query frontend operation state with timeout.
        Returns True if agent_task can proceed, False if blocked.
        """
        return frontend_state_queries.query_frontend_operation_state_sync(self, timeout_seconds)

    def handle_operation_state_response(self, response_data: Dict[str, Any]):
        """Handle operation state response from frontend."""
        frontend_state_queries.handle_operation_state_response(self, response_data)

    def query_widget_state_sync(self, timeout_seconds: float = 0.2) -> Dict[str, Any]:
        """
        Synchronously query widget state with timeout.
        Returns dict with: can_accept_agent_task, is_processing, has_completed_result, root_task_id
        """
        return frontend_state_queries.query_widget_state_sync(self, timeout_seconds)

    def handle_widget_state_response(self, response_data: Dict[str, Any]):
        """Handle widget state response from frontend."""
        frontend_state_queries.handle_widget_state_response(self, response_data)

    def _capture_immediate_screenshot(self) -> Dict[str, Any]:
        """Immediately capture a screenshot using Swift WindowCaptureService."""
        return screenshot_capture.capture_immediate_screenshot(self)
