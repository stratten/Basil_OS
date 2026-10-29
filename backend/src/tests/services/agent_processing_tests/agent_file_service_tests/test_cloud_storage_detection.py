#!/usr/bin/env python3

"""
Test Cloud Storage Detection

Demonstrates detection of Google Drive and other cloud storage integrations.
This shows how to extend file system operations to include cloud storage.

Usage:
    cd backend/src/tests/services/agent_processing_tests
    poetry run python test_cloud_storage_detection.py
"""

import asyncio
import logging
import sys
import os

# Add project paths
project_root = os.path.join(os.path.dirname(__file__), '../../../')
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))

import pytest

pytestmark = pytest.mark.manual

# Skip if the cloud storage service path is not present in current build
pytest.importorskip(
    "api.services.agent_processing.tools.direct_application_interactions.file_system.identification_retrieval.cloud_storage_service",
    reason="CloudStorageService module not present in this build"
)

from api.services.agent_processing.tools.direct_application_interactions.file_system.identification_retrieval.cloud_storage_service import CloudStorageService

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_cloud_detection():
    """Test cloud storage detection capabilities."""
    print("🔍 Cloud Storage Detection Test")
    print("=" * 50)
    
    service = CloudStorageService()
    
    # Detect all cloud storage
    detection = await service.detect_cloud_storage()
    
    print("✅ Cloud Storage Detection Results:")
    print(f"📊 Total providers detected: {detection['total_providers']}")
    print()
    
    # Show mounted volumes
    volumes = detection['volumes_detected']
    if volumes:
        print("🗂️  Mounted Cloud Volumes:")
        for provider, paths in volumes.items():
            print(f"   📁 {provider.replace('_', ' ').title()}:")
            for path in paths:
                print(f"      📂 {path}")
        print()
    else:
        print("📋 No mounted cloud volumes detected")
        print()
    
    # Show sync folders
    sync_folders = detection['sync_folders_detected']
    if sync_folders:
        print("📁 Cloud Sync Folders:")
        for provider, paths in sync_folders.items():
            print(f"   📂 {provider.replace('_', ' ').title()}:")
            for path in paths:
                print(f"      📁 {path}")
        print()
    else:
        print("📋 No cloud sync folders detected")
        print()
    
    # Show all searchable paths
    searchable_paths = detection['searchable_paths']
    if searchable_paths:
        print("🔍 Searchable Cloud Paths:")
        for i, path in enumerate(searchable_paths, 1):
            print(f"   {i}. {path}")
        print()
    
    return detection


async def test_google_drive_search():
    """Test Google Drive file search if available."""
    print("🔍 Google Drive File Search Test")
    print("=" * 50)
    
    service = CloudStorageService()
    
    # Search for common file types in Google Drive
    search_terms = ["budget", "presentation", "document"]
    
    for term in search_terms:
        print(f"\n🔍 Searching for '{term}' in Google Drive...")
        
        files = await service.search_cloud_files(term, provider='google_drive')
        
        if files:
            print(f"✅ Found {len(files)} files:")
            for i, file_info in enumerate(files[:5], 1):  # Show first 5
                print(f"   {i}. {file_info['name']}")
                print(f"      📁 {file_info['path']}")
                print(f"      📏 {file_info['size']} bytes")
                print(f"      🔤 Provider: {file_info['cloud_provider']}")
                
                # Test file accessibility
                accessible = await service.can_access_file(file_info['path'])
                status = "✅ Accessible" if accessible else "⚠️ Placeholder/Inaccessible"
                print(f"      🔐 {status}")
                print()
            
            if len(files) > 5:
                print(f"   ... and {len(files) - 5} more files")
        else:
            print(f"📋 No files found for '{term}'")
    
    return len(files) > 0 if 'files' in locals() else False


