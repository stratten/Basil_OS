#!/usr/bin/env python3

"""
Test script for File Retrieval Service

Tests the core file system integration functionality:
1. File search by name using Spotlight
2. File content reading and encoding
3. Base64 preparation for LLM integration
4. End-to-end "find and prepare" workflow

Usage:
    cd Basil/tests/services/agent_processing_tests
    poetry run python test_file_retrieval_service.py
"""

import asyncio
import logging
import sys
import os
import tempfile

# Add the project root to the Python path
project_root = os.path.join(os.path.dirname(__file__), '../../../')
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))

import pytest

pytest.importorskip(
    "api.services.agent_processing.tools.direct_application_interactions.file_system.identification_retrieval.file_retrieval_service",
    reason="FileRetrievalService module not present in this build",
)
pytest.importorskip(
    "api.services.agent_processing.tools.direct_application_interactions.file_system.file_models",
    reason="file_models not present in this build",
)

from api.services.agent_processing.tools.direct_application_interactions.file_system.identification_retrieval.file_retrieval_service import FileRetrievalService
from api.services.agent_processing.tools.direct_application_interactions.file_system.file_models import ContentEncoding

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_file_search():
    """Test file search functionality."""
    print("\n🔍 Testing File Search Functionality")
    print("=" * 50)
    
    service = FileRetrievalService()
    
    # Test 1: Search for common files
    print("\n📋 Test 1: Search for Python files")
    search_result = await service.search_files_by_name("test_", [project_root])
    
    print(f"✅ Found {len(search_result.files_found)} files in {search_result.search_duration:.2f}s")
    print(f"🔍 Search method: {search_result.search_method}")
    
    # Show first few results
    for i, file_meta in enumerate(search_result.files_found[:3]):
        print(f"   📄 {i+1}. {file_meta.name} ({file_meta.size} bytes)")
        print(f"      📁 {file_meta.parent_directory}")
        print(f"      🏷️  Type: {file_meta.file_type.value}, Extension: {file_meta.extension}")
    
    if len(search_result.files_found) > 3:
        print(f"   ... and {len(search_result.files_found) - 3} more files")
    
    return len(search_result.files_found) > 0


@pytest.mark.asyncio
async def test_file_content_reading():
    """Test file content reading with different encodings."""
    print("\n📖 Testing File Content Reading")
    print("=" * 50)
    
    service = FileRetrievalService()
    
    # Create a temporary test file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as temp_file:
        test_content = "This is a test file for file retrieval service validation.\nLine 2: Special characters: àáâãäå\nLine 3: Numbers: 12345"
        temp_file.write(test_content)
        temp_file_path = temp_file.name
    
    try:
        print(f"📄 Created test file: {temp_file_path}")
        
        # Test 1: UTF-8 text reading
        print("\n📋 Test 1: UTF-8 Text Reading")
        utf8_content = await service.read_file_content(temp_file_path, ContentEncoding.UTF8_TEXT)
        
        if utf8_content:
            print(f"✅ UTF-8 reading successful")
            print(f"📊 Content size: {utf8_content.content_size} bytes")
            print(f"🔤 Content type: {utf8_content.content_type.value}")
            print(f"📝 Content preview: {utf8_content.raw_content[:100]}...")
        else:
            print("❌ UTF-8 reading failed")
            return False
        
        # Test 2: Base64 encoding
        print("\n📋 Test 2: Base64 Encoding")
        base64_content = await service.read_file_content(temp_file_path, ContentEncoding.BASE64)
        
        if base64_content:
            print(f"✅ Base64 encoding successful")
            print(f"📊 Content size: {base64_content.content_size} bytes")
            print(f"🔤 Content type: {base64_content.content_type.value}")
            print(f"📦 Base64 preview: {base64_content.base64_content[:100]}...")
        else:
            print("❌ Base64 encoding failed")
            return False
        
        return True
        
    finally:
        # Clean up
        os.unlink(temp_file_path)
        print(f"🗑️  Cleaned up test file")


