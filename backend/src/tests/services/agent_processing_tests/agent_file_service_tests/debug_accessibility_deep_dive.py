"""
Debug Accessibility APIs - Deep Dive

This script explores what accessibility information different applications expose,
helping us understand if we can extract actual file paths or document metadata
directly from accessibility APIs rather than relying on fallback search.

Usage: Open different document applications and run this to see their accessibility data.
"""

import asyncio
import subprocess
import time
import sys
import os

# Add project root to Python path
project_root = os.path.join(os.path.dirname(__file__), '../../../..')
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))

from api.services.agent_processing.tools.direct_application_interactions.file_system.identification_retrieval.file_context_detection_service import FileContextDetectionService

class AccessibilityDeepDive:
    """Explore accessibility APIs across different applications."""
    
    def __init__(self):
        self.detection_service = FileContextDetectionService()

    async def run_comprehensive_accessibility_scan(self):
        """Run a comprehensive accessibility scan with detailed output."""
        print("🔍 COMPREHENSIVE ACCESSIBILITY API DEEP DIVE")
        print("=" * 60)
        print()
        
        # Get current window info
        window_info = await self.detection_service._get_window_info()
        
        if not window_info.get("success"):
            print("❌ Could not get window information")
            print(f"Error: {window_info.get('error', 'Unknown error')}")
            return
        
        app_name = window_info["app_name"]
        bundle_id = window_info["bundle_id"]
        window_title = window_info["window_title"]
        
        print(f"🖥️  CURRENT APPLICATION:")
        print(f"   App: {app_name}")
        print(f"   Bundle ID: {bundle_id}")
        print(f"   Window: {window_title}")
        print()
        
        # Run our enhanced accessibility probe
        print("🔍 RUNNING ENHANCED ACCESSIBILITY PROBE...")
        print("-" * 50)
        
        accessibility_output = await self._run_enhanced_accessibility_probe()
        
        if accessibility_output:
            print("📊 RAW ACCESSIBILITY OUTPUT:")
            print("=" * 40)
            print(accessibility_output)
            print("=" * 40)
            print()
            
            # Analyze the output
            await self._analyze_accessibility_output(accessibility_output, app_name)
        else:
            print("❌ No accessibility output received")
        
        print()
        print("🎯 ANALYSIS COMPLETE")

    async def _run_enhanced_accessibility_probe(self) -> str:
        """Run the enhanced accessibility probe and return raw output."""
        script = '''
        tell application "System Events"
            try
                set frontApp to first process whose frontmost is true
                set frontWindow to front window of frontApp
                
                set windowInfo to {}
                
                -- Try multiple accessibility attributes that might contain file information
                set attributesToCheck to {"AXDocument", "AXValue", "AXFilename", "AXTitle", "AXURL", "AXPath", "AXRepresentedFilename", "AXURLString", "AXFileReference", "AXProxy", "AXRepresentedURL"}
                
                -- Level 1: Check window attributes
                set end of windowInfo to "=== WINDOW LEVEL ==="
                repeat with attributeName in attributesToCheck
                    try
                        set attributeValue to value of attribute attributeName of frontWindow
                        if attributeValue is not missing value and attributeValue is not "" then
                            set end of windowInfo to (attributeName & ": " & attributeValue)
                        end if
                    on error
                        -- Skip this attribute if not available
                    end try
                end repeat
                
                -- Level 2: Check all UI elements in the window  
                set end of windowInfo to "=== UI ELEMENTS LEVEL ==="
                try
                    set allUIElements to every UI element of frontWindow
                    set elementCount to count of allUIElements
                    set end of windowInfo to ("Found " & elementCount & " UI elements")
                    
                    -- Check first 15 UI elements for document attributes
                    set maxElements to 15
                    if elementCount < maxElements then set maxElements to elementCount
                    
                    repeat with i from 1 to maxElements
                        try
                            set currentElement to item i of allUIElements
                            set elementRole to value of attribute "AXRole" of currentElement
                            set elementDescription to ""
                            try
                                set elementDescription to value of attribute "AXDescription" of currentElement
                            end try
                            
                            set foundAttributes to {}
                            repeat with attributeName in attributesToCheck
                                try
                                    set attributeValue to value of attribute attributeName of currentElement
                                    if attributeValue is not missing value and attributeValue is not "" then
                                        set end of foundAttributes to (attributeName & ": " & attributeValue)
                                    end if
                                on error
                                    -- Skip this attribute if not available
                                end try
                            end repeat
                            
                            if (count of foundAttributes) > 0 then
                                set end of windowInfo to ("Element" & i & " (" & elementRole & ", '" & elementDescription & "'):")
                                repeat with attr in foundAttributes
                                    set end of windowInfo to ("  " & attr)
                                end repeat
                            end if
                        on error
                            -- Skip problematic elements
                        end try
                    end repeat
                end try
                
                -- Level 3: Deep dive - check specific element types
                set end of windowInfo to "=== DEEP PROBE ==="
                
                -- Check scroll areas
                try
                    set scrollAreas to (every UI element of frontWindow whose value of attribute "AXRole" is "AXScrollArea")
                    if (count of scrollAreas) > 0 then
                        set end of windowInfo to ("Found " & (count of scrollAreas) & " scroll areas")
                        repeat with i from 1 to (count of scrollAreas)
                            set scrollArea to item i of scrollAreas
                            repeat with attributeName in attributesToCheck
                                try
                                    set attributeValue to value of attribute attributeName of scrollArea
                                    if attributeValue is not missing value and attributeValue is not "" then
                                        set end of windowInfo to ("ScrollArea" & i & "_" & attributeName & ": " & attributeValue)
                                    end if
                                on error
                                end try
                            end repeat
                        end repeat
                    end if
                end try
                
                -- Check text elements
                try
                    set textElements to (every UI element of frontWindow whose value of attribute "AXRole" is in {"AXTextField", "AXStaticText", "AXTextArea"})
                    set textCount to count of textElements
                    if textCount > 0 then
                        set end of windowInfo to ("Found " & textCount & " text elements")
                        set maxTextElements to 8
                        if textCount < maxTextElements then set maxTextElements to textCount
                        
                        repeat with i from 1 to maxTextElements
                            try
                                set textElement to item i of textElements
                                set textValue to value of textElement
                                set textRole to value of attribute "AXRole" of textElement
                                if textValue is not missing value and length of (textValue as string) > 5 then
                                    set end of windowInfo to ("Text" & i & " (" & textRole & "): " & textValue)
                                end if
                            on error
                            end try
                        end repeat
                    end if
                end try
                
                -- Check for web areas (for browser-based docs)
                try
                    set webAreas to (every UI element of frontWindow whose value of attribute "AXRole" is "AXWebArea")
                    if (count of webAreas) > 0 then
                        set end of windowInfo to ("Found " & (count of webAreas) & " web areas")
                        repeat with i from 1 to (count of webAreas)
                            set webArea to item i of webAreas
                            repeat with attributeName in attributesToCheck
                                try
                                    set attributeValue to value of attribute attributeName of webArea
                                    if attributeValue is not missing value and attributeValue is not "" then
                                        set end of windowInfo to ("WebArea" & i & "_" & attributeName & ": " & attributeValue)
                                    end if
                                on error
                                end try
                            end repeat
                        end repeat
                    end if
                end try
                
                return windowInfo as string
            on error errMsg
                return "ERROR: " & errMsg
            end try
        end tell
        '''
        
        try:
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True,
                timeout=15
            )
            
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                return f"AppleScript Error: {result.stderr}"
                
        except Exception as e:
            return f"Exception: {e}"

    async def _analyze_accessibility_output(self, output: str, app_name: str):
        """Analyze the accessibility output for useful patterns."""
        print("🧠 ACCESSIBILITY ANALYSIS:")
        print("-" * 30)
        
        lines = output.split('\n') if output else []
        
        # Count different types of information found
        file_paths = []
        urls = []
        filenames = []
        interesting_text = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Look for file paths
            if ('AXDocument:' in line or 'AXURL:' in line or 'AXPath:' in line) and ('/' in line):
                file_paths.append(line)
            
            # Look for URLs
            elif 'file://' in line or 'http' in line:
                urls.append(line)
            
            # Look for filenames with extensions
            elif any(ext in line.lower() for ext in ['.pdf', '.doc', '.txt', '.xls', '.ppt']):
                filenames.append(line)
            
            # Look for interesting text content
            elif len(line) > 20 and any(word in line.lower() for word in ['plan', 'report', 'document', 'implementation']):
                interesting_text.append(line)
        
        print(f"📁 File Paths Found: {len(file_paths)}")
        for path in file_paths[:3]:  # Show first 3
            print(f"   {path}")
        
        print(f"🔗 URLs Found: {len(urls)}")
        for url in urls[:3]:  # Show first 3
            print(f"   {url}")
        
        print(f"📄 Filenames Found: {len(filenames)}")
        for filename in filenames[:3]:  # Show first 3
            print(f"   {filename}")
        
        print(f"💬 Interesting Text: {len(interesting_text)}")
        for text in interesting_text[:3]:  # Show first 3
            print(f"   {text[:80]}...")
        
        # Check if we found anything useful
        total_useful = len(file_paths) + len(urls) + len(filenames)
        print()
        print(f"🎯 USEFULNESS SCORE: {total_useful} useful items found")
        
        if total_useful > 0:
            print("✅ This application exposes useful file information via accessibility!")
        else:
            print("⚠️  This application doesn't expose much file info via accessibility")
        
        print()
        print(f"📱 For {app_name}:")
        if file_paths:
            print("   → Direct file paths available!")
        elif filenames:
            print("   → Filenames available, could be combined with search")
        else:
            print("   → Fallback search strategy is best approach")

async def run_accessibility_exploration():
    """Run the accessibility exploration with countdown."""
    dive = AccessibilityDeepDive()
    
    print("🔬 ACCESSIBILITY API DEEP DIVE")
    print("=" * 50)
    print()
    print("⏰ COUNTDOWN: Switch to document window in...")
    
    # 10 second countdown
    for i in range(10, 0, -1):
        print(f"   {i} seconds - Open a document and make it active!")
        await asyncio.sleep(1)
    
    print("   🚀 STARTING ACCESSIBILITY SCAN NOW!")
    print()
    
    await dive.run_comprehensive_accessibility_scan()

if __name__ == "__main__":
    print("🔬 Accessibility API Deep Dive Tool")
    print("=" * 40)
    
    try:
        asyncio.run(run_accessibility_exploration())
    except KeyboardInterrupt:
        print("\n⚠️ Scan interrupted by user")
    except Exception as e:
        print(f"\n❌ Scan failed: {e}")
        import traceback
        traceback.print_exc() 