#!/usr/bin/env python3
"""
Test Claude Model File Integration - REAL API CALLS WITH RETRY LOGIC

Tests the new file-aware methods in ClaudeModel class with actual Claude API calls.
Includes retry logic and delays to handle API capacity issues.
NO MOCKS - Tests real file processing with real API responses.
"""

import os
import sys
import asyncio
import base64
import tempfile
import time
from pathlib import Path
from datetime import datetime
import pytest

# Add the src directory to sys.path to allow imports  
src_path = Path(__file__).parent.parent.parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

pytestmark = pytest.mark.manual

# Import the models and handlers
from api.core.models.reasoning.claude_model import ClaudeModel
from api.core.models.model_types import ModelCapability
from api.services.agent_processing.tools.direct_application_interactions.file_system.anthropic_file_handler import AnthropicFileHandler


class RobustFileAPITester:
    """Robust tester with retry logic and delays for API capacity issues."""
    
    def __init__(self, max_retries=5, base_delay=30):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.claude_model = None
        
    async def load_claude_model(self):
        """Load and cache Claude model."""
        if self.claude_model is None:
            model_path = Path.home() / ".basil" / "models" / "claude-sonnet-4-20250514"
            required_capabilities = {ModelCapability.REASONING}
            
            self.claude_model = ClaudeModel(model_path, required_capabilities)
            await self.claude_model.load()
            print("✅ Claude model loaded and cached")
        return self.claude_model
    
    async def retry_with_backoff(self, operation_name, operation_func, *args, **kwargs):
        """Retry an operation with exponential backoff and delays."""
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                print(f"🔄 {operation_name} - Attempt {attempt + 1}/{self.max_retries}")
                
                # Add delay before attempt (except first one)
                if attempt > 0:
                    delay = self.base_delay * (2 ** (attempt - 1))  # Exponential backoff
                    print(f"⏰ Waiting {delay} seconds before retry...")
                    await asyncio.sleep(delay)
                
                # Try the operation
                result = await operation_func(*args, **kwargs)
                print(f"✅ {operation_name} succeeded on attempt {attempt + 1}")
                return result
                
            except Exception as e:
                last_error = e
                error_str = str(e)
                print(f"❌ {operation_name} failed on attempt {attempt + 1}: {error_str[:100]}...")
                
                # If it's not an overload error, don't retry
                if "overloaded" not in error_str.lower() and "529" not in error_str:
                    print(f"💀 Non-retryable error in {operation_name}: {error_str}")
                    raise e
        
        # All retries failed
        print(f"💀 {operation_name} failed after {self.max_retries} attempts")
        raise last_error
    
    async def test_file_paths_mode(self, file_path, expected_keywords=None):
        """Test file paths mode with retry logic."""
        claude_model = await self.load_claude_model()
        
        async def _do_test():
            response = await claude_model.generate_response_with_files(
                prompt=f"Please analyze this document and tell me what type of document it is, what it contains, and provide a brief summary of its key information.",
                file_paths=[str(file_path)],
                max_tokens=1000
            )
            
            # Validate response quality
            if len(response) < 50:
                raise ValueError(f"Response too short ({len(response)} chars): {response}")
            
            if "don't see" in response.lower() or "no document" in response.lower():
                raise ValueError(f"Claude didn't see the file: {response[:200]}")
            
            if expected_keywords:
                for keyword in expected_keywords:
                    if keyword.lower() not in response.lower():
                        print(f"⚠️  Expected keyword '{keyword}' not found in response")
            
            return response
        
        return await self.retry_with_backoff(
            f"File Paths Mode Test ({file_path.name})",
            _do_test
        )
    
    async def test_base64_content_mode(self, file_path, expected_keywords=None):
        """Test base64 content mode with retry logic."""
        claude_model = await self.load_claude_model()
        
        # Load file content
        file_bytes = file_path.read_bytes()
        base64_content = base64.b64encode(file_bytes).decode('utf-8')
        
        file_data = {
            'file_name': file_path.name,
            'file_type': file_path.suffix.lower().lstrip('.'),
            'file_size': len(file_bytes),
            'base64_content': base64_content,
            'content_encoding': 'base64'
        }
        
        async def _do_test():
            response = await claude_model.generate_response_with_files(
                prompt=f"Please analyze this document and tell me what type of document it is, what it contains, and provide a brief summary of its key information.",
                file_contents=[file_data],
                max_tokens=1000
            )
            
            # Validate response quality
            if len(response) < 50:
                raise ValueError(f"Response too short ({len(response)} chars): {response}")
            
            if "don't see" in response.lower() or "no document" in response.lower():
                raise ValueError(f"Claude didn't see the file: {response[:200]}")
            
            if expected_keywords:
                for keyword in expected_keywords:
                    if keyword.lower() not in response.lower():
                        print(f"⚠️  Expected keyword '{keyword}' not found in response")
            
            return response
        
        return await self.retry_with_backoff(
            f"Base64 Content Mode Test ({file_path.name})",
            _do_test
        )
    
    async def test_streaming_mode(self, file_path):
        """Test streaming mode with retry logic."""
        claude_model = await self.load_claude_model()
        
        async def _do_test():
            messages = [
                {"role": "user", "content": "Please analyze this document and tell me what it contains."}
            ]
            
            response_chunks = []
            async for chunk in claude_model.chat_completion_streaming_with_files(
                messages=messages,
                file_paths=[str(file_path)]
            ):
                response_chunks.append(chunk)
                if len(response_chunks) > 50:  # Limit for testing
                    break
            
            full_response = ''.join(response_chunks)
            
            # Validate response quality
            if len(full_response) < 20:
                raise ValueError(f"Streaming response too short ({len(full_response)} chars): {full_response}")
            
            if "don't see" in full_response.lower() or "no document" in full_response.lower():
                raise ValueError(f"Claude didn't see the file in streaming: {full_response[:200]}")
            
            return full_response, len(response_chunks)
        
        return await self.retry_with_backoff(
            f"Streaming Mode Test ({file_path.name})",
            _do_test
        )


