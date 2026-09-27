"""
AppleScript Automation Service - Email Client Automation Implementation

This service implements the actual AppleScript automation for email operations
across Mail.app and Microsoft Outlook, leveraging the non-sandboxed capabilities
of Basil for comprehensive email automation.

Key Features:
- Multi-client AppleScript generation (Mail.app, Outlook)
- Comprehensive email operations (read, compose, send, organize)
- Advanced search and filtering capabilities
- Folder management and bulk operations
- Error handling and timeout management
"""

import asyncio
import contextlib
import logging
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from .email_models import EmailData, EmailRequest, EmailOperation, EmailSearchCriteria

logger = logging.getLogger(__name__)


# Wall-clock watchdog tuning.
#
# Background: the May 22 2026 8 PM scheduled task ran for 957 s because
# macOS Maintenance Sleep suspended an in-flight osascript subprocess.
# ``asyncio.wait_for(..., timeout=self.timeout)`` schedules its
# cancellation via ``loop.call_later``, which is keyed to a monotonic
# clock; monotonic clocks pause through OS sleep, so the configured
# 90 s timeout never fired even though wall-clock elapsed was ~16 min.
#
# Mitigation: alongside the existing monotonic timeout, we run a
# companion watchdog task that compares wall-clock elapsed
# (``time.time()``) against monotonic elapsed
# (``asyncio.get_event_loop().time()``). Two outcomes:
#
#   1. **Drift WARN**: as soon as we observe wall-clock >> monotonic by
#      more than ``_DRIFT_WARN_THRESHOLD_SECONDS`` we log a single WARN
#      with both clocks. This makes "we were asleep for X seconds"
#      legible in the logs without operators having to cross-reference
#      ``pmset -g log`` after the fact.
#
#   2. **Hard kill at bound × multiplier**: if wall-clock elapsed
#      crosses ``self.timeout * _WALLCLOCK_BOUND_MULTIPLIER``, the
#      watchdog kills the wedged osascript subprocess. The 2x cushion
#      gives a genuinely slow (but progressing) AppleScript a chance
#      to finish post-wake before we yank it -- we only kill calls
#      that have visibly overshot any reasonable wall-clock budget.
#
# These numbers are intentionally not configurable on the instance --
# they are about defending against an OS-level behavior, not about
# tuning per-call performance.
_WATCHDOG_POLL_INTERVAL_SECONDS = 1.0
_DRIFT_WARN_THRESHOLD_SECONDS = 5.0
_WALLCLOCK_BOUND_MULTIPLIER = 2


@dataclass
class _WallclockWatchdogState:
    """Shared state between ``execute_applescript`` and its watchdog.

    Populated by ``_wallclock_watchdog`` when it terminates a wedged
    subprocess. ``execute_applescript`` reads this after
    ``wait_for(process.communicate(), ...)`` returns so it can
    synthesize a timeout-shaped ``AppleScriptResult`` rather than a
    generic "process killed" stderr.
    """
    terminated_by_watchdog: bool = False
    wall_elapsed_at_kill: float = 0.0
    drift_warned: bool = field(default=False)


