#!/usr/bin/env python3

"""
Test File System Service Integration

Tests the complete file system service integration with agent workflows.
Validates the primary use case: "Take this document and draft a reply to this email"

Usage:
    cd Basil/tests/services/agent_processing_tests
    poetry run python test_file_system_integration.py
"""

import asyncio
import logging
import sys
import os
import tempfile
import json

# Add the project root to the Python path
project_root = os.path.join(os.path.dirname(__file__), '../../../')
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))

from api.services.agent_processing.tools.direct_application_interactions.file_system.file_system_service import FileSystemService

import pytest

pytestmark = pytest.mark.manual

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_service_initialization():
    """Test file system service initialization."""
    print("\n🔧 Testing Service Initialization")
    print("=" * 50)
    
    service = FileSystemService()
    
    # Test initialization
    success = await service.initialize()
    
    if success:
        print("✅ File System Service initialized successfully")
        print(f"📁 Default search paths: {len(service.default_search_paths)}")
        for path in service.default_search_paths:
            print(f"   📁 {path}")
        return True
    else:
        print("❌ Service initialization failed")
        return False


async def test_agent_workflow_simulation():
    """Test the complete agent workflow simulation."""
    print("\n🎯 Testing Agent Workflow: 'Take this document and draft a reply'")
    print("=" * 70)
    
    service = FileSystemService()
    await service.initialize()
    
    # Create a realistic test document
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, 
                                   dir=os.path.expanduser("~/Desktop")) as temp_file:
        document_content = """# Q4 Budget Proposal

## Executive Summary
Our Q4 budget proposal includes strategic investments in technology infrastructure and team expansion to support projected 25% growth.

## Key Budget Items
- Technology Infrastructure: $150,000
- Team Expansion: $200,000  
- Marketing Initiatives: $75,000
- Operational Expenses: $100,000

## Expected ROI
We anticipate a 35% return on investment by Q2 2025, driven by increased productivity and market expansion.

## Next Steps
1. Approval from executive team
2. Department-level budget allocation
3. Implementation timeline finalization

---
*Prepared by Finance Team | December 2024*
"""
        temp_file.write(document_content)
        temp_file_path = temp_file.name
    
    try:
        print(f"📄 Created test document: {os.path.basename(temp_file_path)}")
        
        # Simulate agent workflow: User says "Take the budget document and draft a reply"
        print("\n🗣️  User instruction: 'Take the budget document and draft a reply to this email'")
        
        # Step 1: Agent calls find_file_for_llm
        context = "This budget document should be used to draft a professional email reply about our Q4 financial planning and investment strategy."
        
        file_result = await service.find_file_for_llm(
            filename="budget",  # User mentioned "budget document"
            context=context,
            search_paths=[os.path.expanduser("~/Desktop")]  # Search user's desktop
        )
        
        if not file_result or not file_result.get("success"):
            print("❌ File not found in agent workflow")
            return False
        
        print("✅ Agent workflow successful!")
        print(f"📁 Found file: {file_result['file_name']}")
        print(f"📊 File size: {file_result['file_size']} bytes")
        print(f"🔤 Content encoding: {file_result['content_encoding']}")
        print(f"📝 Context for LLM: {file_result['prompt_context'][:100]}...")
        
        # Step 2: Simulate LLM processing (show what would be sent)
        print("\n🤖 LLM Integration Preview:")
        print("=" * 30)
        print("📦 Base64 content ready for Anthropic")
        print(f"📏 Content size: {len(file_result['base64_content'])} characters")
        print(f"📦 Base64 preview: {file_result['base64_content'][:100]}...")
        
        # Step 3: Show metadata available to LLM
        print("\n📋 Metadata available to LLM:")
        metadata = file_result['metadata']
        print(f"   📄 File name: {file_result['file_name']}")
        print(f"   📏 Size: {file_result['file_size']} bytes")
        print(f"   🏷️  Type: {file_result['file_type']}")
        print(f"   📅 Modified: {metadata['modified_date']}")
        print(f"   📁 Directory: {metadata['parent_directory']}")
        
        # Step 4: Simulate what the agent would do next
        print("\n🔄 Next Agent Steps:")
        print("   1. ✅ File found and prepared for LLM")
        print("   2. 🤖 Send Base64 content + context to LLM")
        print("   3. ✍️  LLM generates email reply using document content")
        print("   4. 📧 Create email draft with generated content")
        
        return True
        
    finally:
        # Clean up
        os.unlink(temp_file_path)
        print(f"\n🗑️  Cleaned up test document")


