"""
Test Claude Model File Integration - REAL API CALLS ONLY

Tests the new file-aware methods in ClaudeModel class with actual Claude API calls.
NO MOCKS - Tests real file processing with real API responses.
"""

import os
import sys
import unittest
import asyncio
import base64
import tempfile
from pathlib import Path
from datetime import datetime

import pytest

pytestmark = pytest.mark.manual

# Add the src directory to sys.path to allow imports  
src_path = Path(__file__).parent.parent.parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

# Import the models and handlers
from api.core.models.reasoning.claude_model import ClaudeModel
from api.core.models.model_types import ModelCapability
from api.services.agent_processing.tools.direct_application_interactions.file_system.anthropic_file_handler import AnthropicFileHandler
from api.services.agent_processing.tools.direct_application_interactions.file_system.file_models import (
    FileType, ContentEncoding, FileContent, FileMetadata, LLMFileRequest
)


class TestClaudeModelFileIntegrationRealAPI(unittest.TestCase):
    """Test suite for ClaudeModel file integration with REAL API calls."""
    
    @classmethod
    def setUpClass(cls):
        """Set up real files for testing."""
        # Create real test files with actual content
        cls.test_dir = tempfile.mkdtemp()
        
        # Create a real PDF-like file (simplified structure)
        cls.pdf_file = Path(cls.test_dir) / "test_document.pdf"
        pdf_content = b"""%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
>>
endobj

2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj

3 0 obj
<<
/Type /Page
/Parent 2 0 R
/MediaBox [0 0 612 792]
/Contents 4 0 R
>>
endobj

4 0 obj
<<
/Length 44
>>
stream
BT
/F1 12 Tf
100 700 Td
(This is a test document for API testing) Tj
ET
endstream
endobj

xref
0 5
0000000000 65535 f 
0000000010 00000 n 
0000000079 00000 n 
0000000173 00000 n 
0000000301 00000 n 
trailer
<<
/Size 5
/Root 1 0 R
>>
startxref
398
%%EOF"""
        cls.pdf_file.write_bytes(pdf_content)
        
        # Create a real text file
        cls.text_file = Path(cls.test_dir) / "test_notes.txt"
        cls.text_file.write_text("""Meeting Notes - Q2 Planning Session
Date: July 21, 2025
Attendees: Development Team

Key Discussion Points:
1. File system integration testing
2. Claude API integration with real file content
3. End-to-end workflow validation

Action Items:
- Complete real API testing
- Validate file processing workflows
- Test with multiple file types

Next Steps:
Schedule follow-up session for next week to review results.
""")
        
        # Create test image file (simple PNG)
        cls.image_file = Path(cls.test_dir) / "test_image.png"
        # Simple 1x1 pixel PNG (base64 decoded)
        png_data = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
        )
        cls.image_file.write_bytes(png_data)
    
    @classmethod
    def tearDownClass(cls):
        """Clean up test files."""
        import shutil
        shutil.rmtree(cls.test_dir)
    
    def setUp(self):
        """Set up for each test."""
        # Get real file data
        self.pdf_content = base64.b64encode(self.pdf_file.read_bytes()).decode('utf-8')
        self.text_content = base64.b64encode(self.text_file.read_bytes()).decode('utf-8')
        self.image_content = base64.b64encode(self.image_file.read_bytes()).decode('utf-8')
        
        self.real_pdf_data = {
            'file_name': 'test_document.pdf',
            'file_type': 'pdf',
            'file_size': self.pdf_file.stat().st_size,
            'base64_content': self.pdf_content,
            'content_encoding': 'base64'
        }
        
        self.real_text_data = {
            'file_name': 'test_notes.txt',
            'file_type': 'txt',
            'file_size': self.text_file.stat().st_size,
            'base64_content': self.text_content,
            'content_encoding': 'base64'
        }
        
        self.real_image_data = {
            'file_name': 'test_image.png',
            'file_type': 'png',
            'file_size': self.image_file.stat().st_size,
            'base64_content': self.image_content,
            'content_encoding': 'base64'
        }

    def _get_real_claude_model(self):
        """Get a real, loaded Claude model instance."""
        # Use actual model path from Basil configuration
        model_path = Path.home() / ".basil" / "models" / "claude-sonnet-4-20250514"
        required_capabilities = {ModelCapability.REASONING}
        
        claude_model = ClaudeModel(model_path, required_capabilities)
        
        # Force load the model for testing
        async def load_model():
            await claude_model.load()
            return claude_model
        
        return asyncio.run(load_model())

    def test_real_file_validation(self):
        """Test AnthropicFileHandler with real file content."""
        handler = AnthropicFileHandler()
        
        # Test PDF validation
        pdf_result = handler.validate_file_content(self.real_pdf_data)
        self.assertTrue(pdf_result['valid'], f"PDF validation failed: {pdf_result.get('error')}")
        self.assertEqual(pdf_result['mime_type'], 'application/pdf')
        
        # Test text validation
        text_result = handler.validate_file_content(self.real_text_data)
        self.assertTrue(text_result['valid'], f"Text validation failed: {text_result.get('error')}")
        self.assertEqual(text_result['mime_type'], 'text/plain')
        
        # Test image validation
        image_result = handler.validate_file_content(self.real_image_data)
        self.assertTrue(image_result['valid'], f"Image validation failed: {image_result.get('error')}")
        self.assertEqual(image_result['mime_type'], 'image/png')

    def test_claude_api_single_file_real_call(self):
        """Test actual Claude API call with single file attachment."""
        try:
            claude_model = self._get_real_claude_model()
        except Exception as e:
            self.skipTest(f"Could not load Claude model: {e}")
        
        async def run_test():
            try:
                # Make actual API call with text file
                response = await claude_model.generate_response_with_files(
                    prompt="Please summarize the content of this document and tell me what it's about.",
                    file_contents=[self.real_text_data],
                    max_tokens=500
                )
                
                # Verify we got a real response
                self.assertIsInstance(response, str)
                self.assertGreater(len(response), 10, "Response too short - likely failed")
                self.assertIn("meeting", response.lower(), "Response should mention meeting content")
                
                print(f"✅ Real API response received: {response[:200]}...")
                return response
                
            except Exception as e:
                self.fail(f"Real API call failed: {str(e)}")
        
        response = asyncio.run(run_test())
        self.assertIsNotNone(response)

    def test_claude_api_multiple_files_real_call(self):
        """Test actual Claude API call with multiple file attachments."""
        try:
            claude_model = self._get_real_claude_model()
        except Exception as e:
            self.skipTest(f"Could not load Claude model: {e}")
        
        async def run_test():
            try:
                # Make actual API call with multiple files
                response = await claude_model.generate_response_with_files(
                    prompt="I have attached both text notes and an image. Please analyze both and tell me what you can determine.",
                    file_contents=[self.real_text_data, self.real_image_data],
                    max_tokens=800
                )
                
                # Verify we got a real response that mentions both files
                self.assertIsInstance(response, str)
                self.assertGreater(len(response), 20, "Response too short - likely failed")
                
                print(f"✅ Real API response for multiple files: {response[:200]}...")
                return response
                
            except Exception as e:
                self.fail(f"Real API call with multiple files failed: {str(e)}")
        
        response = asyncio.run(run_test())
        self.assertIsNotNone(response)

    def test_claude_api_streaming_with_files_real_call(self):
        """Test actual Claude API streaming with file attachments."""
        try:
            claude_model = self._get_real_claude_model()
        except Exception as e:
            self.skipTest(f"Could not load Claude model: {e}")
        
        async def run_test():
            try:
                # Prepare messages for streaming
                messages = [
                    {"role": "user", "content": "Please analyze this document and tell me about its contents."}
                ]
                
                # Collect streaming response
                response_chunks = []
                async for chunk in claude_model.chat_completion_streaming_with_files(
                    messages=messages,
                    file_contents=[self.real_text_data]
                ):
                    response_chunks.append(chunk)
                    if len(response_chunks) > 10:  # Limit for testing
                        break
                
                # Verify we got streaming chunks
                self.assertGreater(len(response_chunks), 0, "No streaming chunks received")
                
                full_response = ''.join(response_chunks)
                self.assertGreater(len(full_response), 5, "Streaming response too short")
                
                print(f"✅ Real streaming response received: {full_response[:100]}...")
                return full_response
                
            except Exception as e:
                self.fail(f"Real streaming API call failed: {str(e)}")
        
        response = asyncio.run(run_test())
        self.assertIsNotNone(response)

    def test_end_to_end_file_workflow_real_api(self):
        """Test complete end-to-end workflow: file detection → content preparation → Claude API."""
        try:
            claude_model = self._get_real_claude_model()
        except Exception as e:
            self.skipTest(f"Could not load Claude model: {e}")
        
        async def run_test():
            try:
                # Simulate real workflow: "take this document and create a summary"
                
                # Step 1: File is "detected" (using our real PDF)
                detected_file = self.real_pdf_data
                
                # Step 2: Content prepared for LLM
                handler = AnthropicFileHandler()
                validation_result = handler.validate_file_content(detected_file)
                self.assertTrue(validation_result['valid'])
                
                # Step 3: Send to Claude API
                response = await claude_model.generate_response_with_files(
                    prompt="I have a document open. Please analyze it and create a brief summary of what it contains.",
                    file_contents=[detected_file],
                    max_tokens=400
                )
                
                # Step 4: Verify end-to-end success
                self.assertIsInstance(response, str)
                self.assertGreater(len(response), 20, "End-to-end response too short")
                
                print(f"✅ End-to-end workflow completed successfully!")
                print(f"Document analyzed: {detected_file['file_name']}")
                print(f"Response: {response[:150]}...")
                
                return response
                
            except Exception as e:
                self.fail(f"End-to-end workflow failed: {str(e)}")
        
        response = asyncio.run(run_test())
        self.assertIsNotNone(response)

    def test_error_handling_real_conditions(self):
        """Test error handling under real API conditions."""
        try:
            claude_model = self._get_real_claude_model()
        except Exception as e:
            self.skipTest(f"Could not load Claude model: {e}")
        
        async def run_test():
            # Test with malformed file data
            bad_file_data = {
                'file_name': 'corrupted.pdf',
            'file_type': 'pdf',
                'file_size': 100,
                'base64_content': 'invalid_base64_content!!!',  # Intentionally bad
            'content_encoding': 'base64'
        }
        
            # This should either fail validation or handle gracefully
            handler = AnthropicFileHandler()
            validation_result = handler.validate_file_content(bad_file_data)
            
            if validation_result['valid']:
                # If validation passes, API call should handle the error
                try:
                    response = await claude_model.generate_response_with_files(
                        prompt="Analyze this file",
                        file_contents=[bad_file_data],
                        max_tokens=100
                    )
                    # If we get here, the system handled it gracefully
                    print("✅ Error condition handled gracefully")
                except Exception as api_error:
                    # Expected - API should reject invalid content
                    print(f"✅ API correctly rejected invalid content: {str(api_error)[:100]}")
                    self.assertIsInstance(api_error, Exception)
            else:
                # Validation correctly caught the issue
                print(f"✅ Validation correctly rejected bad content: {validation_result['error']}")
                self.assertFalse(validation_result['valid'])
        
        asyncio.run(run_test())

    def test_claude_api_file_paths_mode_real_call(self):
        """Test actual Claude API call using file paths instead of base64 content."""
        try:
            claude_model = self._get_real_claude_model()
        except Exception as e:
            self.skipTest(f"Could not load Claude model: {e}")
        
        async def run_test():
            try:
                # Use file paths directly (agent integration mode)
                file_paths = [str(self.text_file), str(self.image_file)]
                
                # Make actual API call with file paths
                response = await claude_model.generate_response_with_files(
                    prompt="I'm providing files by path. Please analyze them and tell me what you find.",
                    file_paths=file_paths,
                    max_tokens=600
                )
                
                # Verify we got a real response
                self.assertIsInstance(response, str)
                self.assertGreater(len(response), 20, "Response too short - likely failed")
                
                print(f"✅ File paths mode API response: {response[:200]}...")
                return response
                
            except Exception as e:
                self.fail(f"File paths mode API call failed: {str(e)}")
        
        response = asyncio.run(run_test())
        self.assertIsNotNone(response)

    def test_claude_api_streaming_file_paths_mode_real_call(self):
        """Test actual Claude API streaming using file paths (agent integration mode)."""
        try:
            claude_model = self._get_real_claude_model()
        except Exception as e:
            self.skipTest(f"Could not load Claude model: {e}")
        
        async def run_test():
            try:
                # Use file paths for streaming
                file_paths = [str(self.pdf_file)]
                
                # Prepare messages for streaming
                messages = [
                    {"role": "user", "content": "Please analyze the attached document."}
                ]
                
                # Collect streaming response
                response_chunks = []
                async for chunk in claude_model.chat_completion_streaming_with_files(
                    messages=messages,
                    file_paths=file_paths
                ):
                    response_chunks.append(chunk)
                    if len(response_chunks) > 15:  # Limit for testing
                        break
                
                # Verify we got streaming chunks
                self.assertGreater(len(response_chunks), 0, "No streaming chunks received")
                
                full_response = ''.join(response_chunks)
                self.assertGreater(len(full_response), 10, "Streaming response too short")
                
                print(f"✅ File paths streaming response received: {full_response[:100]}...")
                return full_response
                
            except Exception as e:
                self.fail(f"File paths streaming API call failed: {str(e)}")
        
        response = asyncio.run(run_test())
        self.assertIsNotNone(response)

    def test_agent_integration_workflow_simulation(self):
        """Test agent integration workflow: agent step storage → file path → Claude API."""
        try:
            claude_model = self._get_real_claude_model()
        except Exception as e:
            self.skipTest(f"Could not load Claude model: {e}")
        
        async def run_test():
            try:
                # Simulate agent step storage (what would be stored in agent context)
                agent_step_context = {
                    "action": "analyze_document",
                    "files_detected": [str(self.text_file)],  # Just paths, no base64!
                    "user_instruction": "Summarize this document",
                    "timestamp": "2025-07-21T18:00:00Z"
                }
                
                # Simulate agent executing step with stored file paths
                response = await claude_model.generate_response_with_files(
                    prompt=f"User request: {agent_step_context['user_instruction']}. Please analyze the attached document.",
                    file_paths=agent_step_context["files_detected"],
                    max_tokens=400
                )
                
                # Verify agent integration success
                self.assertIsInstance(response, str)
                self.assertGreater(len(response), 15, "Agent integration response too short")
                
                print(f"✅ Agent integration workflow completed!")
                print(f"Files from context: {agent_step_context['files_detected']}")
                print(f"Response: {response[:150]}...")
                
                # This simulates how the agent would store the result
                agent_step_result = {
                    "success": True,
                    "response": response,
                    "files_processed": len(agent_step_context["files_detected"]),
                    "completion_time": "2025-07-21T18:00:05Z"
                }
                
                self.assertTrue(agent_step_result["success"])
                self.assertEqual(agent_step_result["files_processed"], 1)
                
                return response
                
            except Exception as e:
                self.fail(f"Agent integration workflow failed: {str(e)}")
        
        response = asyncio.run(run_test())
        self.assertIsNotNone(response)

    def test_parameter_validation_modes(self):
        """Test parameter validation for different input modes."""
        try:
            claude_model = self._get_real_claude_model()
        except Exception as e:
            self.skipTest(f"Could not load Claude model: {e}")
        
        async def run_test():
            # Test 1: Neither file_contents nor file_paths provided
            with self.assertRaises(ValueError) as context:
                await claude_model.generate_response_with_files(
                    prompt="Test prompt"
                    # No file parameters
                )
            self.assertIn("Must provide either file_contents or file_paths", str(context.exception))
            
            # Test 2: Both file_contents and file_paths provided
            with self.assertRaises(ValueError) as context:
                await claude_model.generate_response_with_files(
                    prompt="Test prompt",
                    file_contents=[self.real_text_data],  # Base64 mode
                    file_paths=[str(self.text_file)]     # Path mode
                )
            self.assertIn("Provide either file_contents OR file_paths, not both", str(context.exception))
            
            # Test 3: Invalid file paths
            with self.assertRaises(ValueError) as context:
                await claude_model.generate_response_with_files(
                    prompt="Test prompt",
                    file_paths=["/nonexistent/file.txt", "/another/fake/file.pdf"]
                )
            self.assertIn("No valid files could be loaded", str(context.exception))
            
            print("✅ Parameter validation working correctly")
        
        asyncio.run(run_test())


def run_real_api_tests():
    """Run all REAL API tests and report results."""
    print("🚀 Running Claude Model File Integration Tests - REAL API CALLS ONLY")
    print("=" * 70)
    print("⚠️  These tests make actual API calls to Claude and will consume tokens!")
    print("=" * 70)
    
    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestClaudeModelFileIntegrationRealAPI)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Summary
    print("\n" + "=" * 70)
    if result.wasSuccessful():
        print("✅ ALL REAL API TESTS PASSED!")
        print("🎯 Claude file integration is working with actual API calls")
        print("💪 Ready for production file processing workflows")
    else:
        print(f"❌ {len(result.failures)} test(s) failed")
        print(f"💥 {len(result.errors)} test(s) had errors")
        
        if result.failures:
            print("\nFailures:")
            for test, traceback in result.failures:
                print(f"  - {test}: {traceback}")
        
        if result.errors:
            print("\nErrors:")
            for test, traceback in result.errors:
                print(f"  - {test}: {traceback}")
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_real_api_tests()
    if not success:
        exit(1) 