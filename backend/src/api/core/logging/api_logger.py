import logging
import sys
import os
from pathlib import Path
from typing import Optional
import plistlib # For reading macOS preferences

from ..config.api_settings import settings

# --- Desktop Debug Logging Preference --- 
def _read_desktop_logging_preference() -> bool:
    try:
        bundle_id = "com.stratten.basil" # From Info.plist
        prefs_path = Path.home() / "Library" / "Preferences" / f"{bundle_id}.plist"
        
        if not prefs_path.exists():
            # print(f"[Backend Logging Pref] Preferences file not found: {prefs_path}") # Avoid print before logger setup
            return False
            
        with open(prefs_path, 'rb') as fp:
            prefs = plistlib.load(fp)
        
        enabled = prefs.get("DesktopLoggingEnabled", False) # Default to False if key is missing
        # print(f"[Backend Logging Pref] Read DesktopLoggingEnabled: {enabled} from {prefs_path}")
        return bool(enabled)
    except Exception as e:
        # print(f"[Backend Logging Pref] Error reading preferences: {e}, defaulting to False.")
        return False

ENABLE_DESKTOP_DEBUG_LOGGING = _read_desktop_logging_preference()

# Force disable desktop logging for bundled/packaged versions
# This prevents debug logs from appearing on user desktops in release builds
if os.getenv('BASIL_BUNDLED', 'false').lower() == 'true':
    ENABLE_DESKTOP_DEBUG_LOGGING = False

DESKTOP_DEBUG_LOG_DIR = Path.home() / "Desktop" / "BasilDebugLogs"
if ENABLE_DESKTOP_DEBUG_LOGGING:
    DESKTOP_DEBUG_LOG_DIR.mkdir(parents=True, exist_ok=True)

def setup_api_logger(
    name: str,
    log_file: Optional[Path] = None,
    level: int = logging.INFO,
    format_string: Optional[str] = None
) -> logging.Logger:
    if format_string is None:
        format_string = (
            "%(asctime)s - %(name)s - %(levelname)s - [API Backend] %(message)s"
        )
    
    logger = logging.getLogger(f"api.{name}")
    logger.setLevel(level)
    logger.propagate = False
    
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    formatter = logging.Formatter(format_string)
    
    # Use _original_stdout for setup messages before redirection
    # These prints help confirm if the preference was read correctly during startup.
    # They will go to the original stdout, which is useful if redirection itself fails.
    if name == "main": # Only print these global setup messages once for the main logger
        _original_stdout.write(f"[Backend Logging Setup Init] Read DesktopLoggingEnabled preference: {ENABLE_DESKTOP_DEBUG_LOGGING!r}\\n")

    if ENABLE_DESKTOP_DEBUG_LOGGING:
        DESKTOP_DEBUG_LOG_DIR.mkdir(parents=True, exist_ok=True) 
        
        # Use timestamped filename pattern matching the client (Basil_YYYYMMDD_HHMMSS_SESSIONID.log)
        import datetime
        import uuid
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        session_id = str(uuid.uuid4())[:8]  # Match client's 8-character session ID
        effective_log_file_path = DESKTOP_DEBUG_LOG_DIR / f"Basil_Backend_{timestamp}_{session_id}.log"
        
        console_handler = logging.StreamHandler(_original_stdout) # Log to original stdout too
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        desktop_file_handler = logging.FileHandler(str(effective_log_file_path), mode='w')  # Use 'w' for new file each session
        desktop_file_handler.setFormatter(formatter)
        logger.addHandler(desktop_file_handler)
        
        if name == "main":
             _original_stdout.write(f"[Backend Logging Setup Init] Desktop debug logging ENABLED for '{logger.name}'. Logging to: {effective_log_file_path}\\n")

    else:
        console_handler = logging.StreamHandler(_original_stdout) # Log to original stdout
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        if log_file: 
            log_file.parent.mkdir(parents=True, exist_ok=True)
            standard_file_handler = logging.FileHandler(str(log_file), mode='a')
            standard_file_handler.setFormatter(formatter)
            logger.addHandler(standard_file_handler)
            if name == "main":
                _original_stdout.write(f"[Backend Logging Setup Init] Desktop debug logging DISABLED for '{logger.name}'. Using standard logs. File: {log_file}\\n")
        elif name == "main":
            _original_stdout.write(f"[Backend Logging Setup Init] Desktop debug logging DISABLED for '{logger.name}'. Using standard logs (Console only).\\n")

    # --- Pytest log clamping ---
    # If running under pytest, reduce noise from very verbose subsystems unless explicitly overridden
    try:
        import os
        is_pytest = bool(os.getenv("PYTEST_CURRENT_TEST"))
        verbose_tests = os.getenv("BASIL_VERBOSE_TEST_LOGS") == "1"
        if is_pytest and not verbose_tests:
            # Determine desired level for noisy loggers during tests
            test_level_name = os.getenv("BASIL_TEST_LOG_LEVEL", "WARNING").upper()
            test_level = getattr(logging, test_level_name, logging.WARNING)

            noisy_loggers = [
                "api.main",
                "api.core.knowledge.sqlite.sqlite_knowledge_service",
                "api.core.models.preferences",
                "api.routes.capture.activity_routes",
                # Legacy Huey scheduled tasks were removed in Phase 1 of the
                # Huey-removal plan. The asyncio replacements log under
                # `[CAPTURE_CLEANUP]` / `[DOWNLOAD_MANAGER]` prefixes via
                # `api_logger` directly.
                "api.services.maintenance.capture_cleanup_scheduler",
            ]
            for ln in noisy_loggers:
                try:
                    lg = logging.getLogger(ln)
                    lg.setLevel(test_level)
                except Exception:
                    pass
    except Exception:
        pass

    return logger

