"""
Test Complete "Take This Document" Workflow

Demonstrates the end-to-end file context detection and preparation workflow.
This test validates the integration of:
1. File context detection (generic pattern-based)
2. File retrieval and preparation 
3. LLM-ready content formatting
4. Context storage for agent processing

Usage: Open a document in any application, then run this test.
"""

import asyncio
import sys
import os
import logging

# Add project root to Python path
project_root = os.path.join(os.path.dirname(__file__), '../../../..')
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))

from api.services.agent_processing.tools.direct_application_interactions.file_system.file_system_service import FileSystemService

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TakeThisDocumentWorkflowTester:
    """Test the complete 'take this document' workflow."""
    
    def __init__(self):
        self.file_service = FileSystemService()

    async def test_complete_workflow(self):
        """Test the complete workflow from detection to LLM preparation."""
        print("🚀 Testing Complete 'Take This Document' Workflow")
        print("=" * 60)
        print()
        print("📋 Instructions:")
        print("   1. Open a document file in any application")
        print("   2. Make sure the file has a clear name in the window title")
        print("   3. Run this test while that application is active")
        print()
        print("🔍 Starting workflow detection...")
        print()

        # Initialize the service
        print("📦 Initializing file system service...")
        await self.file_service.initialize()
        print("   ✅ Service initialized")
        print()

        # Test the main workflow
        print("🎯 PHASE 1: DETECTING CURRENT DOCUMENT")
        print("-" * 40)
        
        context = "Document to be used for email reply analysis"
        result = await self.file_service.detect_and_prepare_current_document(context)
        
        if not result:
            print("❌ Workflow returned None")
            return False
        
        print(f"📊 Workflow Result: {'SUCCESS' if result['success'] else 'FAILURE'}")
        print()
        
        if result["success"]:
            self._display_success_result(result)
            return True
        else:
            self._display_failure_result(result)
            return False

    def _display_success_result(self, result):
        """Display detailed success information."""
        print("✅ SUCCESS: Document detected and prepared!")
        print()
        
        # Detection information
        print("🔍 DETECTION DETAILS:")
        print(f"   Method: {result.get('detection_method', 'unknown')}")
        print(f"   Confidence: {result.get('confidence', 0):.1%}")
        print(f"   File: {result.get('file_name', 'unknown')}")
        print(f"   Path: {result.get('file_path', 'unknown')}")
        print()
        
        # Application context
        if "app_context" in result:
            app_ctx = result["app_context"]
            print("🖥️  APPLICATION CONTEXT:")
            print(f"   App: {app_ctx.get('app_name', 'unknown')}")
            print(f"   Bundle ID: {app_ctx.get('bundle_id', 'unknown')}")
            print(f"   Window: {app_ctx.get('window_title', 'unknown')}")
            print()
        
        # LLM preparation
        if "llm_request" in result:
            llm_req = result["llm_request"]
            print("🤖 LLM PREPARATION:")
            print(f"   Content Type: {llm_req.encoding_preference}")
            print(f"   Content Size: {llm_req.max_content_size:,} bytes max")
            print(f"   File Path: {llm_req.file_path}")
            
            # Show content preview
            if hasattr(llm_req, 'file_content') and llm_req.file_content:
                content = llm_req.file_content
                print(f"   Content Encoding: {content.content_type}")
                print(f"   Actual Size: {content.content_size:,} bytes")
                
                if content.content_type.name == "UTF8_TEXT" and hasattr(content, 'raw_content'):
                    preview = str(content.raw_content)[:200]
                    print(f"   Preview: {preview}...")
                elif content.content_type.name == "BASE64" and hasattr(content, 'base64_content'):
                    b64_len = len(content.base64_content) if content.base64_content else 0
                    print(f"   Base64 Length: {b64_len:,} characters")
            print()
        
        # Cloud information
        if result.get("is_cloud_file"):
            print("☁️  CLOUD FILE DETECTED:")
            print(f"   Provider: {result.get('cloud_provider', 'unknown')}")
            print()
        
        print("🎯 WORKFLOW SUMMARY:")
        print("   ✅ File successfully detected from current application")
        print("   ✅ File content retrieved and validated")
        print("   ✅ Content prepared for LLM processing")
        print("   ✅ Complete context available for agent processing")
        print()
        print("🔗 NEXT STEPS:")
        print("   → This result can be stored in agent step context")
        print("   → LLM can process the file content for email replies")
        print("   → Agent can reference app context for workflow decisions")

    def _display_failure_result(self, result):
        """Display detailed failure information."""
        print("❌ FAILURE: Could not complete workflow")
        print()
        
        print("🔍 FAILURE DETAILS:")
        print(f"   Error: {result.get('error', 'unknown error')}")
        print()
        
        # Show detection attempt if available
        if "detection_result" in result:
            detection = result["detection_result"]
            print("📱 DETECTION ATTEMPT:")
            print(f"   App: {detection.app_name}")
            print(f"   Window: {detection.window_title}")
            print(f"   Success: {detection.success}")
            if detection.error_message:
                print(f"   Error: {detection.error_message}")
            print()
        
        # Show suggestions
        if "suggestions" in result:
            print("💡 SUGGESTIONS:")
            for suggestion in result["suggestions"]:
                print(f"   • {suggestion}")
            print()
        
        print("🔧 TROUBLESHOOTING:")
        print("   • Make sure a document is open and active")
        print("   • Check that the window title contains the filename")
        print("   • Try opening a file with a clear extension (.pdf, .docx, etc.)")
        print("   • Ensure the file is accessible and readable")

    async def test_service_capabilities(self):
        """Test and display service capabilities."""
        print("🔧 SERVICE CAPABILITIES TEST")
        print("=" * 40)
        
        capabilities = self.file_service.get_service_capabilities()
        
        print(f"Service: {capabilities['service_name']} v{capabilities['version']}")
        print(f"Description: {capabilities['description']}")
        print()
        
        print("📋 Available Methods:")
        for method in capabilities['methods']:
            print(f"   • {method['name']}: {method['description']}")
            for use_case in method.get('use_cases', []):
                print(f"     - {use_case}")
        print()
        
        print("✨ Features:")
        for feature in capabilities['features']:
            print(f"   • {feature}")
        print()
        
        print(f"🎯 Detection Accuracy: {capabilities['detection_accuracy']}")
        print(f"📱 Supported Apps: {capabilities['supported_applications']}")
        print()

async def run_comprehensive_test():
    """Run all tests in sequence."""
    tester = TakeThisDocumentWorkflowTester()
    
    try:
        # Test 1: Service capabilities
        await tester.test_service_capabilities()
        
        print("\n" * 2)
        
        # Give user time to switch to a document window
        print("⏰ COUNTDOWN: Opening document window in...")
        for i in range(10, 0, -1):
            print(f"   {i} seconds - Go open a document file now!")
            await asyncio.sleep(1)
        print("   🚀 STARTING TEST NOW!")
        print()
        
        # Test 2: Complete workflow
        success = await tester.test_complete_workflow()
        
        print("\n" + "=" * 60)
        print("🏁 FINAL RESULT")
        
        if success:
            print("✅ Complete workflow test PASSED")
            print("   The 'take this document' feature is working correctly!")
        else:
            print("❌ Complete workflow test FAILED")
            print("   Check the troubleshooting suggestions above")
        
        return success
        
    except Exception as e:
        print(f"❌ Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 'Take This Document' Workflow Test Suite")
    print("=" * 50)
    print()
    
    try:
        success = asyncio.run(run_comprehensive_test())
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n⚠️ Test interrupted by user")
        exit(1) 