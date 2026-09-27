#!/usr/bin/env python3
"""
Component Testing Script for Basil

Tests individual components in isolation to quickly identify issues
without needing full app builds.
"""

import asyncio
import argparse
import sys
import os
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, List

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

async def test_model_download():
    """Test model download functionality in isolation"""
    print("🧪 Testing Model Download Component...")
    
    try:
        from api.core.models.model_downloader import ModelDownloader
        from api.core.config.config import Config
        
        # Use temporary directory for testing
        with tempfile.TemporaryDirectory() as temp_dir:
            test_config = {
                'models': {
                    'storage_path': temp_dir,
                    'huggingface_cache_dir': os.path.join(temp_dir, 'hf_cache')
                }
            }
            
            # Mock config
            config = Config()
            config.data.update(test_config)
            
            downloader = ModelDownloader(config)
            
            # Test small model for quick verification
            test_model = "microsoft/DialoGPT-small"  # ~300MB model
            
            print(f"📦 Testing download of {test_model}")
            print(f"📂 Download location: {temp_dir}")
            
            # Test download with progress tracking
            async def progress_callback(downloaded: int, total: int, message: str):
                if total > 0:
                    percent = (downloaded / total) * 100
                    print(f"  📊 Progress: {percent:.1f}% - {message}")
            
            success = await downloader.download_model(
                test_model,
                progress_callback=progress_callback
            )
            
            if success:
                print("✅ Model download test PASSED")
                return True
            else:
                print("❌ Model download test FAILED")
                return False
                
    except Exception as e:
        print(f"❌ Model download test ERROR: {e}")
        return False

async def test_permissions():
    """Test macOS permission checking"""
    print("🧪 Testing Permission Components...")
    
    try:
        import subprocess
        
        # Test TCC database access
        result = subprocess.run([
            'sqlite3', 
            '/Library/Application Support/com.apple.TCC/TCC.db',
            'SELECT service, client FROM access WHERE client LIKE "%basil%";'
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ TCC database access: WORKING")
            if result.stdout.strip():
                print(f"  📋 Found permissions: {result.stdout.strip()}")
            else:
                print("  📋 No Basil permissions found (clean state)")
        else:
            print("❌ TCC database access: FAILED")
            print(f"  Error: {result.stderr}")
            
        # Test file system permissions
        test_paths = [
            "~/.basil/models",
            "~/Desktop/BasilDebugLogs",
            "~/Documents",
            "/tmp"
        ]
        
        for path in test_paths:
            expanded_path = os.path.expanduser(path)
            try:
                os.makedirs(expanded_path, exist_ok=True)
                test_file = os.path.join(expanded_path, "test_permissions.txt")
                with open(test_file, 'w') as f:
                    f.write("test")
                os.remove(test_file)
                print(f"✅ Write access to {path}: WORKING")
            except Exception as e:
                print(f"❌ Write access to {path}: FAILED - {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ Permission test ERROR: {e}")
        return False

async def test_backend_connectivity():
    """Test backend server startup and API connectivity"""
    print("🧪 Testing Backend Connectivity...")
    
    try:
        import aiohttp
        import json
        from api.core.config.config import Config
        
        # Test config loading
        config = Config()
        print(f"✅ Config loaded: {config.get('server.host')}:{config.get('server.port')}")
        
        # Test basic HTTP connectivity
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get('http://127.0.0.1:8000/health', timeout=5) as response:
                    if response.status == 200:
                        print("✅ Backend health check: WORKING")
                        return True
                    else:
                        print(f"❌ Backend health check: HTTP {response.status}")
                        return False
            except aiohttp.ClientError as e:
                print(f"❌ Backend connectivity: FAILED - {e}")
                return False
                
    except Exception as e:
        print(f"❌ Backend test ERROR: {e}")
        return False

async def test_hotkey_detection():
    """Test hotkey detection capabilities"""
    print("🧪 Testing Hotkey Detection...")
    
    try:
        # Test if we can detect key events (requires permissions)
        import subprocess
        
        # Test input monitoring permission
        result = subprocess.run([
            'sqlite3',
            '/Library/Application Support/com.apple.TCC/TCC.db',
            'SELECT service FROM access WHERE service="kTCCServiceListenEvent" AND client LIKE "%basil%";'
        ], capture_output=True, text=True)
        
        if "kTCCServiceListenEvent" in result.stdout:
            print("✅ Input Monitoring permission: GRANTED")
        else:
            print("❌ Input Monitoring permission: NOT GRANTED")
        
        # Test accessibility permission
        result = subprocess.run([
            'sqlite3',
            '/Library/Application Support/com.apple.TCC/TCC.db',
            'SELECT service FROM access WHERE service="kTCCServiceAccessibility" AND client LIKE "%basil%";'
        ], capture_output=True, text=True)
        
        if "kTCCServiceAccessibility" in result.stdout:
            print("✅ Accessibility permission: GRANTED")
        else:
            print("❌ Accessibility permission: NOT GRANTED")
        
        return True
        
    except Exception as e:
        print(f"❌ Hotkey test ERROR: {e}")
        return False

async def run_all_tests():
    """Run all component tests"""
    print("🚀 Starting Basil Component Tests\n")
    
    tests = [
        ("Permissions", test_permissions),
        ("Backend Connectivity", test_backend_connectivity),
        ("Hotkey Detection", test_hotkey_detection),
        ("Model Download", test_model_download),
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        print(f"\n{'='*50}")
        try:
            results[test_name] = await test_func()
        except Exception as e:
            print(f"❌ {test_name} test crashed: {e}")
            results[test_name] = False
        print(f"{'='*50}")
    
    # Summary
    print(f"\n📊 TEST SUMMARY")
    print("=" * 30)
    passed = sum(1 for r in results.values() if r)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name}: {status}")
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed!")
        return 0
    else:
        print("⚠️ Some tests failed - check logs above")
        return 1

def main():
    parser = argparse.ArgumentParser(description="Test Basil components in isolation")
    parser.add_argument("--test", choices=["permissions", "backend", "hotkeys", "models", "all"], 
                       default="all", help="Which test to run")
    
    args = parser.parse_args()
    
    if args.test == "all":
        return asyncio.run(run_all_tests())
    elif args.test == "permissions":
        return asyncio.run(test_permissions())
    elif args.test == "backend":
        return asyncio.run(test_backend_connectivity())
    elif args.test == "hotkeys":
        return asyncio.run(test_hotkey_detection())
    elif args.test == "models":
        return asyncio.run(test_model_download())

if __name__ == "__main__":
    sys.exit(main()) 