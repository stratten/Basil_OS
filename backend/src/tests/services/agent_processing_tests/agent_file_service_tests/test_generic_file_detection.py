"""
Test Generic File Path Detection Across Applications

Investigates scalable approaches to detecting file information from active windows:
1. Generic window title pattern analysis (primary approach)
2. Enhanced accessibility API probing (fallback)
3. Smart context detection (last resort)

This tests the hypothesis that we can achieve 80-90% coverage with generic patterns
rather than requiring app-specific handling for every application.
"""

import asyncio
import subprocess
import re
import os
import json
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

import pytest

pytestmark = pytest.mark.manual

@dataclass
class WindowInfo:
    """Information extracted from the active window."""
    app_name: str
    bundle_id: str
    window_title: str
    detected_filename: Optional[str] = None
    detected_path: Optional[str] = None
    confidence: float = 0.0
    detection_method: str = "none"

class GenericFileDetector:
    """Test different approaches to generically detecting file information from active windows."""
    
    def __init__(self):
        # Common window title patterns (prioritized by reliability)
        self.title_patterns = [
            # Pattern 1: "filename.ext - AppName" (most common)
            r'^(.+\.[a-zA-Z0-9]+)\s*[-–—]\s*(.+)$',
            
            # Pattern 2: Full path in title
            r'^(/[^/]+/[^/]+/.*\.[a-zA-Z0-9]+)',
            
            # Pattern 3: "filename.ext" (simple)
            r'^([^/\\:*?"<>|]+\.[a-zA-Z0-9]+)$',
            
            # Pattern 4: "AppName - filename.ext"
            r'^(.+?)\s*[-–—]\s*(.+\.[a-zA-Z0-9]+)$',
            
            # Pattern 5: "[Modified] filename.ext - AppName"
            r'^\[.*?\]\s*(.+\.[a-zA-Z0-9]+)\s*[-–—]\s*(.+)$',
            
            # Pattern 6: "AppName: filename.ext"
            r'^(.+?):\s*(.+\.[a-zA-Z0-9]+)$'
        ]
        
        # File extensions that indicate document files
        self.document_extensions = {
            '.txt', '.rtf', '.doc', '.docx', '.pages',
            '.pdf', '.xls', '.xlsx', '.numbers', 
            '.ppt', '.pptx', '.keynote', '.md', '.json',
            '.csv', '.xml', '.html', '.htm'
        }

    async def get_current_window_info(self) -> WindowInfo:
        """Get comprehensive information about the current window."""
        script = '''
        tell application "System Events"
            set frontApp to first process whose frontmost is true
            set appName to displayed name of frontApp
            set bundleID to bundle identifier of frontApp
            
            try
                set windowTitle to title of front window of frontApp
            on error
                set windowTitle to ""
            end try
            
            return appName & "|||" & bundleID & "|||" & windowTitle
        end tell
        '''
        
        try:
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                parts = output.split('|||')
                if len(parts) >= 3:
                    app_name = parts[0]
                    bundle_id = parts[1] 
                    window_title = '|||'.join(parts[2:])  # In case title contains separator
                    
                    return WindowInfo(
                        app_name=app_name,
                        bundle_id=bundle_id,
                        window_title=window_title
                    )
            
            return WindowInfo("Unknown", "Unknown", "")
            
        except Exception as e:
            print(f"Error getting window info: {e}")
            return WindowInfo("Error", "Error", "")

    def analyze_window_title(self, window_info: WindowInfo) -> WindowInfo:
        """Analyze window title using generic patterns to detect filename."""
        title = window_info.window_title.strip()
        
        if not title:
            return window_info
        
        print(f"\n🔍 Analyzing title: '{title}'")
        
        # Try each pattern in order of reliability
        for i, pattern in enumerate(self.title_patterns, 1):
            match = re.search(pattern, title)
            if match:
                groups = match.groups()
                print(f"   ✅ Pattern {i} matched: {groups}")
                
                # Determine which group contains the filename
                filename = self._extract_filename_from_groups(groups, pattern)
                
                if filename and self._is_likely_filename(filename):
                    window_info.detected_filename = filename
                    window_info.confidence = 1.0 - (i * 0.1)  # Higher confidence for earlier patterns
                    window_info.detection_method = f"title_pattern_{i}"
                    
                    # Try to construct full path
                    potential_path = self._construct_potential_path(filename)
                    if potential_path:
                        window_info.detected_path = potential_path
                    
                    return window_info
        
        print("   ❌ No title patterns matched")
        return window_info

    def _extract_filename_from_groups(self, groups: Tuple[str, ...], pattern: str) -> Optional[str]:
        """Extract the most likely filename from regex groups."""
        for group in groups:
            if self._is_likely_filename(group):
                return group.strip()
        return None

    def _is_likely_filename(self, text: str) -> bool:
        """Check if text looks like a filename."""
        if not text or len(text) > 255:  # Max filename length
            return False
        
        # Must have an extension
        if '.' not in text:
            return False
        
        # Check for valid extension
        ext = Path(text).suffix.lower()
        if ext in self.document_extensions:
            return True
        
        # Check for other common extensions
        if len(ext) >= 2 and ext[1:].isalnum():
            return True
        
        return False

    def _construct_potential_path(self, filename: str) -> Optional[str]:
        """Try to construct a full path for the filename."""
        # This would integrate with our existing file search
        # For now, just return the filename
        return filename

    async def probe_accessibility_info(self, window_info: WindowInfo) -> WindowInfo:
        """Use accessibility APIs to probe for document information."""
        if window_info.detected_filename:
            return window_info  # Already found via title
        
        script = f'''
        tell application "System Events"
            try
                set frontApp to first process whose frontmost is true
                set frontWindow to front window of frontApp
                
                -- Try to get document-related accessibility attributes
                set windowInfo to {{}}
                
                try
                    set documentInfo to value of attribute "AXDocument" of frontWindow
                    set end of windowInfo to ("AXDocument: " & documentInfo)
                end try
                
                try
                    set titleInfo to value of attribute "AXTitle" of frontWindow  
                    set end of windowInfo to ("AXTitle: " & titleInfo)
                end try
                
                try
                    set valueInfo to value of attribute "AXValue" of frontWindow
                    set end of windowInfo to ("AXValue: " & valueInfo)
                end try
                
                try
                    set roleDesc to value of attribute "AXRoleDescription" of frontWindow
                    set end of windowInfo to ("AXRoleDescription: " & roleDesc)
                end try
                
                return windowInfo
            on error errMsg
                return {{"Error: " & errMsg}}
            end try
        end tell
        '''
        
        try:
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                print(f"\n🔍 Accessibility probe results:")
                print(f"   {output}")
                
                # Look for file-like information in the accessibility data
                filename = self._extract_filename_from_accessibility(output)
                if filename:
                    window_info.detected_filename = filename
                    window_info.confidence = 0.7
                    window_info.detection_method = "accessibility_probe"
            
        except Exception as e:
            print(f"Error probing accessibility: {e}")
        
        return window_info

    def _extract_filename_from_accessibility(self, accessibility_output: str) -> Optional[str]:
        """Extract filename from accessibility API output."""
        # Look for file-like patterns in the accessibility data
        for line in accessibility_output.split(','):
            line = line.strip()
            
            # Look for anything that looks like a filename
            filename_match = re.search(r'([^/\\:*?"<>|]+\.[a-zA-Z0-9]+)', line)
            if filename_match:
                potential_filename = filename_match.group(1)
                if self._is_likely_filename(potential_filename):
                    return potential_filename
        
        return None

    async def test_comprehensive_detection(self) -> Dict[str, Any]:
        """Run comprehensive file detection test on current window."""
        print("🚀 Starting Comprehensive File Detection Test")
        print("=" * 60)
        
        # Step 1: Get basic window information
        print("\n📋 Step 1: Getting Window Information")
        window_info = await self.get_current_window_info()
        
        print(f"   App: {window_info.app_name}")
        print(f"   Bundle ID: {window_info.bundle_id}")
        print(f"   Window Title: '{window_info.window_title}'")
        
        # Step 2: Analyze window title
        print("\n📋 Step 2: Analyzing Window Title")
        window_info = self.analyze_window_title(window_info)
        
        # Step 3: Probe accessibility if needed
        if not window_info.detected_filename:
            print("\n📋 Step 3: Probing Accessibility APIs")
            window_info = await self.probe_accessibility_info(window_info)
        else:
            print("\n📋 Step 3: Skipping accessibility probe (filename already detected)")
        
        # Results
        print("\n🎯 DETECTION RESULTS")
        print("=" * 40)
        
        if window_info.detected_filename:
            print(f"✅ SUCCESS: Detected filename")
            print(f"   Filename: {window_info.detected_filename}")
            print(f"   Method: {window_info.detection_method}")
            print(f"   Confidence: {window_info.confidence:.1%}")
            if window_info.detected_path:
                print(f"   Path: {window_info.detected_path}")
        else:
            print("❌ FAILED: No filename detected")
            print("   Possible fallbacks:")
            print("   - OCR screen content for filenames")
            print("   - Search for common document patterns")
            print("   - Ask user to specify file")
        
        return {
            "success": bool(window_info.detected_filename),
            "app_name": window_info.app_name,
            "bundle_id": window_info.bundle_id,
            "window_title": window_info.window_title,
            "detected_filename": window_info.detected_filename,
            "detected_path": window_info.detected_path,
            "detection_method": window_info.detection_method,
            "confidence": window_info.confidence
        }

