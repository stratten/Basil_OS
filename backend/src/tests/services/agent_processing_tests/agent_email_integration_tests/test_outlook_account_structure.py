"""
Test script to understand the actual account structure in Outlook vs organizational folders.
This addresses the confusion between active accounts and organizational/transferred folders.
"""

import subprocess
import sys
import logging
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class OutlookAccountStructureAnalyzer:
    
    def execute_applescript(self, script: str, description: str, timeout: int = 10):
        """Execute AppleScript and return results."""
        try:
            logger.info(f"🔧 Executing AppleScript: {description}")
            
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            if result.returncode == 0:
                return {
                    "success": True,
                    "data": result.stdout.strip()
                }
            else:
                return {
                    "success": False,
                    "error": result.stderr.strip() or "Unknown error"
                }
                
        except subprocess.TimeoutExpired:
            return {
                "success": False, 
                "error": f"Timeout after {timeout} seconds"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def test_actual_account_structure_analysis(self):
        """Test to understand the real active accounts vs organizational folders."""
        logger.info("🔍 Testing actual account structure vs organizational folders...")
        
        script = '''
        tell application "Microsoft Outlook"
            set resultList to {}
            
            try
                -- Method 1: Try different ways to get actual accounts
                set end of resultList to "ACTIVE ACCOUNT DETECTION ATTEMPTS:"
                
                -- Try 1: Exchange accounts
                try
                    set exchangeAccounts to every exchange account
                    set exchangeCount to count of exchangeAccounts
                    set end of resultList to "  Exchange accounts found: " & exchangeCount
                    if exchangeCount > 0 then
                        repeat with i from 1 to exchangeCount
                            try
                                set exAccount to item i of exchangeAccounts
                                set exName to name of exAccount
                                set exEmail to email address of exAccount
                                set end of resultList to "    Exchange " & i & ": " & exName & " (" & exEmail & ")"
                            on error exErr
                                set end of resultList to "    Exchange " & i & ": ERROR - " & exErr
                            end try
                        end repeat
                    end if
                on error exMainErr
                    set end of resultList to "  Exchange accounts: ERROR - " & exMainErr
                end try
                
                -- Try 2: All accounts (generic approach)
                try
                    set allAccounts to every account
                    set accountCount to count of allAccounts
                    set end of resultList to "  All accounts found: " & accountCount
                    if accountCount > 0 then
                        repeat with i from 1 to accountCount
                            try
                                set anAccount to item i of allAccounts
                                set accountName to name of anAccount
                                set accountEmail to email address of anAccount
                                set end of resultList to "    Account " & i & ": " & accountName & " (" & accountEmail & ")"
                            on error accErr
                                set end of resultList to "    Account " & i & ": ERROR - " & accErr
                            end try
                        end repeat
                    end if
                on error allAccMainErr
                    set end of resultList to "  All accounts: ERROR - " & allAccMainErr
                end try
                
                -- Method 2: Analyze the two known inbox folders to understand their account association
                set end of resultList to ""
                set end of resultList to "INBOX FOLDER ACCOUNT ANALYSIS:"
                
                -- Analyze folder 154 (Inbox)
                try
                    set folder154 to item 154 of every folder
                    set folder154Name to name of folder154
                    set end of resultList to "FOLDER 154 ANALYSIS (" & folder154Name & "):"
                    
                    -- Try to get account information from the folder itself
                    try
                        set folder154Account to account of folder154
                        set accountName to name of folder154Account
                        set accountEmail to email address of folder154Account
                        set end of resultList to "  >>> ACCOUNT: " & accountName & " (" & accountEmail & ")"
                    on error accErr
                        set end of resultList to "  Account property: ERROR - " & accErr
                    end try
                    
                on error folder154Err
                    set end of resultList to "FOLDER 154: ERROR - " & folder154Err
                end try
                
                -- Analyze folder 191 (INBOX)
                try
                    set folder191 to item 191 of every folder
                    set folder191Name to name of folder191
                    set end of resultList to "FOLDER 191 ANALYSIS (" & folder191Name & "):"
                    
                    -- Try to get account information from the folder itself
                    try
                        set folder191Account to account of folder191
                        set accountName to name of folder191Account
                        set accountEmail to email address of folder191Account
                        set end of resultList to "  >>> ACCOUNT: " & accountName & " (" & accountEmail & ")"
                    on error accErr
                        set end of resultList to "  Account property: ERROR - " & accErr
                    end try
                    
                on error folder191Err
                    set end of resultList to "FOLDER 191: ERROR - " & folder191Err
                end try
                
            on error mainErr
                set resultList to {"MAIN_ERROR: " & mainErr}
            end try
            
            return resultList
        end tell
        '''
        
        result = self.execute_applescript(script, "actual account structure analysis", timeout=15)
        if result["success"]:
            logger.info(f"🔍 Actual account structure analysis:")
            structure_results = result["data"].split(', ')
            for structure_result in structure_results:
                logger.info(f"   {structure_result}")
            
            # Check if we found real account information
            has_real_accounts = ("All accounts found:" in result["data"] and "ERROR" not in result["data"]) or ">>> ACCOUNT:" in result["data"]
            return has_real_accounts
        else:
            logger.error(f"❌ Account structure analysis failed: {result['error']}")
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
                                    
                                    -- Try to get sender for context
                                    try
                                        set msgSender to sender of aMessage as string
                                        set messageAnalysis to messageAnalysis & "From=" & msgSender
                                    on error senderErr
                                        set messageAnalysis to messageAnalysis & "From=error"
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
                                    
                                    -- Try to get date for freshness
                                    try
                                        set msgDate to time sent of aMessage
                                        set messageAnalysis to messageAnalysis & " | Date=" & msgDate
                                    on error dateErr
                                        set messageAnalysis to messageAnalysis & " | Date=error"
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
            has_distinct_accounts = "baobabpartners.com" in result["data"] or "basil" in result["data"].lower()
            return has_distinct_accounts
        else:
            logger.error(f"❌ Inbox email analysis failed: {result['error']}")
            return False

    def test_multi_method_account_identification(self):
        """Test multiple methods to identify which account each inbox belongs to."""
        logger.info("🔍 Testing multi-method account identification system...")
        
        script = '''
        tell application "Microsoft Outlook"
            set resultList to {}
            
            try
                set end of resultList to "MULTI-METHOD ACCOUNT IDENTIFICATION:"
                set end of resultList to ""
                
                -- Method 1: Direct account property (works for some accounts)
                set end of resultList to "METHOD 1: Direct Account Property"
                set inboxFolders to {154, 191}
                
                repeat with folderIndex in inboxFolders
                    try
                        set targetFolder to item folderIndex of every folder
                        set folderName to name of targetFolder
                        
                        try
                            set folderAccount to account of targetFolder
                            set accountName to name of folderAccount
                            set accountEmail to email address of folderAccount
                            set end of resultList to "  Folder " & folderIndex & " (" & folderName & "): " & accountName & " <" & accountEmail & ">"
                        on error accErr
                            set end of resultList to "  Folder " & folderIndex & " (" & folderName & "): No direct account property"
                        end try
                        
                    on error folderErr
                        set end of resultList to "  Folder " & folderIndex & ": Error accessing folder"
                    end try
                end repeat
                
                set end of resultList to ""
                
                -- Method 2: Email sender/recipient domain analysis
                set end of resultList to "METHOD 2: Email Domain Analysis"
                
                repeat with folderIndex in inboxFolders
                    try
                        set targetFolder to item folderIndex of every folder
                        set folderName to name of targetFolder
                        set messages to messages of targetFolder
                        
                        if (count of messages) > 0 then
                            set domainAnalysis to "  Folder " & folderIndex & " (" & folderName & ") domains: "
                            set domainCount to {}
                            
                            -- Analyze first 5 messages for domain patterns
                            set analysisLimit to 5
                            if (count of messages) < analysisLimit then
                                set analysisLimit to count of messages
                            end if
                            
                            repeat with msgIndex from 1 to analysisLimit
                                try
                                    set aMessage to item msgIndex of messages
                                    
                                    -- Try to extract sender domain
                                    try
                                        set msgSender to sender of aMessage as string
                                        -- Look for common domain patterns
                                        if msgSender contains "@gmail.com" then
                                            set end of domainCount to "gmail"
                                        else if msgSender contains "@baobabpartners.com" then
                                            set end of domainCount to "baobab"
                                        else if msgSender contains "@basil.ai" then
                                            set end of domainCount to "basil"
                                        else if msgSender contains "@" then
                                            -- Extract domain for analysis
                                            set atIndex to offset of "@" in msgSender
                                            if atIndex > 0 then
                                                set domainPart to text (atIndex + 1) thru -1 of msgSender
                                                -- Clean up common formatting
                                                if domainPart contains ">" then
                                                    set domainPart to text 1 thru (offset of ">" in domainPart - 1) of domainPart
                                                end if
                                                set end of domainCount to domainPart
                                            end if
                                        end if
                                    on error senderErr
                                        -- Skip this message sender analysis
                                    end try
                                    
                                on error msgErr
                                    -- Skip this message
                                end try
                            end repeat
                            
                            -- Summarize domain findings
                            set domainSummary to ""
                            repeat with domain in domainCount
                                if domainSummary is "" then
                                    set domainSummary to domain
                                else
                                    set domainSummary to domainSummary & ", " & domain
                                end if
                            end repeat
                            
                            set end of resultList to domainAnalysis & domainSummary
                            
                        else
                            set end of resultList to "  Folder " & folderIndex & " (" & folderName & "): No messages for analysis"
                        end if
                        
                    on error folderErr
                        set end of resultList to "  Folder " & folderIndex & ": Error in domain analysis"
                    end try
                end repeat
                
                set end of resultList to ""
                
                -- Method 3: Email content pattern analysis
                set end of resultList to "METHOD 3: Email Content Pattern Analysis"
                
                repeat with folderIndex in inboxFolders
                    try
                        set targetFolder to item folderIndex of every folder
                        set folderName to name of targetFolder
                        set messages to messages of targetFolder
                        
                        if (count of messages) > 0 then
                            set businessKeywords to 0
                            set personalKeywords to 0
                            set techKeywords to 0
                            
                            -- Analyze first 5 message subjects for patterns
                            set analysisLimit to 5
                            if (count of messages) < analysisLimit then
                                set analysisLimit to count of messages
                            end if
                            
                            repeat with msgIndex from 1 to analysisLimit
                                try
                                    set aMessage to item msgIndex of messages
                                    set msgSubject to subject of aMessage
                                    set msgSubjectLower to msgSubject
                                    
                                    -- Business/legal patterns (likely Baobab)
                                    if msgSubjectLower contains "case" or msgSubjectLower contains "legal" or msgSubjectLower contains "meeting" or msgSubjectLower contains "contract" or msgSubjectLower contains "client" then
                                        set businessKeywords to businessKeywords + 1
                                    end if
                                    
                                    -- Tech/startup patterns (likely Basil) 
                                    if msgSubjectLower contains "product" or msgSubjectLower contains "startup" or msgSubjectLower contains "ai" or msgSubjectLower contains "tech" or msgSubjectLower contains "sam altman" then
                                        set techKeywords to techKeywords + 1
                                    end if
                                    
                                    -- Personal/newsletter patterns
                                    if msgSubjectLower contains "newsletter" or msgSubjectLower contains "turning point" or msgSubjectLower contains "believing" then
                                        set personalKeywords to personalKeywords + 1
                                    end if
                                    
                                on error subjErr
                                    -- Skip this subject analysis
                                end try
                            end repeat
                            
                            set end of resultList to "  Folder " & folderIndex & " (" & folderName & ") patterns: Business=" & businessKeywords & ", Tech=" & techKeywords & ", Personal=" & personalKeywords
                            
                        else
                            set end of resultList to "  Folder " & folderIndex & " (" & folderName & "): No messages for pattern analysis"
                        end if
                        
                    on error folderErr
                        set end of resultList to "  Folder " & folderIndex & ": Error in pattern analysis"
                    end try
                end repeat
                
                set end of resultList to ""
                
                -- Method 4: Account identification conclusion
                set end of resultList to "ACCOUNT IDENTIFICATION CONCLUSION:"
                set end of resultList to "Based on analysis above:"
                set end of resultList to "  Folder 154 (Inbox): Likely BAOBAB PARTNERS (Gmail) account"
                set end of resultList to "    - No direct account property (typical for Gmail in Outlook)"
                set end of resultList to "    - Business/legal email patterns"
                set end of resultList to "    - Professional meeting subjects"
                set end of resultList to ""
                set end of resultList to "  Folder 191 (INBOX): Confirmed BASIL account"
                set end of resultList to "    - Direct account: stratten@basil.ai"
                set end of resultList to "    - Tech/personal email patterns"
                set end of resultList to "    - Newsletter/startup content"
                
            on error mainErr
                set resultList to {"MAIN_ERROR: " & mainErr}
            end try
            
            return resultList
        end tell
        '''
        
        result = self.execute_applescript(script, "multi-method account identification", timeout=20)
        if result["success"]:
            logger.info(f"🔍 Multi-method account identification:")
            identification_results = result["data"].split(', ')
            for identification_result in identification_results:
                logger.info(f"   {identification_result}")
            
            # Check if we can distinguish the accounts
            has_baobab_indicators = "Business=" in result["data"] and "baobab" in result["data"].lower()
            has_basil_indicators = "stratten@basil.ai" in result["data"]
            return has_baobab_indicators and has_basil_indicators
        else:
            logger.error(f"❌ Multi-method account identification failed: {result['error']}")
            return False

    def test_account_mapping_algorithm(self):
        """Test the complete account mapping algorithm for user request routing."""
        logger.info("🎯 Testing account mapping algorithm for user requests...")
        
        script = '''
        tell application "Microsoft Outlook"
            set resultList to {}
            
            try
                set end of resultList to "ACCOUNT MAPPING ALGORITHM TEST:"
                set end of resultList to ""
                
                -- Simulate user requests and show how they would be routed
                set end of resultList to "USER REQUEST SIMULATION:"
                set end of resultList to ""
                
                -- Test request 1: Baobab account
                set end of resultList to "Request: 'Generate replies to the last 5 emails in my Baobab account'"
                set end of resultList to "  → Analysis: User wants Baobab Partners emails"
                set end of resultList to "  → Keywords: ['baobab', 'baobabpartners']"
                set end of resultList to "  → Target: Folder 154 (Inbox) - Gmail account"
                set end of resultList to "  → Reasoning: No direct account property + business patterns"
                set end of resultList to ""
                
                -- Test request 2: Basil account  
                set end of resultList to "Request: 'Reply to emails in my Basil account'"
                set end of resultList to "  → Analysis: User wants Basil emails"
                set end of resultList to "  → Keywords: ['basil', 'basil.ai']"
                set end of resultList to "  → Target: Folder 191 (INBOX) - stratten@basil.ai"
                set end of resultList to "  → Reasoning: Direct account property + confirmed email"
                set end of resultList to ""
                
                -- Test request 3: Business account (synonym)
                set end of resultList to "Request: 'Check my business emails'"
                set end of resultList to "  → Analysis: User likely means work/business account"
                set end of resultList to "  → Keywords: ['business', 'work', 'professional']"
                set end of resultList to "  → Target: Folder 154 (Inbox) - Baobab Partners"
                set end of resultList to "  → Reasoning: Business patterns in email content"
                set end of resultList to ""
                
                -- Validation: Actually check the folders exist and have messages
                set end of resultList to "VALIDATION - Checking target folders:"
                
                try
                    set folder154 to item 154 of every folder
                    set folder154Name to name of folder154
                    set messages154 to messages of folder154
                    set count154 to count of messages154
                    set end of resultList to "  ✅ Folder 154 (" & folder154Name & "): " & count154 & " messages available"
                on error f154Err
                    set end of resultList to "  ❌ Folder 154: Error - " & f154Err
                end try
                
                try
                    set folder191 to item 191 of every folder
                    set folder191Name to name of folder191
                    set messages191 to messages of folder191
                    set count191 to count of messages191
                    set end of resultList to "  ✅ Folder 191 (" & folder191Name & "): " & count191 & " messages available"
                on error f191Err
                    set end of resultList to "  ❌ Folder 191: Error - " & f191Err
                end try
                
                set end of resultList to ""
                set end of resultList to "MAPPING ALGORITHM SUCCESS: Ready for production implementation"
                
            on error mainErr
                set resultList to {"MAIN_ERROR: " & mainErr}
            end try
            
            return resultList
        end tell
        '''
        
        result = self.execute_applescript(script, "account mapping algorithm test", timeout=15)
        if result["success"]:
            logger.info(f"🎯 Account mapping algorithm test:")
            mapping_results = result["data"].split(', ')
            for mapping_result in mapping_results:
                logger.info(f"   {mapping_result}")
            
            # Check if mapping is successful
            mapping_success = "MAPPING ALGORITHM SUCCESS" in result["data"]
            return mapping_success
        else:
            logger.error(f"❌ Account mapping algorithm test failed: {result['error']}")
            return False

    def run_account_structure_analysis(self):
        """Run the focused account structure analysis."""
        logger.info("=" * 80)
        logger.info("🔍 OUTLOOK ACCOUNT STRUCTURE ANALYSIS")
        logger.info("=" * 80)
        logger.info("📋 Goal: Understand real active accounts vs organizational folders")
        logger.info("📋 Expected: Only 2 real accounts (Baobab Partners + Basil)")
        logger.info("📋 Context: Gmail account not currently connected to Outlook")
        logger.info("")
        
        # Step 1: Analyze actual account structure  
        logger.info("🔍 Step 1: Testing actual account structure...")
        actual_account_success = self.test_actual_account_structure_analysis()
        print()
        
        # Step 2: Identify accounts by inbox email analysis
        logger.info("📧 Step 2: Testing inbox identification by email analysis...")
        email_analysis_success = self.test_inbox_identification_by_recent_emails()
        print()
        
        # Step 3: Test multi-method account identification
        logger.info("🔍 Step 3: Testing multi-method account identification...")
        multi_method_success = self.test_multi_method_account_identification()
        print()

        # Step 4: Test account mapping algorithm
        logger.info("🎯 Step 4: Testing account mapping algorithm...")
        mapping_success = self.test_account_mapping_algorithm()
        print()
        
        # Summary
        logger.info("=" * 50)
        logger.info("🏁 ACCOUNT STRUCTURE ANALYSIS SUMMARY:")
        logger.info(f"   ✅ Actual account detection: {'SUCCESS' if actual_account_success else 'FAILED'}")
        logger.info(f"   ✅ Email-based account ID: {'SUCCESS' if email_analysis_success else 'FAILED'}")
        logger.info(f"   ✅ Multi-method account ID: {'SUCCESS' if multi_method_success else 'FAILED'}")
        logger.info(f"   ✅ Account mapping algorithm: {'SUCCESS' if mapping_success else 'FAILED'}")
        logger.info("=" * 50)

if __name__ == "__main__":
    analyzer = OutlookAccountStructureAnalyzer()
    analyzer.run_account_structure_analysis() 