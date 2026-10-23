"""
Test script to debug the off-by-one error when retrieving 5 unread emails.

This focuses ONLY on the issue where we request 5 emails but get 4.
DOES NOT USE ANY EXISTING SERVICES - tests raw AppleScript directly.
"""

import asyncio
import subprocess
import logging
import time

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StandaloneAppleScriptTester:
    """Test AppleScript directly without any existing services."""
    
    def execute_applescript(self, script: str, description: str = "AppleScript", timeout: int = 15) -> dict:
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
    
    def test_basic_mail_access(self):
        """Test basic Mail.app access."""
        logger.info("🧪 Testing basic Mail.app access...")
        
        # Test 1: Can we access Mail.app at all?
        script1 = '''
        tell application "Mail"
            return "Mail is accessible"
        end tell
        '''
        
        result1 = self.execute_applescript(script1, "basic Mail access")
        if result1["success"]:
            logger.info(f"✅ Basic Mail access: {result1['data']}")
        else:
            logger.error(f"❌ Basic Mail access failed: {result1['error']}")
            return False
        
        # Test 2: Can we access inbox?
        script2 = '''
        tell application "Mail"
            return "Inbox accessible"
        end tell
        '''
        
        result2 = self.execute_applescript(script2, "inbox access")
        if result2["success"]:
            logger.info(f"✅ Inbox access: {result2['data']}")
        else:
            logger.error(f"❌ Inbox access failed: {result2['error']}")
            return False
        
        # Test 3: Can we count total messages?
        script3 = '''
        tell application "Mail"
            return count of messages of inbox
        end tell
        '''
        
        result3 = self.execute_applescript(script3, "count total messages", 60)
        if result3["success"]:
            logger.info(f"✅ Total messages: {result3['data']}")
        else:
            logger.error(f"❌ Count total messages failed: {result3['error']}")
            return False
        
        return True
    
    def test_simple_unread_count(self):
        """Test the simplest possible unread count."""
        logger.info("🧪 Testing simple unread count...")
        
        script = '''
        tell application "Mail"
            set unreadCount to 0
            set allMessages to messages of inbox
            repeat with aMessage in allMessages
                if (read status of aMessage) is false then
                    set unreadCount to unreadCount + 1
                end if
            end repeat
            return unreadCount
        end tell
        '''
        
        result = self.execute_applescript(script, "simple unread count")
        if result["success"]:
            try:
                count = int(result["data"])
                logger.info(f"📊 Simple unread count: {count}")
                return count
            except ValueError:
                logger.error(f"❌ Could not parse count: {result['data']}")
                return 0
        else:
            logger.error(f"❌ Simple unread count failed: {result['error']}")
            return 0
    
    def test_unread_email_count(self):
        """Check how many unread emails actually exist (using proven syntax)."""
        logger.info("🧪 Testing unread email count...")
        
        script = '''
        tell application "Mail"
            return the unread count of inbox
        end tell
        '''
        
        result = self.execute_applescript(script, "count unread emails")
        if result["success"]:
            try:
                count = int(result["data"])
                logger.info(f"📊 Total unread emails available (recent 100): {count}")
                return count
            except ValueError:
                logger.error(f"❌ Could not parse count: {result['data']}")
                return 0
        else:
            logger.error(f"❌ Count failed: {result['error']}")
            return 0
    
    def test_approach_1_simple_count(self, limit: int):
        """Test approach 1: Get first N unread messages (proven syntax)."""
        logger.info(f"🧪 Approach 1: Get first N unread messages (limit: {limit})...")
        
        script = f'''
        tell application "Mail"
            set unreadMessages to {{}}
            set allMessages to messages of inbox
            
            repeat with aMessage in allMessages
                if (read status of aMessage) is false then
                    set end of unreadMessages to aMessage
                    if (count of unreadMessages) >= {limit} then
                        exit repeat
                    end if
                end if
            end repeat
            
            return (count of unreadMessages)
        end tell
        '''
        
        result = self.execute_applescript(script, "approach 1")
        if result["success"]:
            try:
                count = int(result["data"])
                logger.info(f"📊 Approach 1: Requested {limit}, got {count}")
                return count
            except ValueError:
                logger.error(f"❌ Could not parse count: {result['data']}")
                return 0
        else:
            logger.error(f"❌ Approach 1 failed: {result['error']}")
            return 0
    
    def test_approach_2_range_selection(self, limit: int):
        """Test approach 2: Range selection."""
        logger.info(f"🧪 Approach 2: Range selection (limit: {limit})...")
        
        script = f'''
        tell application "Mail"
            set unreadMessages to {{}}
            set allMessages to messages of inbox
            
            repeat with aMessage in allMessages
                if (read status of aMessage) is false then
                    set end of unreadMessages to aMessage
                    if (count of unreadMessages) >= {limit} then
                        exit repeat
                    end if
                end if
            end repeat
            
            return (count of unreadMessages)
        end tell
        '''
        
        result = self.execute_applescript(script, "approach 2")
        if result["success"]:
            try:
                count = int(result["data"])
                logger.info(f"📊 Approach 2: Requested {limit}, got {count}")
                return count
            except ValueError:
                logger.error(f"❌ Could not parse count: {result['data']}")
                return 0
        else:
            logger.error(f"❌ Approach 2 failed: {result['error']}")
            return 0
    
    def test_approach_3_direct_items(self, limit: int):
        """Test approach 3: Using 'every message where' syntax."""
        logger.info(f"🧪 Approach 3: Using 'every message where' syntax (limit: {limit})...")
        
        script = f'''
        tell application "Mail"
            set unreadMessages to (every message in inbox where read status is false)
            
            if (count of unreadMessages) >= {limit} then
                set selectedMessages to items 1 thru {limit} of unreadMessages
                return (count of selectedMessages)
            else
                return (count of unreadMessages)
            end if
        end tell
        '''
        
        result = self.execute_applescript(script, "approach 3")
        if result["success"]:
            try:
                count = int(result["data"])
                logger.info(f"📊 Approach 3: Requested {limit}, got {count}")
                return count
            except ValueError:
                logger.error(f"❌ Could not parse count: {result['data']}")
                return 0
        else:
            logger.error(f"❌ Approach 3 failed: {result['error']}")
            return 0
    
    def run_off_by_one_debug(self):
        """Run the focused off-by-one debugging."""
        logger.info("🚀 DEBUGGING OFF-BY-ONE ERROR: Requesting 5 unread emails")
        logger.info("=" * 70)
        
        # Step 0: Test basic Mail.app access
        logger.info("🔍 Testing basic Mail.app functionality...")
        if not self.test_basic_mail_access():
            logger.error("❌ Basic Mail.app access failed - cannot continue")
            return
        print()
        
        # Step 1: Test simple unread count
        simple_unread = self.test_simple_unread_count()
        print()
        
        # Step 2: Check how many unread emails exist (original method)
        total_unread = self.test_unread_email_count()
        print()
        
        if total_unread < 5:
            logger.warning(f"⚠️ Only {total_unread} unread emails available, but testing limit=5 anyway")
        else:
            logger.info(f"✅ {total_unread} unread emails available, should be able to get 5")
        print()
        
        # Step 3: Test different approaches
        count1 = self.test_approach_1_simple_count(5)
        print()
        
        count2 = self.test_approach_2_range_selection(5)
        print()
        
        count3 = self.test_approach_3_direct_items(5)
        print()
        
        # Summary
        logger.info("📋 SUMMARY:")
        logger.info(f"    Simple unread count: {simple_unread}")
        logger.info(f"    Total unread available: {total_unread}")
        logger.info(f"    Approach 1 (simple loop): {count1}")
        logger.info(f"    Approach 2 (range selection): {count2}")
        logger.info(f"    Approach 3 (direct items): {count3}")
        logger.info("    Expected: 5")
        
        if count1 == 5 and count2 == 5 and count3 == 5:
            logger.info("✅ OFF-BY-ONE ERROR FIXED!")
        else:
            logger.error("❌ OFF-BY-ONE ERROR STILL EXISTS!")
            
        # Try to identify which approach works best
        working_approaches = []
        if count1 == 5:
            working_approaches.append("Simple loop")
        if count2 == 5:
            working_approaches.append("Range selection")
        if count3 == 5:
            working_approaches.append("Direct items")
        
        if working_approaches:
            logger.info(f"✅ Working approaches: {', '.join(working_approaches)}")
        else:
            logger.error("❌ No approaches are working correctly!")

def main():
    """Run the standalone AppleScript debugging."""
    tester = StandaloneAppleScriptTester()
    tester.run_off_by_one_debug()

if __name__ == "__main__":
    main() 