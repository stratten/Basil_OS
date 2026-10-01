"""
Generic AppleScript Automation Service
Provides dynamic AppleScript generation and execution for unlimited macOS automation
"""

import asyncio
import contextlib
import re
import subprocess
import tempfile
import os
import logging
import time
from typing import Dict, Any, Optional, List
from dataclasses import asdict, dataclass, field

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.security.protected_runtime_paths import (
    PROTECTED_RUNTIME_REFUSAL,
    log_protected_runtime_refusal,
    references_protected_runtime_path,
)
from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context
from api.services.agent_processing.tools.safety import ExecutionApprovalService
from .script_outcome_review import (
    build_outcome_review_error,
    detect_semantic_script_error,
    parse_script_outcome_review,
)


# Wall-clock watchdog tuning -- mirrors the email AppleScript service
# (see ``email_integration.applescript_automation_service``). Same root
# cause: ``asyncio.wait_for`` uses a monotonic clock that pauses during
# macOS Maintenance Sleep, so the configured 60 s timeout for
# generic AppleScript automations can also be silently bypassed when
# the laptop sleeps mid-call. The watchdog WARNs once on observed
# drift between wall-clock and monotonic clocks, and kills the wedged
# osascript subprocess once wall-clock elapsed crosses
# ``execution_timeout_s * _WALLCLOCK_BOUND_MULTIPLIER``.
#
# Constants are intentionally module-private rather than instance
# attributes -- they defend against an OS-level behavior, not a
# per-call tuning knob.
_WATCHDOG_POLL_INTERVAL_SECONDS = 1.0
_DRIFT_WARN_THRESHOLD_SECONDS = 5.0
_WALLCLOCK_BOUND_MULTIPLIER = 2


@dataclass
class _WallclockWatchdogState:
    """Shared state between ``execute_applescript`` and its watchdog.

    Populated by ``_wallclock_watchdog`` when it kills a wedged
    subprocess. The caller reads this after ``wait_for`` returns so it
    can synthesize a timeout-shaped error string rather than a generic
    "process killed" stderr.
    """
    terminated_by_watchdog: bool = False
    wall_elapsed_at_kill: float = 0.0
    drift_warned: bool = field(default=False)


