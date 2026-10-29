#!/usr/bin/env python3

"""
Live test for Outlook draft creation - actually executes AppleScript.

This script will create a real draft in Outlook to verify our fixes work.
"""

import asyncio
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../src'))

from api.services.agent_processing.tools.direct_application_interactions.email_integration.outlook.outlook_service import OutlookAppleScriptService
from api.services.agent_processing.tools.direct_application_interactions.email_integration.applescript_automation_service import AppleScriptAutomationService
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_models import EmailRequest

import pytest

pytestmark = pytest.mark.manual


async def test_live_draft_creation():
    """Test creating a real draft in Outlook."""
    
    print("🔧 LIVE OUTLOOK DRAFT CREATION TEST")
    print("=" * 50)
    print("⚠️  This will create a REAL draft in Microsoft Outlook!")
    print()
    
    # Confirm with user (for safety)
    confirm = input("Continue? (yes/no): ").lower().strip()
    if confirm != 'yes':
        print("❌ Test canceled by user")
        return
    
    try:
        # Create the Outlook service
        outlook_service = OutlookAppleScriptService()
        automation_service = AppleScriptAutomationService()
        
        # Create a test email request
        email_request = EmailRequest(
            action="compose_email",
            recipient="test@example.com",
            subject="TEST DRAFT - Please Delete",
            body="This is a test draft created by our AppleScript automation. Please delete this draft."
        )
        
        print("📝 Generating AppleScript...")
        script = outlook_service.compose_email_script(email_request, draft_only=True)
        
        print(f"📄 Generated script ({len(script)} chars):")
        print("-" * 40)
        print(script)
        print("-" * 40)
        print()
        
        print("🚀 Executing AppleScript against Microsoft Outlook...")
        result = await automation_service.execute_applescript(script, "Live Draft Creation Test")
        
        if result.success:
            print("✅ AppleScript executed successfully!")
            print(f"⏱️  Execution time: {result.execution_time:.2f} seconds")
            print()
            print("🔍 CHECK MICROSOFT OUTLOOK NOW:")
            print("   - A new draft should be visible")
            print("   - Subject: 'TEST DRAFT - Please Delete'")
            print("   - Recipient: test@example.com")
            print("   - The draft window should be open")
            print()
            print("✅ If you see the draft, our fix works!")
            print("❌ If no draft appears, we still have an issue")
            
        else:
            print("❌ AppleScript execution failed!")
            print(f"Error: {result.error}")
            
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("🎯 Starting live draft creation test...")
    asyncio.run(test_live_draft_creation()) 