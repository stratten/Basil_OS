"""
Test Anthropic File Handler

Tests the AnthropicFileHandler class for file validation, formatting, and API integration.
Updated to match official Anthropic API specification (2025).
"""

import unittest
import base64
import json
from pathlib import Path
from datetime import datetime

# Import the handler
from api.services.agent_processing.tools.direct_application_interactions.file_system.anthropic_file_handler import AnthropicFileHandler

# Import file models for testing LLMFileRequest integration
from api.services.agent_processing.tools.direct_application_interactions.file_system.file_models import (
    FileType, ContentEncoding, FileContent, FileMetadata, LLMFileRequest
)


class TestAnthropicFileHandler(unittest.TestCase):
    """Test suite for AnthropicFileHandler."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.handler = AnthropicFileHandler()
        
        # Create sample file data for testing
        self.sample_pdf_content = base64.b64encode(b"Sample PDF content").decode('utf-8')
        self.sample_image_content = base64.b64encode(b"Sample image content").decode('utf-8')
        
        self.valid_pdf_data = {
            'file_name': 'test_document.pdf',
            'file_type': 'pdf',
            'file_size': 1024,  # 1KB
            'base64_content': self.sample_pdf_content,
            'content_encoding': 'base64'
        }
        
        self.valid_image_data = {
            'file_name': 'test_image.png',
            'file_type': 'png',
            'file_size': 2048,  # 2KB
            'base64_content': self.sample_image_content,
            'content_encoding': 'base64'
        }
        
        self.large_document_data = {
            'file_name': 'large_document.pdf',
            'file_type': 'pdf',
            'file_size': 35 * 1024 * 1024,  # 35MB (over the 32MB request limit)
            'base64_content': self.sample_pdf_content,
            'content_encoding': 'base64'
        }
        
        self.unsupported_file_data = {
            'file_name': 'test_file.xyz',
            'file_type': 'xyz',
            'file_size': 1024,
            'base64_content': self.sample_pdf_content,
            'content_encoding': 'base64'
        }

    def test_validate_valid_pdf(self):
        """Test validation of a valid PDF file."""
        result = self.handler.validate_file_content(self.valid_pdf_data)
        
        self.assertTrue(result['valid'])
        self.assertIsNone(result['error'])
        self.assertEqual(result['mime_type'], 'application/pdf')
        
    def test_validate_valid_image(self):
        """Test validation of a valid image file."""
        result = self.handler.validate_file_content(self.valid_image_data)
        
        self.assertTrue(result['valid'])
        self.assertIsNone(result['error'])
        self.assertEqual(result['mime_type'], 'image/png')
        
    def test_validate_large_document(self):
        """Test validation of an oversized document."""
        result = self.handler.validate_file_content(self.large_document_data)
        
        self.assertFalse(result['valid'])
        self.assertIn('File too large', result['error'])
        self.assertIn('32MB', result['error'])
        
    def test_validate_unsupported_type(self):
        """Test validation of an unsupported file type."""
        result = self.handler.validate_file_content(self.unsupported_file_data)
        
        self.assertFalse(result['valid'])
        self.assertIn('Unsupported file type', result['error'])
        self.assertIsNone(result['mime_type'])
        
    def test_validate_missing_content(self):
        """Test validation with missing base64 content."""
        invalid_data = self.valid_pdf_data.copy()
        invalid_data['base64_content'] = ''
        
        result = self.handler.validate_file_content(invalid_data)
        
        self.assertFalse(result['valid'])
        self.assertIn('No base64 content provided', result['error'])
        
    def test_format_for_anthropic_api_document(self):
        """Test formatting a document for Anthropic API."""
        result = self.handler.format_for_anthropic_api(self.valid_pdf_data)
        
        expected_structure = {
            'type': 'document',
            'source': {
                'type': 'base64',
                'media_type': 'application/pdf',
                'data': self.sample_pdf_content
            }
        }
        
        self.assertEqual(result, expected_structure)
        
    def test_format_for_anthropic_api_image(self):
        """Test formatting an image for Anthropic API."""
        result = self.handler.format_for_anthropic_api(self.valid_image_data)
        
        expected_structure = {
            'type': 'image',
            'source': {
                'type': 'base64',
                'media_type': 'image/png',
                'data': self.sample_image_content
            }
        }
        
        self.assertEqual(result, expected_structure)
        
    def test_format_invalid_file_raises_error(self):
        """Test that formatting an invalid file raises an error."""
        with self.assertRaises(ValueError) as context:
            self.handler.format_for_anthropic_api(self.unsupported_file_data)
        
        self.assertIn('File validation failed', str(context.exception))
        
    def test_create_mixed_content_message(self):
        """Test creating a mixed content message with text and files."""
        text_prompt = "Please analyze these files"
        file_contents = [self.valid_pdf_data, self.valid_image_data]
        
        result = self.handler.create_mixed_content_message(text_prompt, file_contents)
        
        # Should have 3 blocks: text, document, image.
        self.assertEqual(len(result), 3)
        
        # Check text block
        self.assertEqual(result[0]['type'], 'text')
        self.assertEqual(result[0]['text'], text_prompt)
        
        # Check first document block (PDF)
        self.assertEqual(result[1]['type'], 'document')
        self.assertEqual(result[1]['source']['media_type'], 'application/pdf')
        
        # Check second image block.
        self.assertEqual(result[2]['type'], 'image')
        self.assertEqual(result[2]['source']['media_type'], 'image/png')
        
    def test_create_mixed_content_with_invalid_file(self):
        """Test mixed content creation with some invalid files."""
        text_prompt = "Analyze what you can"
        file_contents = [self.valid_pdf_data, self.unsupported_file_data]
        
        result = self.handler.create_mixed_content_message(text_prompt, file_contents)
        
        # Should have 2 blocks: text and the valid document (invalid file skipped)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['type'], 'text')
        self.assertEqual(result[1]['type'], 'document')
        
    def test_create_mixed_content_text_only(self):
        """Test mixed content creation with text only."""
        text_prompt = "Hello world"
        file_contents = []
        
        result = self.handler.create_mixed_content_message(text_prompt, file_contents)
        
        # Should have 1 text block
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['type'], 'text')
        self.assertEqual(result[0]['text'], text_prompt)
        
    def test_get_supported_file_types(self):
        """Test getting supported file types."""
        result = self.handler.get_supported_file_types()
        
        self.assertIsInstance(result, list)
        self.assertIn('pdf', result)
        self.assertIn('png', result)
        self.assertIn('jpg', result)
        self.assertIn('txt', result)
        
    def test_get_api_limits(self):
        """Test getting API limits."""
        result = self.handler.get_api_limits()
        
        self.assertEqual(result['max_request_size_mb'], 32)
        self.assertEqual(result['max_request_size_bytes'], 32 * 1024 * 1024)
        self.assertEqual(result['max_pages_per_request'], 100)
        self.assertEqual(result['content_block_type'], 'document')
        self.assertIn('supported_file_types', result)
        self.assertIn('notes', result)
        
    def test_validate_request_size(self):
        """Test request size validation."""
        text_content = "This is a test prompt"
        file_contents = [self.valid_pdf_data, self.valid_image_data]
        
        result = self.handler.validate_request_size(file_contents, text_content)
        
        self.assertTrue(result['valid'])
        self.assertGreater(result['total_size'], len(text_content.encode('utf-8')))
        self.assertEqual(len(result['files_that_fit']), 2)
        self.assertEqual(len(result['files_excluded']), 0)
        
    def test_validate_request_size_with_large_files(self):
        """Test request size validation with files that exceed limits."""
        text_content = "Test"
        file_contents = [self.valid_pdf_data, self.large_document_data]  # One normal, one too large
        
        result = self.handler.validate_request_size(file_contents, text_content)
        
        self.assertFalse(result['valid'])
        self.assertIsNotNone(result['error'])
        self.assertEqual(len(result['files_that_fit']), 1)  # Only the small file fits
        self.assertEqual(len(result['files_excluded']), 1)  # Large file excluded
        
    def test_extract_file_info_from_llm_request(self):
        """Test extracting file info from LLMFileRequest."""
        # Create test metadata
        metadata = FileMetadata(
            path="/test/document.pdf",
            name="document.pdf",
            size=1024,
            created_date=datetime.now(),
            modified_date=datetime.now(),
            accessed_date=datetime.now(),
            file_type=FileType.PDF,
            extension="pdf",
            mime_type="application/pdf"
        )
        
        # Create test file content
        file_content = FileContent(
            file_path="/test/document.pdf",
            content_type=ContentEncoding.BASE64,
            raw_content=b"test content",
            base64_content=self.sample_pdf_content,
            metadata=metadata
        )
        
        # Create LLM request
        llm_request = LLMFileRequest(
            file_path="/test/document.pdf",
            file_content=file_content,
            prompt_context="Test context",
            encoding_preference=ContentEncoding.BASE64
        )
        
        # Extract file info
        result = self.handler.extract_file_info_from_llm_request(llm_request)
        
        # Verify extracted info
        self.assertEqual(result['file_name'], 'document.pdf')
        self.assertEqual(result['file_type'], 'pdf')
        self.assertEqual(result['file_size'], 1024)
        self.assertEqual(result['base64_content'], self.sample_pdf_content)
        self.assertEqual(result['file_path'], '/test/document.pdf')
        
    def test_request_size_tracking_in_mixed_content(self):
        """Test that mixed content creation properly tracks request size."""
        # Create multiple small files
        small_files = []
        for i in range(5):
            small_files.append({
                'file_name': f'small_file_{i}.txt',
                'file_type': 'txt',
                'file_size': 1024,  # 1KB each
                'base64_content': base64.b64encode(f"Content {i}".encode()).decode(),
                'content_encoding': 'base64'
            })
        
        result = self.handler.create_mixed_content_message("Test prompt", small_files)
        
        # Should include text + all 5 files (total well under 32MB)
        self.assertEqual(len(result), 6)  # 1 prompt + 5 text files
        self.assertEqual(result[0]['type'], 'text')
        for i in range(1, 6):
            self.assertEqual(result[i]['type'], 'text')


def run_anthropic_file_handler_tests():
    """Run all tests and report results."""
    print("🧪 Running Anthropic File Handler Tests (Updated for Official API)")
    print("=" * 60)
    
    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAnthropicFileHandler)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Summary
    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print("✅ All tests passed! AnthropicFileHandler matches official API spec.")
    else:
        print(f"❌ {len(result.failures)} test(s) failed")
        print(f"💥 {len(result.errors)} test(s) had errors")
        
        # Print details of failures/errors
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
    success = run_anthropic_file_handler_tests()
    if not success:
        exit(1) 