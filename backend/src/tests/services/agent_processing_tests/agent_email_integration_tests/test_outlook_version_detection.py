"""
Test to detect Outlook version (New vs Legacy) and AppleScript support.

This determines if Outlook is running in "New Outlook" (no AppleScript) 
or "Legacy Outlook" (has AppleScript support).
"""

import subprocess
import logging
import time

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def execute_applescript(script: str, description: str = "AppleScript", timeout: int = 10) -> dict:
    """Execute AppleScript directly using subprocess."""
    logger.info(f"🍎 Executing {description}...")
    
    try:
        start_time = time.time()
        
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

def detect_outlook_version():
    """Detect if Outlook is running New or Legacy mode."""
    logger.info("🔍 DETECTING OUTLOOK VERSION (New vs Legacy)")
    logger.info("=" * 60)
    
    # Test 1: Check if basic AppleScript access works
    basic_script = '''
    tell application "Microsoft Outlook"
        return "AppleScript access works"
    end tell
    '''
    
    basic_result = execute_applescript(basic_script, "basic Outlook AppleScript test")
    
    if not basic_result["success"]:
        logger.error("❌ Basic AppleScript access failed - Outlook may not be running")
        return "unknown"
    
    # Test 2: Try to access AppleScript dictionary elements that only work in Legacy
    legacy_test_script = '''
    tell application "Microsoft Outlook"
        try
            -- These instructions only work in Legacy Outlook
            set accountCount to count of accounts
            return "Legacy Outlook detected - account count: " & accountCount
        on error errMsg
            return "New Outlook detected - error: " & errMsg
        end try
    end tell
    '''
    
    legacy_result = execute_applescript(legacy_test_script, "legacy features test")
    
    if legacy_result["success"]:
        if "Legacy Outlook detected" in legacy_result["data"]:
            logger.info("🎯 DETECTED: Legacy Outlook (AppleScript supported)")
            return "legacy"
        elif "New Outlook detected" in legacy_result["data"]:
            logger.info("🎯 DETECTED: New Outlook (AppleScript NOT supported)")
            return "new"
    
    # Test 3: Try another Legacy-specific feature
    messages_test_script = '''
    tell application "Microsoft Outlook"
        try
            set msgCount to count of messages of inbox
            return "Legacy - inbox messages: " & msgCount
        on error errMsg
            return "New - inbox error: " & errMsg
        end try
    end tell
    '''
    
    messages_result = execute_applescript(messages_test_script, "inbox access test")
    
    if messages_result["success"]:
        logger.info(f"📧 Inbox test result: {messages_result['data']}")
        if "Legacy" in messages_result["data"]:
            logger.info("🎯 CONFIRMED: Legacy Outlook")
            return "legacy"
        elif "New" in messages_result["data"]:
            logger.info("🎯 CONFIRMED: New Outlook")
            return "new"
    
    logger.warning("⚠️ Could not definitively determine Outlook version")
    return "unknown"

def provide_solution(version):
    """Provide solution based on detected version."""
    logger.info("\n🔧 SOLUTION RECOMMENDATIONS:")
    logger.info("=" * 60)
    
    if version == "legacy":
        logger.info("✅ You're using Legacy Outlook - AppleScript should work!")
        logger.info("🔍 The AppleScript syntax issue may be elsewhere in our code.")
        
    elif version == "new":
        logger.error("❌ You're using New Outlook - AppleScript is NOT supported!")
        logger.info("🔧 SOLUTION: Switch to Legacy Outlook:")
        logger.info("   1. Open Outlook")
        logger.info("   2. Look for 'Legacy Outlook' toggle and turn it ON")
        logger.info("   3. OR go to Help menu → 'Revert to Legacy Outlook'")
        logger.info("")
        logger.warning("⚠️  WARNING: Legacy Outlook support ends October 2025")
        logger.warning("⚠️  Microsoft has no timeline for New Outlook AppleScript support")
        
    else:
        logger.warning("⚠️ Could not determine version - try switching to Legacy Outlook")
        logger.info("🔧 Try: Help menu → 'Revert to Legacy Outlook'")

def main():
    """Main detection and solution function."""
    version = detect_outlook_version()
    provide_solution(version)
    
    return version

if __name__ == "__main__":
    detected_version = main()
    print(f"\nDetected version: {detected_version}") 