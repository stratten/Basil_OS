#!/usr/bin/env python3
"""
Test script for capture file cleanup functionality.
This script creates test capture files and tests the automatic cleanup system.
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any

# Add the Basil source to Python path
script_dir = Path(__file__).parent
# Go up to tests/, then services/, then capture_management_tests/, then up 3 more to get to Basil root
basil_root = script_dir.parent.parent.parent
basil_src = basil_root / "src"
sys.path.insert(0, str(basil_src))

from api.core.services.capture_management_service import CaptureManagementService
from api.core.services.file_storage_service import StorageService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("capture_cleanup_test")

class CaptureCleanupTester:
    def __init__(self, development_mode: bool = True):
        self.development_mode = development_mode
        self.storage_service = StorageService(development_mode=development_mode)
        self.capture_service = CaptureManagementService(storage_service=self.storage_service)
        
        # Test file directories
        self.structured_dir = self.storage_service.base_path / "data" / "captures"
        self.temp_dir = self.storage_service.base_path / "data" / "temp"
        
        logger.info(f"Initialized tester with development_mode={development_mode}")
        logger.info(f"Structured captures dir: {self.structured_dir}")
        logger.info(f"Temp captures dir: {self.temp_dir}")

    def create_test_directories(self):
        """Create the necessary test directories."""
        self.structured_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Created test directories")

    def create_test_files(self):
        """Create test capture files of different ages."""
        logger.info("Creating test capture files...")
        
        # Create structured captures (date-based directories)
        test_dates = [
            datetime.now().date(),  # Today
            (datetime.now() - timedelta(days=1)).date(),  # 1 day ago
            (datetime.now() - timedelta(days=3)).date(),  # 3 days ago
            (datetime.now() - timedelta(days=7)).date(),  # 7 days ago
            (datetime.now() - timedelta(days=15)).date(), # 15 days ago
            (datetime.now() - timedelta(days=35)).date(), # 35 days ago
        ]
        
        files_created = 0
        for test_date in test_dates:
            date_dir = self.structured_dir / test_date.strftime("%Y-%m-%d")
            date_dir.mkdir(exist_ok=True)
            
            # Create 2-3 test files per date
            for i in range(2):
                filename = f"capture_{test_date.strftime('%Y%m%d')}_{140000 + i}_TestApp.png"
                test_file = date_dir / filename
                
                # Create a small test file
                test_content = f"Test capture file for {test_date} - file {i+1}".encode()
                test_file.write_bytes(test_content)
                files_created += 1
                
        logger.info(f"Created {files_created} structured test files")
        
        # Create flat temp captures (in temp directory)
        temp_files_created = 0
        for test_date in test_dates:
            for i in range(2):
                filename = f"capture_{test_date.strftime('%Y%m%d')}_{150000 + i}_TempApp.png"
                test_file = self.temp_dir / filename
                
                # Create a small test file
                test_content = f"Temp test capture file for {test_date} - file {i+1}".encode()
                test_file.write_bytes(test_content)
                temp_files_created += 1
                
        logger.info(f"Created {temp_files_created} temp test files")
        logger.info(f"Total test files created: {files_created + temp_files_created}")

    async def test_stats(self):
        """Test the capture statistics functionality."""
        logger.info("=== Testing Capture Statistics ===")
        stats = await self.capture_service.get_capture_stats()
        
        logger.info(f"Total files: {stats['total_files']}")
        logger.info(f"Total size: {stats['total_size_bytes']} bytes")
        logger.info(f"Files last 7 days: {stats['files_last_7_days']}")
        logger.info(f"Files last 30 days: {stats['files_last_30_days']}")
        
        return stats

    async def test_cleanup_settings(self):
        """Test cleanup settings functionality."""
        logger.info("=== Testing Cleanup Settings ===")
        
        # Get current settings
        current_settings = await self.capture_service.get_cleanup_settings()
        logger.info(f"Current settings: {current_settings}")
        
        # Update settings for testing
        test_settings = await self.capture_service.update_cleanup_settings(
            auto_cleanup_enabled=True,
            retention_days=10  # Keep files for 10 days for testing
        )
        logger.info(f"Updated settings: {test_settings}")
        
        return test_settings

    async def test_manual_cleanup(self, days: int = 10):
        """Test manual cleanup functionality."""
        logger.info(f"=== Testing Manual Cleanup (older than {days} days) ===")
        
        # Get stats before cleanup
        stats_before = await self.capture_service.get_capture_stats()
        logger.info(f"Files before cleanup: {stats_before['total_files']}")
        
        # Run cleanup
        result = await self.capture_service.clear_captures_older_than(days)
        logger.info(f"Cleanup result: {result}")
        
        # Get stats after cleanup
        stats_after = await self.capture_service.get_capture_stats()
        logger.info(f"Files after cleanup: {stats_after['total_files']}")
        
        return result

    async def test_automatic_cleanup(self):
        """Test the automatic cleanup functionality."""
        logger.info("=== Testing Automatic Cleanup ===")
        
        # Get stats before cleanup
        stats_before = await self.capture_service.get_capture_stats()
        logger.info(f"Files before automatic cleanup: {stats_before['total_files']}")
        
        # Run automatic cleanup
        await self.capture_service.run_automatic_cleanup()
        
        # Get stats after cleanup
        stats_after = await self.capture_service.get_capture_stats()
        logger.info(f"Files after automatic cleanup: {stats_after['total_files']}")
        
        files_removed = stats_before['total_files'] - stats_after['total_files']
        logger.info(f"Files removed by automatic cleanup: {files_removed}")

    def cleanup_test_files(self):
        """Remove all test files and directories."""
        logger.info("=== Cleaning up test files ===")
        
        import shutil
        
        if self.structured_dir.exists():
            shutil.rmtree(self.structured_dir)
            logger.info(f"Removed structured test directory: {self.structured_dir}")
            
        # Only remove test files from temp dir, not the whole directory
        if self.temp_dir.exists():
            for file in self.temp_dir.glob("capture_*.png"):
                try:
                    file.unlink()
                    logger.info(f"Removed temp test file: {file.name}")
                except Exception as e:
                    logger.error(f"Failed to remove {file}: {e}")

    async def run_full_test(self):
        """Run the complete test suite."""
        logger.info("🧪 Starting Capture File Cleanup Test Suite")
        logger.info("=" * 60)
        
        try:
            # Setup
            self.create_test_directories()
            self.create_test_files()
            
            # Test stats
            await self.test_stats()
            
            # Test settings
            await self.test_cleanup_settings()
            
            # Test manual cleanup
            await self.test_manual_cleanup(days=14)  # Remove files older than 14 days
            
            # Create more test files
            logger.info("Creating additional test files for automatic cleanup test...")
            self.create_test_files()
            
            # Test automatic cleanup
            await self.test_automatic_cleanup()
            
            logger.info("✅ All tests completed successfully!")
            
        except Exception as e:
            logger.error(f"❌ Test failed: {e}", exc_info=True)
        finally:
            # Clean up
            self.cleanup_test_files()
            logger.info("🧹 Test cleanup completed")

async def main():
    """Main test function."""
    if len(sys.argv) > 1 and sys.argv[1] == "--production":
        logger.warning("Running in PRODUCTION mode - this will affect real capture files!")
        development_mode = False
    else:
        logger.info("Running in DEVELOPMENT mode (safe testing)")
        development_mode = True
    
    tester = CaptureCleanupTester(development_mode=development_mode)
    await tester.run_full_test()

if __name__ == "__main__":
    asyncio.run(main()) 