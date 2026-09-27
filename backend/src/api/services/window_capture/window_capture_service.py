"""Service for capturing window screenshots."""

import subprocess
import os
from datetime import datetime
import asyncio
from pathlib import Path
import pwd
import logging
import time

from .models import NoWindowError, CaptureFailedError, TextInsertError
from ...core.services.file_storage_service import StorageService
from ...core.services.model_service import ModelService
from ..image_processing.image_processing_service import ImageProcessor

logger = logging.getLogger(__name__)


class WindowCaptureService:
    def __init__(
        self,
        model_service: ModelService,
        image_processor: ImageProcessor,
        test_mode: bool = False
    ) -> None:
        """Initialize window capture service.
        
        Args:
            model_service: Service for managing AI models
            image_processor: Service for processing captured images
            test_mode: Whether to run in test mode (skip writing capture script)
        """
        self.storage = StorageService()
        self.image_processor = image_processor
        self.test_mode = test_mode
        self._capture_script = """#!/usr/bin/osascript

tell application "System Events"
    -- Get frontmost process
    set frontProcess to first process whose frontmost is true
    set frontAppName to name of frontProcess
    
    -- Check if process has windows
    if (count of windows of frontProcess) is 0 then
        set logLine to "[INFO] No window for frontmost process"
        do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
        return frontAppName & "|No Window|no_capture"
    end if
    
    -- Get window info
    set frontWindow to window 1 of frontProcess
    set winTitle to "Unknown"
    try
        set winTitle to name of frontWindow
    on error errMsg
        set logLine to "[INFO] Failed to get window title: " & errMsg
        do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
    end try
    
    -- Replace pipe characters in window title to prevent parsing issues
    set AppleScript's text item delimiters to "|"
    set winTitleParts to every text item of winTitle
    set AppleScript's text item delimiters to "⎮"  -- Use a visually similar but different character
    set winTitle to winTitleParts as string
    set AppleScript's text item delimiters to ""  -- Reset delimiters
    
    -- Get window position and size
    try
        set windowPosition to position of frontWindow
        set windowSize to size of frontWindow
        
        set xPos to item 1 of windowPosition
        set yPos to item 2 of windowPosition
        set winWidth to item 1 of windowSize
        set winHeight to item 2 of windowSize
        
        set logLine to "[INFO] xPos: " & xPos
        do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
        set logLine to "[INFO] yPos: " & yPos
        do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
        set logLine to "[INFO] winWidth: " & winWidth
        do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
        set logLine to "[INFO] winHeight: " & winHeight
        do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
        
        set timestamp to do shell script "date +%Y%m%d_%H%M%S"
        set capturePath to "/tmp/capture_" & timestamp & ".png"
        set logLine to "[INFO] capturePath: " & capturePath
        do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
        
        -- Use coordinates method - most reliable and non-interactive
        set captureCmd to "screencapture -x -R " & xPos & "," & yPos & "," & winWidth & "," & winHeight & " " & quoted form of capturePath
        set logLine to "[INFO] Capture instruction: " & captureCmd
        do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
        try
            do shell script captureCmd
            delay 0.2
        on error captureErr
            set logLine to "[INFO] screencapture failed: " & captureErr
            do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
            return frontAppName & "|" & winTitle & "|error: screencapture failed: " & captureErr
        end try
        
        -- Verify capture succeeded and has meaningful content
        set fileExists to do shell script "[ -f " & quoted form of capturePath & " ] && echo 'true' || echo 'false'"
        if fileExists is "true" then
            set fileSize to do shell script "/usr/bin/stat -f%z " & quoted form of capturePath
            set logLine to "[INFO] Capture file size: " & fileSize
            do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
            -- No early return for small files; always return the capture path
            return frontAppName & "|" & winTitle & "|" & capturePath
        else
            set logLine to "[INFO] Capture file not found: " & capturePath
            do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
            return frontAppName & "|" & winTitle & "|error: capture file not found"
        end if
    on error errMsg
        set logLine to "[INFO] Failed to get window position/size or capture: " & errMsg
        do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
        return frontAppName & "|" & winTitle & "|error: window region capture failed: " & errMsg
    end try
end tell"""

    async def _fallback_full_screen_capture(self, output_path: str) -> bool:
        """Fallback method to capture the full screen when window capture fails.
        
        Args:
            output_path: Path where to save the screenshot
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Attempting fallback full screen capture to {output_path}")
            proc = await asyncio.create_subprocess_exec(
                "screencapture", "-x", output_path,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                logger.error(f"Fallback capture failed: {stderr.decode()}")
                return False
                
            return os.path.exists(output_path) and os.path.getsize(output_path) > 0
            
        except Exception as e:
            logger.error(f"Fallback capture exception: {str(e)}")
            return False

    async def capture_temp_window(self) -> tuple[str, str, str, dict]:
        """Capture window to temporary location and process it.
        
        Returns:
            Tuple of (file_path, app_name, window_title, processing_results)
        """
        capture_id = f"temp_{int(time.time() * 1000)}"
        logger.info(f"[{capture_id}] Starting temporary window capture")
        
        try:
            # Create temporary script file
            script_path = self.storage.get_temp_path("capture_script.scpt")
            if not self.test_mode:
                with open(script_path, "w") as f:
                    f.write(self._capture_script)
            
            # Make script executable
            os.chmod(script_path, 0o755)

            # Execute script using osascript
            proc = await asyncio.create_subprocess_exec(
                "osascript", str(script_path), stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )

            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise CaptureFailedError(f"Capture failed: {stderr.decode()}")

            # Parse output
            output_parts = stdout.decode().strip().split("|", 2)  # Limit to 3 parts: app_name, window_title, temp_path
            if len(output_parts) != 3:
                raise CaptureFailedError(f"Invalid AppleScript output format: expected 3 parts, got {len(output_parts)}")
            app_name, window_title, temp_path = output_parts

            # Handle error cases
            if temp_path.startswith("error:"):
                raise CaptureFailedError(f"AppleScript error: {temp_path[6:]}", app_name)
            elif temp_path == "no_capture":
                logger.warning(f"[{capture_id}] No window available to capture for {app_name}, trying fallback full screen capture")
                # Fallback to full screen capture for apps with non-standard windows (wrappers, PWAs, etc.)
                fallback_path = self.storage.get_temp_path(f"fallback_temp_{int(time.time() * 1000)}.png")
                success = await self._fallback_full_screen_capture(fallback_path)
                if success:
                    temp_path = fallback_path
                    logger.info(f"[{capture_id}] Fallback full screen capture successful for {app_name}")
                else:
                    raise NoWindowError(f"No window available to capture and fallback failed", app_name)

            # Verify the captured file exists and has meaningful content
            if not os.path.exists(temp_path):
                logger.warning(f"[{capture_id}] Capture file does not exist at {temp_path}, trying fallback")
                # Fallback to full screen capture
                fallback_path = self.storage.get_temp_path(f"fallback_temp_{int(time.time() * 1000)}.png")
                await self._fallback_full_screen_capture(fallback_path)
                temp_path = fallback_path
            else:
                # Check file size to ensure it's not just a tiny capture of a UI element
                file_size = os.path.getsize(temp_path)
                if file_size < 5000:  # Less than 5KB is likely not a meaningful capture
                    logger.warning(f"[{capture_id}] Capture file too small ({file_size} bytes), trying fallback")
                    # Fallback to full screen capture
                    fallback_path = self.storage.get_temp_path(f"fallback_temp_{int(time.time() * 1000)}.png")
                    await self._fallback_full_screen_capture(fallback_path)
                    
                    # Only use fallback if original is really tiny or fallback is significantly larger
                    if file_size < 1000 or os.path.getsize(fallback_path) > file_size * 3:
                        os.remove(temp_path)  # Remove the original tiny capture
                        temp_path = fallback_path
                    else:
                        os.remove(fallback_path)  # Keep original if fallback isn't much better

            # Move to temp directory
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            final_path = self.storage.get_temp_path(f"temp_capture_{timestamp}_{app_name}.png")

            if os.path.exists(temp_path):
                os.rename(temp_path, final_path)

            # Process the image
            processing_result = await self.image_processor.process_image(str(final_path))

            logger.info(f"[{capture_id}] Captured and processed {app_name} window")
            return str(final_path), app_name, window_title, processing_result.model_dump()

        except (NoWindowError, CaptureFailedError):
            raise
        except Exception as e:
            raise CaptureFailedError(f"Failed to capture window: {str(e)}")
        finally:
            if os.path.exists(script_path):
                os.remove(script_path)

    async def capture_active_window(self) -> tuple[str, str, str, dict]:
        """Capture the active window, store it permanently, and process it.
        
        Returns:
            Tuple of (file_path, app_name, window_title, processing_results)
        """
        capture_id = f"cap_{int(time.time() * 1000)}"
        logger.info(f"[{capture_id}] Starting active window capture")
        try:
            # Create temporary script file
            script_path = self.storage.get_temp_path("capture_script.scpt")
            if not self.test_mode:
                logger.info(f"[{capture_id}] Creating AppleScript at {script_path}")
                with open(script_path, "w") as f:
                    f.write(self._capture_script)
            
            # Make script executable
            os.chmod(script_path, 0o755)

            # Execute script using osascript
            logger.info(f"[{capture_id}] Executing AppleScript")
            proc = await asyncio.create_subprocess_exec(
                "osascript", str(script_path), stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )

            stdout, stderr = await proc.communicate()
            logger.info(f"[{capture_id}] AppleScript execution completed with return code {proc.returncode}")

            if proc.returncode != 0:
                error_msg = stderr.decode()
                logger.error(f"[{capture_id}] Capture failed: {error_msg}")
                raise CaptureFailedError(f"Capture failed: {error_msg}")

            # Parse output
            stdout_str = stdout.decode().strip()
            logger.info(f"[{capture_id}] Parsing AppleScript output: {stdout_str[:100]}...")
            output_parts = stdout_str.split("|", 2)  # Limit to 3 parts: app_name, window_title, result
            if len(output_parts) != 3:
                error_msg = f"Invalid AppleScript output format: expected 3 parts, got {len(output_parts)}"
                logger.error(f"[{capture_id}] {error_msg}")
                raise CaptureFailedError(error_msg)
            app_name, window_title, result = output_parts

            # Handle error cases
            if result.startswith("error:"):
                error_msg = result[6:]
                logger.error(f"[{capture_id}] AppleScript error: {error_msg}")
                raise CaptureFailedError(f"AppleScript error: {error_msg}", app_name)
            elif result == "no_capture":
                logger.warning(f"[{capture_id}] No window available to capture for {app_name}, trying fallback full screen capture")
                # Fallback to full screen capture for apps with non-standard windows (wrappers, PWAs, etc.)
                fallback_path = self.storage.get_temp_path(f"fallback_capture_{int(time.time() * 1000)}.png")
                success = await self._fallback_full_screen_capture(fallback_path)
                if success:
                    result = fallback_path
                    logger.info(f"[{capture_id}] Fallback full screen capture successful for {app_name}")
                else:
                    raise NoWindowError(f"No window available to capture and fallback failed", app_name)

            # Verify the captured file exists and has meaningful content
            if not os.path.exists(result):
                logger.warning(f"[{capture_id}] Capture file does not exist at {result}, trying fallback")
                # Fallback to full screen capture
                fallback_path = self.storage.get_temp_path(f"fallback_capture_{int(time.time() * 1000)}.png")
                await self._fallback_full_screen_capture(fallback_path)
                result = fallback_path
            else:
                # Check file size to ensure it's not just a tiny capture of a UI element
                file_size = os.path.getsize(result)
                if file_size < 5000:  # Less than 5KB is likely not a meaningful capture
                    logger.warning(f"[{capture_id}] Capture file too small ({file_size} bytes), trying fallback")
                    # Fallback to full screen capture
                    fallback_path = self.storage.get_temp_path(f"fallback_capture_{int(time.time() * 1000)}.png")
                    await self._fallback_full_screen_capture(fallback_path)
                    
                    # Only use fallback if original is really tiny or fallback is significantly larger
                    if file_size < 1000 or os.path.getsize(fallback_path) > file_size * 3:
                        os.remove(result)  # Remove the original tiny capture
                        result = fallback_path
                    else:
                        os.remove(fallback_path)  # Keep original if fallback isn't much better

            # Move to permanent storage
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"capture_{timestamp}_{app_name}.png"
            logger.info(f"[{capture_id}] Moving capture from {result} to permanent storage")

            final_path = self.storage.store_capture(Path(result), filename)
            logger.info(f"[{capture_id}] Capture stored at {final_path}")

            # Clean up temporary file
            if os.path.exists(result):
                os.remove(result)
                logger.info(f"[{capture_id}] Cleaned up temporary file at {result}")

            processing_result = await self.image_processor.process_image(str(final_path))
            logger.info(f"[{capture_id}] Capture successful for {app_name} - {window_title}")
            return str(final_path), app_name, window_title, processing_result.model_dump()

        except (NoWindowError, CaptureFailedError) as e:
            logger.error(f"[{capture_id}] Capture error: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"[{capture_id}] Unexpected capture error: {str(e)}", exc_info=True)
            raise CaptureFailedError(f"Failed to capture window: {str(e)}")
        finally:
            # Cleanup script
            if os.path.exists(script_path):
                os.remove(script_path)
                logger.info(f"[{capture_id}] Cleaned up script at {script_path}")
            # Clean up any leftover temporary files
            self.storage.cleanup_temp()
            logger.info(f"[{capture_id}] Cleaned up temporary files")

    async def insert_text(self, text: str) -> None:
        """Insert text into the active window at current cursor position."""
        import base64

        # Encode the text in base64 to avoid shell escaping issues
        encoded_text = base64.b64encode(text.encode()).decode()

        script = f"""#!/usr/bin/osascript
tell application "System Events"
    set encoded_text to "{encoded_text}"
    set the clipboard to (do shell script "echo " & encoded_text & " | base64 --decode")
    delay 0.1
    keystroke "v" using instruction down
end tell"""

        script_path = self.storage.get_temp_path("insert_script.scpt")
        try:
            with open(script_path, "w") as f:
                f.write(script)

            os.chmod(script_path, 0o755)

            proc = await asyncio.create_subprocess_exec(
                "osascript", str(script_path), stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )

            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise TextInsertError(f"Text insertion failed: {stderr.decode()}")

        except TextInsertError:
            raise
        except Exception as e:
            raise TextInsertError(f"Failed to insert text: {str(e)}")
        finally:
            if os.path.exists(script_path):
                os.remove(script_path)