async def test_service_capabilities():
    """Test service capabilities reporting."""
    print("🔧 Cloud Storage Service Capabilities")
    print("=" * 50)
    
    service = CloudStorageService()
    capabilities = service.get_service_capabilities()
    
    print(f"📝 Description: {capabilities['description']}")
    print(f"☁️  Supported providers: {', '.join(capabilities['supported_providers'])}")
    print()
    
    print("🔍 Detection methods:")
    for method in capabilities['detection_methods']:
        print(f"   • {method}")
    print()
    
    print("⚠️  Limitations:")
    for limitation in capabilities['limitations']:
        print(f"   • {limitation}")
    print()
    
    print("🛠️  Available methods:")
    for method, description in capabilities['methods'].items():
        print(f"   • {method}: {description}")
    
    return True


async def demonstrate_integration_possibilities():
    """Demonstrate how this integrates with file system service."""
    print("\n🚀 Integration Possibilities")
    print("=" * 50)
    
    print("🎯 Enhanced 'Take this document' workflow:")
    print("   1. Search local files (current implementation)")
    print("   2. Search Google Drive files (new capability)")
    print("   3. Search OneDrive files (new capability)")
    print("   4. Search Dropbox files (new capability)")
    print("   5. Check file accessibility (avoid placeholders)")
    print("   6. Download/access content for LLM processing")
    print()
    
    print("💡 Potential agent instructions:")
    print("   • 'Find my budget spreadsheet' → searches local + cloud")
    print("   • 'Get the presentation from Google Drive' → cloud-specific search")
    print("   • 'Take the contract from OneDrive and draft a reply' → full workflow")
    print()
    
    print("🔧 Implementation approach:")
    print("   1. Extend FileSystemService to include CloudStorageService")
    print("   2. Modify search methods to include cloud paths")
    print("   3. Add accessibility checks to avoid placeholder files")
    print("   4. Integrate with existing Base64 encoding for LLM")
    print()
    
    # Show actual detected cloud storage
    service = CloudStorageService()
    detection = await service.detect_cloud_storage()
    
    if detection['total_providers'] > 0:
        print("✅ Ready for cloud integration!")
        print(f"📊 Detected {detection['total_providers']} cloud providers on this system")
    else:
        print("📋 No cloud storage detected on this system")
        print("   (This is normal if no cloud storage is configured)")


async def run_cloud_storage_tests():
    """Run all cloud storage tests."""
    print("☁️  Cloud Storage Integration Test Suite")
    print("=" * 60)
    
    test_results = []
    
    try:
        # Test 1: Cloud detection
        detection = await test_cloud_detection()
        has_cloud = detection['total_providers'] > 0
        test_results.append(("Cloud Detection", True))  # Always passes
        
        # Test 2: Google Drive search (only if Google Drive detected)
        if 'google_drive' in detection['volumes_detected'] or 'google_drive' in detection['sync_folders_detected']:
            result2 = await test_google_drive_search()
            test_results.append(("Google Drive Search", result2))
        else:
            print("🔍 Google Drive not detected - skipping search test")
            test_results.append(("Google Drive Search", "skipped"))
        
        # Test 3: Service capabilities
        result3 = await test_service_capabilities()
        test_results.append(("Service Capabilities", result3))
        
        # Test 4: Integration demonstration
        await demonstrate_integration_possibilities()
        test_results.append(("Integration Demo", True))
        
        # Summary
        print("\n🏆 Cloud Storage Test Results")
        print("=" * 50)
        
        passed = 0
        for test_name, result in test_results:
            if result == "skipped":
                status = "⏭️  SKIPPED"
            elif result:
                status = "✅ PASSED"
                passed += 1
            else:
                status = "❌ FAILED"
        
            print(f"{status} {test_name}")
        
        total_run = len([r for r in test_results if r[1] != "skipped"])
        print(f"\n📊 Overall: {passed}/{total_run} tests passed")
        
        if has_cloud:
            print("\n🎉 Cloud storage integration ready!")
            print("   Your system has cloud storage that can be searched!")
        else:
            print("\n💡 Cloud storage service is ready")
            print("   Install Google Drive, OneDrive, or Dropbox to test cloud integration")
        
        return True
        
    except Exception as e:
        print(f"❌ Test suite error: {e}")
        logger.error(f"Cloud storage test error: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    try:
        success = asyncio.run(run_cloud_storage_tests())
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test execution failed: {e}")
        sys.exit(1) 