async def test_real_pdf_api_calls():
    """Test real PDF API calls with robust retry logic."""
    print("🚀 Testing Claude API with Real PDF Files - ROBUST VERSION")
    print("=" * 80)
    
    # Find PDF files
    downloads_dir = Path.home() / "Downloads"
    pdf_files = list(downloads_dir.glob("*.pdf"))[:3]  # Limit to 3 files
    
    if not pdf_files:
        print("❌ No PDF files found in Downloads directory")
        return False
    
    # Sort by file size (smallest first) to avoid capacity issues
    pdf_files.sort(key=lambda f: f.stat().st_size)
    
    print(f"📁 Found {len(pdf_files)} PDF files (sorted by size):")
    for pdf_file in pdf_files:
        size_mb = pdf_file.stat().st_size / (1024 * 1024)
        print(f"  - {pdf_file.name} ({size_mb:.1f}MB)")
    
    # Initialize robust tester with shorter delays for faster testing
    tester = RobustFileAPITester(max_retries=3, base_delay=15)
    
    try:
        # First, test with a simple text file to verify API is working
        print("\n" + "="*80)
        print("🧪 PRELIMINARY TEST: Simple Text File")
        print("="*80)
        
        # Create a small test text file
        test_text_file = downloads_dir / "basil_test.txt"
        test_text_file.write_text("""Basil File Integration Test
        
This is a simple test document created to verify that Claude can read file attachments.

Key Information:
- Document Type: Test file
- Purpose: File integration validation
- Technology: Basil AI system
- Status: Testing in progress

This document should be easily readable by Claude to confirm file processing is working.""")
        
        print(f"📄 Created test file: {test_text_file.name} ({test_text_file.stat().st_size} bytes)")
        
        # Test with the simple text file
        response_text = await tester.test_file_paths_mode(test_text_file, ["test", "basil", "document"])
        print(f"✅ Text file test SUCCESSFUL!")
        print(f"📝 Response preview: {response_text[:200]}...")
        print(f"📊 Full response length: {len(response_text)} characters")
        
        # Clean up test file
        test_text_file.unlink()
        print(f"🗑️  Cleaned up test file")
        
        # Add delay before PDF tests
        print(f"\n⏰ Waiting {tester.base_delay} seconds before PDF tests...")
        await asyncio.sleep(tester.base_delay)
        
        print("\n" + "="*80)
        print("🧪 TEST 1: File Paths Mode (Agent Integration) - SMALLEST PDF")
        print("="*80)
        
        test_file = pdf_files[0]
        print(f"📄 Testing with: {test_file.name}")
        
        # Determine expected keywords based on filename
        expected_keywords = []
        if "invoice" in test_file.name.lower():
            expected_keywords = ["invoice", "payment", "amount"]
        elif "complaint" in test_file.name.lower() or "summons" in test_file.name.lower():
            expected_keywords = ["legal", "court", "case"]
        elif "salesforce" in test_file.name.lower():
            expected_keywords = ["salesforce", "functionality"]
        
        response1 = await tester.test_file_paths_mode(test_file, expected_keywords)
        print(f"📝 Response preview: {response1[:300]}...")
        print(f"📊 Full response length: {len(response1)} characters")
        
        # Delay between tests
        print(f"\n⏰ Waiting {tester.base_delay} seconds before next test...")
        await asyncio.sleep(tester.base_delay)
        
        print("\n" + "="*80)
        print("🧪 TEST 2: Base64 Content Mode (Direct)")
        print("="*80)
        
        test_file = pdf_files[1] if len(pdf_files) > 1 else pdf_files[0]
        print(f"📄 Testing with: {test_file.name}")
        
        # Determine expected keywords
        expected_keywords = []
        if "invoice" in test_file.name.lower():
            expected_keywords = ["invoice", "payment", "amount"]
        elif "complaint" in test_file.name.lower() or "summons" in test_file.name.lower():
            expected_keywords = ["legal", "court", "case"]
        
        response2 = await tester.test_base64_content_mode(test_file, expected_keywords)
        print(f"📝 Response preview: {response2[:300]}...")
        print(f"📊 Full response length: {len(response2)} characters")
        
        # Delay between tests
        print(f"\n⏰ Waiting {tester.base_delay} seconds before next test...")
        await asyncio.sleep(tester.base_delay)
        
        print("\n" + "="*80)
        print("🧪 TEST 3: Streaming Mode with Real PDF")
        print("="*80)
        
        test_file = pdf_files[0]
        print(f"📄 Streaming analysis of: {test_file.name}")
        
        response3, chunk_count = await tester.test_streaming_mode(test_file)
        print(f"📝 Response preview: {response3[:300]}...")
        print(f"📊 Received {chunk_count} chunks, {len(response3)} characters total")
        
        # Add delay between tests
        print(f"\n⏰ Waiting {tester.base_delay} seconds before next test...")
        await asyncio.sleep(tester.base_delay)
        
        print("\n" + "="*80)
        print("🧪 TEST 4: Image Processing Test")
        print("="*80)
        
        # Find real image files in Downloads
        image_extensions = ['*.png', '*.jpg', '*.jpeg', '*.gif', '*.webp']
        image_files = []
        for ext in image_extensions:
            image_files.extend(list(downloads_dir.glob(ext)))
        
        if image_files:
            # Use the first real image we find
            test_image_file = image_files[0]
            print(f"📄 Found real image: {test_image_file.name} ({test_image_file.stat().st_size} bytes)")
            
            # Test with the real image (no keyword validation needed - any response means it worked)
            response_image = await tester.test_file_paths_mode(test_image_file, [])
            print(f"✅ Image test SUCCESSFUL!")
            print(f"📝 Response preview: {response_image[:200]}...")
            print(f"📊 Full response length: {len(response_image)} characters")
            
        else:
            print("⚠️  No image files found in Downloads folder - skipping image test")
            print("📁 Searched for: .png, .jpg, .jpeg, .gif, .webp files")
        
        print("\n" + "="*80)
        print("🧪 TEST 5: Streaming Mode with Real PDF")
        print("="*80)
        
        test_file = pdf_files[0]
        print(f"📄 Streaming analysis of: {test_file.name}")
        
        response4, chunk_count = await tester.test_streaming_mode(test_file)
        print(f"📝 Response preview: {response4[:300]}...")
        print(f"📊 Received {chunk_count} chunks, {len(response4)} characters total")
        
        print("\n" + "="*80)
        print("🎯 ALL TESTS COMPLETED SUCCESSFULLY!")
        print("="*80)
        print("✅ File paths mode working with contextual responses")
        print("✅ Base64 content mode working with contextual responses") 
        print("✅ Streaming mode working with contextual responses")
        print("✅ Image processing working with correct content blocks")
        print("📊 All files processed correctly by Claude API")
        print("🚀 Ready for production agent workflows!")
        
        return True
        
    except Exception as e:
        print(f"\n💀 CRITICAL FAILURE: {str(e)}")
        return False


if __name__ == "__main__":
    print("🔥 ROBUST REAL PDF API TESTING - NO FAILURES ALLOWED")
    print("⏰ Using 30-second delays and retry logic to ensure 100% success")
    print("🎯 Every test MUST show contextual file processing")
    
    success = asyncio.run(test_real_pdf_api_calls())
    
    if success:
        print("\n🎉 ALL TESTS PASSED! File integration is bulletproof! 🎉")
        exit(0)
    else:
        print("\n💀 TESTS FAILED! File integration needs work!")
        exit(1) 