async def test_service_capabilities():
    """Test service capabilities reporting."""
    print("\n🔍 Testing Service Capabilities")
    print("=" * 50)
    
    service = FileSystemService()
    capabilities = service.get_service_capabilities()
    
    print("✅ Service capabilities retrieved")
    print(f"📝 Description: {capabilities['description']}")
    print(f"🎯 Primary use case: {capabilities['primary_use_case']}")
    print(f"📚 Methods available: {len(capabilities['methods'])}")
    
    # Show key methods
    for method_name, method_info in capabilities['methods'].items():
        print(f"   🔧 {method_name}: {method_info['signature']}")
    
    print(f"📁 Default search paths: {len(capabilities['default_search_paths'])}")
    print(f"🏷️  Supported file types: {', '.join(capabilities['supported_file_types'])}")
    print(f"🔤 Encoding options: {', '.join(capabilities['encoding_options'])}")
    
    return True


async def test_error_handling():
    """Test error handling for missing files."""
    print("\n⚠️  Testing Error Handling")
    print("=" * 50)
    
    service = FileSystemService()
    await service.initialize()
    
    # Test with non-existent file
    result = await service.find_file_for_llm(
        filename="nonexistent_file_12345",
        context="This file should not exist"
    )
    
    if result and not result.get("success"):
        print("✅ Error handling working correctly")
        print(f"❌ Expected error: {result.get('error', 'No error message')}")
        print(f"📄 File requested: {result.get('file_name', 'Unknown')}")
        return True
    else:
        print("❌ Error handling not working as expected")
        return False


async def test_multiple_file_handling():
    """Test handling of multiple matching files."""
    print("\n📊 Testing Multiple File Handling")
    print("=" * 50)
    
    service = FileSystemService()
    await service.initialize()
    
    # Search for common file pattern that likely has multiple matches
    search_result = await service.search_files({
        'name_contains': 'test',
        'search_paths': [project_root]
    })
    
    if search_result.get("success") and search_result.get("total_found", 0) > 0:
        print(f"✅ Multiple file search successful")
        print(f"📊 Found {search_result['total_found']} files")
        print(f"⏱️  Search duration: {search_result['search_duration']:.2f}s")
        print(f"🔍 Search method: {search_result['search_method']}")
        
        # Show first few files
        files = search_result['files']
        for i, file_info in enumerate(files[:3]):
            print(f"   📄 {i+1}. {file_info['name']} ({file_info['size']} bytes)")
        
        if len(files) > 3:
            print(f"   ... and {len(files) - 3} more files")
        
        return True
    else:
        print("⚠️  No test files found or search failed")
        return False


async def run_integration_tests():
    """Run all file system integration tests."""
    print("🚀 File System Service Integration Test Suite")
    print("=" * 70)
    
    test_results = []
    
    try:
        # Test 1: Service initialization
        result1 = await test_service_initialization()
        test_results.append(("Service Initialization", result1))
        
        # Test 2: Agent workflow simulation
        result2 = await test_agent_workflow_simulation()
        test_results.append(("Agent Workflow Simulation", result2))
        
        # Test 3: Service capabilities
        result3 = await test_service_capabilities()
        test_results.append(("Service Capabilities", result3))
        
        # Test 4: Error handling
        result4 = await test_error_handling()
        test_results.append(("Error Handling", result4))
        
        # Test 5: Multiple file handling
        result5 = await test_multiple_file_handling()
        test_results.append(("Multiple File Handling", result5))
        
        # Summary
        print("\n🏆 Integration Test Results Summary")
        print("=" * 50)
        
        passed = 0
        for test_name, result in test_results:
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"{status} {test_name}")
            if result:
                passed += 1
        
        print(f"\n📊 Overall: {passed}/{len(test_results)} tests passed")
        
        if passed == len(test_results):
            print("🎉 All file system integration tests passed!")
            print("\n🔥 Ready for agent integration:")
            print("   • File search and retrieval working")
            print("   • Base64 encoding for Anthropic ready")
            print("   • 'Take this document' workflow implemented")
            print("   • Error handling robust")
            print("   • Service capabilities discoverable")
            return True
        else:
            print("⚠️  Some tests failed - check logs for details")
            return False
        
    except Exception as e:
        print(f"❌ Test suite error: {e}")
        logger.error(f"Integration test suite error: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    try:
        success = asyncio.run(run_integration_tests())
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test execution failed: {e}")
        sys.exit(1) 