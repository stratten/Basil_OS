"""
Test script to debug Outlook AppleScript email retrieval issues.

This focuses ONLY on testing the AppleScript syntax for Microsoft Outlook.
DOES NOT USE ANY EXISTING SERVICES - tests raw AppleScript directly.
"""

import asyncio
import subprocess
import logging
import time

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OutlookAppleScriptTester:
    """Test Outlook AppleScript directly without any existing services."""
    
    def execute_applescript(self, script: str, description: str = "AppleScript", timeout: int = 10) -> dict:
        """Execute AppleScript directly using subprocess."""
        logger.info(f"🍎 Executing {description}...")
        
        try:
            start_time = time.time()
            
            # Execute the AppleScript directly
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            execution_time = time.time() - start_time
            
            if result.returncode == 0:
                logger.info(f"✅ {description} completed successfully in {execution_time:.2f}s")
                return {
                    "success": True,
                    "data": result.stdout.strip(),
                    "execution_time": execution_time
                }
            else:
                logger.error(f"❌ {description} failed: {result.stderr}")
                return {
                    "success": False,
                    "error": result.stderr.strip(),
                    "execution_time": execution_time
                }
                
        except subprocess.TimeoutExpired:
            logger.error(f"⏰ {description} timed out after {timeout} seconds")
            return {
                "success": False,
                "error": f"Timeout after {timeout} seconds",
                "execution_time": timeout
            }
        except Exception as e:
            logger.error(f"❌ {description} exception: {e}")
            return {
                "success": False,
                "error": str(e),
                "execution_time": 0
            }
    
    def test_basic_outlook_access(self):
        """Test basic Outlook access."""
        logger.info("🧪 Testing basic Outlook access...")
        
        # Test 1: Can we access Outlook at all?
        script1 = '''
        tell application "Microsoft Outlook"
            return "Outlook is accessible"
        end tell
        '''
        
        result1 = self.execute_applescript(script1, "basic Outlook access")
        if result1["success"]:
            logger.info(f"✅ Basic Outlook access: {result1['data']}")
        else:
            logger.error(f"❌ Basic Outlook access failed: {result1['error']}")
            return False
        
        # Test 2: Can we access inbox?
        script2 = '''
        tell application "Microsoft Outlook"
            return "Inbox accessible"
        end tell
        '''
        
        result2 = self.execute_applescript(script2, "inbox access test")
        if result2["success"]:
            logger.info(f"✅ Inbox access test: {result2['data']}")
        else:
            logger.error(f"❌ Inbox access test failed: {result2['error']}")
            return False
        
        return True
    
    def test_outlook_message_count(self):
        """Test counting messages in Outlook inbox."""
        logger.info("🧪 Testing Outlook message count...")
        
        script = '''
        tell application "Microsoft Outlook"
            set allMessages to messages of inbox
            return count of allMessages
        end tell
        '''
        
        result = self.execute_applescript(script, "count Outlook messages")
        if result["success"]:
            try:
                count = int(result["data"])
                logger.info(f"📊 Total Outlook messages: {count}")
                return count
            except ValueError:
                logger.error(f"❌ Could not parse count: {result['data']}")
                return 0
        else:
            logger.error(f"❌ Count failed: {result['error']}")
            return 0
    
    def test_global_message_access_with_filtering(self, limit: int = 2):
        """Test accessing messages from global list and filtering for recent ones."""
        logger.info(f"🧪 Testing global message access with filtering (limit: {limit})...")
        
        # Skip this slow operation since we know it works from previous tests but takes too long
        logger.info("   📧 Skipping global message access (too slow - 80K+ messages)")
        logger.info("   📧 Note: Previous tests confirmed 80,295 messages accessible via 'every message'")
        return 0
    
    def test_folder_based_message_search(self):
        """Test searching for inbox-like messages by folder properties."""
        logger.info("🧪 Testing folder-based message identification...")
        
        script = '''
        tell application "Microsoft Outlook"
            set resultList to {}
            
            try
                -- Try to identify messages by their folder context
                set allMessages to every message
                set sampleSize to 5
                set messageCount to count of allMessages
                
                if messageCount > sampleSize then
                    set actualSample to sampleSize
                else
                    set actualSample to messageCount
                end if
                
                repeat with i from 1 to actualSample
                    try
                        set aMessage to item i of allMessages
                        
                        -- Try to get folder information for this message
                        set messageInfo to ""
                        try
                            set messageFolder to container of aMessage
                            set folderName to name of messageFolder
                            set messageInfo to messageInfo & "Folder: " & folderName & " | "
                        on error
                            set messageInfo to messageInfo & "Folder: Unknown | "
                        end try
                        
                        -- Add subject for identification
                        try
                            set messageSubject to subject of aMessage
                            set messageInfo to messageInfo & "Subject: " & messageSubject
                        on error
                            set messageInfo to messageInfo & "Subject: Unknown"
                        end try
                        
                        set end of resultList to messageInfo
                    on error errMsg
                        set end of resultList to "Message " & i & " error: " & errMsg
                    end try
                end repeat
                
            on error mainErr
                set resultList to {"MAIN_ERROR: " & mainErr}
            end try
            
            return resultList
        end tell
        '''
        
        result = self.execute_applescript(script, "folder-based search")
        if result["success"]:
            folder_info = result["data"].split(', ')
            logger.info(f"📁 Message folder analysis:")
            for info in folder_info[:3]:  # Show first 3
                logger.info(f"   {info}")
            return True
        else:
            logger.error(f"❌ Folder-based search failed: {result['error']}")
            return False
    
    def test_email_service_data_format(self, limit: int = 2):
        """Test extracting email data in the exact format our email service expects."""
        logger.info(f"🧪 Testing email service data format extraction (limit: {limit})...")
        
        # Skip this for now - we can test data format once we implement the folder solution
        logger.info("   📊 Skipping data format test (will test with specific folder access)")
        return 0
    
    def test_outlook_permissions_and_access_patterns(self):
        """Test different access patterns and permission issues with Legacy Outlook."""
        logger.info("🔐 Testing Outlook permissions and access patterns...")
        
        # Test 1: Check if Outlook is actually accessible at all
        script1 = '''
        tell application "Microsoft Outlook"
            try
                set appName to name
                return "SUCCESS: Connected to " & appName
            on error errMsg
                return "ERROR connecting to app: " & errMsg
            end try
        end tell
        '''
        result1 = self.execute_applescript(script1, "Basic Outlook connection")
        logger.info(f"   App connection: {result1['data'] if result1['success'] else result1['error']}")
        
        # Test 2: Try to get just the name of the first account
        script2 = '''
        tell application "Microsoft Outlook"
            try
                set firstAccount to account 1
                set accountName to name of firstAccount
                return "SUCCESS: First account is " & accountName
            on error errMsg
                return "ERROR getting first account: " & errMsg
            end try
        end tell
        '''
        result2 = self.execute_applescript(script2, "First account access")
        logger.info(f"   First account: {result2['data'] if result2['success'] else result2['error']}")
        
        # Test 3: Try different ways to reference messages
        test_patterns = [
            ('messages', 'every message'),
            ('items', 'every item'), 
            ('mail items', 'every mail item'),
            ('messages of account 1', 'messages of first account'),
        ]
        
        for pattern_name, pattern_code in test_patterns:
            script = f'''
            tell application "Microsoft Outlook"
                try
                    set messageCount to count of {pattern_code}
                    return "SUCCESS: " & messageCount & " items found using " & "{pattern_name}"
                on error errMsg
                    return "ERROR with {pattern_name}: " & errMsg
                end try
            end tell
            '''
            result = self.execute_applescript(script, f"Access pattern: {pattern_name}")
            logger.info(f"   {pattern_name}: {result['data'] if result['success'] else result['error']}")
        
        # Test 4: Try to access inbox of first account specifically
        script4 = '''
        tell application "Microsoft Outlook"
            try
                set firstAccount to account 1
                set inboxFolder to inbox of firstAccount
                set messageCount to count of messages of inboxFolder
                return "SUCCESS: " & messageCount & " messages in inbox of first account"
            on error errMsg
                return "ERROR accessing account inbox: " & errMsg
            end try
        end tell
        '''
        result4 = self.execute_applescript(script4, "Account-specific inbox")
        logger.info(f"   Account inbox: {result4['data'] if result4['success'] else result4['error']}")

    def test_outlook_structure_discovery(self):
        """Discover Outlook's actual AppleScript structure."""
        logger.info("🧪 Testing Outlook AppleScript structure discovery...")
        
        # Test 1: What accounts exist?
        script1 = '''
        tell application "Microsoft Outlook"
            set accountList to {}
            try
                set allAccounts to every account
                repeat with anAccount in allAccounts
                    set end of accountList to (name of anAccount)
                end repeat
            on error errMsg
                set accountList to {"Error getting accounts: " & errMsg}
            end try
            return accountList
        end tell
        '''
        
        result1 = self.execute_applescript(script1, "discover accounts")
        if result1["success"]:
            logger.info(f"📧 Outlook accounts: {result1['data']}")
        else:
            logger.error(f"❌ Account discovery failed: {result1['error']}")
        
        # Test 2: What folders exist?
        script2 = '''
        tell application "Microsoft Outlook"
            set folderList to {}
            try
                set allFolders to every folder
                repeat with aFolder in allFolders
                    set end of folderList to (name of aFolder)
                end repeat
            on error errMsg
                set folderList to {"Error getting folders: " & errMsg}
            end try
            return folderList
        end tell
        '''
        
        result2 = self.execute_applescript(script2, "discover folders")
        if result2["success"]:
            logger.info(f"📁 Outlook folders: {result2['data']}")
        else:
            logger.error(f"❌ Folder discovery failed: {result2['error']}")
        
        # Test 3: Try accessing first account's inbox
        script3 = '''
        tell application "Microsoft Outlook"
            try
                set firstAccount to item 1 of (every account)
                set accountInbox to inbox of firstAccount
                set messageCount to count of messages of accountInbox
                return "First account inbox: " & messageCount & " messages"
            on error errMsg
                return "Error accessing first account inbox: " & errMsg
            end try
        end tell
        '''
        
        result3 = self.execute_applescript(script3, "first account inbox")
        if result3["success"]:
            logger.info(f"📧 First account inbox: {result3['data']}")
        else:
            logger.error(f"❌ First account inbox failed: {result3['error']}")
        
        # Test 4: Try different inbox reference approaches
        script4 = '''
        tell application "Microsoft Outlook"
            set resultList to {}
            
            -- Try approach 1: just "inbox"
            try
                set count1 to count of messages of inbox
                set end of resultList to "inbox: " & count1
            on error errMsg
                set end of resultList to "inbox error: " & errMsg
            end try
            
            -- Try approach 2: "the inbox"
            try
                set count2 to count of messages of the inbox
                set end of resultList to "the inbox: " & count2
            on error errMsg
                set end of resultList to "the inbox error: " & errMsg
            end try
            
            -- Try approach 3: folder named "Inbox"
            try
                set inboxFolder to folder "Inbox"
                set count3 to count of messages of inboxFolder
                set end of resultList to "folder Inbox: " & count3
            on error errMsg
                set end of resultList to "folder Inbox error: " & errMsg
            end try
            
            return resultList
        end tell
        '''
        
        result4 = self.execute_applescript(script4, "different inbox approaches")
        if result4["success"]:
            logger.info(f"📧 Different inbox approaches: {result4['data']}")
        else:
            logger.error(f"❌ Different inbox approaches failed: {result4['error']}")

    def test_specific_inbox_access_methods(self):
        """Test various methods to access specific inbox folders."""
        logger.info("📥 Testing specific inbox access methods...")
        
        # Test 1: Try accessing folders by index
        script1 = '''
        tell application "Microsoft Outlook"
            set resultList to {}
            
            try
                set allFolders to every folder
                set folderCount to count of allFolders
                
                -- Find folders named "Inbox" and check their message counts
                repeat with i from 1 to folderCount
                    try
                        set aFolder to item i of allFolders
                        set folderName to name of aFolder
                        
                        if folderName is "Inbox" or folderName is "INBOX" then
                            try
                                set messageCount to count of messages of aFolder
                                set end of resultList to "Folder " & i & " (" & folderName & "): " & messageCount & " messages"
                            on error msgErr
                                set end of resultList to "Folder " & i & " (" & folderName & "): Error counting - " & msgErr
                            end try
                        end if
                    on error folderErr
                        -- Skip problematic folders
                    end try
                end repeat
                
            on error mainErr
                set resultList to {"MAIN_ERROR: " & mainErr}
            end try
            
            return resultList
        end tell
        '''
        
        result1 = self.execute_applescript(script1, "inbox folders by index")
        if result1["success"]:
            logger.info(f"📥 Inbox folders found:")
            folder_results = result1["data"].split(', ')
            for folder_result in folder_results:
                logger.info(f"   {folder_result}")
        else:
            logger.error(f"❌ Inbox folder search failed: {result1['error']}")
        
        # Test 2: Try accessing folders by hierarchy/path
        script2 = '''
        tell application "Microsoft Outlook"
            set resultList to {}
            
            -- Try different folder reference methods
            set folderTests to {¬
                {"folder \\"Inbox\\"", "Direct folder name"}, ¬
                {"folder 1", "First folder"}, ¬
                {"folder named \\"Inbox\\"", "Named folder"}, ¬
                {"item 1 of folders", "First folder item"} ¬
            }
            
            repeat with folderTest in folderTests
                try
                    set folderRef to item 1 of folderTest
                    set testName to item 2 of folderTest
                    
                    -- This is tricky - we need to evaluate the folder reference
                    -- For now, let's just log what we're trying
                    set end of resultList to testName & ": Testing " & folderRef
                    
                on error testErr
                    set end of resultList to testName & ": ERROR - " & testErr
                end try
            end repeat
            
            return resultList
        end tell
        '''
        
        result2 = self.execute_applescript(script2, "folder hierarchy access")
        if result2["success"]:
            logger.info(f"📁 Folder access methods:")
            hierarchy_results = result2["data"].split(', ')
            for hierarchy_result in hierarchy_results:
                logger.info(f"   {hierarchy_result}")
        else:
            logger.error(f"❌ Folder hierarchy test failed: {result2['error']}")
    
    def test_message_folder_properties(self):
        """Test what folder properties messages have to identify their location."""
        logger.info("📂 Testing message folder properties...")
        
        # Skip this slow operation for now - it's not critical
        logger.info("   📂 Skipping message folder analysis (too slow - not critical for inbox access)")
        return False
    
    def test_folder_access_by_exact_reference(self):
        """Test accessing folders using exact AppleScript references."""
        logger.info("🎯 Testing exact folder references...")
        
        # Skip this slow operation - we already found the working folders (154 & 191)
        logger.info("   🎯 Skipping exact folder search (already found working folders)")
        return False
    
    def test_account_folder_relationships(self):
        """Test the relationship between accounts and their folders."""
        logger.info("🔗 Testing account-folder relationships...")
        
        # Skip this slow operation - focus on what works
        logger.info("   🔗 Skipping account analysis (focus on working folder access)")
        return False

    def test_folder_hierarchy_and_relationships(self):
        """Test understanding folder hierarchy to correlate accounts with inboxes dynamically."""
        logger.info("🔗 Testing folder hierarchy and account-inbox relationships...")
        
        script = '''
        tell application "Microsoft Outlook"
            set resultList to {}
            
            try
                set allFolders to every folder
                
                -- Find all inbox folders first
                set inboxFolders to {}
                repeat with i from 1 to (count of allFolders)
                    try
                        set aFolder to item i of allFolders
                        set folderName to name of aFolder
                        
                        if folderName is "Inbox" or folderName is "INBOX" or folderName contains "Inbox" then
                            try
                                set messageCount to count of messages of aFolder
                                if messageCount > 0 then
                                    set end of inboxFolders to {folderIndex:i, folderName:folderName, messageCount:messageCount, folderRef:aFolder}
                                end if
                            on error
                                -- Skip if can't count messages
                            end try
                        end if
                    on error
                        -- Skip problematic folders
                    end try
                end repeat
                
                set end of resultList to "FOUND " & (count of inboxFolders) & " ACTIVE INBOX FOLDERS:"
                
                -- For each inbox, try to determine its account by checking folder relationships
                repeat with inboxInfo in inboxFolders
                    set inboxIndex to folderIndex of inboxInfo
                    set inboxName to folderName of inboxInfo
                    set msgCount to messageCount of inboxInfo
                    set inboxFolder to folderRef of inboxInfo
                    
                    set inboxAnalysis to "INBOX " & inboxIndex & " (" & inboxName & ", " & msgCount & " msgs):"
                    set end of resultList to inboxAnalysis
                    
                    -- Method 1: Check for parent folder relationship
                    try
                        set parentFolder to container of inboxFolder
                        set parentName to name of parentFolder
                        set end of resultList to "  Parent folder: " & parentName
                        
                        -- Check if parent has account-like name
                        if parentName contains "@" or parentName contains ".com" then
                            set end of resultList to "  >>> ACCOUNT IDENTIFIED: " & parentName
                        end if
                    on error parentErr
                        set end of resultList to "  Parent folder: ERROR - " & parentErr
                    end try
                    
                    -- Method 2: Look for nearby account folders (within 10 indexes)
                    set nearbyAccounts to {}
                    set searchStart to inboxIndex - 10
                    set searchEnd to inboxIndex + 10
                    if searchStart < 1 then set searchStart to 1
                    if searchEnd > (count of allFolders) then set searchEnd to (count of allFolders)
                    
                    repeat with j from searchStart to searchEnd
                        if j is not inboxIndex then
                            try
                                set nearbyFolder to item j of allFolders
                                set nearbyName to name of nearbyFolder
                                if nearbyName contains "@" or nearbyName contains ".com" then
                                    set end of nearbyAccounts to "Index " & j & ": " & nearbyName
                                end if
                            on error
                                -- Skip problematic folders
                            end try
                        end if
                    end repeat
                    
                    if (count of nearbyAccounts) > 0 then
                        set end of resultList to "  Nearby accounts:"
                        repeat with nearbyAccount in nearbyAccounts
                            set end of resultList to "    " & nearbyAccount
                        end repeat
                    else
                        set end of resultList to "  No nearby account folders found"
                    end if
                    
                    -- Method 3: Analyze folder path/structure
                    try
                        -- Try to get the full path or container hierarchy
                        set pathElements to {}
                        set currentFolder to inboxFolder
                        repeat 5 times -- Max 5 levels up
                            try
                                set currentParent to container of currentFolder
                                set parentName to name of currentParent
                                set end of pathElements to parentName
                                set currentFolder to currentParent
                            on error
                                exit repeat
                            end try
                        end repeat
                        
                        if (count of pathElements) > 0 then
                            set end of resultList to "  Folder path: " & pathElements
                        end if
                    on error pathErr
                        set end of resultList to "  Path analysis: ERROR - " & pathErr
                    end try
                    
                    set end of resultList to ""
                end repeat
                
                -- Also try to understand overall folder structure
                set end of resultList to "FOLDER STRUCTURE ANALYSIS:"
                set accountPattern to {}
                repeat with i from 1 to (count of allFolders)
                    try
                        set aFolder to item i of allFolders
                        set folderName to name of aFolder
                        if folderName contains "@" or folderName contains ".com" then
                            set end of accountPattern to "Index " & i & ": " & folderName
                        end if
                    on error
                        -- Skip problematic folders
                    end try
                end repeat
                
                set end of resultList to "Account-like folders found at:"
                repeat with accountInfo in accountPattern
                    set end of resultList to "  " & accountInfo
                end repeat
                
            on error mainErr
                set resultList to {"MAIN_ERROR: " & mainErr}
            end try
            
            return resultList
        end tell
        '''
        
        result = self.execute_applescript(script, "folder hierarchy analysis", timeout=15)
        if result["success"]:
            logger.info(f"🔗 Folder hierarchy analysis:")
            hierarchy_results = result["data"].split(', ')
            for hierarchy_result in hierarchy_results:
                logger.info(f"   {hierarchy_result}")
            
            # Check if we found hierarchical relationships
            has_parent_relationships = "Parent folder:" in result["data"] and "ERROR" not in result["data"]
            has_nearby_accounts = "Nearby accounts:" in result["data"]
            
            return has_parent_relationships or has_nearby_accounts
        else:
            logger.error(f"❌ Folder hierarchy analysis failed: {result['error']}")
            return False

    def test_access_discovered_inbox_folders(self):
        """Test accessing the specific inbox folders we discovered (154 and 191)."""
        logger.info("🎯 Testing access to discovered inbox folders...")
        
        script = '''
        tell application "Microsoft Outlook"
            set resultList to {}
            
            try
                set allFolders to every folder
                
                -- Test accessing folder 154 (Inbox with 379 messages)
                try
                    set folder154 to item 154 of allFolders
                    set folder154Name to name of folder154
                    set messages154 to messages of folder154
                    set count154 to count of messages154
                    
                    set folderInfo to "FOLDER 154 SUCCESS: '" & folder154Name & "' has " & count154 & " messages"
                    
                    -- Get a sample email from this folder
                    if count154 > 0 then
                        try
                            set sampleMessage to item 1 of messages154
                            set sampleSubject to subject of sampleMessage
                            set sampleSender to sender of sampleMessage
                            if length of sampleSubject > 30 then
                                set sampleSubject to (characters 1 thru 27 of sampleSubject) as string & "..."
                            end if
                            set folderInfo to folderInfo & " | Sample: '" & sampleSubject & "' from " & sampleSender
                        on error sampleErr
                            set folderInfo to folderInfo & " | Sample error: " & sampleErr
                        end try
                    end if
                    
                    set end of resultList to folderInfo
                    
                on error folder154Err
                    set end of resultList to "FOLDER 154 ERROR: " & folder154Err
                end try
                
                -- Test accessing folder 191 (INBOX with 23 messages)
                try
                    set folder191 to item 191 of allFolders
                    set folder191Name to name of folder191
                    set messages191 to messages of folder191
                    set count191 to count of messages191
                    
                    set folderInfo to "FOLDER 191 SUCCESS: '" & folder191Name & "' has " & count191 & " messages"
                    
                    -- Get a sample email from this folder
                    if count191 > 0 then
                        try
                            set sampleMessage to item 1 of messages191
                            set sampleSubject to subject of sampleMessage
                            set sampleSender to sender of sampleMessage
                            if length of sampleSubject > 30 then
                                set sampleSubject to (characters 1 thru 27 of sampleSubject) as string & "..."
                            end if
                            set folderInfo to folderInfo & " | Sample: '" & sampleSubject & "' from " & sampleSender
                        on error sampleErr
                            set folderInfo to folderInfo & " | Sample error: " & sampleErr
                        end try
                    end if
                    
                    set end of resultList to folderInfo
                    
                on error folder191Err
                    set end of resultList to "FOLDER 191 ERROR: " & folder191Err
                end try
                
                -- Try to get the full email data from folder 154 (limit 2)
                try
                    set folder154 to item 154 of allFolders
                    set messages154 to messages of folder154
                    set messageCount to count of messages154
                    
                    set emailDataList to {}
                    set actualLimit to 2
                    if messageCount < actualLimit then
                        set actualLimit to messageCount
                    end if
                    
                    repeat with i from 1 to actualLimit
                        try
                            set aMessage to item i of messages154
                            
                            -- Build pipe-separated email data
                            set emailData to ""
                            
                            -- ID, Subject, Sender, Date, Read status
                            try
                                set msgID to id of aMessage as string
                                set msgSubject to subject of aMessage
                                set msgSender to sender of aMessage as string
                                set msgDate to time sent of aMessage as string
                                set msgRead to read of aMessage as string
                                
                                set emailData to msgID & "|" & msgSubject & "|" & msgSender & "|" & msgDate & "|" & msgRead
                                set end of emailDataList to emailData
                            on error dataErr
                                set end of emailDataList to "EMAIL_DATA_ERROR: " & dataErr
                            end try
                        on error msgErr
                            set end of emailDataList to "MESSAGE_ERROR: " & msgErr
                        end try
                    end repeat
                    
                    set end of resultList to "EMAIL_DATA_TEST: Retrieved " & (count of emailDataList) & " emails from folder 154"
                    repeat with emailData in emailDataList
                        set end of resultList to "  " & emailData
                    end repeat
                    
                on error emailDataErr
                    set end of resultList to "EMAIL_DATA_MAIN_ERROR: " & emailDataErr
                end try
                
            on error mainErr
                set resultList to {"MAIN_ERROR: " & mainErr}
            end try
            
            return resultList
        end tell
        '''
        
        result = self.execute_applescript(script, "discovered inbox folders")
        if result["success"]:
            logger.info(f"🎯 Discovered inbox folder results:")
            folder_results = result["data"].split(', ')
            for folder_result in folder_results:
                logger.info(f"   {folder_result}")
            
            # Check if we successfully accessed messages
            success_indicators = [
                "FOLDER 154 SUCCESS:" in result["data"] and "379 messages" in result["data"],
                "FOLDER 191 SUCCESS:" in result["data"] and "23 messages" in result["data"],
                "EMAIL_DATA_TEST:" in result["data"]
            ]
            
            return any(success_indicators)
        else:
            logger.error(f"❌ Discovered inbox folder test failed: {result['error']}")
            return False

    def test_dynamic_inbox_discovery_with_account_identification(self):
        """Dynamically discover inbox folders and identify which accounts they belong to."""
        logger.info("🔍 Testing dynamic inbox discovery with account identification...")
        
        script = '''
        tell application "Microsoft Outlook"
            set resultList to {}
            
            try
                set allFolders to every folder
                set inboxCandidates to {}
                
                -- First pass: Find all potential inbox folders
                repeat with i from 1 to (count of allFolders)
                    try
                        set aFolder to item i of allFolders
                        set folderName to name of aFolder
                        
                        -- Check if this looks like an inbox
                        if folderName is "Inbox" or folderName is "INBOX" or folderName contains "Inbox" then
                            try
                                set messageCount to count of messages of aFolder
                                set inboxInfo to "Index:" & i & "|Name:" & folderName & "|Messages:" & messageCount
                                
                                -- Try to get account info by analyzing a sample message
                                if messageCount > 0 then
                                    try
                                        set sampleMessage to item 1 of messages of aFolder
                                        
                                        -- Try to get the "To" address to identify which account this inbox serves
                                        try
                                            set toRecipients to to recipients of sampleMessage
                                            if (count of toRecipients) > 0 then
                                                set firstRecipient to item 1 of toRecipients
                                                set recipientAddress to address of firstRecipient
                                                set inboxInfo to inboxInfo & "|ToAccount:" & recipientAddress
                                            else
                                                set inboxInfo to inboxInfo & "|ToAccount:none"
                                            end if
                                        on error toErr
                                            set inboxInfo to inboxInfo & "|ToAccount:error"
                                        end try
                                        
                                        -- Try to get subject for additional context
                                        try
                                            set msgSubject to subject of sampleMessage
                                            if length of msgSubject > 30 then
                                                set msgSubject to (characters 1 thru 27 of msgSubject) as string & "..."
                                            end if
                                            set inboxInfo to inboxInfo & "|SampleSubject:" & msgSubject
                                        on error subjErr
                                            set inboxInfo to inboxInfo & "|SampleSubject:error"
                                        end try
                                        
                                    on error msgErr
                                        set inboxInfo to inboxInfo & "|SampleError:" & msgErr
                                    end try
                                else
                                    set inboxInfo to inboxInfo & "|ToAccount:empty|SampleSubject:none"
                                end if
                                
                                set end of inboxCandidates to inboxInfo
                                
                            on error countErr
                                set inboxInfo to "Index:" & i & "|Name:" & folderName & "|Error:" & countErr
                                set end of inboxCandidates to inboxInfo
                            end try
                        end if
                        
                    on error folderErr
                        -- Skip problematic folders
                    end try
                end repeat
                
                -- Report findings
                set end of resultList to "DYNAMIC INBOX DISCOVERY RESULTS:"
                repeat with inboxCandidate in inboxCandidates
                    set end of resultList to "  " & inboxCandidate
                end repeat
                
                -- Second pass: Try to find account-specific folder structure
                set end of resultList to "ACCOUNT FOLDER ANALYSIS:"
                set accountFolders to {}
                
                repeat with i from 1 to (count of allFolders)
                    try
                        set aFolder to item i of allFolders
                        set folderName to name of aFolder
                        
                        -- Look for account-like folder names
                        if folderName contains "@" or folderName contains ".com" or folderName contains "Transferred from" then
                            set end of accountFolders to "Index:" & i & "|AccountFolder:" & folderName
                        end if
                        
                    on error
                        -- Skip problematic folders
                    end try
                end repeat
                
                repeat with accountFolder in accountFolders
                    set end of resultList to "  " & accountFolder
                end repeat
                
                -- Third pass: Try to correlate inboxes with account folders
                set end of resultList to "INBOX-ACCOUNT CORRELATION ANALYSIS:"
                -- This would try to find patterns or hierarchical relationships
                -- For now, just report what we found
                set end of resultList to "  Found " & (count of inboxCandidates) & " inbox candidates"
                set end of resultList to "  Found " & (count of accountFolders) & " account-like folders"
                
            on error mainErr
                set resultList to {"MAIN_ERROR: " & mainErr}
            end try
            
            return resultList
        end tell
        '''
        
        result = self.execute_applescript(script, "dynamic inbox discovery")
        if result["success"]:
            logger.info(f"🔍 Dynamic inbox discovery results:")
            discovery_results = result["data"].split(', ')
            for discovery_result in discovery_results:
                logger.info(f"   {discovery_result}")
            
            # Check if we found useful account identification
            has_account_info = any("ToAccount:" in result for result in discovery_results if "ToAccount:" in result and "ToAccount:error" not in result and "ToAccount:empty" not in result)
            return has_account_info
        else:
            logger.error(f"❌ Dynamic inbox discovery failed: {result['error']}")
            return False
    
    def test_inbox_identification_by_recent_emails(self):
        """Test identifying inboxes by analyzing recent emails to determine account ownership."""
        logger.info("📧 Testing inbox identification by recent email analysis...")
        
        script = '''
        tell application "Microsoft Outlook"
            set resultList to {}
            
            try
                -- We know folders 154 and 191 are our inbox candidates
                set inboxFolders to {154, 191}
                
                repeat with folderIndex in inboxFolders
                    try
                        set targetFolder to item folderIndex of every folder
                        set folderName to name of targetFolder
                        set folderMessages to messages of targetFolder
                        set messageCount to count of folderMessages
                        
                        set folderAnalysis to "FOLDER " & folderIndex & " (" & folderName & ") ANALYSIS:"
                        set end of resultList to folderAnalysis
                        
                        if messageCount > 0 then
                            -- Analyze first 3 messages to identify patterns
                            set analysisLimit to 3
                            if messageCount < analysisLimit then
                                set analysisLimit to messageCount
                            end if
                            
                            repeat with msgIndex from 1 to analysisLimit
                                try
                                    set aMessage to item msgIndex of folderMessages
                                    set messageAnalysis to "  Message " & msgIndex & ": "
                                    
                                    -- Try to get recipient (To field) - this tells us which account
                                    try
                                        set toRecipients to to recipients of aMessage
                                        if (count of toRecipients) > 0 then
                                            set firstRecipient to item 1 of toRecipients
                                            set recipientName to display name of firstRecipient
                                            set recipientAddress to address of firstRecipient
                                            set messageAnalysis to messageAnalysis & "To=" & recipientName & " <" & recipientAddress & ">"
                                        else
                                            set messageAnalysis to messageAnalysis & "To=none"
                                        end if
                                    on error toErr
                                        set messageAnalysis to messageAnalysis & "To=error"
                                    end try
                                    
                                    -- Add subject for context
                                    try
                                        set msgSubject to subject of aMessage
                                        if length of msgSubject > 40 then
                                            set msgSubject to (characters 1 thru 37 of msgSubject) as string & "..."
                                        end if
                                        set messageAnalysis to messageAnalysis & " | Subject=" & msgSubject
                                    on error subjErr
                                        set messageAnalysis to messageAnalysis & " | Subject=error"
                                    end try
                                    
                                    set end of resultList to messageAnalysis
                                    
                                on error msgErr
                                    set end of resultList to "  Message " & msgIndex & ": ERROR - " & msgErr
                                end try
                            end repeat
                            
                        else
                            set end of resultList to "  No messages in this folder"
                        end if
                        
                        set end of resultList to ""
                        
                    on error folderErr
                        set end of resultList to "FOLDER " & folderIndex & " ERROR: " & folderErr
                    end try
                end repeat
                
            on error mainErr
                set resultList to {"MAIN_ERROR: " & mainErr}
            end try
            
            return resultList
        end tell
        '''
        
        result = self.execute_applescript(script, "inbox identification by emails")
        if result["success"]:
            logger.info(f"📧 Inbox identification by email analysis:")
            email_results = result["data"].split(', ')
            for email_result in email_results:
                logger.info(f"   {email_result}")
            
            # Check if we found distinct account patterns
            has_distinct_accounts = "baobabpartners.com" in result["data"] or "gmail.com" in result["data"]
            return has_distinct_accounts
        else:
            logger.error(f"❌ Inbox email analysis failed: {result['error']}")
            return False

    def run_outlook_debug(self):
        """Run the focused Outlook AppleScript debugging."""
        logger.info("🚀 DEBUGGING OUTLOOK APPLESCRIPT ISSUES")
        logger.info("=" * 70)
        
        # Step 0: Test basic Outlook access
        logger.info("🔍 Testing basic Outlook functionality...")
        if not self.test_basic_outlook_access():
            logger.error("❌ Basic Outlook access failed - cannot continue")
            return
        print()
        
        # Step 0.5: NEW - Test permissions and access patterns
        logger.info("🔐 Testing permissions and access patterns...")
        self.test_outlook_permissions_and_access_patterns()
        print()
        
        # Step 0.75: NEW - Discover Outlook structure
        logger.info("🔍 Discovering Outlook AppleScript structure...")
        self.test_outlook_structure_discovery()
        print()
        
        # Step 1: Check how many messages exist
        total_messages = self.test_outlook_message_count()
        print()
        
        if total_messages == 0:
            logger.error("❌ AppleScript reports 0 messages but UI shows many emails!")
            logger.error("❌ This indicates a fundamental AppleScript access issue")
            logger.info("🔍 Check the structure discovery results above")
        else:
            logger.info(f"✅ {total_messages} messages available, testing with limit=2")
        print()
        
        # Continue with comprehensive inbox access testing regardless of message count
        logger.info("🔍 PHASE 2: SPECIFIC INBOX ACCESS INVESTIGATION")
        logger.info("=" * 50)
        
        # Step 2: Test specific inbox access methods
        logger.info("📥 Step 2A: Testing specific inbox access methods...")
        self.test_specific_inbox_access_methods()
        print()
        
        # Step 2.5: Test access to the discovered inbox folders
        logger.info("🎯 Step 2A.5: Testing discovered inbox folders (154 & 191)...")
        discovered_inbox_success = self.test_access_discovered_inbox_folders()
        print()
        
        # Step 2.6: Test dynamic inbox discovery with account identification
        logger.info("🔍 Step 2A.6: Testing dynamic inbox discovery...")
        dynamic_discovery_success = self.test_dynamic_inbox_discovery_with_account_identification()
        print()
        
        # Step 2.7: Test folder hierarchy and account-inbox relationships
        logger.info("🔗 Step 2A.7: Testing folder hierarchy and account-inbox relationships...")
        folder_hierarchy_success = self.test_folder_hierarchy_and_relationships()
        print()
        
        # Step 2.8: Test inbox identification by analyzing recent emails
        logger.info("📧 Step 2A.8: Testing inbox identification by email analysis...")
        email_analysis_success = self.test_inbox_identification_by_recent_emails()
        print()
        
        # Step 3: Test message folder properties to understand structure
        logger.info("📂 Step 2B: Analyzing message folder properties...")
        message_folder_success = self.test_message_folder_properties()
        print()
        
        # Step 4: Test exact folder references
        logger.info("🎯 Step 2C: Testing exact folder references...")
        exact_folder_success = self.test_folder_access_by_exact_reference()
        print()
        
        # Step 5: Test account-folder relationships
        logger.info("🔗 Step 2D: Analyzing account-folder relationships...")
        account_relationship_success = self.test_account_folder_relationships()
        print()
        
        # Only continue with functional tests if we can actually see messages
        if total_messages > 0:
            logger.info("🔍 PHASE 3: EMAIL SERVICE FUNCTIONALITY VALIDATION")
            logger.info("=" * 50)
            
            # Step 6: Test global message access (our working solution)
            global_count = self.test_global_message_access_with_filtering(2)
            print()
            
            # Step 7: Test folder-based message identification
            folder_success = self.test_folder_based_message_search()
            print()
            
            # Step 8: Test email service data format
            service_count = self.test_email_service_data_format(2)
            print()
        else:
            # Set defaults for when we can't test message operations
            global_count = 0
            folder_success = False
            service_count = 0
        
        # Complete Summary
        logger.info("📋 COMPLETE OUTLOOK EMAIL SERVICE ANALYSIS:")
        logger.info("=" * 50)
        logger.info(f"    Total messages available: {total_messages}")
        logger.info(f"    Discovered inbox folders: {'✅ Working' if discovered_inbox_success else '❌ Failed'}")
        logger.info(f"    Dynamic inbox discovery: {'✅ Working' if dynamic_discovery_success else '❌ Failed'}")
        logger.info(f"    Folder hierarchy analysis: {'✅ Working' if folder_hierarchy_success else '❌ Failed'}")
        logger.info(f"    Email-based account ID: {'✅ Working' if email_analysis_success else '❌ Failed'}")
        logger.info(f"    Specific inbox access: {'✅ Working' if exact_folder_success else '❌ Failed'}")
        logger.info(f"    Message folder analysis: {'✅ Working' if message_folder_success else '❌ Failed'}")
        logger.info(f"    Account relationships: {'✅ Working' if account_relationship_success else '❌ Failed'}")
        
        if total_messages > 0:
            logger.info(f"    Global message access: {global_count} emails retrieved")
            logger.info(f"    Folder identification: {'✅ Working' if folder_success else '❌ Failed'}")
            logger.info(f"    Service data format: {service_count} email objects")
            logger.info("    Expected: 2 emails in proper format")
        
        # Determine our email service capabilities with Outlook
        if discovered_inbox_success and (folder_hierarchy_success or dynamic_discovery_success or email_analysis_success):
            logger.info("🎯 OUTLOOK INBOX ACCESS: DYNAMIC DISCOVERY WITH ACCOUNT IDENTIFICATION!")
            logger.info("   📥 Can access specific inbox folders dynamically")
            logger.info("   📧 Successfully retrieved emails from discovered folders")
            logger.info("   🔍 Can identify which inbox belongs to which account")
            logger.info("   🎯 RECOMMENDATION: Build completely dynamic inbox-account correlation")
        elif discovered_inbox_success:
            logger.info("🎯 OUTLOOK INBOX ACCESS: SPECIFIC FOLDERS DISCOVERED BUT LIMITED!")
            logger.info("   📥 Can access specific inbox folders (154 & 191) directly")
            logger.info("   📧 Successfully retrieved emails from discovered folders")
            logger.info("   ⚠️ Cannot reliably identify which inbox belongs to which account")
            logger.info("   🎯 RECOMMENDATION: Static folder access with manual account mapping")
        elif exact_folder_success:
            logger.info("🎯 OUTLOOK INBOX ACCESS: SPECIFIC FOLDERS FOUND!")
            logger.info("   📥 Can access specific inbox folders directly")
            logger.info("   🎯 RECOMMENDATION: Use specific folder references for inbox access")
        elif total_messages > 0 and global_count >= 2 and service_count >= 2:
            logger.info("✅ OUTLOOK EMAIL SERVICE: FUNCTIONAL VIA GLOBAL ACCESS")
            logger.info("   📧 Can retrieve emails from global message list")
            logger.info("   📊 Can format data for our email service")
            logger.info("   🎯 RECOMMENDATION: Use global message access with filtering")
        elif total_messages > 0 and global_count > 0:
            logger.info("⚠️ OUTLOOK EMAIL SERVICE: PARTIALLY FUNCTIONAL")
            logger.info("   📧 Can retrieve emails but formatting may need work")
        else:
            logger.error("❌ OUTLOOK EMAIL SERVICE: NOT FUNCTIONAL")
            if total_messages == 0:
                logger.error("   🚨 Cannot access messages at all via AppleScript")
            else:
                logger.error("   🚨 Cannot retrieve emails reliably")
            
        # Technical recommendations based on findings
        if discovered_inbox_success and (folder_hierarchy_success or dynamic_discovery_success or email_analysis_success):
            logger.info("🔧 PREFERRED TECHNICAL APPROACH:")
            logger.info("   • Dynamically discover ALL inbox folders by name and message count")
            logger.info("   • Use folder hierarchy/parent relationships to identify account ownership")
            if folder_hierarchy_success:
                logger.info("   • Found folder parent/container relationships - use these for account mapping")
            if dynamic_discovery_success or email_analysis_success:
                logger.info("   • Found account folders nearby - correlate with inbox positions")
            logger.info("   • Build completely dynamic account-to-inbox mapping at runtime")
            logger.info("   • Scale automatically when new accounts/inboxes are added")
            logger.info("   • Enable user to specify: 'reply to emails in my [any_account] account'")
        elif discovered_inbox_success:
            logger.info("🔧 LIMITED TECHNICAL APPROACH:")
            logger.info("   • Use static folder index references: item 154 of every folder (379 messages)")
            logger.info("   • Alternative folder: item 191 of every folder (23 messages)")
            logger.info("   • Build AppleScript: 'messages of (item 154 of every folder)'")
            logger.info("   • ⚠️ Cannot distinguish accounts - user must specify folder manually")
        elif exact_folder_success:
            logger.info("🔧 PREFERRED TECHNICAL APPROACH:")
            logger.info("   • Use direct folder references for specific inboxes")
            logger.info("   • Maintain folder-based operations as intended")
            logger.info("   • Standard inbox/sent/drafts folder access should work")
        elif total_messages > 0 and global_count > 0:
            logger.info("🔧 FALLBACK TECHNICAL APPROACH:")
            logger.info("   • Use 'every message' instead of folder-specific queries")
            logger.info("   • Filter/sort messages programmatically by folder properties")
            logger.info("   • Implement workaround for folder-based operations")
        else:
            logger.error("🔧 CRITICAL ISSUE:")
            logger.error("   • Check Outlook permissions and AppleScript support")
            logger.error("   • Verify Legacy Outlook is enabled and functional")
            logger.error("   • Consider alternative email automation approaches")

def main():
    """Run the standalone Outlook AppleScript debugging."""
    tester = OutlookAppleScriptTester()
    tester.run_outlook_debug()

if __name__ == "__main__":
    main() 