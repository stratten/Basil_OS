#!/usr/bin/env python3
"""
Test script for capture file cleanup API endpoints.
This script tests the HTTP API endpoints for capture management.
"""

import asyncio
import aiohttp
import json
import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("capture_cleanup_api_test")

class CaptureCleanupAPITester:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def test_health(self) -> bool:
        """Test if the backend is running."""
        try:
            async with self.session.get(f"{self.base_url}/health") as response:
                if response.status == 200:
                    logger.info("✅ Backend is running")
                    return True
                else:
                    logger.error(f"❌ Backend health check failed: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"❌ Backend is not accessible: {e}")
            return False

    async def test_capture_stats(self) -> Dict[str, Any]:
        """Test the capture statistics endpoint."""
        logger.info("=== Testing Capture Statistics API ===")
        try:
            async with self.session.get(f"{self.base_url}/api/v1/capture-management/stats") as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"✅ Stats retrieved: {data}")
                    return data
                else:
                    error_text = await response.text()
                    logger.error(f"❌ Stats request failed: {response.status} - {error_text}")
                    return {}
        except Exception as e:
            logger.error(f"❌ Stats request error: {e}")
            return {}

    async def test_cleanup_settings(self) -> Dict[str, Any]:
        """Test the cleanup settings endpoints."""
        logger.info("=== Testing Cleanup Settings API ===")
        
        # Get current settings
        try:
            async with self.session.get(f"{self.base_url}/api/v1/capture-management/settings") as response:
                if response.status == 200:
                    current_settings = await response.json()
                    logger.info(f"✅ Current settings: {current_settings}")
                else:
                    error_text = await response.text()
                    logger.error(f"❌ Get settings failed: {response.status} - {error_text}")
                    return {}
        except Exception as e:
            logger.error(f"❌ Get settings error: {e}")
            return {}

        # Update settings
        try:
            test_settings = {
                "auto_cleanup_enabled": True,
                "retention_days": 7
            }
            async with self.session.post(
                f"{self.base_url}/api/v1/capture-management/settings",
                json=test_settings
            ) as response:
                if response.status == 200:
                    updated_settings = await response.json()
                    logger.info(f"✅ Settings updated: {updated_settings}")
                    return updated_settings
                else:
                    error_text = await response.text()
                    logger.error(f"❌ Update settings failed: {response.status} - {error_text}")
                    return current_settings
        except Exception as e:
            logger.error(f"❌ Update settings error: {e}")
            return current_settings

    async def test_manual_cleanup(self, days: int = 30) -> Dict[str, Any]:
        """Test the manual cleanup endpoint."""
        logger.info(f"=== Testing Manual Cleanup API (older than {days} days) ===")
        try:
            async with self.session.post(f"{self.base_url}/api/v1/capture-management/clear-older-than/{days}") as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"✅ Manual cleanup result: {data}")
                    return data
                else:
                    error_text = await response.text()
                    logger.error(f"❌ Manual cleanup failed: {response.status} - {error_text}")
                    return {}
        except Exception as e:
            logger.error(f"❌ Manual cleanup error: {e}")
            return {}

    async def test_automatic_cleanup(self) -> Dict[str, Any]:
        """Test the automatic cleanup endpoint."""
        logger.info("=== Testing Automatic Cleanup API ===")
        try:
            async with self.session.post(f"{self.base_url}/api/v1/capture-management/test-automatic-cleanup") as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"✅ Automatic cleanup result: {data}")
                    return data
                else:
                    error_text = await response.text()
                    logger.error(f"❌ Automatic cleanup failed: {response.status} - {error_text}")
                    return {}
        except Exception as e:
            logger.error(f"❌ Automatic cleanup error: {e}")
            return {}

    async def test_clear_all(self) -> Dict[str, Any]:
        """Test the clear all captures endpoint."""
        logger.info("=== Testing Clear All Captures API ===")
        
        # Ask for confirmation since this is destructive
        user_input = input("This will delete ALL capture files. Type 'yes' to continue: ")
        if user_input.lower() != 'yes':
            logger.info("Skipping clear all test")
            return {}
        
        try:
            async with self.session.post(f"{self.base_url}/api/v1/capture-management/clear-all") as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"✅ Clear all result: {data}")
                    return data
                else:
                    error_text = await response.text()
                    logger.error(f"❌ Clear all failed: {response.status} - {error_text}")
                    return {}
        except Exception as e:
            logger.error(f"❌ Clear all error: {e}")
            return {}

    async def run_full_test(self):
        """Run the complete API test suite."""
        logger.info("🧪 Starting Capture File Cleanup API Test Suite")
        logger.info("=" * 60)
        
        # Check if backend is running
        if not await self.test_health():
            logger.error("❌ Backend is not running. Please start the backend first.")
            return
        
        try:
            # Test stats
            await self.test_capture_stats()
            await asyncio.sleep(1)
            
            # Test settings
            await self.test_cleanup_settings()
            await asyncio.sleep(1)
            
            # Test automatic cleanup
            await self.test_automatic_cleanup()
            await asyncio.sleep(1)
            
            # Test manual cleanup
            await self.test_manual_cleanup(days=60)  # Only clean very old files
            await asyncio.sleep(1)
            
            # Test clear all (optional and destructive)
            await self.test_clear_all()
            
            logger.info("✅ All API tests completed!")
            
        except Exception as e:
            logger.error(f"❌ API test failed: {e}", exc_info=True)

async def main():
    """Main test function."""
    logger.info("Starting Capture Cleanup API Tests")
    
    async with CaptureCleanupAPITester() as tester:
        await tester.run_full_test()

if __name__ == "__main__":
    asyncio.run(main()) 