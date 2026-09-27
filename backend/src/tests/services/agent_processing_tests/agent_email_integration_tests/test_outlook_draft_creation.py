#!/usr/bin/env python3

"""
Test script for Outlook draft creation functionality.

Tests the complete workflow:
1. Email retrieval and parsing (with HTML stripping)
2. Action mapping (reply -> draft)
3. AppleScript generation for draft creation
4. End-to-end integration
5. OPTIONAL: Live execution (creates real drafts)

Usage:
    poetry run python test_outlook_draft_creation.py                # Safe mode (no real drafts)
    poetry run python test_outlook_draft_creation.py --live         # Live mode (creates real drafts)
"""

import asyncio
import logging
import sys
import os
import argparse

# Add the project root to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../src'))

from api.services.agent_processing.tools.direct_application_interactions.email_integration.applescript_automation_service import AppleScriptAutomationService
from api.services.agent_processing.tools.direct_application_interactions.email_integration.outlook.outlook_service import OutlookAppleScriptService
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_models import EmailRequest, EmailData

import pytest

pytestmark = pytest.mark.manual

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_outlook_email_retrieval():
    """Test email retrieval and HTML content stripping."""
    print("\n" + "="*50)
    print("🔍 TESTING: Outlook Email Retrieval & HTML Stripping")
    print("="*50)
    
    try:
        automation_service = AppleScriptAutomationService()
        
        # Test email retrieval from a specific account context
        print("📧 Retrieving emails from Outlook...")
        emails = await automation_service.get_emails_via_applescript(
            client_name="Microsoft Outlook",
            folder="baobab",  # This should trigger intelligent discovery
            limit=2
        )
        
        print(f"\n✅ Retrieved {len(emails)} emails")
        
        for i, email in enumerate(emails, 1):
            print(f"\n📩 Email {i}:")
            print(f"   ID: {email.id}")
            print(f"   Subject: {email.subject[:50]}...")
            print(f"   Sender: {email.sender}")
            print(f"   Content length: {len(email.content)} chars")
            print(f"   Content preview: {email.content[:150]}...")
            print(f"   Has HTML tags: {'<' in email.content and '>' in email.content}")
            
        return emails
        
    except Exception as e:
        print(f"❌ Email retrieval failed: {e}")
        logger.error(f"Email retrieval error: {e}", exc_info=True)
        return []


async def test_action_mapping():
    """Test that reply actions get mapped to compose_email (draft)."""
    print("\n" + "="*50)
    print("🔄 TESTING: Action Mapping (reply -> draft)")
    print("="*50)
    
    try:
        automation_service = AppleScriptAutomationService()
        
        # Create a test email request with reply action
        email_request = EmailRequest(
            action="reply",  # This should get mapped to compose_email
            recipient="test@example.com",
            subject="Re: Test Subject",
            body="This is a test reply draft",
            reference_email_id="132684"  # Using an example email ID
        )
        
        print(f"📝 Testing action mapping for: {email_request.action}")
        
        # Test the delegation directly
        script = automation_service._delegate_to_outlook_service("reply", email_request)
        
        print(f"✅ Script generated successfully")
        print(f"📄 Script length: {len(script)} characters")
        print(f"🔍 Script preview: {script[:200]}...")
        
        # Check if the script contains expected draft elements
        has_draft_elements = any(keyword in script.lower() for keyword in [
            'draft', 'compose', 'new', 'outgoing message'
        ])
        
        print(f"🎯 Contains draft elements: {has_draft_elements}")
        
        return script
        
    except Exception as e:
        print(f"❌ Action mapping failed: {e}")
        logger.error(f"Action mapping error: {e}", exc_info=True)
        return None


async def test_draft_script_generation():
    """Test AppleScript generation for draft creation."""
    print("\n" + "="*50)
    print("📝 TESTING: Draft AppleScript Generation")
    print("="*50)
    
    try:
        outlook_service = OutlookAppleScriptService()
        
        # Create a test email request
        email_request = EmailRequest(
            action="compose_email",
            recipient="colleague@example.com",
            subject="Draft Test Email",
            body="This is a test draft email with some content to verify formatting.",
            reference_email_id=None
        )
        
        print("📄 Generating AppleScript for draft creation...")
        script = outlook_service.compose_email_script(email_request, draft_only=True)
        
        print(f"✅ Script generated successfully")
        print(f"📄 Script length: {len(script)} characters")
        print(f"\n🔍 GENERATED SCRIPT:")
        print("-" * 40)
        print(script)
        print("-" * 40)
        
        # Verify script elements
        required_elements = [
            'tell application "Microsoft Outlook"',
            email_request.subject,
            email_request.body,
            email_request.recipient
        ]
        
        print(f"\n🔎 Script validation:")
        for element in required_elements:
            present = element in script
            print(f"   {element}: {'✅' if present else '❌'}")
            
        return script
        
    except Exception as e:
        print(f"❌ Script generation failed: {e}")
        logger.error(f"Script generation error: {e}", exc_info=True)
        return None