async def test_multiple_scenarios():
    """Test file detection across different scenarios."""
    detector = GenericFileDetector()
    
    print("🧪 Generic File Detection Test Suite")
    print("=" * 50)
    print()
    print("Instructions:")
    print("1. Open different applications with documents")
    print("2. Run this test while each app is active")
    print("3. See how well generic detection works")
    print()
    print("Testing current window...")
    
    result = await detector.test_comprehensive_detection()
    
    print("\n" + "=" * 60)
    print("📊 CONCLUSION:")
    
    if result["success"]:
        print(f"✅ Generic detection SUCCEEDED for {result['app_name']}")
        print(f"   This demonstrates the viability of pattern-based detection")
    else:
        print(f"❌ Generic detection FAILED for {result['app_name']}")
        print(f"   This app may need specific handling or fallback methods")
    
    return result

async def demo_pattern_effectiveness():
    """Demonstrate how effective generic patterns are across realistic window titles."""
    detector = GenericFileDetector()
    
    # Realistic window titles from various applications
    test_cases = [
        # Microsoft Office
        ("Microsoft Word", "Document1.docx - Microsoft Word", True),
        ("Microsoft Excel", "Budget2024.xlsx - Microsoft Excel", True),
        ("Microsoft PowerPoint", "Presentation.pptx - Microsoft PowerPoint", True),
        
        # Adobe Products  
        ("Adobe Acrobat", "Report.pdf - Adobe Acrobat Pro", True),
        ("Adobe Photoshop", "design.psd - Adobe Photoshop 2024", True),
        
        # Text Editors
        ("Visual Studio Code", "config.json - my-project - Visual Studio Code", True),
        ("Sublime Text", "script.py - Sublime Text", True),
        ("TextEdit", "notes.txt", True),
        
        # Browsers (no file context)
        ("Safari", "GitHub - mozilla/firefox", False),
        ("Chrome", "Google Search", False),
        
        # Apple Apps
        ("Pages", "Letter.pages - Pages", True),
        ("Numbers", "Calculations.numbers - Numbers", True),
        ("Keynote", "Slides.keynote - Keynote", True),
        
        # PDF Viewers (alternative)
        ("Preview", "manual.pdf", True),
        ("PDF Expert", "contract.pdf - PDF Expert", True),
        
        # Alternative patterns
        ("Finder", "/Users/user/Documents/file.txt", True),
        ("Terminal", "user@mac: ~/Documents/project", False),
        
        # Edge cases
        ("Custom App", "[Modified] document.txt - CustomApp", True),
        ("Another App", "MyApp: important.pdf", True),
        ("Yet Another", "data-file.csv (Read-Only) - Editor", True),
    ]
    
    print("🧪 Pattern Effectiveness Demonstration")
    print("=" * 60)
    print("Testing generic patterns against realistic window titles...")
    print()
    
    successful = 0
    total = 0
    
    for app_name, window_title, should_detect in test_cases:
        total += 1
        
        # Create window info
        window_info = WindowInfo(
            app_name=app_name,
            bundle_id=f"com.example.{app_name.lower().replace(' ', '')}",
            window_title=window_title
        )
        
        # Test pattern detection
        result = detector.analyze_window_title(window_info)
        detected = bool(result.detected_filename)
        
        # Evaluate result
        if detected == should_detect:
            successful += 1
            status = "✅ CORRECT"
        else:
            status = "❌ WRONG"
        
        expected_str = "SHOULD detect" if should_detect else "should NOT detect"
        detected_str = f"detected: {result.detected_filename}" if detected else "no detection"
        
        print(f"{status} | {app_name:15} | {window_title:35} | {expected_str:15} | {detected_str}")
    
    print()
    print("=" * 60)
    print(f"📊 RESULTS: {successful}/{total} ({successful/total:.1%}) correct classifications")
    print()
    
    if successful/total >= 0.85:
        print("✅ EXCELLENT: Generic patterns achieve >85% accuracy")
        print("   This validates the scalable approach!")
    elif successful/total >= 0.70:
        print("⚠️  GOOD: Generic patterns achieve >70% accuracy") 
        print("   Viable with some fallback handling")
    else:
        print("❌ POOR: Generic patterns below 70% accuracy")
        print("   May need more app-specific handling")
    
    return successful/total

