#!/usr/bin/env python3

"""
Test Smart Account Discovery - Email-Based Approach

This test validates the new smart account discovery that analyzes email 'To' fields
to infer account ownership, solving OAuth account detection issues.

Usage:
    poetry run python test_smart_account_discovery.py
"""

import asyncio
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../src'))

from api.services.agent_processing.tools.direct_application_interactions.email_integration.outlook.outlook_service import OutlookAppleScriptService
from api.services.agent_processing.tools.direct_application_interactions.email_integration.applescript_automation_service import AppleScriptAutomationService

import pytest

pytestmark = pytest.mark.manual


@pytest.mark.asyncio
async def test_smart_account_discovery():
    """Test the new email-based account discovery approach."""
    print("🎯 Testing Smart Account Discovery")
    print("=" * 50)
    
    try:
        # Initialize services
        applescript_service = AppleScriptAutomationService()
        outlook_service = OutlookAppleScriptService()
        
        print("🔍 Testing traditional account count...")
        account_count = await outlook_service.quick_account_count(applescript_service.execute_applescript)
        print(f"📊 Traditional account count: {account_count}")
        
        print("\n🎯 Testing smart email-based discovery...")
        smart_accounts = await outlook_service.discover_accounts_by_email_analysis(applescript_service.execute_applescript)
        
        print(f"\n✅ Smart discovery results:")
        print(f"   📧 Found {len(smart_accounts)} accounts")
        
        for account_key, account_info in smart_accounts.items():
            print(f"   🔑 {account_key}:")
            print(f"      Email: {account_info.get('account_email', 'unknown')}")
            print(f"      Folder: {account_info.get('folder_name', 'unknown')}")
            print(f"      Method: {account_info.get('discovery_method', 'unknown')}")
        assert smart_accounts, "smart account discovery should infer at least one account"
        
        # Test specific account matching (like 'baobab')
        print(f"\n🧪 Testing account matching:")
        test_contexts = ['baobab', 'gmail', 'work', 'personal']
        
        for context in test_contexts:
            if context in smart_accounts:
                account_info = smart_accounts[context]
                print(f"   ✅ '{context}' -> {account_info['account_email']}")
            else:
                print(f"   ❌ '{context}' -> No match found")
        
        print(f"\n🎯 Testing integrated intelligent discovery...")
        integrated_result = await outlook_service.intelligent_discovery(
            applescript_service.execute_applescript, 
            account_context='baobab'
        )
        
        print(f"   📊 Integrated discovery found: {len(integrated_result)} accounts")
        for key, info in integrated_result.items():
            print(f"   📧 {key}: {info}")
        assert integrated_result, "integrated discovery should return at least one inbox"
        
        print(f"\n✅ Smart account discovery test completed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == "__main__":
    print("🚀 Running Smart Account Discovery Test")
    success = asyncio.run(test_smart_account_discovery())
    
    if success:
        print("\n🎉 All tests passed!")
    else:
        print("\n💥 Tests failed!")
        sys.exit(1) 