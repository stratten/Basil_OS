# Capture Management Tests

This directory tests Activity Capture and the automated capture-file cleanup service.

## Pytest suites

These files run under pytest, and CI collects them with the rest of `backend/src/tests`:

- `test_activity_capture_compaction.py`, `test_activity_capture_data_lifecycle.py`, `test_activity_capture_frequency_config.py`, and `test_activity_capture_policy.py` cover ingestion-time compaction, cascade deletion, the capture-frequency setting, and the exclusion policy.
- `test_activity_processing_progress.py`, `test_activity_processing_retry_loop.py`, `test_activity_processing_run_policy.py`, `test_activity_processing_service_hybrid_init.py`, and `test_activity_processing_stage_coordinator.py` cover processing progress and run control, the retry loop, run-policy resolution, SQLite initialization, and the OCR and analysis stage coordinator.
- `test_automatic_capture_activity_counts.py`, `test_capture_file_stats.py`, and `test_work_context.py` cover the durable activity counts, capture-file statistics, and work-context extraction.

From the repository root:

```bash
PYTHONPATH=.:backend/src poetry run pytest backend/src/tests/services/capture_management_tests -q
```

## Manual cleanup scripts

Two files are scripts you run by hand, not pytest suites:

- `test_capture_cleanup.py` exercises `CaptureManagementService` directly: statistics, cleanup settings, manual cleanup, and automatic cleanup. It creates capture files of different ages (structured `YYYY-MM-DD/` directories and flat temporary files) under test directories and removes them afterward. Running it with `--production` targets real capture files, so use that flag only when you intend to.
- `test_capture_cleanup_api.py` calls the capture-management HTTP endpoints and needs a running backend. It asks for confirmation before any destructive step.

Run them from this directory with `python test_capture_cleanup.py` and `python test_capture_cleanup_api.py`.