async def run_comprehensive_tests():
    """Run both live detection and pattern demonstration."""
    print("🔬 COMPREHENSIVE FILE DETECTION ANALYSIS")
    print("=" * 70)
    print()
    
    # First, test current window
    print("PART 1: Live Window Detection")
    print("-" * 30)
    detector = GenericFileDetector()
    live_result = await detector.test_comprehensive_detection()
    
    print("\n" * 2)
    
    # Then, demonstrate pattern effectiveness
    print("PART 2: Pattern Effectiveness Analysis")  
    print("-" * 40)
    pattern_accuracy = await demo_pattern_effectiveness()
    
    print("\n" * 2)
    print("🎯 FINAL CONCLUSION")
    print("=" * 50)
    
    if pattern_accuracy >= 0.85:
        print("✅ RECOMMENDATION: Implement generic pattern-based detection")
        print("   • Primary: Window title pattern matching")
        print("   • Fallback: Accessibility API probing") 
        print("   • Last resort: OCR + file search")
        print()
        print("   This approach will scale to handle most applications")
        print("   without requiring app-specific patterns.")
    else:
        print("⚠️  RECOMMENDATION: Hybrid approach needed")
        print("   • Generic patterns for common cases")
        print("   • Specific handling for problem applications")
        print("   • Fallback methods for edge cases")
    
    return {
        "live_detection_success": live_result["success"],
        "pattern_accuracy": pattern_accuracy,
        "recommendation": "generic" if pattern_accuracy >= 0.85 else "hybrid"
    }

async def run_generic_detection_test():
    """Main test runner."""
    try:
        result = await run_comprehensive_tests()
        print(f"\n📋 Test completed. Success: {result['live_detection_success']}")
        return result
    except KeyboardInterrupt:
        print("\n⚠️ Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_generic_detection_test()) 