@pytest.mark.asyncio
async def test_llm_preparation():
    """Test LLM preparation workflow."""
    print("\n🤖 Testing LLM Preparation Workflow")
    print("=" * 50)
    
    service = FileRetrievalService()
    
    # Create a test file with content relevant to email workflow
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as temp_file:
        test_content = """# Project Status Report

## Completed Tasks
- Email integration with Outlook
- AppleScript automation fixes
- Draft creation validation

## Next Steps
- File system integration
- Base64 encoding for LLM requests
- Spotlight search implementation

## Notes
This document contains project updates for Q4 2024.
"""
        temp_file.write(test_content)
        temp_file_path = temp_file.name
    
    try:
        print(f"📄 Created test document: {temp_file_path}")
        
        # Test LLM preparation
        prompt_context = "This document contains project status information. Please use it to draft a professional email reply summarizing our progress."
        
        llm_request = await service.prepare_file_for_llm(
            temp_file_path, 
            prompt_context, 
            ContentEncoding.BASE64
        )
        
        if llm_request:
            print(f"✅ LLM preparation successful")
            print(f"📁 File path: {llm_request.file_path}")
            print(f"🔤 Encoding: {llm_request.encoding_preference.value}")
            print(f"📊 Content size: {llm_request.file_content.content_size} bytes")
            print(f"📝 Context: {llm_request.prompt_context[:100]}...")
            print(f"🏷️  Metadata included: {llm_request.include_metadata}")
            
            if llm_request.file_content.metadata:
                meta = llm_request.file_content.metadata
                print(f"📋 File metadata:")
                print(f"   📄 Name: {meta.name}")
                print(f"   📏 Size: {meta.size} bytes")
                print(f"   🏷️  Type: {meta.file_type.value}")
                print(f"   📅 Modified: {meta.modified_date}")
        else:
            print("❌ LLM preparation failed")
            return False
        
        return True
        
    finally:
        # Clean up
        os.unlink(temp_file_path)
        print(f"🗑️  Cleaned up test document")


@pytest.mark.asyncio
async def test_find_and_prepare_workflow():
    """Test the complete find and prepare workflow."""
    print("\n🎯 Testing Complete Find and Prepare Workflow")
    print("=" * 50)
    
    service = FileRetrievalService()
    
    # Test with actual files in the project
    print("\n📋 Test 1: Find project files")
    
    # Look for implementation plan files
    llm_request = await service.find_and_prepare_file(
        "FileSystemIntegrationImplementationPlan",
        "Use this implementation plan to draft a reply explaining our file system integration approach.",
        [project_root]
    )
    
    if llm_request:
        print(f"✅ Find and prepare workflow successful!")
        print(f"📁 Found file: {llm_request.file_content.metadata.name}")
        print(f"📊 Content size: {llm_request.file_content.content_size} bytes")
        print(f"🔤 Encoding: {llm_request.encoding_preference.value}")
        print(f"📝 Context ready for LLM processing")
        
        # Show Base64 sample (first 200 chars)
        if llm_request.file_content.base64_content:
            print(f"📦 Base64 sample: {llm_request.file_content.base64_content[:200]}...")
        
        return True
    else:
        print("⚠️  No implementation plan file found, trying alternative search...")
        
        # Alternative: Look for any Python file
        llm_request = await service.find_and_prepare_file(
            "file_retrieval_service.py",
            "Use this code file to explain our file retrieval implementation.",
            [project_root]
        )
        
        if llm_request:
            print(f"✅ Alternative search successful!")
            print(f"📁 Found file: {llm_request.file_content.metadata.name}")
            return True
        else:
            print("❌ Find and prepare workflow failed")
            return False


async def run_comprehensive_test():
    """Run all file retrieval service tests."""
    print("🚀 File Retrieval Service Test Suite")
    print("=" * 60)
    
    test_results = []
    
    try:
        # Test 1: File search
        result1 = await test_file_search()
        test_results.append(("File Search", result1))
        
        # Test 2: Content reading
        result2 = await test_file_content_reading()
        test_results.append(("Content Reading", result2))
        
        # Test 3: LLM preparation
        result3 = await test_llm_preparation()
        test_results.append(("LLM Preparation", result3))
        
        # Test 4: Complete workflow
        result4 = await test_find_and_prepare_workflow()
        test_results.append(("Find and Prepare Workflow", result4))
        
        # Summary
        print("\n🏆 Test Results Summary")
        print("=" * 50)
        
        passed = 0
        for test_name, result in test_results:
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"{status} {test_name}")
            if result:
                passed += 1
        
        print(f"\n📊 Overall: {passed}/{len(test_results)} tests passed")
        
        if passed == len(test_results):
            print("🎉 All file retrieval tests passed!")
            return True
        else:
            print("⚠️  Some tests failed - check logs for details")
            return False
        
    except Exception as e:
        print(f"❌ Test suite error: {e}")
        logger.error(f"Test suite error: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    try:
        success = asyncio.run(run_comprehensive_test())
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test execution failed: {e}")
        sys.exit(1) 