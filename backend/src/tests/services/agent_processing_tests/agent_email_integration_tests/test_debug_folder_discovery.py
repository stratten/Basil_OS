#!/usr/bin/env python3

"""
Debug Folder Discovery for Smart Account Discovery

This test debugs the folder discovery step that's failing in smart account discovery.
"""

import asyncio
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../src'))

import pytest

from api.services.agent_processing.tools.direct_application_interactions.email_integration.applescript_automation_service import AppleScriptAutomationService

pytestmark = pytest.mark.manual

async def test_folder_discovery_steps():
    """Debug folder discovery step by step."""
    print("🔍 Debugging Folder Discovery")
    print("=" * 50)
    
    applescript_service = AppleScriptAutomationService()
    
    # Test 1: Basic Outlook connection
    print("\n🧪 Test 1: Basic Outlook Connection")
    basic_test = '''
    tell application "Microsoft Outlook"
        return "Connected to Outlook"
    end tell
    '''
    
    result = await applescript_service.execute_applescript(basic_test, "Basic Outlook test")
    print(f"   Result: {result.success} - {result.data if result.success else result.error}")
    
    # Test 2: Get folder count
    print("\n🧪 Test 2: Get Folder Count")
    folder_count_test = '''
    tell application "Microsoft Outlook"
        try
            set allFolders to every folder
            return count of allFolders
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    '''
    
    result = await applescript_service.execute_applescript(folder_count_test, "Folder count test")
    print(f"   Result: {result.success} - {result.data if result.success else result.error}")
    
    # Test 3: Get folder names (simpler approach)
    print("\n🧪 Test 3: Get Folder Names")
    folder_names_test = '''
    tell application "Microsoft Outlook"
        set folderNames to {}
        try
            set allFolders to every folder
            repeat with aFolder in allFolders
                try
                    set folderName to name of aFolder
                    set end of folderNames to folderName
                on error
                    -- Skip folders that can't be accessed
                end try
            end repeat
        on error errMsg
            return "Error: " & errMsg
        end try
        
        return folderNames as string
    end tell
    '''
    
    result = await applescript_service.execute_applescript(folder_names_test, "Folder names test")
    print(f"   Result: {result.success} - {result.data if result.success else result.error}")
    
    # Test 4: Try to find inbox folders (without folder type check)
    print("\n🧪 Test 4: Find Inbox Folders (Simple)")
    inbox_simple_test = '''
    tell application "Microsoft Outlook"
        set inboxFolders to {}
        try
            set allFolders to every folder
            repeat with aFolder in allFolders
                try
                    set folderName to name of aFolder
                    
                    -- Look for folders with "inbox" in the name (case insensitive)
                    if folderName contains "Inbox" or folderName contains "inbox" or folderName contains "INBOX" then
                        set folderID to id of aFolder as string
                        set end of inboxFolders to folderName & "|" & folderID
                    end if
                on error
                    -- Skip folders that can't be accessed
                end try
            end repeat
        on error errMsg
            return "Error: " & errMsg
        end try
        
        return inboxFolders as string
    end tell
    '''
    
    result = await applescript_service.execute_applescript(inbox_simple_test, "Simple inbox discovery")
    print(f"   Result: {result.success} - {result.data if result.success else result.error}")
    
    return result.success and result.data

if __name__ == "__main__":
    print("🚀 Running Folder Discovery Debug Test")
    success = asyncio.run(test_folder_discovery_steps())
    
    if success:
        print("\n🎉 Debug completed - check results above!")
    else:
        print("\n💥 Debug failed!")
        sys.exit(1) 