_original_stdout = sys.stdout # Define before api_logger uses it for setup messages
_original_stderr = sys.stderr

api_logger = setup_api_logger(
    "main",
    log_file=settings.STORAGE_DIR / "logs" / "api.log" if not settings.DEBUG else None,
    level=logging.DEBUG if settings.DEBUG else logging.INFO
)

# Custom filter to block raw WebSocket frame payload logs while keeping
# connection events, handshake diagnostics, and errors visible. DEBUG frame
# dumps can include access tokens before application-level redaction runs.
class WebSocketFrameSafetyFilter(logging.Filter):
    """Filter out raw WebSocket frame payload logs from protocol loggers."""
    def filter(self, record):
        msg = record.getMessage()
        frame_markers = ("< BINARY", "> BINARY", "% BINARY", "< TEXT", "> TEXT", "% TEXT")
        if any(marker in msg for marker in frame_markers):
            return False

        sensitive_fragments = (
            "access_token",
            "refresh_token",
            "id_token",
            "authorization",
            "api_key",
            "client_secret",
            "gho_",
        )
        lowered = msg.lower()
        return not any(fragment in lowered for fragment in sensitive_fragments)

# Apply the filter to websockets loggers AND uvicorn loggers to block raw frame spam.
# The frame logs come from uvicorn's WebSocket protocol logging, not just websockets.
frame_safety_filter = WebSocketFrameSafetyFilter()
for logger_name in ['websockets', 'websockets.server', 'websockets.protocol', 'uvicorn', 'uvicorn.access', 'uvicorn.error']:
    logger_obj = logging.getLogger(logger_name)
    logger_obj.addFilter(frame_safety_filter)

class StreamToLogger:
    def __init__(self, logger_instance, log_level=logging.INFO, original_stream=None):
        self.logger = logger_instance
        self.log_level = log_level
        self.linebuf = ''
        self.original_stream = original_stream

    def write(self, buf):
        # Tee to original stream if it exists and is not the redirected stream itself
        if self.original_stream and self.original_stream is not sys.__stdout__ and self.original_stream is not sys.__stderr__:
             self.original_stream.write(buf)
             self.original_stream.flush()

        for line in buf.rstrip().splitlines():
            # Avoid self-logging of setup messages that were already sent to _original_stdout
            if not (line.startswith("[Backend Logging Setup Init]") or \
                    line.startswith("[Backend Stdio Redirect Init]") or \
                    line.startswith("[Backend Logging Pref]")):
                 self.logger.log(self.log_level, line.rstrip())

    def flush(self):
        if self.original_stream and self.original_stream is not sys.__stdout__ and self.original_stream is not sys.__stderr__:
            self.original_stream.flush()

    def isatty(self):
        return False

_stdio_redirected = False

def redirect_stdio_to_logger(logger_instance_for_stdio):
    global _stdio_redirected
    if _stdio_redirected:
        # _original_stdout.write("[Backend Stdio Redirect Init] Stdio already redirected.\\n") # Avoid recursion
        return
    # Skip stdio redirection during pytest runs or when explicitly disabled
    try:
        import os
        if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("BASIL_DISABLE_STDIO_REDIRECT") == "1":
            return
    except Exception:
        pass

    # These initial messages always go to the actual original stdout/stderr
    _original_stdout.write(f"[Backend Stdio Redirect Init] Attempting stdio redirection. Desktop logging pref: {ENABLE_DESKTOP_DEBUG_LOGGING!r}\\n")

    if ENABLE_DESKTOP_DEBUG_LOGGING:
        sys.stdout = StreamToLogger(logger_instance_for_stdio, logging.INFO, _original_stdout)
        # Avoid redirecting stderr to prevent recursion in logging error paths during tests/runtime
        # Keep stderr on original to ensure logging internal errors don't recurse back into logger
        sys.stderr = _original_stderr
        _stdio_redirected = True
        # This message will be the first to go through the new sys.stdout (which tees to original)
        print(f"[Backend Stdio Redirect] Stdout/stderr REDIRECTED to logger ({logger_instance_for_stdio.name}).")
    else:
        _original_stdout.write("[Backend Stdio Redirect Init] Stdio redirection SKIPPED (desktop debug logging disabled).\\n") 