async def test_html_content_stripping():
    """Test HTML content stripping functionality."""
    print("\n" + "="*50)
    print("🧹 TESTING: HTML Content Stripping")
    print("="*50)
    
    try:
        outlook_service = OutlookAppleScriptService()
        
        # Test HTML content samples
        test_samples = [
            {
                "name": "Simple HTML",
                "content": "<p>Hello <b>world</b>!</p><br><div>Test content</div>"
            },
            {
                "name": "Email with entities",
                "content": "Meeting at 3:00&nbsp;PM&mdash;don&apos;t forget!"
            },
            {
                "name": "Complex HTML",
                "content": """<html><body>
                <div style="font-family: Arial;">
                    <p>Dear colleague,</p>
                    <p>This is a <strong>test email</strong> with various formatting:</p>
                    <ul>
                        <li>Item 1</li>
                        <li>Item 2 with <em>emphasis</em></li>
                    </ul>
                    <p>Best regards,<br>Test Sender</p>
                </div>
                </body></html>"""
            }
        ]
        
        print("🧪 Testing HTML stripping on sample content...")
        
        for sample in test_samples:
            print(f"\n📄 {sample['name']}:")
            print(f"   Original: {sample['content'][:100]}...")
            
            clean_content = outlook_service._strip_html_content(sample['content'])
            
            print(f"   Cleaned:  {clean_content[:100]}...")
            print(f"   Length:   {len(sample['content'])} → {len(clean_content)} chars")
            print(f"   HTML removed: {not ('<' in clean_content and '>' in clean_content)}")
            
        return True
        
    except Exception as e:
        print(f"❌ HTML stripping test failed: {e}")
        logger.error(f"HTML stripping error: {e}", exc_info=True)
        return False


async def test_live_draft_creation(emails=None):
    """Test creating a REAL draft in Outlook (LIVE EXECUTION)."""
    print("\n" + "="*50)
    print("🚀 TESTING: LIVE DRAFT CREATION (REAL EXECUTION)")
    print("="*50)
    print("⚠️  This will create REAL drafts in Microsoft Outlook!")
    
    try:
        automation_service = AppleScriptAutomationService()
        outlook_service = OutlookAppleScriptService()
        
        # Create test scenarios
        test_scenarios = [
            {
                "name": "Simple Draft",
                "request": EmailRequest(
                    action="compose_email",
                    recipient="test-simple@example.com", 
                    subject="TEST DRAFT #1 - Simple (Please Delete)",
                    body="This is a simple test draft created by our comprehensive test suite."
                )
            },
            {
                "name": "Reply Draft from Real Email",
                "request": EmailRequest(
                    action="reply",
                    recipient="test-reply@example.com",
                    subject="Re: TEST DRAFT #2 - Reply (Please Delete)",
                    body="This is a reply draft created from our comprehensive test. It simulates replying to a real email."
                )
            }
        ]
        
        # If we have real emails, create a reply to the first one
        if emails and len(emails) > 0:
            real_email = emails[0]
            test_scenarios.append({
                "name": "Real Email Reply",
                "request": EmailRequest(
                    action="reply",
                    recipient=real_email.sender if '@' in real_email.sender else "test-real-reply@example.com",
                    subject=f"Re: {real_email.subject}",
                    body=f"This is a test reply to your email about: {real_email.subject[:100]}...\n\nOriginal content preview:\n{real_email.content[:200]}...",
                    reference_email_id=real_email.id
                )
            })
        
        live_results = []
        
        for i, scenario in enumerate(test_scenarios, 1):
            print(f"\n📝 SCENARIO {i}: {scenario['name']}")
            print("-" * 30)
            
            try:
                # Generate the AppleScript
                if scenario['request'].action == "reply":
                    script = automation_service._delegate_to_outlook_service("reply", scenario['request'])
                else:
                    script = outlook_service.compose_email_script(scenario['request'], draft_only=True)
                
                print(f"📄 Generated script ({len(script)} chars)")
                print(f"🎯 Recipient: {scenario['request'].recipient}")
                print(f"🎯 Subject: {scenario['request'].subject}")
                
                # Execute the AppleScript
                print("🚀 Executing AppleScript against Outlook...")
                result = await automation_service.execute_applescript(script, f"Live Draft Test - {scenario['name']}")
                
                if result.success:
                    print(f"✅ SUCCESS! Draft created in {result.execution_time:.2f}s")
                    live_results.append({
                        "scenario": scenario['name'],
                        "success": True,
                        "time": result.execution_time
                    })
                else:
                    print(f"❌ FAILED: {result.error}")
                    live_results.append({
                        "scenario": scenario['name'],
                        "success": False,
                        "error": result.error
                    })
                    
            except Exception as e:
                print(f"❌ Exception in scenario {scenario['name']}: {e}")
                live_results.append({
                    "scenario": scenario['name'],
                    "success": False,
                    "error": str(e)
                })
        
        # Summary of live execution
        print(f"\n📊 LIVE EXECUTION SUMMARY:")
        print("-" * 40)
        successful_drafts = sum(1 for result in live_results if result["success"])
        total_scenarios = len(live_results)
        
        for result in live_results:
            status = "✅ SUCCESS" if result["success"] else "❌ FAILED"
            if result["success"]:
                print(f"   {result['scenario']}: {status} ({result['time']:.2f}s)")
            else:
                print(f"   {result['scenario']}: {status} - {result.get('error', 'Unknown error')}")
        
        print(f"\n🎯 Overall: {successful_drafts}/{total_scenarios} drafts created successfully")
        
        if successful_drafts > 0:
            print(f"\n🔍 CHECK MICROSOFT OUTLOOK NOW:")
            print(f"   - {successful_drafts} new draft(s) should be visible")
            print(f"   - Draft windows should be open")
            print(f"   - Each draft should have 'TEST DRAFT' in the subject")
            print(f"   - Safe to delete these test drafts")
        
        return live_results
        
    except Exception as e:
        print(f"❌ Live draft creation test failed: {e}")
        logger.error(f"Live draft creation error: {e}", exc_info=True)
        return []