async def _wallclock_watchdog(
    process: asyncio.subprocess.Process,
    *,
    timeout_seconds: int,
    start_monotonic: float,
    start_wall: float,
    description: str,
    state: _WallclockWatchdogState,
) -> None:
    """Compare wall-clock vs monotonic elapsed; WARN on drift, kill on
    excessive wall-clock elapsed.

    Exits cleanly when the subprocess exits, when it gets cancelled, or
    after it kills the subprocess for crossing the wall-clock bound.

    Implementation notes:
      * Polls on a fixed 1 s interval -- shorter intervals add CPU
        wakeups for no benefit; longer intervals delay detection after
        wake. The watchdog itself is suspended during OS sleep along
        with everything else on the event loop, so wake-detection
        latency is bounded by this interval plus one event-loop tick.
      * The drift WARN fires at most once per call (latched on
        ``state.drift_warned``) so a long-running call that sees
        cumulative drift doesn't log every iteration.
      * On the kill path the watchdog flips
        ``state.terminated_by_watchdog`` BEFORE issuing ``kill()`` so
        the caller can observe the flag even if ``kill()`` itself
        raises.
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
            logger.warning(
                "⚠️ %s: wall-clock drift of %.1fs detected "
                "(wall_elapsed=%.1fs, mono_elapsed=%.1fs); "
                "system likely entered sleep during osascript execution. "
                "Wall-clock watchdog will kill the subprocess if it crosses "
                "%dx the configured %ds timeout.",
                description,
                drift,
                wall_elapsed,
                mono_elapsed,
                _WALLCLOCK_BOUND_MULTIPLIER,
                timeout_seconds,
            )
            state.drift_warned = True

        if wall_elapsed >= timeout_seconds * _WALLCLOCK_BOUND_MULTIPLIER:
            logger.error(
                "⛔ %s: wall-clock elapsed %.1fs exceeds %dx configured "
                "timeout (%ds); terminating wedged osascript subprocess "
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
                # The subprocess exited between our returncode check
                # above and the kill -- benign race, just exit.
                pass
            except Exception as kill_err:
                logger.error(
                    "   watchdog kill error for pid=%s: %s",
                    process.pid,
                    kill_err,
                )
            return


@dataclass
class AppleScriptResult:
    """Represents the result of an AppleScript execution."""
    success: bool
    data: Any
    error: Optional[str] = None
    execution_time: float = 0.0


class AppleScriptAutomationService:
    """
    AppleScript automation service for email client operations.
    
    Provides comprehensive AppleScript implementations for Mail.app and Outlook
    automation, supporting all email operations defined in the email client service.
    """
    
    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self.supported_clients = {
            "Mail": "com.apple.mail",
            "Mail.app": "com.apple.mail",
            "Microsoft Outlook": "com.microsoft.Outlook"
        }
        
        # Initialize client-specific services
        from .outlook import OutlookAppleScriptService
        from .mail_app import MailAppService
        self.outlook_service = OutlookAppleScriptService()
        self.mail_app_service = MailAppService()
        
        # AppleScript templates for different operations
        self.script_templates = {
            "mail_app": {
                "get_emails": self.mail_app_service.get_emails_script,
                "get_email_metadata": self.mail_app_service.get_email_metadata_script,
                "expand_email_details": self.mail_app_service.expand_email_details_script,
                "compose_email": self.mail_app_service.compose_email_script,
                "send_email": self.mail_app_service.send_email_script,
                "reply_to_email": self.mail_app_service.reply_to_email_script,
                "organize_emails": self.mail_app_service.organize_emails_script,
                "get_folders": self.mail_app_service.get_folders_script,
                "create_folder": self.mail_app_service.create_folder_script
            },
            "outlook": {
                "get_emails": lambda folder, limit, search_criteria=None: self._delegate_to_outlook_service("get_emails", folder, limit, search_criteria),
                "get_email_metadata": lambda folder, limit, search_criteria=None: self._delegate_to_outlook_service("get_email_metadata", folder, limit, search_criteria),
                "expand_email_details": lambda folder, email_ids, excerpt_chars=4000: self._delegate_to_outlook_service("expand_email_details", folder, email_ids, excerpt_chars),
                "compose_email": lambda email_request, **kwargs: self._delegate_to_outlook_service("compose_email", email_request, **kwargs),
                "send_email": lambda email_request, **kwargs: self._delegate_to_outlook_service("send_email", email_request, **kwargs),
                "reply_to_email": lambda email_request, **kwargs: self._delegate_to_outlook_service("reply_to_email", email_request, **kwargs),
                "organize_emails": lambda operation, **kwargs: self._delegate_to_outlook_service("organize_emails", operation, **kwargs),
                "get_folders": lambda: self._delegate_to_outlook_service("get_folders", None),
                "create_folder": lambda folder_name, parent_folder=None: self._delegate_to_outlook_service(
                    "create_folder", folder_name, parent_folder
                ),
            }
        }
    
    async def execute_applescript(self, script: str, description: str = "AppleScript") -> AppleScriptResult:
        """
        Execute AppleScript with comprehensive error handling and timeout management.
        
        Args:
            script: The AppleScript code to execute
            description: Description of the operation for logging
            
        Returns:
            AppleScriptResult with success status and data/error info
        """
        logger.info(f"🍎 Executing {description}...")
        logger.info(f"🔍 SCRIPT DEBUG - Length: {len(script)} characters")
        logger.info(f"🔍 SCRIPT DEBUG - First 500 chars: {script[:500]}")
        logger.info(f"🔍 SCRIPT DEBUG - Timeout set to: {self.timeout} seconds")

        # Reject placeholder error scripts before they reach osascript. Upstream
        # script generators emit "SCRIPT_ERROR: ..." strings when an action is
        # unsupported; passing those to osascript produces a confusing
        # "syntax error" instead of the real routing failure.
        if script.lstrip().startswith("SCRIPT_ERROR:"):
            placeholder = script.strip()
            logger.error(
                f"❌ Refusing to execute placeholder error script for "
                f"{description}: {placeholder}"
            )
            return AppleScriptResult(
                success=False,
                data=None,
                error=placeholder,
            )

        start_time = asyncio.get_event_loop().time()
        # Companion wall-clock anchor. ``asyncio.wait_for`` and the
        # ``execution_time`` calc above both use the event loop's
        # monotonic clock (``loop.time()``), which pauses through OS
        # sleep. The wall-clock anchor lets the watchdog below detect
        # post-sleep wakeups and kill any osascript that has visibly
        # overshot the configured timeout by 2x in real time. See
        # module-level constants for rationale.
        start_wall = time.time()

        try:
            logger.info(f"🔧 Creating subprocess for osascript...")

            # Create subprocess to execute AppleScript
            process = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            logger.info(f"🔧 Subprocess created, PID: {process.pid}")
            logger.info(f"🔧 Starting subprocess communication with {self.timeout}s timeout...")

            # Launch the wall-clock watchdog alongside the monotonic
            # ``wait_for`` timer. Both fire on overshoot, but they
            # measure different things -- ``wait_for`` only knows about
            # event-loop time, the watchdog only knows about wall time.
            # The pair gives us coverage across the OS-sleep case.
            watchdog_state = _WallclockWatchdogState()
            watchdog_task = asyncio.create_task(
                _wallclock_watchdog(
                    process,
                    timeout_seconds=self.timeout,
                    start_monotonic=start_time,
                    start_wall=start_wall,
                    description=description,
                    state=watchdog_state,
                )
            )

            try:
                # Wait for completion with timeout
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
            finally:
                # Cancel the watchdog whether wait_for succeeded,
                # raised, or the watchdog already exited on its own.
                # Suppressing CancelledError keeps the cancellation
                # noise out of the caller's traceback.
                watchdog_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watchdog_task

            execution_time = asyncio.get_event_loop().time() - start_time
            wall_execution_time = time.time() - start_wall
            logger.info(
                f"🔧 Subprocess communication completed in "
                f"{execution_time:.2f}s (wall={wall_execution_time:.2f}s)"
            )
            logger.info(f"🔧 Process return code: {process.returncode}")

            if watchdog_state.terminated_by_watchdog:
                # The watchdog killed the subprocess because wall-clock
                # elapsed crossed the bound (almost always: OS sleep
                # mid-call). Surface this as a timeout-shaped failure
                # so callers and fixtures that key off "Timeout after"
                # keep working unchanged -- the additional context in
                # parentheses is purely informational.
                logger.error(
                    f"⏰ {description} terminated by wall-clock watchdog after "
                    f"{watchdog_state.wall_elapsed_at_kill:.1f}s wall "
                    f"(monotonic elapsed={execution_time:.2f}s, "
                    f"configured timeout={self.timeout}s)"
                )
                return AppleScriptResult(
                    success=False,
                    data=None,
                    error=(
                        f"Timeout after {self.timeout} seconds "
                        f"(wall-clock watchdog terminated subprocess at "
                        f"{watchdog_state.wall_elapsed_at_kill:.0f}s wall)"
                    ),
                    execution_time=execution_time,
                )

            if process.returncode == 0:
                result_data = stdout.decode('utf-8').strip()
                logger.info(f"✅ {description} completed successfully in {execution_time:.2f}s")
                logger.info(f"🔍 RESULT DEBUG - Length: {len(result_data)} characters")
                logger.info(f"🔍 RESULT DEBUG - First 500 chars: {result_data[:500]}")
                
                return AppleScriptResult(
                    success=True,
                    data=result_data,
                    execution_time=execution_time
                )
            else:
                error_msg = stderr.decode('utf-8').strip()
                logger.error(f"❌ {description} failed: {error_msg}")
                logger.error(f"🔍 ERROR DEBUG - Return code: {process.returncode}")
                logger.error(f"🔍 ERROR DEBUG - Stderr length: {len(error_msg)} characters")
                
                return AppleScriptResult(
                    success=False,
                    data=None,
                    error=error_msg,
                    execution_time=execution_time
                )
                
        except asyncio.TimeoutError:
            logger.error(f"⏰ {description} timed out after {self.timeout} seconds")
            logger.error(f"🔍 TIMEOUT DEBUG - Elapsed time: {asyncio.get_event_loop().time() - start_time:.2f}s")
            
            # Try to kill the process if it's still running
            try:
                if hasattr(process, 'pid') and process.returncode is None:
                    logger.error(f"🔍 TIMEOUT DEBUG - Attempting to terminate hanging process PID: {process.pid}")
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=5)
                        logger.error(f"🔍 TIMEOUT DEBUG - Process terminated gracefully")
                    except asyncio.TimeoutError:
                        logger.error(f"🔍 TIMEOUT DEBUG - Process didn't terminate, attempting kill")
                        process.kill()
            except Exception as kill_error:
                logger.error(f"🔍 TIMEOUT DEBUG - Error during process cleanup: {kill_error}")
            
            return AppleScriptResult(
                success=False,
                data=None,
                error=f"Timeout after {self.timeout} seconds"
            )
        except asyncio.CancelledError:
            logger.info(f"🛑 {description} cancelled; cleaning up osascript subprocess")
            try:
                if "process" in locals() and hasattr(process, "pid") and process.returncode is None:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2)
                    except asyncio.TimeoutError:
                        logger.warning(f"🛑 osascript PID {process.pid} did not terminate after cancel; killing")
                        process.kill()
                        await process.wait()
            except ProcessLookupError:
                pass
            except Exception as kill_error:
                logger.warning(f"🛑 Error during cancellation cleanup: {kill_error}")
            raise
        except Exception as e:
            execution_time = asyncio.get_event_loop().time() - start_time
            logger.error(f"❌ {description} error: {e}")
            logger.error(f"🔍 EXCEPTION DEBUG - Execution time: {execution_time:.2f}s")
            logger.error(f"🔍 EXCEPTION DEBUG - Exception type: {type(e).__name__}")
            import traceback
            logger.error(f"🔍 EXCEPTION DEBUG - Traceback: {traceback.format_exc()}")
            
            return AppleScriptResult(
                success=False,
                data=None,
                error=str(e),
                execution_time=execution_time
            )
    
    def _is_mail_app_client(self, client_name: str) -> bool:
        """Return true for the Mail.app names used by discovery and legacy callers."""
        return client_name in {"Mail", "Mail.app"}

    async def _execute_for_client(self, client_name: str, operation: str, description: str, *args, **kwargs) -> Any:
        """
        Generic method to execute an operation for a specific email client.
        Eliminates duplicate client routing logic across all public methods.
        
        Args:
            client_name: Name of the email client (Mail, Microsoft Outlook)
            operation: Operation name (key in script_templates)
            description: Human-readable description for logging
            *args, **kwargs: Arguments to pass to the script template function
            
        Returns:
            Result data (varies by operation)
            
        Raises:
            ValueError: If client is unsupported
            RuntimeError: If AppleScript execution fails
        """
        try:
            if self._is_mail_app_client(client_name):
                script = self.script_templates["mail_app"][operation](*args, **kwargs)
            elif client_name == "Microsoft Outlook":
                script = self.script_templates["outlook"][operation](*args, **kwargs)
            else:
                raise ValueError(f"Unsupported client: {client_name}")
            
            result = await self.execute_applescript(script, description)
            
            if not result.success:
                error_msg = f"AppleScript execution failed: {result.error}"
                logger.error(f"❌ {error_msg}")
                raise RuntimeError(error_msg)

            self._raise_for_semantic_applescript_error(result)
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Error executing {operation} for {client_name}: {e}", exc_info=True)
            raise

    def _raise_for_semantic_applescript_error(self, result: AppleScriptResult) -> None:
        """Raise when a successful osascript process returns an app-level failure."""
        if not isinstance(result.data, str):
            return

        output = result.data.strip()
        error_prefixes = ("ERROR:", "SCRIPT_ERROR:", "MAIN_ERROR:")
        if output.startswith(error_prefixes):
            raise RuntimeError(f"AppleScript operation failed: {output}")
    
    async def get_emails_via_applescript(self, client_name: str, folder: str = "inbox", 
                                       limit: int = 10, search_criteria: Optional[EmailSearchCriteria] = None) -> List[EmailData]:
        """
        Get emails from specified client and folder using AppleScript.
        
        Args:
            client_name: Name of the email client (Mail, Microsoft Outlook)
            folder: Folder to retrieve emails from
            limit: Maximum number of emails to retrieve
            search_criteria: Optional search criteria to filter emails
            
        Returns:
            List of EmailData objects
        """
        logger.info(f"📧 Getting emails from {client_name} - {folder} (limit: {limit})")
        
        try:
            # Ensure Outlook discovery if needed
            if client_name == "Microsoft Outlook":
                await self._ensure_outlook_discovery(folder)
            
            # Execute the operation
            result = await self._execute_for_client(
                client_name, "get_emails", f"get emails from {client_name}",
                folder, limit, search_criteria
            )
            
            # Log raw output
            logger.info(f"📧 RAW APPLESCRIPT OUTPUT ({len(result.data)} chars):")
            logger.info(f"📧 RAW OUTPUT START:")
            logger.info(result.data)
            logger.info(f"📧 RAW OUTPUT END")
            
            # Parse emails (client-specific parsing)
            if self._is_mail_app_client(client_name):
                parsed_emails = self.mail_app_service.parse_emails_from_applescript(result.data, client_name)
            elif client_name == "Microsoft Outlook":
                parsed_emails = self.outlook_service.parse_emails_from_applescript(result.data)
            else:
                parsed_emails = []
            
            logger.info(f"📧 PARSED {len(parsed_emails)} EMAILS FROM RAW OUTPUT")
            return parsed_emails
                
        except Exception as e:
            logger.error(f"❌ Error getting emails from {client_name}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to retrieve emails from {client_name}: {e}") from e

    async def get_email_metadata_via_applescript(
        self,
        client_name: str,
        folder: str = "inbox",
        limit: int = 50,
        search_criteria: Optional[EmailSearchCriteria] = None,
    ) -> List[EmailData]:
        """Retrieve metadata-only email records without expanding message bodies."""
        logger.info(f"📧 Getting email metadata from {client_name} - {folder} (limit: {limit})")

        try:
            if client_name == "Microsoft Outlook":
                await self._ensure_outlook_discovery(folder)

            result = await self._execute_for_client(
                client_name,
                "get_email_metadata",
                f"get email metadata from {client_name}",
                folder,
                limit,
                search_criteria,
            )

            if self._is_mail_app_client(client_name):
                return self.mail_app_service.parse_emails_from_applescript(result.data, client_name)
            if client_name == "Microsoft Outlook":
                return self.outlook_service.parse_emails_from_applescript(result.data)
            return []
        except Exception as e:
            logger.error(f"❌ Error getting email metadata from {client_name}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to retrieve email metadata from {client_name}: {e}") from e

    async def expand_email_details_via_applescript(
        self,
        client_name: str,
        email_ids: List[str],
        folder: str = "inbox",
        excerpt_chars: int = 4000,
    ) -> List[EmailData]:
        """Expand selected message ids to bounded body excerpts."""
        logger.info(f"📧 Expanding {len(email_ids)} email details from {client_name} - {folder}")

        try:
            if client_name == "Microsoft Outlook":
                await self._ensure_outlook_discovery(folder)

            result = await self._execute_for_client(
                client_name,
                "expand_email_details",
                f"expand email details from {client_name}",
                folder,
                email_ids,
                excerpt_chars,
            )

            if self._is_mail_app_client(client_name):
                return self.mail_app_service.parse_emails_from_applescript(result.data, client_name)
            if client_name == "Microsoft Outlook":
                return self.outlook_service.parse_emails_from_applescript(result.data)
            return []
        except Exception as e:
            logger.error(f"❌ Error expanding email details from {client_name}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to expand email details from {client_name}: {e}") from e
    
    async def process_email_via_applescript(self, client_name: str, email_request: EmailRequest) -> bool:
        """
        Process email request (draft, send, reply, forward) using AppleScript.
        
        Args:
            client_name: Name of the email client
            email_request: Email request details
            
        Returns:
            True if operation was successful
        """
        logger.info(f"✍️ Processing email {email_request.action} via {client_name}")
        
        try:
            # Determine operation and kwargs based on action
            if email_request.action == "draft":
                operation = "compose_email"
                kwargs = {"email_request": email_request, "draft_only": True}
            elif email_request.action == "send":
                logger.warning("SAFETY: Direct send requested via AppleScript service; creating a visible draft instead.")
                operation = "compose_email"
                kwargs = {"email_request": email_request, "draft_only": True}
            elif email_request.action == "reply":
                # Use native reply functionality (draft_only=True by default for safety)
                operation = "reply_to_email"
                kwargs = {"email_request": email_request, "reply_all": True, "draft_only": True}
            else:
                raise ValueError(f"Unsupported action: {email_request.action}")
            
            # Execute the operation
            await self._execute_for_client(
                client_name, operation, f"{email_request.action} email via {client_name}",
                **kwargs
            )
            
            logger.info(f"✅ Email {email_request.action} completed successfully")
            return True
                
        except Exception as e:
            logger.error(f"❌ Error processing email via {client_name}: {e}", exc_info=True)
            return False

    async def reply_to_email_via_applescript(
        self,
        client_name: str,
        email_id: str,
        reply_body: str,
        reply_all: bool = True,
        draft_only: bool = True
    ) -> bool:
        """
        Create a native reply draft using client-specific reply options.

        This keeps reply-only options out of the generic EmailRequest path so
        fields such as reply_all are not dropped before script generation.
        """
        logger.info(f"📧 Creating reply draft via {client_name}, reply_all={reply_all}, draft_only={draft_only}")

        try:
            if self._is_mail_app_client(client_name):
                await self._execute_for_client(
                    client_name, "reply_to_email", f"reply email via {client_name}",
                    email_id, reply_body, reply_all, draft_only
                )
            elif client_name == "Microsoft Outlook":
                email_request = EmailRequest(
                    recipient="",
                    subject="",
                    body=reply_body,
                    action="reply",
                    reference_email_id=email_id
                )
                await self._execute_for_client(
                    client_name, "reply_to_email", f"reply email via {client_name}",
                    email_request, reply_all=reply_all, draft_only=draft_only
                )
            else:
                raise ValueError(f"Unsupported client: {client_name}")

            logger.info("✅ Email reply completed successfully")
            return True
        except Exception as e:
            logger.error(f"❌ Error creating reply via {client_name}: {e}", exc_info=True)
            return False
    
    async def organize_emails_via_applescript(self, client_name: str, operation: EmailOperation) -> bool:
        """
        Organize emails using AppleScript (move, delete, flag, etc.).
        
        Args:
            client_name: Name of the email client
            operation: Organization operation details
            
        Returns:
            True if operation was successful
        """
        logger.info(f"📁 Organizing emails via {client_name} - {operation.operation}")
        
        try:
            await self._execute_for_client(
                client_name, "organize_emails", f"organize emails via {client_name}",
                operation
            )
            
            logger.info(f"✅ Email organization completed successfully")
            return True
                
        except Exception as e:
            logger.error(f"❌ Error organizing emails via {client_name}: {e}", exc_info=True)
            return False
    
    async def get_folders_via_applescript(self, client_name: str) -> List[str]:
        """
        Get list of email folders using AppleScript.
        
        Args:
            client_name: Name of the email client
            
        Returns:
            List of folder names
        """
        logger.info(f"📁 Getting folders from {client_name}")
        
        try:
            result = await self._execute_for_client(
                client_name, "get_folders", f"get folders from {client_name}"
            )
            return self.mail_app_service.parse_folders_from_applescript(result.data)
                
        except Exception as e:
            logger.error(f"❌ Error getting folders from {client_name}: {e}", exc_info=True)
            return []
    
    async def create_folder_via_applescript(self, client_name: str, folder_name: str, parent_folder: Optional[str] = None) -> bool:
        """
        Create email folder using AppleScript.
        
        Args:
            client_name: Name of the email client
            folder_name: Name of folder to create
            parent_folder: Parent folder (if creating subfolder)
            
        Returns:
            True if folder was created successfully
        """
        logger.info(f"📁 Creating folder '{folder_name}' in {client_name}")
        
        try:
            await self._execute_for_client(
                client_name, "create_folder", f"create folder in {client_name}",
                folder_name, parent_folder
            )
            
            logger.info(f"✅ Folder '{folder_name}' created successfully")
            return True
                
        except Exception as e:
            logger.error(f"❌ Error creating folder in {client_name}: {e}", exc_info=True)
            return False
    
    # AppleScript Template Methods (Outlook) - Enhanced with account mapping
    def _delegate_to_outlook_service(self, action_name: str, email_request_or_folder, *args, **kwargs):
        """
        Delegate email operations to the OutlookAppleScriptService.
        
        Args:
            action_name: The email action to perform ('get_emails', 'compose_email', 'reply_to_email', etc.)
            email_request_or_folder: EmailRequest object for actions, or folder string for get_emails
            *args: Additional arguments (limit, search_criteria for get_emails)
            
        Returns:
            AppleScript string from OutlookAppleScriptService
        """
        try:
            # Handle get_emails separately - different parameter signature
            if action_name == "get_emails":
                folder = email_request_or_folder
                limit = args[0] if args else 10
                search_criteria = args[1] if len(args) > 1 else None
                return self.outlook_service.get_emails_script(folder, limit, search_criteria)

            # Metadata-first triage path: folder + limit + optional search criteria.
            if action_name == "get_email_metadata":
                folder = email_request_or_folder
                limit = args[0] if args else 25
                search_criteria = args[1] if len(args) > 1 else None
                return self.outlook_service.get_email_metadata_script(folder, limit, search_criteria)

            # Selected-id expansion path: folder + email_ids + excerpt_chars.
            if action_name == "expand_email_details":
                folder = email_request_or_folder
                email_ids = args[0] if args else []
                excerpt_chars = (
                    args[1] if len(args) > 1 else kwargs.get("excerpt_chars", 4000)
                )
                return self.outlook_service.expand_email_details_script(
                    folder, email_ids, excerpt_chars
                )

            if action_name == "get_folders":
                return self.outlook_service.get_folders_script()

            if action_name == "create_folder":
                folder_name = email_request_or_folder
                parent_folder = args[0] if args else None
                return self.outlook_service.create_folder_script(folder_name, parent_folder)

            if action_name == "organize_emails":
                return self.outlook_service.organize_emails_script(email_request_or_folder)

            # All other actions use email_request as second parameter
            email_request = email_request_or_folder
            
            if action_name == "compose_email":
                return self.outlook_service.compose_email_script(email_request)
            elif action_name == "reply_to_email" or action_name == "reply":
                # Use native reply method with reference_email_id from EmailRequest
                if email_request.reference_email_id:
                    logger.info(f"📧 Using native Outlook reply for email_id={email_request.reference_email_id[:20]}...")
                    reply_all = kwargs.get('reply_all', True)
                    draft_only = kwargs.get('draft_only', True)
                    return self.outlook_service.reply_to_email_script(
                        email_id=email_request.reference_email_id,
                        reply_body=email_request.body,
                        reply_all=reply_all,
                        draft_only=draft_only
                    )
                else:
                    # Fallback to compose if no reference_email_id
                    logger.warning(f"⚠️ No reference_email_id for reply, falling back to compose_email")
                    return self.outlook_service.compose_email_script(email_request, draft_only=True)
            elif action_name == "forward_email":
                # Map forward to compose for now
                logger.info(f"📧 Mapping '{action_name}' to 'compose_email' (draft mode)")
                return self.outlook_service.compose_email_script(email_request, draft_only=True)
            elif action_name == "send_email":
                return self.outlook_service.send_email_script(email_request)
            else:
                logger.error(f"❌ Unsupported Outlook action: {action_name}")
                return f"SCRIPT_ERROR: Unsupported action '{action_name}' for Outlook"
                
        except Exception as e:
            logger.error(f"❌ Error delegating to Outlook service: {e}")
            return f"SCRIPT_ERROR: Failed to delegate action '{action_name}': {str(e)}"

    async def _ensure_outlook_discovery(self, folder: str = "inbox"):
        """Ensure Outlook account discovery has been performed with intelligent routing."""
        if not self.outlook_service.discovered_accounts:
            logger.info("🔍 Performing intelligent Outlook discovery...")
            
            # Extract account context from folder parameter if it's account-qualified
            account_context = None
            if folder and folder.lower() != "inbox":
                # User specified something like "baobab" instead of "inbox"
                # This indicates account-qualified folder reference
                account_context = folder.lower()
                logger.info(f"🎯 Detected account context: '{account_context}'")
            
            # Use intelligent discovery that adapts to account count and context
            self.outlook_service.discovered_accounts = await self.outlook_service.intelligent_discovery(
                self.execute_applescript, account_context
            )
            
            if self.outlook_service.discovered_accounts:
                logger.info(f"✅ Intelligent discovery completed: {len(self.outlook_service.discovered_accounts)} accounts/inboxes mapped")
            else:
                logger.warning("⚠️ Intelligent discovery returned no results")
        else:
            logger.debug("📧 Outlook discovery already completed") 