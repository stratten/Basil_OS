# Capture Management Tests

This directory contains comprehensive tests for the automated capture file cleanup functionality in Basil.

## Test Files

### 1. `test_capture_cleanup.py`
**Service-Level Tests**
- Tests the `CaptureManagementService` directly
- Creates test capture files with various ages
- Tests statistics calculation, settings management, and cleanup operations
- Safe to run in development mode (uses test directories)

### 2. `test_capture_cleanup_api.py`
**API Endpoint Tests**
- Tests all HTTP API endpoints for capture management
- Requires the backend to be running
- Tests all CRUD operations via HTTP requests
- Safe - asks for confirmation before destructive operations

### 3. `test_huey_cleanup.py`
**Scheduled Task Tests**
- Tests the Huey-based scheduled cleanup tasks
- Checks Huey consumer status and configuration
- Manually triggers scheduled cleanup functions
- Displays schedule information

### 4. `run_tests.py`
**Test Runner**
- Runs all tests in sequence or individually
- Provides summary of test results
- Easy instruction-line interface

## Running the Tests

### Prerequisites
1. Make sure you're in the Basil root directory
2. For API tests: Ensure the backend is running (`poetry run python src/basil_api.py`)
3. For Huey tests: Ensure Huey consumer is running

### Run All Tests
```bash
cd Basil/tests/services/capture_management_tests
python run_tests.py
```

### Run Individual Tests
```bash
# Service-level tests only
python run_tests.py service

# API endpoint tests only  
python run_tests.py api

# Huey scheduled task tests only
python run_tests.py huey
```

### Run Tests Directly
```bash
# Individual test files can also be run directly
python test_capture_cleanup.py
python test_capture_cleanup_api.py
python test_huey_cleanup.py
```

## Test Modes

### Development Mode (Default)
- Uses `~/.basil/` directory for test files
- Safe for testing without affecting production data
- Creates and cleans up test files automatically

### Production Mode
- **WARNING**: Affects real capture files
- Use with extreme caution
- Run with `--production` flag: `python test_capture_cleanup.py --production`

## What the Tests Cover

### Functionality Tested
- ✅ Capture file statistics calculation
- ✅ Cleanup settings management (get/update)
- ✅ Manual cleanup (clear all, clear older than X days)
- ✅ Automatic cleanup based on settings
- ✅ Huey scheduled task execution
- ✅ API endpoint responses and error handling
- ✅ File system operations and error handling

### Test Scenarios
- Files with different ages (today, 1 day, 3 days, 7 days, 15 days, 35 days old)
- Both structured captures (`YYYY-MM-DD/` directories) and flat temp files
- Various retention periods (7, 10, 14, 30 days)
- Enable/disable automatic cleanup
- Error conditions and edge cases

## Expected Output

### Successful Test Run
```
🧪 Starting Capture File Cleanup Test Suite
============================================================
Created test directories
Creating test capture files...
Created 12 structured test files
Created 12 temp test files
Total test files created: 24

=== Testing Capture Statistics ===
Total files: 24
Total size: 1440 bytes
Files last 7 days: 8
Files last 30 days: 20

=== Testing Cleanup Settings ===
Current settings: {'auto_cleanup_enabled': False, 'retention_days': 30}
Updated settings: {'auto_cleanup_enabled': True, 'retention_days': 10}

=== Testing Manual Cleanup (older than 14 days) ===
Files before cleanup: 24
Cleanup result: {'status': 'success', 'message': 'Captures older than 14 days cleared.', 'files_deleted': 4, 'space_freed_bytes': 240}
Files after cleanup: 20

...

✅ All tests completed successfully!
```

## Troubleshooting

### Common Issues
1. **Import errors**: Make sure you're running from the correct directory
2. **Backend not running**: Start the backend before running API tests
3. **Permission errors**: Ensure write permissions to test directories
4. **Huey not running**: Start Huey consumer before running Huey tests

### Debug Mode
Add `--debug` flag or set logging level to DEBUG for more verbose output.

## Integration with CI/CD
These tests can be integrated into automated testing pipelines:
```bash
# Example CI instruction
cd Basil/tests/services/capture_management_tests && python run_tests.py
``` 