async def _wallclock_watchdog(
    process: asyncio.subprocess.Process,
    *,
    timeout_seconds: float,
    start_monotonic: float,
    start_wall: float,
    description: str,
    state: _WallclockWatchdogState,
) -> None:
    """Companion to ``asyncio.wait_for``: kills the subprocess when
    wall-clock elapsed crosses ``timeout * bound_multiplier``.

    Exits when the subprocess exits, when it gets canceled, or
    after killing the subprocess. Mirrors the email service's
    watchdog -- see its docstring for the full rationale.
    """
    while True:
        try:
            await asyncio.sleep(_WATCHDOG_POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            return

        if process.returncode is not None:
            return

        wall_elapsed = time.time() - start_wall
        mono_elapsed = asyncio.get_event_loop().time() - start_monotonic
        drift = wall_elapsed - mono_elapsed

        if drift >= _DRIFT_WARN_THRESHOLD_SECONDS and not state.drift_warned:
            logging.getLogger(__name__).warning(
                "⚠️ %s: wall-clock drift of %.1fs detected "
                "(wall_elapsed=%.1fs, mono_elapsed=%.1fs); "
                "system likely entered sleep during osascript execution. "
                "Wall-clock watchdog will kill the subprocess if it crosses "
                "%dx the configured %.0fs timeout.",
                description,
                drift,
                wall_elapsed,
                mono_elapsed,
                _WALLCLOCK_BOUND_MULTIPLIER,
                timeout_seconds,
            )
            state.drift_warned = True

        if wall_elapsed >= timeout_seconds * _WALLCLOCK_BOUND_MULTIPLIER:
            logging.getLogger(__name__).error(
                "⛔ %s: wall-clock elapsed %.1fs exceeds %dx configured "
                "timeout (%.0fs); terminating wedged osascript subprocess "
                "pid=%s",
                description,
                wall_elapsed,
                _WALLCLOCK_BOUND_MULTIPLIER,
                timeout_seconds,
                process.pid,
            )
            state.terminated_by_watchdog = True
            state.wall_elapsed_at_kill = wall_elapsed
            try:
                process.kill()
            except ProcessLookupError:
                # Subprocess exited between the returncode check and
                # the kill -- benign race.
                pass
            except Exception as kill_err:
                logging.getLogger(__name__).error(
                    "   watchdog kill error for pid=%s: %s",
                    process.pid,
                    kill_err,
                )
            return


@dataclass
class AppleScriptResult:
    """Result of AppleScript execution."""
    success: bool
    output: str
    error: Optional[str] = None
    script_content: Optional[str] = None
    execution_duration: Optional[float] = None
    approval_denied: bool = False
    execution_success: Optional[bool] = None
    outcome_verification_status: str = "not_reported"
    needs_outcome_review: bool = False
    outcome_review: Optional[Dict[str, Any]] = None


class GenericAppleScriptService:
    """
    Generic AppleScript automation service for dynamic script generation and execution.
    
    This service enables the LLM to generate and execute AppleScript for any macOS automation
    task that hasn't been explicitly built into the system.
    """

    def __init__(self, knowledge_service: Optional[SQLiteKnowledgeService] = None, websocket_manager=None):
        self.logger = logging.getLogger(__name__)
        self.knowledge_service = knowledge_service
        self._websocket_manager = websocket_manager
        self._approval_service: Optional[ExecutionApprovalService] = None
        self.execution_timeout_s = 60.0
        # Set per-request by the coordinator so approval broadcasts can route to the right agent
        self._agent_task_id: Optional[str] = None

    def _resolve_agent_task_id(self, context: Optional[Dict[str, Any]]) -> Optional[str]:
        """Prefer the task-local agent context over the shared per-instance attribute."""
        for candidate in (
            get_current_agent_context().get("agent_task_id"),
            (context or {}).get("agent_task_id"),
            self._agent_task_id,
        ):
            if isinstance(candidate, str) and candidate.strip():
                return candidate
        return None

    def _semantic_applescript_error(self, output: str) -> Optional[str]:
        """Return an app-level error when osascript succeeds but the script reports failure."""
        return detect_semantic_script_error(output)

    def _format_applescript_process_error(self, stdout: bytes, stderr: bytes, returncode: Optional[int]) -> str:
        """Preserve both stderr and stdout so agents can recover from the real failure."""
        stdout_text = stdout.decode('utf-8', errors='replace').strip()
        stderr_text = stderr.decode('utf-8', errors='replace').strip()

        details = [f"osascript exited with code {returncode}"]
        if stderr_text:
            details.append(f"stderr: {stderr_text}")
        if stdout_text:
            details.append(f"stdout: {stdout_text}")

        return "\n".join(details)

    def _extract_embedded_shell_commands(self, script_content: str) -> List[str]:
        """Extract 'do shell script' invocations from AppleScript content for risk scanning."""
        pattern = r'do\s+shell\s+script\s+"([^"]*)"'
        return re.findall(pattern, script_content, re.IGNORECASE)

    def _detect_browser_foreground_control(self, script_content: str) -> bool:
        """Return true when AppleScript appears to foreground-control a browser."""
        lowered = script_content.lower()
        targets_browser = any(
            browser in lowered
            for browser in (
                'application "safari"',
                'application "google chrome"',
                'application "chrome"',
                'application "microsoft edge"',
                'application "edge"',
            )
        )
        uses_foreground_control = any(
            marker in lowered
            for marker in (
                "activate",
                "system events",
                "keystroke",
                "key code",
                "click at",
                "click ",
                "menu item",
                "menu bar",
            )
        )
        return targets_browser and uses_foreground_control

    async def _enforce_browser_foreground_control_policy(
        self,
        script_content: str,
        context: Optional[Dict[str, Any]],
    ) -> Optional[AppleScriptResult]:
        """Block or approve browser foreground takeover according to user preference."""
        if not self._detect_browser_foreground_control(script_content):
            return None

        from api.core.preferences.preferences_io import load_preferences

        policy = load_preferences().browser_automation.foreground_control_policy
        task_desc = (context or {}).get("task_description", "AppleScript browser automation")

        if policy == "background_only":
            return AppleScriptResult(
                success=False,
                output="",
                error=(
                    "Browser foreground control is disabled. Enable browser JavaScript automation "
                    "permissions or change Browser Automation Security to allow foreground takeover."
                ),
                script_content=script_content,
                approval_denied=True,
            )

        if policy == "allow_foreground_when_needed":
            return None

        if self._approval_service is None and self._websocket_manager is not None:
            self._approval_service = ExecutionApprovalService(websocket_manager=self._websocket_manager)

        if self._approval_service is None:
            return AppleScriptResult(
                success=False,
                output="",
                error=(
                    "Browser foreground control requires explicit approval, but no approval channel "
                    "is available. Enable browser JavaScript automation permissions or approve from "
                    "a live agent task UI."
                ),
                script_content=script_content,
                approval_denied=True,
            )

        approval_context: Dict[str, Any] = {
            "source": "applescript_service",
            "description": f"Allow foreground browser control for: {task_desc}",
            "script_content": script_content,
            "execution_type": "browser_foreground_control",
            "risk_level": "high",
            "reason": (
                "This script appears to activate a browser and use System Events, keyboard, "
                "mouse, or menu automation against the visible desktop."
            ),
        }
        agent_task_id = self._resolve_agent_task_id(context)
        if isinstance(agent_task_id, str) and agent_task_id.strip():
            approval_context["agent_task_id"] = agent_task_id

        approved, _remember, _pattern_type = await self._approval_service.request_approval(
            f"Browser foreground control: {task_desc}",
            context=approval_context,
        )
        if approved:
            return None

        return AppleScriptResult(
            success=False,
            output="",
            error="Browser foreground control was denied by user",
            script_content=script_content,
            approval_denied=True,
        )

    async def execute_applescript(
        self,
        script_content: str,
        context: Optional[Dict[str, Any]] = None,
        save_successful_scripts: bool = True,
        skip_approval_check: bool = False
    ) -> AppleScriptResult:
        """
        Execute AppleScript content and return results.
        
        Args:
            script_content: The AppleScript code to execute
            context: Optional context information for logging/debugging
            save_successful_scripts: Whether to save successful scripts for future reuse
            skip_approval_check: Skip command approval check (for internal/trusted calls)
            
        Returns:
            AppleScriptResult with execution details
        """
        start_time = time.time()
        # Companion monotonic anchor for the wall-clock watchdog. The
        # existing ``execution_duration`` calculations key off wall
        # time (``time.time()``); the watchdog needs both clocks so it
        # can compare drift and detect post-sleep wakeups. See module
        # constants for rationale.
        start_monotonic = asyncio.get_event_loop().time()
        
        try:
            self.logger.info(f"🍎 Executing AppleScript automation")
            if references_protected_runtime_path(script_content):
                log_protected_runtime_refusal("AppleScript")
                return AppleScriptResult(
                    success=False,
                    output="",
                    error=PROTECTED_RUNTIME_REFUSAL,
                    script_content=script_content,
                    execution_duration=time.time() - start_time,
                    approval_denied=True,
                )
            if context:
                self.logger.info(f"📋 Context: {context}")

            foreground_policy_result = await self._enforce_browser_foreground_control_policy(
                script_content,
                context,
            )
            if foreground_policy_result is not None:
                foreground_policy_result.execution_duration = time.time() - start_time
                return foreground_policy_result

            # --- Command approval check ---
            if not skip_approval_check:
                if self._approval_service is None and self._websocket_manager is not None:
                    self._approval_service = ExecutionApprovalService(websocket_manager=self._websocket_manager)

                if self._approval_service:
                    try:
                        # Scan for embedded 'do shell script' commands and block dangerous ones
                        embedded_commands = self._extract_embedded_shell_commands(script_content)
                        if embedded_commands:
                            from api.services.agent_processing.tools.safety.risk_assessment import RiskAssessor
                            from api.core.preferences.preferences_io import load_preferences
                            risk_assessor = RiskAssessor()
                            prefs = load_preferences()
                            for embedded_cmd in embedded_commands:
                                blocked, block_reason = risk_assessor.check_dangerous_patterns(
                                    embedded_cmd, prefs.tool_execution
                                )
                                if blocked:
                                    self.logger.warning(f"🚫 AppleScript blocked: embedded shell command '{embedded_cmd}' is dangerous: {block_reason}")
                                    return AppleScriptResult(
                                        success=False,
                                        output="",
                                        error=f"Script blocked: embedded shell command is dangerous — {block_reason}",
                                        script_content=script_content,
                                        execution_duration=time.time() - start_time,
                                        approval_denied=True,
                                    )

                        # Build a short summary for the approval prompt; full script goes as script_content
                        task_desc = (context or {}).get("task_description", "AppleScript automation")
                        approval_summary = f"AppleScript: {task_desc}"

                        approval_context: Dict[str, Any] = {
                            "source": "applescript_service",
                            "description": f"Execute AppleScript: {task_desc}",
                            "script_content": script_content,
                            "execution_type": "applescript",
                        }
                        agent_task_id = self._resolve_agent_task_id(context)
                        if isinstance(agent_task_id, str) and agent_task_id.strip():
                            approval_context["agent_task_id"] = agent_task_id

                        approved, remember, pattern_type = await self._approval_service.request_approval(
                            approval_summary,
                            context=approval_context,
                        )

                        if not approved:
                            self.logger.warning(f"AppleScript approval denied")
                            return AppleScriptResult(
                                success=False,
                                output="",
                                error="Script execution was denied by user",
                                script_content=script_content,
                                execution_duration=time.time() - start_time,
                                approval_denied=True,
                            )

                        if remember:
                            try:
                                await self._approval_service.add_to_whitelist(
                                    approval_summary,
                                    pattern_type=pattern_type,
                                    description="User-approved AppleScript",
                                    record_initial_use=True,
                                )
                            except Exception as e:
                                self.logger.warning(f"Failed to add AppleScript to whitelist: {e}")

                        self.logger.info(f"✅ AppleScript approved for execution")

                    except Exception as e:
                        self.logger.error(f"Error during AppleScript approval check: {e}", exc_info=True)
                        return AppleScriptResult(
                            success=False,
                            output="",
                            error=f"AppleScript approval check failed: {str(e)}",
                            script_content=script_content,
                            execution_duration=time.time() - start_time,
                        )

            # Create temporary file for script
            with tempfile.NamedTemporaryFile(mode='w', suffix='.scpt', delete=False) as temp_file:
                temp_file.write(script_content)
                temp_file_path = temp_file.name

            try:
                # Execute AppleScript using osascript
                # Extended timeout to allow for permission dialogs
                process = await asyncio.create_subprocess_exec(
                    'osascript', temp_file_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                # Launch the wall-clock watchdog alongside the
                # monotonic ``wait_for`` timer. The two fire on
                # overshoot but measure different clocks -- this is
                # what catches the macOS sleep case where the
                # monotonic timer never advances. See module-level
                # _wallclock_watchdog for details.
                watchdog_state = _WallclockWatchdogState()
                watchdog_task = asyncio.create_task(
                    _wallclock_watchdog(
                        process,
                        timeout_seconds=self.execution_timeout_s,
                        start_monotonic=start_monotonic,
                        start_wall=start_time,
                        description=f"GenericAppleScript ({(context or {}).get('task_description', 'unknown')})",
                        state=watchdog_state,
                    )
                )

                # Allow time for permission dialogs and user interaction, but always bound execution.
                try:
                    try:
                        stdout, stderr = await asyncio.wait_for(
                            process.communicate(),
                            timeout=self.execution_timeout_s
                        )
                    finally:
                        # Always cancel the watchdog -- whether wait_for
                        # succeeded, raised, or the watchdog already
                        # exited on its own (kill path or natural
                        # subprocess exit). Suppressing CancelledError
                        # keeps the cancellation off the caller's
                        # traceback.
                        watchdog_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await watchdog_task
                except asyncio.TimeoutError:
                    self.logger.error(f"⏰ AppleScript timed out after {self.execution_timeout_s:.0f}s; cleaning up osascript PID {process.pid}")
                    try:
                        process.terminate()
                        await asyncio.wait_for(process.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        self.logger.error(f"⏰ osascript PID {process.pid} did not terminate; killing")
                        process.kill()
                        await process.wait()
                    return AppleScriptResult(
                        success=False,
                        output="",
                        error=f"AppleScript execution timed out after {self.execution_timeout_s:.0f}s (possibly waiting for permissions, a modal dialog, or a hung application AppleEvent)",
                        script_content=script_content,
                        execution_duration=time.time() - start_time
                    )
                except asyncio.CancelledError:
                    self.logger.info(f"🛑 AppleScript canceled; cleaning up osascript PID {process.pid}")
                    try:
                        process.terminate()
                        await asyncio.wait_for(process.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        self.logger.warning(f"🛑 osascript PID {process.pid} did not terminate after cancel; killing")
                        process.kill()
                        await process.wait()
                    except ProcessLookupError:
                        pass
                    raise

                if watchdog_state.terminated_by_watchdog:
                    # Wall-clock watchdog killed the subprocess because
                    # we crossed bound × multiplier in real time
                    # (almost always: OS sleep mid-call). Surface as a
                    # timeout-shaped failure with diagnostic context.
                    self.logger.error(
                        f"⏰ AppleScript terminated by wall-clock watchdog "
                        f"after {watchdog_state.wall_elapsed_at_kill:.1f}s wall "
                        f"(configured timeout={self.execution_timeout_s:.0f}s); "
                        f"this almost always means the system slept mid-call."
                    )
                    return AppleScriptResult(
                        success=False,
                        output="",
                        error=(
                            f"AppleScript execution timed out after "
                            f"{self.execution_timeout_s:.0f}s "
                            f"(wall-clock watchdog terminated subprocess at "
                            f"{watchdog_state.wall_elapsed_at_kill:.0f}s wall; "
                            f"system likely entered sleep during the call)"
                        ),
                        script_content=script_content,
                        execution_duration=time.time() - start_time,
                    )

                execution_duration = time.time() - start_time
                
                if process.returncode == 0:
                    output = stdout.decode('utf-8').strip()
                    semantic_error = self._semantic_applescript_error(output)
                    if semantic_error:
                        self.logger.error(f"❌ AppleScript reported semantic failure: {semantic_error}")
                        return AppleScriptResult(
                            success=False,
                            output=output,
                            error=f"AppleScript operation failed: {semantic_error}",
                            script_content=script_content,
                            execution_duration=execution_duration,
                            execution_success=True,
                        )

                    outcome_review = parse_script_outcome_review(output)
                    outcome_review_error = build_outcome_review_error(outcome_review)
                    if outcome_review_error:
                        self.logger.error(f"❌ AppleScript outcome verification failed: {outcome_review_error}")
                        return AppleScriptResult(
                            success=False,
                            output=output,
                            error=outcome_review_error,
                            script_content=script_content,
                            execution_duration=execution_duration,
                            execution_success=True,
                            outcome_verification_status=outcome_review.verification_status,
                            needs_outcome_review=False,
                            outcome_review=asdict(outcome_review),
                        )

                    needs_outcome_review = (
                        outcome_review.material_write
                        and outcome_review.verification_status == "unverified"
                    )
                    self.logger.info(f"✅ AppleScript executed successfully in {execution_duration:.2f}s")
                    self.logger.info(f"📤 Output: {output}")
                    
                    # Save successful script if requested
                    if save_successful_scripts and self.knowledge_service:
                        await self._save_successful_script(script_content, context, output)
                    
                    return AppleScriptResult(
                        success=True,
                        output=output,
                        script_content=script_content,
                        execution_duration=execution_duration,
                        execution_success=True,
                        outcome_verification_status=outcome_review.verification_status,
                        needs_outcome_review=needs_outcome_review,
                        outcome_review=asdict(outcome_review) if outcome_review.verification_status != "not_reported" else None,
                    )
                else:
                    error_msg = self._format_applescript_process_error(stdout, stderr, process.returncode)
                    self.logger.error(f"❌ AppleScript execution failed: {error_msg}")
                    
                    # Check for common permission-related errors
                    if "Access not allowed" in error_msg or "-10003" in error_msg:
                        permission_guidance = (
                            f"Permission denied. To fix this:\n"
                            f"1. Go to System Preferences → Security & Privacy → Privacy → Accessibility\n"
                            f"2. Add the current application to the allowed list\n"
                            f"3. Enable the checkbox\n"
                            f"Original error: {error_msg}"
                        )
                        error_msg = permission_guidance
                    
                    return AppleScriptResult(
                        success=False,
                        output="",
                        error=error_msg,
                        script_content=script_content,
                        execution_duration=execution_duration
                    )
                    
            finally:
                # Clean up temporary file
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(temp_file_path)
                
        except Exception as e:
            execution_duration = time.time() - start_time
            error_msg = f"Failed to execute AppleScript: {str(e)}"
            self.logger.error(f"💥 {error_msg}")
            
            return AppleScriptResult(
                success=False,
                output="",
                error=error_msg,
                script_content=script_content,
                execution_duration=execution_duration
            )

    async def generate_and_execute_applescript(
        self,
        task_description: str,
        target_application: Optional[str] = None,
        context_data: Optional[Dict[str, Any]] = None
    ) -> AppleScriptResult:
        """
        Generate and execute AppleScript dynamically for ANY task.
        
        Uses an LLM to generate proper AppleScript on-the-fly, enabling automation
        of any macOS application without pre-defined tooling. This is the key to
        true extensibility - the agent can accomplish tasks we never anticipated.
        
        Args:
            task_description: Natural language description of what to automate
                             (e.g., "Send a message via Messages app", "Get my calendar events")
            target_application: Optional specific macOS application to target
            context_data: Additional context for script generation (dates, names, etc.)
            
        Returns:
            AppleScriptResult with execution details and output
        """
        self.logger.info(f"🎯 Generating AppleScript for task: {task_description}")
        if target_application:
            self.logger.info(f"🎯 Target application: {target_application}")
            
        # Generate appropriate AppleScript based on the task description
        # Uses LLM for dynamic generation, enabling ANY macOS automation
        script_template = await self._generate_script_for_task(task_description, target_application, context_data) 

        return await self.execute_applescript(
            script_content=script_template,
            context={
                "task_description": task_description,
                "target_application": target_application,
                "context_data": context_data,
                "generation_method": "template"
            }
        )

    async def _generate_script_for_task(
        self,
        task_description: str,
        target_application: Optional[str] = None,
        context_data: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate AppleScript dynamically using an LLM based on task description.
        
        This enables the agent to perform ANY macOS automation without pre-defined tools.
        All tasks are handled by the LLM to avoid keyword-based misrouting.
        """
        return await self._llm_generate_applescript(task_description, target_application, context_data)

    async def _llm_generate_applescript(
        self,
        task_description: str,
        target_application: Optional[str] = None,
        context_data: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Use an LLM to generate proper AppleScript for any task.
        
        This is the key to making the generic service truly generic - the agent can
        accomplish ANY macOS automation without pre-defined tooling.
        """
        from api.services.model_usage_service import ModelUsageService
        from api.dependencies import get_model_service
        from api.core.models.model_types import ModelCapability
        
        # Build a detailed prompt for AppleScript generation
        context_info = ""
        if context_data:
            context_info = f"\n\nAdditional context:\n{context_data}"
        
        app_info = f" for {target_application}" if target_application else ""
        
        prompt = f"""Generate a complete, executable AppleScript{app_info} to accomplish this task:

Task: {task_description}{context_info}

Requirements:
1. Return ONLY the AppleScript code, no explanations or markdown
2. Include proper error handling with try/catch blocks
3. Return a clear success or error message at the end, plus exactly one RESULT_JSON line
4. Use modern AppleScript syntax compatible with macOS 10.15+
5. If querying data, format results clearly (e.g., line-separated for emails)
6. If the target application needs to be activated, include an 'activate' statement
7. Be specific and complete - this will be executed as-is
8. This script has a hard 60-second execution timeout — it will be killed if it hasn't completed. Never use blocking 'delay' for long durations
9. When a native macOS app handles the task (Clock for timers, Reminders for reminders, Calendar for events, Notes for notes), use 'tell application' to delegate rather than reimplementing the functionality in raw AppleScript
10. Prefer 'do shell script' with backgrounded processes (nohup/&) for deferred actions over blocking AppleScript waits
11. For read-only scripts, include a line beginning RESULT_JSON: with JSON containing material_write=false, verification_status="not_applicable", summary, evidence, expected, actual, and discrepancies
12. For scripts that create or modify app state, perform a non-destructive readback or state check after writing when the application supports it
13. For write scripts, the RESULT_JSON line must include material_write=true, verification_status="verified" | "unverified" | "failed", summary, evidence, expected, actual, and discrepancies
14. If the app accepts the write but readback is impossible or unreliable, use verification_status="unverified" and explain that limitation in summary; do not print SUCCESS as if the user-visible outcome was verified
15. If readback shows missing or wrong fields, use verification_status="failed" and list discrepancies

Generate the AppleScript now:"""

        try:
            # Get a reasoning-capable model for code generation
            model_service = get_model_service()
            model_usage_service = ModelUsageService(model_service)
            
            llm = await model_usage_service.get_model_for_task(
                capabilities={ModelCapability.REASONING}
            )
            
            if not llm:
                raise Exception("No suitable model found for AppleScript generation")
            
            response = await llm.generate_response(
                prompt,
                max_tokens=2000
            )
            
            generated_script = response.strip()
            
            # Remove markdown code fences if present
            fence_match = re.search(r'```\w*\n(.*?)```', generated_script, re.DOTALL)
            if fence_match:
                generated_script = fence_match.group(1).strip()
            
            self.logger.info(f"🤖 LLM generated AppleScript ({len(generated_script)} chars)")
            return generated_script
            
        except Exception as e:
            self.logger.error(f"❌ Failed to generate AppleScript with LLM: {e}")
            # Fallback: Return a minimal script that at least returns an error
            return f'''
-- Failed to generate AppleScript for: {task_description}
-- Error: {str(e)}

return "ERROR: Could not generate AppleScript for this task: {task_description}"
'''

    async def _save_successful_script(
        self,
        script_content: str,
        context: Optional[Dict[str, Any]],
        output: str
    ) -> None:
        """Save successful scripts to knowledge base for future reuse."""
        if not self.knowledge_service:
            return
            
        try:
            # This would save to a scripts knowledge base table
            # Implementation depends on your knowledge service structure
            self.logger.info("💾 Saving successful AppleScript for future reuse")
            
        except Exception as e:
            self.logger.warning(f"⚠️  Failed to save script: {e}")

    def get_service_capabilities(self) -> Dict[str, Any]:
        """Return service capabilities for tool integration."""
        return {
            "service_name": "GenericAppleScriptService",
            "description": "Dynamic AppleScript generation and execution for unlimited macOS automation",
            "category": "automation",
            "execution_principles": [
                "Prefer 'tell application' delegation to native macOS apps (Clock, Reminders, Calendar, Notes, Messages) over scripting functionality from scratch",
                "Generated scripts must complete within 60 seconds — never use blocking 'delay' for long durations",
                "For deferred actions, use 'do shell script' with backgrounded processes rather than blocking waits.",
            ],
            # Why these slim docs:
            # - applescript_service has only two methods: execute (you wrote
            #   the script) vs. generate_and_execute (Basil writes the script
            #   from a task description). The slim_doc surfaces that
            #   discrimination directly so the agent does not pass a task
            #   description into execute_applescript or, conversely, hand a
            #   prewritten script into generate_and_execute_applescript.
            # - KEEPS the load-bearing 60-second timeout invariant on
            #   execute (the most common script-design footgun) and the
            #   'tell application' delegation hint on generate (so
            #   generated scripts use the right pattern).
            # - DROPS the AppleScriptResult shape (the agent learns the
            #   envelope from a single result) and per-arg descriptions
            #   (the schema's Pydantic field descriptions cover them).
            "supported_methods": {
                "execute_applescript": {
                    "description": "Execute provided AppleScript content",
                    "slim_doc": (
                        "Run an AppleScript that YOU have already written. "
                        "Scripts must complete within 60 seconds; never use "
                        "blocking 'delay' for long waits - use 'do shell "
                        "script' with backgrounded processes for deferred "
                        "actions. Scripts that create or modify user-visible "
                        "state must return one RESULT_JSON line describing "
                        "material_write, verification_status, evidence, "
                        "expected, actual, and discrepancies. If you need Basil to write the script "
                        "from a natural-language task description, call "
                        "generate_and_execute_applescript instead."
                    ),
                    "parameters": {
                        "script_content": {"type": "str", "required": True, "description": "AppleScript code to execute"},
                        "context": {"type": "dict", "required": False, "description": "Optional context information"},
                        "save_successful_scripts": {"type": "bool", "required": False, "description": "Whether to save successful scripts"}
                    },
                    "returns": "AppleScriptResult with success status, output, and execution details"
                },
                "generate_and_execute_applescript": {
                    "description": "Generate and execute AppleScript for a specific automation task",
                    "slim_doc": (
                        "Generate an AppleScript from a natural-language "
                        "task description and execute it. Prefer 'tell "
                        "application' delegation to native macOS apps "
                        "(Reminders, Calendar, Notes, Messages, Clock) over "
                        "scripting functionality from scratch. If you "
                        "already have a script written, call "
                        "execute_applescript instead so Basil does not "
                        "regenerate it. Generated scripts must return one "
                        "RESULT_JSON line; user-visible writes must verify "
                        "their material outcome or mark it unverified/failed."
                    ),
                    "parameters": {
                        "task_description": {"type": "str", "required": True, "description": "Human-readable task description"},
                        "target_application": {"type": "str", "required": False, "description": "Specific macOS application to target"},
                        "context_data": {"type": "dict", "required": False, "description": "Additional context for script generation"}
                    },
                    "returns": "AppleScriptResult with generated script and execution details"
                }
            },
            "automation_capabilities": [
                "File system operations (create, move, delete files/folders)",
                "Application launching and control",
                "Menu item selection and clicking",
                "Text input and form filling",
                "Window management (resize, move, minimize)",
                "System preferences automation",
                "Custom application scripting",
                "Multi-application workflows",
                "Screen capture and image operations",
                "Network and sharing controls"
            ]
        }
