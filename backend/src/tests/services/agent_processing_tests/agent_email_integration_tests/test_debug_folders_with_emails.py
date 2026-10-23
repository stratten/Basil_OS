#!/usr/bin/env python3

"""
Debug: Which folders have emails?

This test shows which folders actually contain emails.
"""

import asyncio
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../src'))

import pytest

from api.services.agent_processing.tools.direct_application_interactions.email_integration.applescript_automation_service import AppleScriptAutomationService

pytestmark = pytest.mark.manual

async def test_folders_with_emails():
    """Find folders that actually have emails."""
    print("🔍 Finding Folders with Emails")
    print("=" * 50)
    
    applescript_service = AppleScriptAutomationService()
    
    # Find folders with messages
    folder_test_script = '''
    tell application "Microsoft Outlook"
        set folderCandidates to {}
        try
            set allFolders to every folder
            repeat with aFolder in allFolders
                try
                    set folderName to name of aFolder
                    set messageCount to count of messages of aFolder
                    
                    if messageCount > 0 then
                        set folderID to id of aFolder as string
                        set folderEntry to folderName & "|" & folderID & "|" & messageCount
                        set end of folderCandidates to folderEntry
                    end if
                on error
                    -- Skip folders that can't be accessed
                end try
            end repeat
        on error errMsg
            return "Error: " & errMsg
        end try
        
        -- Convert list to comma-separated string
        set AppleScript's text item delimiters to ", "
        set folderString to folderCandidates as string
        set AppleScript's text item delimiters to ""
        return folderString
    end tell
    '''
    
    result = await applescript_service.execute_applescript(folder_test_script, "Find folders with emails")
    
    if result.success and result.data:
        folders = result.data.split(', ')
        print(f"📧 Found {len(folders)} folders with emails:")
        
        for i, folder in enumerate(folders[:10], 1):  # Show first 10
            if '|' in folder:
                parts = folder.split('|')
                if len(parts) >= 3:
                    name, folder_id, count = parts[0], parts[1], parts[2]
                    print(f"   {i}. {name} (ID: {folder_id}, Messages: {count})")
                    
                    # Check if this might be a Baobab folder
                    if 'baobab' in name.lower() or 'baobab' in folder_id.lower():
                        print(f"      🎯 BAOBAB CANDIDATE! {name}")
        
        if len(folders) > 10:
            print(f"   ... and {len(folders) - 10} more folders")
            
    else:
        print(f"❌ Failed: {result.error if not result.success else 'No data'}")
    
    return result.success

if __name__ == "__main__":
    asyncio.run(test_folders_with_emails()) 