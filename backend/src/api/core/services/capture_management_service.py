# backend/src/api/core/services/capture_management_service.py
from __future__ import annotations
import logging
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional
import shutil
import os
import json # Added for JSON operations
from datetime import datetime, timedelta

from .file_storage_service import StorageService
# We'll need to define these Pydantic models later, likely in a models file
# from ..models.capture_management_models import CaptureStats, CleanupSettings

logger = logging.getLogger(__name__)

# Default values for capture cleanup settings if not found in the shared config file
DEFAULT_CAPTURE_SETTINGS = {
    "capture_auto_cleanup_enabled": False,
    "capture_retention_days": 30,
    "capture_cleanup_hour": 2,    # Default to 2:00 AM
    "capture_cleanup_minute": 0
}

class CaptureManagementService:
    def __init__(self, storage_service: StorageService):
        self.storage_service = storage_service
        
        # Path for captures stored in YYYY-MM-DD subdirectories, as per FileStorageService.get_capture_path()
        self.captures_path_structured = self.storage_service.base_path / "data" / "captures"
        
        # Path for captures/files stored flatly in the temp directory, as per FileStorageService.get_temp_path()
        # Files here are expected to have dates in their names (e.g., capture_YYYYMMDD_HHMMSS.png)
        self.captures_path_temp_flat = self.storage_service.base_path / "data" / "temp"
        
        # Settings are now part of a shared reasoning_settings.json file
        self.settings_file_path = self.storage_service.base_path / "config" / "reasoning_settings.json"
        # self._settings will store the specific capture-related settings extracted from the shared file
        self._settings: Dict[str, Any] = {} 
        
        # Track the current scheduled task
        self._scheduled_task_id: Optional[str] = None
        
        self._load_settings()

    def _ensure_config_dir_exists(self):
        """Ensures the config directory for settings storage exists."""
        config_dir = self.settings_file_path.parent
        if not config_dir.exists():
            try:
                config_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created config directory: {config_dir}")
            except Exception as e:
                logger.error(f"Failed to create config directory {config_dir}: {e}")
                # Depending on desired robustness, could raise an error here

    def _load_settings(self):
        """Loads capture cleanup settings from reasoning_settings.json, adding defaults if necessary."""
        self._ensure_config_dir_exists()
        
        shared_settings: Dict[str, Any] = {}
        settings_file_updated = False

        try:
            if self.settings_file_path.exists():
                with open(self.settings_file_path, 'r') as f:
                    shared_settings = json.load(f)
                logger.info(f"Successfully loaded shared settings from {self.settings_file_path}")
            else:
                logger.info(f"Shared settings file {self.settings_file_path} not found. Will create with defaults.")
                # If file doesn't exist, shared_settings remains empty, defaults will be added.
                settings_file_updated = True # Mark for saving

        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from {self.settings_file_path}. Will attempt to use defaults and overwrite if possible.")
            # shared_settings remains empty or with partial data, defaults will be added/overwrite.
            settings_file_updated = True # Mark for saving
        except Exception as e:
            logger.error(f"Failed to load shared settings from {self.settings_file_path}: {e}. Will use defaults.")
            # Treat as if file didn't exist for our specific keys
            settings_file_updated = True # Mark for saving

        # Ensure our specific keys are present, using defaults if not
        if "capture_auto_cleanup_enabled" not in shared_settings:
            shared_settings["capture_auto_cleanup_enabled"] = DEFAULT_CAPTURE_SETTINGS["capture_auto_cleanup_enabled"]
            settings_file_updated = True
            logger.info(f"Added default 'capture_auto_cleanup_enabled' to shared settings.")

        if "capture_retention_days" not in shared_settings:
            shared_settings["capture_retention_days"] = DEFAULT_CAPTURE_SETTINGS["capture_retention_days"]
            settings_file_updated = True
            logger.info(f"Added default 'capture_retention_days' to shared settings.")

        if "capture_cleanup_hour" not in shared_settings:
            shared_settings["capture_cleanup_hour"] = DEFAULT_CAPTURE_SETTINGS["capture_cleanup_hour"]
            settings_file_updated = True
            logger.info(f"Added default 'capture_cleanup_hour' to shared settings.")

        if "capture_cleanup_minute" not in shared_settings:
            shared_settings["capture_cleanup_minute"] = DEFAULT_CAPTURE_SETTINGS["capture_cleanup_minute"]
            settings_file_updated = True
            logger.info(f"Added default 'capture_cleanup_minute' to shared settings.")

        # Populate self._settings with the values for our keys
        self._settings["auto_cleanup_enabled"] = shared_settings.get("capture_auto_cleanup_enabled", DEFAULT_CAPTURE_SETTINGS["capture_auto_cleanup_enabled"])
        self._settings["retention_days"] = shared_settings.get("capture_retention_days", DEFAULT_CAPTURE_SETTINGS["capture_retention_days"])
        self._settings["cleanup_hour"] = shared_settings.get("capture_cleanup_hour", DEFAULT_CAPTURE_SETTINGS["capture_cleanup_hour"])
        self._settings["cleanup_minute"] = shared_settings.get("capture_cleanup_minute", DEFAULT_CAPTURE_SETTINGS["capture_cleanup_minute"])

        if settings_file_updated:
            self._save_settings(shared_settings) # Save the potentially modified shared_settings

    def _save_settings(self, settings_to_save: Dict[str, Any]):
        """Saves the provided dictionary (expected to be the full shared settings) to reasoning_settings.json."""
        self._ensure_config_dir_exists()
        try:
            with open(self.settings_file_path, 'w') as f:
                json.dump(settings_to_save, f, indent=4)
            logger.info(f"Successfully saved shared settings to {self.settings_file_path}")
        except Exception as e:
            logger.error(f"Failed to save shared settings to {self.settings_file_path}: {e}")
            raise

    async def get_capture_stats(self) -> Dict[str, Any]: # Replace Any with CaptureStats model
        """
        Calculates statistics about stored capture files from multiple locations.
        - Total number of files
        - Total size of files
        - Number and size of files created in the last 7 days
        - Number and size of files created in the last 30 days
        """
        logger.info(f"[Stats] Initializing capture stats calculation. Structured path: {self.captures_path_structured}, Temp flat path: {self.captures_path_temp_flat}")
        total_files = 0
        total_size_bytes = 0
        files_last_7_days = 0
        size_last_7_days_bytes = 0
        files_last_30_days = 0
        size_last_30_days_bytes = 0

        now = datetime.now()
        seven_days_ago_boundary = (now - timedelta(days=6)).date()
        thirty_days_ago_boundary = (now - timedelta(days=29)).date()

        # --- Process structured captures (YYYY-MM-DD directories) ---
        if self.captures_path_structured.exists():
            logger.info(f"[Stats] Processing structured captures directory: {self.captures_path_structured}")
            for date_dir in self.captures_path_structured.iterdir():
                if date_dir.is_dir():
                    try:
                        dir_date_obj = datetime.strptime(date_dir.name, "%Y-%m-%d")
                        current_dir_date = dir_date_obj.date()

                        for capture_file in date_dir.iterdir():
                            if capture_file.is_file() and capture_file.name.startswith("capture_") and capture_file.suffix == ".png":
                                total_files += 1
                                file_size = capture_file.stat().st_size
                                total_size_bytes += file_size

                                if current_dir_date >= seven_days_ago_boundary:
                                    files_last_7_days += 1
                                    size_last_7_days_bytes += file_size
                                
                                if current_dir_date >= thirty_days_ago_boundary:
                                    files_last_30_days += 1
                                    size_last_30_days_bytes += file_size
                    except ValueError:
                        logger.warning(f"[Stats] Skipping structured capture directory with unexpected name format: {date_dir.name}")
                    except Exception as e:
                        logger.error(f"[Stats] Error processing structured capture directory {date_dir}: {e}")
        else:
            logger.warning(f"[Stats] Structured captures directory does not exist or is not accessible: {self.captures_path_structured}")

        # --- Process flat captures (in temp; several naming conventions have been used
        # over time by the Python legacy capture path and the current Swift capture
        # bridge, so we recognize every known capture-file prefix here rather than
        # just the oldest one). The Swift bridge (WindowCaptureService.swift) writes
        # live automatic-capture screenshots as "capture_<timestamp>.png" directly into
        # this flat temp directory, with no per-date subfolder, so these files must be
        # counted here to avoid silently undercounting the majority of real captures.
        FLAT_TEMP_CAPTURE_PREFIXES = ("capture_", "temp_capture_", "fallback_capture_", "fallback_temp_")
        if self.captures_path_temp_flat.exists():
            logger.info(f"[Stats] Processing temp flat captures directory: {self.captures_path_temp_flat}")
            processed_temp_files = 0
            for item_in_temp in self.captures_path_temp_flat.iterdir(): # Iterate through the corrected path
                logger.debug(f"[Stats] Temp Dir Item: {item_in_temp.name} (is_file: {item_in_temp.is_file()})")
                if (
                    item_in_temp.is_file()
                    and item_in_temp.suffix == ".png"
                    and item_in_temp.name.startswith(FLAT_TEMP_CAPTURE_PREFIXES)
                ):
                    processed_temp_files += 1
                    try:
                        # Flat temp filenames use several timestamp formats over time
                        # (some embed "YYYYMMDD_HHMMSS", others a raw millisecond epoch),
                        # so the file's own modification time is the one reliable signal
                        # for "when was this capture taken" across every naming scheme.
                        file_date = datetime.fromtimestamp(item_in_temp.stat().st_mtime).date()

                        total_files += 1
                        file_size = item_in_temp.stat().st_size
                        total_size_bytes += file_size

                        if file_date >= seven_days_ago_boundary:
                            files_last_7_days += 1
                            size_last_7_days_bytes += file_size

                        if file_date >= thirty_days_ago_boundary:
                            files_last_30_days += 1
                            size_last_30_days_bytes += file_size
                    except Exception as e:
                        logger.error(f"[Stats] Error processing flat temp capture file {item_in_temp.name}: {e}")
            if processed_temp_files == 0:
                logger.info(f"[Stats] No flat temp capture files found in {self.captures_path_temp_flat}.")
        else:
            logger.warning(f"[Stats] Flat temp captures directory does not exist or is not accessible: {self.captures_path_temp_flat}")
        
        logger.info(f"[Stats] Final calculated stats: Total Files={total_files}, Total Size={total_size_bytes}, Last 7 Days Files={files_last_7_days}, Last 30 Days Files={files_last_30_days}")
        return {
            "total_files": total_files,
            "total_size_bytes": total_size_bytes,
            "files_last_7_days": files_last_7_days,
            "size_last_7_days_bytes": size_last_7_days_bytes,
            "files_last_30_days": files_last_30_days,
            "size_last_30_days_bytes": size_last_30_days_bytes,
        }

    async def get_cleanup_settings(self) -> Dict[str, Any]: # Replace Any with CleanupSettings model
        """Returns the current capture cleanup specific settings."""
        logger.info(f"Retrieving capture cleanup settings: {self._settings}")
        return self._settings.copy()

    async def update_cleanup_settings(self, auto_cleanup_enabled: bool, retention_days: int, cleanup_hour: int = None, cleanup_minute: int = None) -> Dict[str, Any]: # Replace Any with CleanupSettings model
        """Updates capture cleanup settings within the shared reasoning_settings.json file."""
        # Store previous state to check for changes
        previous_enabled = self._settings.get("auto_cleanup_enabled", False)
        
        # Use current values if new time values not provided
        if cleanup_hour is None:
            cleanup_hour = self._settings.get("cleanup_hour", DEFAULT_CAPTURE_SETTINGS["capture_cleanup_hour"])
        if cleanup_minute is None:
            cleanup_minute = self._settings.get("cleanup_minute", DEFAULT_CAPTURE_SETTINGS["capture_cleanup_minute"])
        
        # Validate time values
        if not (0 <= cleanup_hour <= 23):
            raise ValueError("cleanup_hour must be between 0 and 23")
        if not (0 <= cleanup_minute <= 59):
            raise ValueError("cleanup_minute must be between 0 and 59")
        
        shared_settings: Dict[str, Any] = {}
        try:
            if self.settings_file_path.exists():
                with open(self.settings_file_path, 'r') as f:
                    shared_settings = json.load(f)
        except Exception as e:
            logger.error(f"Could not read existing shared settings file at {self.settings_file_path} before update: {e}. New settings might overwrite.")
            # Proceed with an empty shared_settings, so at least our keys get saved.

        # Update our specific keys
        shared_settings["capture_auto_cleanup_enabled"] = auto_cleanup_enabled
        shared_settings["capture_retention_days"] = retention_days
        shared_settings["capture_cleanup_hour"] = cleanup_hour
        shared_settings["capture_cleanup_minute"] = cleanup_minute

        self._save_settings(shared_settings) # Save the entire modified shared_settings structure

        # Update in-memory self._settings for immediate use
        self._settings["auto_cleanup_enabled"] = auto_cleanup_enabled
        self._settings["retention_days"] = retention_days
        self._settings["cleanup_hour"] = cleanup_hour
        self._settings["cleanup_minute"] = cleanup_minute
        
        # Manage Huey task scheduling based on setting changes
        if auto_cleanup_enabled != previous_enabled:
            if auto_cleanup_enabled:
                await self._schedule_cleanup_task()
            else:
                await self._unschedule_cleanup_task()
        elif auto_cleanup_enabled:
            # If cleanup is enabled and time changed, reschedule
            await self._schedule_cleanup_task()
        
        logger.info(f"Updated and saved capture cleanup settings within shared config: {self._settings}")
        return self._settings.copy()

    async def _schedule_cleanup_task(self):
        """Wake the in-process capture cleanup scheduler.

        Pre-Huey-removal this enqueued a Huey periodic task. Post step
        1.4.11 the scheduler runs continuously inside FastAPI and re-reads
        `reasoning_settings.json` on every loop iteration. We just kick the
        loop so the user-facing toggle takes effect immediately rather than
        waiting out the in-progress sleep (up to 5 minutes when previously
        disabled).
        """
        try:
            from api.services.maintenance import kick_capture_cleanup_scheduler

            delivered = kick_capture_cleanup_scheduler()
            if delivered:
                logger.info(
                    "Automatic capture cleanup enabled; kicked CaptureCleanupScheduler"
                )
            else:
                # No FastAPI app booted (unit test / standalone tool). Settings
                # were still written to disk, so the scheduler will pick them
                # up the next time it is started.
                logger.info(
                    "Automatic capture cleanup enabled; no scheduler registered "
                    "(settings persisted, will apply on next process start)"
                )
        except Exception as e:
            logger.error(f"Error notifying capture cleanup scheduler: {e}", exc_info=True)

    async def _unschedule_cleanup_task(self):
        """Wake the scheduler so it observes the disabled flag immediately.

        Symmetrical to `_schedule_cleanup_task`. The scheduler's own loop is
        responsible for noticing `capture_auto_cleanup_enabled=False` and
        switching to the polling sleep — kicking just shortens the latency
        between toggle and observed effect.
        """
        try:
            from api.services.maintenance import kick_capture_cleanup_scheduler

            delivered = kick_capture_cleanup_scheduler()
            if delivered:
                logger.info(
                    "Automatic capture cleanup disabled; kicked CaptureCleanupScheduler"
                )
            else:
                logger.info(
                    "Automatic capture cleanup disabled; no scheduler registered "
                    "(settings persisted, will apply on next process start)"
                )
        except Exception as e:
            logger.error(f"Error notifying capture cleanup scheduler: {e}", exc_info=True)

    async def _run_lifecycle_deletion(self, operation: str, **kwargs) -> ActivityCaptureDeletionResult:
        """Delegate structured capture-record deletion to the lifecycle service."""
        from api.services.capture.automatic.activity_capture_data_lifecycle_service import (
            ActivityCaptureDataLifecycleService,
            ActivityCaptureDeletionResult,
        )

        db_path = str(self.storage_service.get_db_path())
        from api.services.retrieval.index_runtime import get_retrieval_index_runtime
        from api.services.zettel.materializer import get_zettel_materializer

        retrieval_runtime = get_retrieval_index_runtime()
        materializer = get_zettel_materializer()

        service = ActivityCaptureDataLifecycleService(db_path, retrieval_runtime, materializer)
        if operation == "all":
            return await service.delete_all()
        if operation == "older_than":
            return await service.delete_older_than(kwargs["cutoff"])
        if operation == "trim":
            return await service.trim_to_storage_limit(kwargs["max_storage_mb"])
        return ActivityCaptureDeletionResult()

    async def clear_all_captures(self) -> Dict[str, Any]:
        """Deletes capture records and legacy orphan image files."""
        lifecycle_result = await self._run_lifecycle_deletion("all")
        filesystem_result = await self._clear_legacy_capture_files_only()
        errors = (
            list(lifecycle_result.file_errors)
            + list(lifecycle_result.post_commit_errors)
            + filesystem_result["errors"]
        )
        status = "partial" if errors else "success"
        return {
            "status": status,
            "message": "All captures cleared.",
            "files_deleted": lifecycle_result.files_deleted + filesystem_result["files_deleted"],
            "space_freed_bytes": lifecycle_result.bytes_freed + filesystem_result["space_freed_bytes"],
            "records_deleted": lifecycle_result.records_deleted,
            "derived_entries_deleted": lifecycle_result.derived_entries_deleted,
            "errors": errors,
        }

    async def _clear_legacy_capture_files_only(self) -> Dict[str, Any]:
        """Remove orphan capture image files not tied to lifecycle deletion."""
        total_deleted_files_count = 0
        total_freed_space_bytes = 0
        errors: List[str] = []

        # --- Clear structured captures (YYYY-MM-DD directories) ---
        if self.captures_path_structured.exists():
            deleted_structured_count = 0
            freed_structured_bytes = 0
            for date_dir in self.captures_path_structured.iterdir():
                if date_dir.is_dir():
                    for capture_file in date_dir.iterdir():
                        if capture_file.is_file():
                            try:
                                file_size = capture_file.stat().st_size
                                capture_file.unlink()
                                deleted_structured_count +=1
                                freed_structured_bytes += file_size
                            except Exception as e:
                                logger.error(f"Failed to delete structured file {capture_file}: {e}")
                                if len(errors) < 20:
                                    errors.append(f"{capture_file}: {e}"[:500])
                    # Attempt to remove the date directory if it's empty
                    try:
                        if not any(date_dir.iterdir()): # Check if directory is empty
                            date_dir.rmdir()
                    except Exception as e:
                        logger.error(f"Failed to remove empty structured directory {date_dir}: {e}")
            total_deleted_files_count += deleted_structured_count
            total_freed_space_bytes += freed_structured_bytes
            if deleted_structured_count > 0:
                 logger.info(f"Cleared structured captures. Deleted {deleted_structured_count} files, freed {freed_structured_bytes} bytes.")
        else:
            logger.info("Structured captures directory not found, skipping clear operation for it.")

        # --- Clear flat temp captures (in temp directory) ---
        if self.captures_path_temp_flat.exists():
            deleted_flat_temp_count = 0
            freed_flat_temp_bytes = 0
            for capture_file in self.captures_path_temp_flat.iterdir(): # Iterate through the corrected path
                if capture_file.is_file() and capture_file.name.startswith("capture_") and capture_file.suffix == ".png":
                    try:
                        file_size = capture_file.stat().st_size
                        capture_file.unlink()
                        deleted_flat_temp_count += 1
                        freed_flat_temp_bytes += file_size
                    except Exception as e:
                        logger.error(f"Failed to delete flat temp file {capture_file}: {e}")
                        if len(errors) < 20:
                            errors.append(f"{capture_file}: {e}"[:500])
            total_deleted_files_count += deleted_flat_temp_count
            total_freed_space_bytes += freed_flat_temp_bytes
            if deleted_flat_temp_count > 0:
                logger.info(f"Cleared flat temp captures. Deleted {deleted_flat_temp_count} files, freed {freed_flat_temp_bytes} bytes.")
        else:
            logger.info("Flat temp captures directory not found, skipping clear operation for it.")
        
        return {
            "files_deleted": total_deleted_files_count,
            "space_freed_bytes": total_freed_space_bytes,
            "errors": errors,
        }

    async def clear_captures_older_than(self, days: int) -> Dict[str, Any]:
        """Deletes capture records and legacy files older than the specified number of days."""
        if days < 0:
            logger.error("Days must be a non-negative integer for cleanup.")
            return {
                "status": "error",
                "message": "Days must be a non-negative integer.",
                "files_deleted": 0,
                "space_freed_bytes": 0,
                "records_deleted": 0,
                "derived_entries_deleted": 0,
                "errors": [],
            }

        cutoff = datetime.now() - timedelta(days=days)
        lifecycle_result = await self._run_lifecycle_deletion("older_than", cutoff=cutoff)
        filesystem_result = await self._clear_legacy_capture_files_older_than(days)
        errors = (
            list(lifecycle_result.file_errors)
            + list(lifecycle_result.post_commit_errors)
            + filesystem_result["errors"]
        )
        status = "partial" if errors else "success"
        return {
            "status": status,
            "message": f"Captures older than {days} days cleared.",
            "files_deleted": lifecycle_result.files_deleted + filesystem_result["files_deleted"],
            "space_freed_bytes": lifecycle_result.bytes_freed + filesystem_result["space_freed_bytes"],
            "records_deleted": lifecycle_result.records_deleted,
            "derived_entries_deleted": lifecycle_result.derived_entries_deleted,
            "errors": errors,
        }

    async def _clear_legacy_capture_files_older_than(self, days: int) -> Dict[str, Any]:
        """Remove orphan capture image files older than days from filesystem locations."""
        cutoff_date = (datetime.now() - timedelta(days=days)).date()
        total_deleted_files_count = 0
        total_freed_space_bytes = 0
        errors: List[str] = []

        # --- Clear structured captures older than 'days' ---
        if self.captures_path_structured.exists():
            deleted_structured_count = 0
            freed_structured_bytes = 0
            for date_dir in self.captures_path_structured.iterdir():
                if date_dir.is_dir():
                    try:
                        dir_date_obj = datetime.strptime(date_dir.name, "%Y-%m-%d")
                        if dir_date_obj.date() < cutoff_date:
                            num_files_in_dir = 0
                            size_of_dir_bytes = 0
                            for item in date_dir.rglob('*'):
                                if item.is_file():
                                    size_of_dir_bytes += item.stat().st_size
                                    num_files_in_dir +=1
                            
                            shutil.rmtree(date_dir)
                            deleted_structured_count += num_files_in_dir
                            freed_structured_bytes += size_of_dir_bytes
                            logger.info(f"Deleted structured directory {date_dir} (older than {days} days).")
                    except ValueError:
                        logger.warning(f"Skipping structured directory with unexpected name format: {date_dir.name} during cleanup.")
                    except Exception as e:
                        logger.error(f"Error processing or deleting structured directory {date_dir}: {e}")
                        if len(errors) < 20:
                            errors.append(f"{date_dir}: {e}"[:500])
            total_deleted_files_count += deleted_structured_count
            total_freed_space_bytes += freed_structured_bytes
            if deleted_structured_count > 0:
                logger.info(f"Cleared structured captures older than {days} days. Deleted {deleted_structured_count}, freed {freed_structured_bytes} bytes.")
        else:
            logger.info("Structured captures directory not found, skipping cleanup for it.")

        # --- Clear flat temp captures older than 'days' ---
        if self.captures_path_temp_flat.exists():
            deleted_flat_temp_count = 0
            freed_flat_temp_bytes = 0
            for capture_file in self.captures_path_temp_flat.iterdir(): # Iterate through the corrected path
                if capture_file.is_file() and capture_file.name.startswith("temp_capture_") and capture_file.suffix == ".png":
                    try:
                        filename_parts = capture_file.name.split("_")
                        if len(filename_parts) > 2:
                            date_str_from_filename = filename_parts[2]
                            if len(date_str_from_filename) >= 8:
                                year = int(date_str_from_filename[0:4])
                                month = int(date_str_from_filename[4:6])
                                day = int(date_str_from_filename[6:8])
                                file_date = datetime(year, month, day).date()

                                if file_date < cutoff_date:
                                    file_size = capture_file.stat().st_size
                                    capture_file.unlink()
                                    deleted_flat_temp_count += 1
                                    freed_flat_temp_bytes += file_size
                                    logger.info(f"Deleted flat temp file {capture_file} (older than {days} days).")
                            else:
                                logger.warning(f"Skipping flat temp file due to short date string: {capture_file.name} during cleanup.")
                        else:
                            logger.warning(f"Skipping flat temp file due to unexpected name format: {capture_file.name} during cleanup.")
                    except ValueError as ve:
                        logger.warning(f"Skipping flat temp file due to date parsing error: {capture_file.name} - {ve} during cleanup.")
                    except Exception as e:
                        logger.error(f"Error processing or deleting flat temp file {capture_file}: {e}")
                        if len(errors) < 20:
                            errors.append(f"{capture_file}: {e}"[:500])
            total_deleted_files_count += deleted_flat_temp_count
            total_freed_space_bytes += freed_flat_temp_bytes
            if deleted_flat_temp_count > 0:
                logger.info(f"Cleared flat temp captures older than {days} days. Deleted {deleted_flat_temp_count}, freed {freed_flat_temp_bytes} bytes.")
        else:
            logger.info("Flat temp captures directory not found, skipping cleanup for it.")
        
        logger.info(
            "Legacy filesystem captures cleared older than %s days. Deleted %s files, freed %s bytes.",
            days,
            total_deleted_files_count,
            total_freed_space_bytes,
        )
        return {
            "files_deleted": total_deleted_files_count,
            "space_freed_bytes": total_freed_space_bytes,
            "errors": errors,
        }

    async def run_automatic_cleanup(self):
        """
        Runs the automatic cleanup process based on current settings.
        This would be called by a scheduler (e.g., on startup or daily).
        """
        settings = await self.get_cleanup_settings()
        if not settings.get("auto_cleanup_enabled"):
            logger.info("Automatic cleanup is not enabled. Skipping.")
            return

        retention_days = settings.get("retention_days", 30)
        if retention_days > 0:
            logger.info(
                "Running automatic cleanup. Deleting capture records older than %s days.",
                retention_days,
            )
            await self.clear_captures_older_than(retention_days)
        else:
            logger.info(
                "Automatic cleanup enabled, but retention_days is %s. Skipping age cleanup.",
                retention_days,
            )

        try:
            from api.core.models.preferences import Preferences

            max_storage_mb = Preferences.load().activity_capture.max_storage_mb
            if max_storage_mb and max_storage_mb > 0:
                logger.info(
                    "Running managed capture storage trim to %s MB.",
                    max_storage_mb,
                )
                await self._run_lifecycle_deletion("trim", max_storage_mb=max_storage_mb)
        except Exception as exc:
            logger.error("Managed capture storage trim failed: %s", exc, exc_info=True)