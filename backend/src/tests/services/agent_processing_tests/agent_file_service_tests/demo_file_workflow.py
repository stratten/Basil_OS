#!/usr/bin/env python3

"""
Demo: "Take this document and draft a reply to this email" Workflow

This demonstrates the complete working file system integration.
"""

import asyncio
import sys
import os
import tempfile

# Add project paths
project_root = os.path.join(os.path.dirname(__file__), '../../../')
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))

from api.services.agent_processing.tools.direct_application_interactions.file_system.file_system_service import FileSystemService


async def demo_workflow():
    """Demonstrate the complete file system workflow."""
    print("🚀 File System Integration Demo")
    print("=" * 50)
    print("🎯 Workflow: 'Take this document and draft a reply to this email'")
    print()
    
    # Initialize service
    service = FileSystemService()
    await service.initialize()
    
    # Create a test document with "budget" in the name (so it will be found)
    desktop_path = os.path.expanduser("~/Desktop")
    test_file_path = os.path.join(desktop_path, "budget_proposal_Q4.md")
    
    document_content = """# Q4 Budget Proposal

## Executive Summary
Our Q4 budget includes strategic technology investments and team expansion.

## Key Budget Items
- Technology Infrastructure: $150,000
- Team Expansion: $200,000
- Marketing: $75,000
- Operations: $100,000

## Expected ROI
35% return by Q2 2025 through productivity gains and market expansion.
"""
    
    # Write test document
    with open(test_file_path, 'w') as f:
        f.write(document_content)
    
    try:
        print(f"📄 Created: {os.path.basename(test_file_path)}")
        print()
        
        # Simulate user instruction: "Take the budget document and draft a reply"
        print("🗣️  User: 'Take the budget document and draft a reply to this email'")
        print()
        
        # Agent workflow
        print("🤖 Agent executing workflow...")
        
        file_result = await service.find_file_for_llm(
            filename="budget",
            context="Use this budget document to draft a professional email reply about Q4 financial planning.",
            search_paths=[desktop_path]
        )
        
        if file_result and file_result.get("success"):
            print("✅ SUCCESS! File found and prepared for LLM")
            print()
            print("📁 File Details:")
            print(f"   📄 Name: {file_result['file_name']}")
            print(f"   📏 Size: {file_result['file_size']} bytes")
            print(f"   🔤 Encoding: {file_result['content_encoding']}")
            print(f"   📦 Base64 ready: {len(file_result['base64_content'])} characters")
            print()
            print("🤖 What happens next:")
            print("   1. ✅ File content sent to LLM as Base64")
            print("   2. 🧠 LLM analyzes budget document")
            print("   3. ✍️  LLM generates contextual email reply")
            print("   4. 📧 Email draft created with generated content")
            print()
            print("🔥 Ready for integration with agent processing workflow!")
            
        else:
            print("❌ File not found")
            
    finally:
        # Clean up
        if os.path.exists(test_file_path):
            os.unlink(test_file_path)
            print(f"\n🗑️  Cleaned up: {os.path.basename(test_file_path)}")


if __name__ == "__main__":
    asyncio.run(demo_workflow()) 