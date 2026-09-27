#!/usr/bin/env python3

"""
Debug Email Analysis for Smart Account Discovery

This test debugs the email analysis step to see why we're not finding accounts.
"""

import asyncio
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../src'))

import pytest

from api.services.agent_processing.tools.direct_application_interactions.email_integration.applescript_automation_service import AppleScriptAutomationService

pytestmark = pytest.mark.manual

async def test_email_analysis_detailed():
    """Debug email analysis step in detail."""
    print("🔍 Debugging Email Analysis")
    print("=" * 50)
    
    applescript_service = AppleScriptAutomationService()
    
    # First, get the inbox folders like our smart discovery does
    print("\n🧪 Step 1: Get Inbox Folders")
    inbox_discovery_script = '''
    tell application "Microsoft Outlook"
        set inboxFolders to {}
        try
            set allFolders to every folder
            repeat with aFolder in allFolders
                try
                    set folderName to name of aFolder
                    if folderName contains "Inbox" or folderName contains "inbox" or folderName contains "INBOX" then
                        set folderID to id of aFolder as string
                        set folderEntry to folderName & "|" & folderID
                        set end of inboxFolders to folderEntry
                    end if
                on error
                    -- Skip folders that can't be accessed
                end try
            end repeat
        on error errMsg
            return "Error discovering folders: " & errMsg
        end try
        
        -- Convert list to comma-separated string for proper parsing
        set AppleScript's text item delimiters to ", "
        set folderString to inboxFolders as string
        set AppleScript's text item delimiters to ""
        return folderString
    end tell
    '''
    
    result = await applescript_service.execute_applescript(inbox_discovery_script, "Get inbox folders")
    print(f"   Inbox folders: {result.data if result.success else result.error}")
    
    if not result.success or not result.data:
        print("   ❌ Can't proceed - no folders found")
        return False
        
    # Parse the first folder to test with
    folder_data = result.data.strip()
    folder_list = folder_data.split(', ') if folder_data else []
    
    if not folder_list:
        print("   ❌ No folders to analyze")
        return False
        
    first_folder = folder_list[0]
    folder_name, folder_id = first_folder.split('|', 1)
    print(f"   Testing with folder: {folder_name} (ID: {folder_id})")
    
    # Test 2: Check if folder has messages
    print(f"\n🧪 Step 2: Check Message Count in {folder_name}")
    message_count_script = f'''
    tell application "Microsoft Outlook"
        try
            set allFolders to every folder
            repeat with aFolder in allFolders
                if (id of aFolder as string) is "{folder_id}" then
                    return count of messages of aFolder
                end if
            end repeat
            return "Folder not found"
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    '''
    
    result = await applescript_service.execute_applescript(message_count_script, "Count messages")
    print(f"   Message count: {result.data if result.success else result.error}")
    
    # Test 3: Get a single message to test recipient access
    print(f"\n🧪 Step 3: Get First Message Details")
    message_details_script = f'''
    tell application "Microsoft Outlook"
        try
            set allFolders to every folder
            repeat with aFolder in allFolders
                if (id of aFolder as string) is "{folder_id}" then
                    if (count of messages of aFolder) > 0 then
                        set firstMessage to message 1 of aFolder
                        set messageSubject to subject of firstMessage
                        set messageSender to sender of firstMessage
                        return "Subject: " & messageSubject & " | Sender: " & (name of messageSender)
                    else
                        return "No messages in folder"
                    end if
                end if
            end repeat
            return "Folder not found"
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    '''
    
    result = await applescript_service.execute_applescript(message_details_script, "Get message details")
    print(f"   Message details: {result.data if result.success else result.error}")
    
    # Test 4: Test recipient access
    print(f"\n🧪 Step 4: Test Recipient Access")
    recipient_test_script = f'''
    tell application "Microsoft Outlook"
        try
            set allFolders to every folder
            repeat with aFolder in allFolders
                if (id of aFolder as string) is "{folder_id}" then
                    if (count of messages of aFolder) > 0 then
                        set firstMessage to message 1 of aFolder
                        set messageRecipients to to recipients of firstMessage
                        set recipientCount to count of messageRecipients
                        
                        if recipientCount > 0 then
                            set firstRecipient to item 1 of messageRecipients
                            set recipientEmail to email address of firstRecipient
                            return "Recipients: " & recipientCount & " | First: " & recipientEmail
                        else
                            return "No recipients found"
                        end if
                    else
                        return "No messages in folder"
                    end if
                end if
            end repeat
            return "Folder not found"
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    '''
    
    result = await applescript_service.execute_applescript(recipient_test_script, "Test recipient access")
    print(f"   Recipient test: {result.data if result.success else result.error}")
    
    return True

if __name__ == "__main__":
    print("🚀 Running Email Analysis Debug Test")
    success = asyncio.run(test_email_analysis_detailed())
    
    if success:
        print("\n🎉 Debug completed!")
    else:
        print("\n💥 Debug failed!")
        sys.exit(1) 