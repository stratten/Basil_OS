"""
Outlook Account Discovery

Handles dynamic discovery and mapping of Outlook email accounts and folders.
Owns the discovered_accounts state and all account/folder resolution logic.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class OutlookAccountDiscovery:
    """Discovers and maps Outlook email accounts and folder structures at runtime."""

    def __init__(self):
        self.discovered_accounts = {}

    def discover_inbox_folders_script(self) -> str:
        """Generate AppleScript to dynamically discover ALL inbox folders at runtime."""
        return '''
        tell application "Microsoft Outlook"
            set inboxCandidates to {}
            set allFolders to every folder
            
            -- Find ALL potential inbox folders
            repeat with i from 1 to (count of allFolders)
                try
                    set aFolder to item i of allFolders
                    set folderName to name of aFolder
                    
                    -- Check if this looks like an inbox
                    if folderName is "Inbox" or folderName is "INBOX" or folderName contains "Inbox" then
                        try
                            set messageCount to count of messages of aFolder
                            
                            -- Only include folders with messages
                            if messageCount > 0 then
                                set inboxInfo to "Index:" & i & "|Name:" & folderName & "|Messages:" & messageCount
                                
                                -- Try to get account information
                                try
                                    set folderAccount to account of aFolder
                                    set accountName to name of folderAccount
                                    set accountEmail to email address of folderAccount
                                    set inboxInfo to inboxInfo & "|Account:" & accountName & "|Email:" & accountEmail
                                on error
                                    set inboxInfo to inboxInfo & "|Account:unknown|Email:unknown"
                                end try
                                
                                -- Get sample email info for additional context
                                try
                                    set sampleMessage to item 1 of messages of aFolder
                                    set msgSubject to subject of sampleMessage
                                    if length of msgSubject > 50 then
                                        set msgSubject to (characters 1 thru 47 of msgSubject) as string & "..."
                                    end if
                                    set inboxInfo to inboxInfo & "|SampleSubject:" & msgSubject
                                on error
                                    set inboxInfo to inboxInfo & "|SampleSubject:error"
                                end try
                                
                                set end of inboxCandidates to inboxInfo
                            end if
                            
                        on error
                            -- Skip folders that can't be accessed
                        end try
                    end if
                    
                on error
                    -- Skip problematic folders
                end try
            end repeat
            
            set AppleScript's text item delimiters to return
            set inboxText to inboxCandidates as text
            set AppleScript's text item delimiters to ""
            
            return inboxText
        end tell
        '''

    async def discover_and_map_accounts(self, applescript_executor) -> Dict[str, Dict[str, Any]]:
        """
        Dynamically discover ALL inbox folders and their details.
        
        Args:
            applescript_executor: Function to execute AppleScript
            
        Returns:
            Dictionary mapping discovered account identifiers to their details
        """
        logger.info("🔍 Dynamically discovering ALL inbox folders...")
        
        script = self.discover_inbox_folders_script()
        result = await applescript_executor(script, "discover inbox folders")
        
        discovered_accounts = {}
        
        if result.success:
            inbox_data = result.data.split('\n')
            
            for inbox_info in inbox_data:
                if not inbox_info.strip():
                    continue
                    
                try:
                    parts = inbox_info.split('|')
                    folder_index = None
                    folder_name = None
                    message_count = 0
                    account_name = "unknown"
                    account_email = "unknown"
                    sample_subject = ""
                    
                    for part in parts:
                        if part.startswith("Index:"):
                            folder_index = int(part.split(":", 1)[1])
                        elif part.startswith("Name:"):
                            folder_name = part.split(":", 1)[1]
                        elif part.startswith("Messages:"):
                            message_count = int(part.split(":", 1)[1])
                        elif part.startswith("Account:"):
                            account_name = part.split(":", 1)[1]
                        elif part.startswith("Email:"):
                            account_email = part.split(":", 1)[1]
                        elif part.startswith("SampleSubject:"):
                            sample_subject = part.split(":", 1)[1]
                    
                    if folder_index is not None and message_count > 0:
                        account_key = account_email if account_email != "unknown" else f"inbox_{folder_index}"
                        
                        discovered_accounts[account_key] = {
                            "folder_index": folder_index,
                            "folder_name": folder_name,
                            "message_count": message_count,
                            "account_name": account_name,
                            "account_email": account_email,
                            "sample_subject": sample_subject
                        }
                        
                        logger.info(f"📧 Found inbox: {account_key} -> Folder {folder_index} ({folder_name}) - {message_count} messages")
                            
                except Exception as e:
                    logger.warning(f"⚠️ Error parsing inbox info '{inbox_info}': {e}")
                    continue
            
            logger.info(f"✅ Dynamic account discovery complete: Found {len(discovered_accounts)} inboxes")
            return discovered_accounts
        else:
            logger.error(f"❌ Failed to discover inbox folders: {result.error}")
            return {}

    def find_matching_account(self, folder_identifier: str, discovered_accounts: Dict[str, Dict[str, Any]]) -> Optional[str]:
        """
        Find the best matching account for a user request.
        
        Args:
            folder_identifier: User's folder/account identifier from their request
            discovered_accounts: Dynamically discovered accounts
            
        Returns:
            Account key of best match, or None if no match
        """
        if not discovered_accounts:
            return None
            
        folder_lower = folder_identifier.lower()
        
        if "@" in folder_identifier:
            for account_key, account_info in discovered_accounts.items():
                if folder_identifier.lower() in account_info["account_email"].lower():
                    logger.info(f"🎯 Direct email match: '{folder_identifier}' -> {account_key}")
                    return account_key
        
        for account_key, account_info in discovered_accounts.items():
            if folder_lower in account_info["account_name"].lower():
                logger.info(f"🎯 Account name match: '{folder_identifier}' -> {account_key}")
                return account_key
                
        for account_key, account_info in discovered_accounts.items():
            if folder_lower in account_info["account_email"].lower():
                logger.info(f"🎯 Domain match: '{folder_identifier}' -> {account_key}")
                return account_key
        
        if folder_lower in ["inbox", "primary", "main", "default"]:
            best_account = max(discovered_accounts.items(), key=lambda x: x[1]["message_count"])
            logger.info(f"🎯 Generic request '{folder_identifier}' -> {best_account[0]} (highest message count)")
            return best_account[0]
        
        logger.warning(f"⚠️ No match found for '{folder_identifier}' in discovered accounts")
        return None

    async def quick_account_count(self, execute_applescript_func) -> int:
        """Quickly count the number of active accounts in Outlook without full discovery."""
        count_script = '''
        tell application "Microsoft Outlook"
            try
                set allAccounts to every account
                return count of allAccounts
            on error
                return 0
            end try
        end tell
        '''
        
        result = await execute_applescript_func(count_script, "Quick account count")
        if result.success:
            try:
                return int(result.data.strip())
            except (ValueError, AttributeError):
                return 0
        return 0

    async def quick_inbox_discovery(self, execute_applescript_func) -> Dict[str, Any]:
        """Quick discovery of inbox folders without account analysis for single-account scenarios."""
        inbox_script = '''
        tell application "Microsoft Outlook"
            set inboxList to {}
            try
                set allFolders to every folder
                repeat with i from 1 to (count of allFolders)
                    try
                        set aFolder to item i of allFolders
                        set folderName to name of aFolder
                        if folderName is "Inbox" or folderName is "INBOX" then
                            set messageCount to count of messages of aFolder
                            if messageCount > 0 then
                                set end of inboxList to "Index:" & i & "|Name:" & folderName & "|Messages:" & messageCount
                            end if
                        end if
                    on error
                        -- Skip problematic folders
                    end try
                end repeat
            on error
                return {}
            end try
            return inboxList
        end tell
        '''
        
        result = await execute_applescript_func(inbox_script, "Quick inbox discovery")
        if result.success and result.data:
            inbox_folders = {}
            for inbox_info in result.data.split(', '):
                if not inbox_info.strip():
                    continue
                try:
                    parts = dict(part.split(':', 1) for part in inbox_info.split('|'))
                    folder_index = parts.get('Index')
                    if folder_index:
                        inbox_folders[f"folder_{folder_index}"] = {
                            'folder_index': int(folder_index),
                            'name': parts.get('Name', 'Unknown'),
                            'message_count': int(parts.get('Messages', 0))
                        }
                except (ValueError, KeyError) as e:
                    logger.warning(f"Failed to parse inbox info: {inbox_info} - {e}")
                    continue
            
            return inbox_folders
        return {}

    async def intelligent_discovery(self, execute_applescript_func, account_context: str = None) -> Dict[str, Any]:
        """Perform intelligent discovery based on context - either quick or full discovery."""
        logger.info(f"🧠 Starting intelligent discovery with account_context='{account_context}'")
        
        account_count = await self.quick_account_count(execute_applescript_func)
        logger.info(f"📊 Found {account_count} accounts in Outlook")
        
        if account_count == 0:
            logger.warning("⚠️ Traditional account discovery failed (likely OAuth accounts)")
            logger.info("🎯 Attempting smart email-based account discovery as enhancement...")
            
            try:
                smart_accounts = await self.discover_accounts_by_email_analysis(execute_applescript_func)
                if smart_accounts:
                    logger.info(f"✅ Smart discovery found {len(smart_accounts)} accounts")
                    return smart_accounts
                else:
                    logger.info("📝 Smart discovery found no accounts, continuing with original logic")
            except Exception as e:
                logger.warning(f"⚠️ Smart discovery failed with error: {e}, continuing with original logic")
            
            logger.info("🔄 Falling back to original discovery logic that was working before")
        
        if account_context:
            logger.info(f"🔍 Account context '{account_context}' specified - performing full discovery")
            discovered = await self.discover_and_map_accounts(execute_applescript_func)
            return discovered
        elif account_count <= 1:
            logger.info(f"⚡ Single account detected - performing quick inbox discovery")
            quick_inboxes = await self.quick_inbox_discovery(execute_applescript_func)
            if quick_inboxes:
                first_inbox = list(quick_inboxes.values())[0]
                return {
                    'default_inbox': {
                        'folder_index': first_inbox['folder_index'],
                        'account_name': 'default_account',
                        'method': 'quick_discovery'
                    }
                }
            return {}
        else:
            logger.info(f"🔍 Multiple accounts detected - performing full discovery for disambiguation")
            return await self.discover_and_map_accounts(execute_applescript_func)

    def get_folder_reference(self, folder_request: str, discovered_accounts: Dict[str, Any], 
                           account_context: str = None) -> str:
        """Get folder reference intelligently based on discovered accounts and context."""
        
        if 'default_inbox' in discovered_accounts:
            default_inbox = discovered_accounts['default_inbox']
            logger.info(f"📧 Using quick-discovered inbox: folder {default_inbox['folder_index']}")
            return str(default_inbox['folder_index'])
        
        if account_context:
            logger.info(f"🎯 Looking for account matching '{account_context}'")
            
            for account_key, account_info in discovered_accounts.items():
                account_name = account_info.get('account_name', '').lower()
                account_email = account_info.get('account_email', '').lower()
                
                if account_context.lower() in account_name or account_context.lower() in account_email:
                    folder_index = account_info.get('folder_index')
                    logger.info(f"✅ Matched '{account_context}' to account: {account_name} (folder {folder_index})")
                    return str(folder_index)
            
            logger.warning(f"❌ Could not match account context '{account_context}' to any discovered account")
        
        if discovered_accounts:
            first_account = list(discovered_accounts.values())[0]
            folder_index = first_account.get('folder_index')
            logger.info(f"📧 Using default first inbox: folder {folder_index}")
            return str(folder_index)
        
        logger.warning("❌ No discovered accounts available, using folder 'inbox'")
        return "inbox"

    def get_account_info_script(self) -> str:
        """Generate AppleScript to get account information from Outlook."""
        return '''
        tell application "Microsoft Outlook"
            set accountInfo to {}
            
            try
                set allAccounts to every account
                repeat with anAccount in allAccounts
                    try
                        set accountData to (name of anAccount) & " (" & (email address of anAccount) & ")"
                        set end of accountInfo to accountData
                    on error
                        set end of accountInfo to "Unknown account"
                    end try
                end repeat
            on error
                set end of accountInfo to "Unable to retrieve accounts"
            end try
            
            set AppleScript's text item delimiters to return
            set accountText to accountInfo as text
            set AppleScript's text item delimiters to ""
            
            return accountText
        end tell
        '''

    async def discover_accounts_by_email_analysis(self, execute_applescript_func) -> Dict[str, Any]:
        """
        Infer accounts by analyzing email 'To' fields.
        
        Works around OAuth account detection issues by using actual email data
        instead of AppleScript account enumeration.
        """
        logger.info("🎯 SMART ACCOUNT DISCOVERY: Analyzing emails to infer accounts")
        discovered_accounts = {}
        
        try:
            folder_discovery_script = '''
            tell application "Microsoft Outlook"
                set folderCandidates to {}
                try
                    -- Get all folders and find ones with messages
                    set allFolders to every folder
                    repeat with aFolder in allFolders
                        try
                            set folderName to name of aFolder
                            set messageCount to count of messages of aFolder
                            
                            -- Look for folders with messages (prioritize inbox-like folders)
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
                    return "Error discovering folders: " & errMsg
                end try
                
                -- Convert list to comma-separated string for proper parsing
                set AppleScript's text item delimiters to ", "
                set folderString to folderCandidates as string
                set AppleScript's text item delimiters to ""
                return folderString
            end tell
            '''
            
            logger.info("📁 Discovering folders with emails...")
            folder_result = await execute_applescript_func(folder_discovery_script, "Discover folders with emails")
            
            if not folder_result.success:
                logger.warning(f"⚠️ Failed to discover folders: {folder_result.error}")
                return {}
            
            folder_data = folder_result.data.strip()
            if not folder_data or "Error" in folder_data:
                logger.warning(f"⚠️ No valid folders found: {folder_data}")
                return {}
            
            folder_list = folder_data.split(', ') if folder_data else []
            logger.info(f"📁 Found {len(folder_list)} potential inbox folders")
            
            folder_candidates = []
            for folder_entry in folder_list:
                try:
                    folder_name, folder_id, message_count = folder_entry.split('|', 2)
                    folder_candidates.append(
                        (folder_name, folder_id, int(message_count))
                    )
                except ValueError:
                    logger.warning(f"⚠️ Failed to parse folder entry: {folder_entry}")
            folder_candidates.sort(
                key=lambda candidate: (
                    "inbox" not in candidate[0].lower(),
                    -candidate[2],
                    candidate[0].lower(),
                )
            )
            inbox_candidates = [
                candidate
                for candidate in folder_candidates
                if "inbox" in candidate[0].lower()
            ]
            selected_candidates = inbox_candidates or folder_candidates

            for folder_name, folder_id, message_count in selected_candidates[:5]:
                try:
                    sample_message_count = min(message_count, 3)
                    logger.info(f"🔍 Analyzing folder: {folder_name}")
                    
                    email_analysis_script = f'''
                    tell application "Microsoft Outlook"
                        set emailRecipients to {{}}
                        try
                            -- Find the folder by ID (safer approach)
                            set allFolders to every folder
                            set targetFolder to missing value
                            repeat with aFolder in allFolders
                                if (id of aFolder as string) is "{folder_id}" then
                                    set targetFolder to aFolder
                                    exit repeat
                                end if
                            end repeat
                            
                            if targetFolder is not missing value then
                                set recentMessages to messages 1 thru {sample_message_count} of targetFolder
                                
                                repeat with aMessage in recentMessages
                                    try
                                        -- Get the 'To' recipients of the message
                                        set messageRecipients to to recipients of aMessage
                                        repeat with aRecipient in messageRecipients
                                            try
                                                set recipientEmail to address of (get email address of aRecipient) as string
                                                if recipientEmail does not contain "missing value" and recipientEmail is not "" then
                                                    set end of emailRecipients to recipientEmail
                                                end if
                                            on error
                                                -- Skip recipients without valid email
                                            end try
                                        end repeat
                                    on error
                                        -- Skip messages that can't be accessed
                                    end try
                                end repeat
                            end if
                        on error errMsg
                            return "Error: " & errMsg
                        end try
                        
                        set AppleScript's text item delimiters to ", "
                        set recipientText to emailRecipients as text
                        set AppleScript's text item delimiters to ""
                        return recipientText
                    end tell
                    '''
                    
                    email_result = await execute_applescript_func(email_analysis_script, f"Analyze emails in {folder_name}")
                    
                    if email_result.success and email_result.data:
                        recipients = email_result.data.strip()
                        if recipients and "Error" not in recipients:
                            recipient_list = recipients.split(', ') if recipients else []
                            
                            if recipient_list:
                                account_email = recipient_list[0].strip()
                                
                                if '@' in account_email:
                                    account_key = account_email.lower()
                                    
                                    discovered_accounts[account_key] = {
                                        "account_email": account_email,
                                        "account_name": folder_name,
                                        "folder_name": folder_name,
                                        "folder_id": folder_id,
                                        "discovery_method": "email_analysis",
                                        "sample_recipients": recipient_list[:3]
                                    }
                                    
                                    logger.info(f"✅ Discovered account: {account_key} -> {account_email}")
                    
                except Exception as e:
                    logger.warning(f"⚠️ Failed to analyze folder {folder_name}: {e}")
                    continue
            
            self._enhance_account_discovery(discovered_accounts)
            
            logger.info(f"🎯 SMART DISCOVERY COMPLETE: Found {len(discovered_accounts)} accounts")
            for key, info in discovered_accounts.items():
                logger.info(f"   📧 {key}: {info['account_email']} ({info['folder_name']})")
            
            return discovered_accounts
            
        except Exception as e:
            logger.error(f"❌ Email-based account discovery failed: {e}", exc_info=True)
            return {}

    def _enhance_account_discovery(self, discovered_accounts: Dict[str, Any]) -> None:
        """
        Enhance discovered accounts with smart pattern matching for common account identifiers.
        Adds alternative keys that users might reference (e.g., 'gmail', 'work', 'personal').
        """
        enhanced_mappings = {}
        
        for account_key, account_info in discovered_accounts.items():
            account_email = account_info["account_email"].lower()
            
            if 'gmail.com' in account_email:
                enhanced_mappings['gmail'] = account_info.copy()
                enhanced_mappings['google'] = account_info.copy()
            elif 'outlook.com' in account_email or 'hotmail.com' in account_email:
                enhanced_mappings['outlook'] = account_info.copy()
                enhanced_mappings['microsoft'] = account_info.copy()
            elif 'icloud.com' in account_email:
                enhanced_mappings['icloud'] = account_info.copy()
                enhanced_mappings['apple'] = account_info.copy()
            
            email_parts = account_email.split('@')
            if len(email_parts) == 2:
                domain_parts = email_parts[1].split('.')
                if domain_parts:
                    domain_key = domain_parts[0]
                    enhanced_mappings[domain_key] = account_info.copy()
        
        discovered_accounts.update(enhanced_mappings)
        
        if enhanced_mappings:
            logger.info(f"🔧 Added {len(enhanced_mappings)} enhanced account mappings")