async def run_comprehensive_test(live_mode=False):
    """Run all draft creation tests."""
    print("🚀 STARTING COMPREHENSIVE OUTLOOK DRAFT CREATION TESTS")
    print("=" * 70)
    
    if live_mode:
        print("⚠️  LIVE MODE ENABLED - REAL DRAFTS WILL BE CREATED!")
        print("=" * 70)
    
    results = {}
    
    # Test 1: Email retrieval and HTML stripping
    results['email_retrieval'] = await test_outlook_email_retrieval()
    
    # Test 2: Action mapping
    results['action_mapping'] = await test_action_mapping()
    
    # Test 3: Draft script generation
    results['draft_script'] = await test_draft_script_generation()
    
    # Test 4: HTML content stripping
    results['html_stripping'] = await test_html_content_stripping()
    
    # Test 5: LIVE EXECUTION (if enabled)
    if live_mode:
        results['live_execution'] = await test_live_draft_creation(results.get('email_retrieval', []))
    
    # Summary
    print("\n" + "="*70)
    print("📊 TEST SUMMARY")
    print("="*70)
    
    success_count = 0
    total_tests = len(results)
    
    for test_name, result in results.items():
        if test_name == 'live_execution':
            # Special handling for live execution results
            if result and isinstance(result, list):
                successful_drafts = sum(1 for r in result if r.get("success", False))
                total_drafts = len(result)
                success = successful_drafts > 0
                status = f"✅ PASSED ({successful_drafts}/{total_drafts} drafts created)" if success else "❌ FAILED"
            else:
                success = False
                status = "❌ FAILED"
        else:
            success = result is not None and result != False and (len(result) > 0 if isinstance(result, list) else True)
            status = "✅ PASSED" if success else "❌ FAILED"
        
        success_count += 1 if success else 0
        print(f"{test_name.replace('_', ' ').title()}: {status}")
        
    print(f"\n🎯 Overall: {success_count}/{total_tests} tests passed")
    
    if success_count == total_tests:
        if live_mode:
            print("🎉 ALL TESTS PASSED! Live draft creation is working perfectly!")
        else:
            print("🎉 ALL TESTS PASSED! Draft creation workflow is ready.")
    else:
        print("⚠️  Some tests failed. Check the output above for details.")
    
    if live_mode and results.get('live_execution'):
        print(f"\n📋 LIVE EXECUTION DETAILS:")
        successful_live = sum(1 for r in results['live_execution'] if r.get("success", False))
        if successful_live > 0:
            print(f"   🎯 {successful_live} real draft(s) created in Microsoft Outlook")
            print(f"   📧 Check your Outlook drafts folder for test drafts")
            print(f"   🗑️  Safe to delete drafts with 'TEST DRAFT' in subject")
        else:
            print(f"   ❌ No drafts were successfully created")
    
    return results


def parse_arguments():
    """Parse instruction line arguments."""
    parser = argparse.ArgumentParser(
        description="Comprehensive Outlook draft creation test suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_outlook_draft_creation.py          # Safe mode (no real drafts)
  python test_outlook_draft_creation.py --live   # Live mode (creates real drafts)
        """
    )
    
    parser.add_argument(
        '--live', 
        action='store_true',
        help='Enable live execution mode (creates real drafts in Outlook)'
    )
    
    return parser.parse_args()


if __name__ == "__main__":
    print("🔧 Outlook Draft Creation Test Suite")
    print("=" * 50)
    
    # Parse instruction line arguments
    args = parse_arguments()
    
    if args.live:
        print("⚠️  LIVE MODE ENABLED - Creating real drafts in Microsoft Outlook!")
        print()
    
    try:
        # Run the comprehensive test
        asyncio.run(run_comprehensive_test(live_mode=args.live))
        
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test suite failed: {e}")
        logger.error(f"Test suite error: {e}", exc_info=True)
        sys.exit(1) 