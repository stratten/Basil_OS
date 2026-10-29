"""
Test Window File Detection Capabilities

Investigates what file information can be extracted from:
1. Generic window titles (via System Events)
2. Application-specific AppleScript
3. Window title pattern analysis

This helps determine whether we need different handling for different applications.
"""

import asyncio
import subprocess
import re
import os
from pathlib import Path
from typing import Dict, Any, Optional, List

import pytest

pytestmark = pytest.mark.manual

class WindowFileDetectionTester:
    """Test different approaches to detecting file information from active windows."""
    
    def __init__(self):
        self.app_patterns = {
            'Microsoft Word': [
                r'(.+?)\.docx? - Microsoft Word',
                r'(.+?) - Microsoft Word',
                r'Document\d+ - Microsoft Word'
            ],
            'Adobe Acrobat Pro': [
                r'(.+?)\.pdf - Adobe Acrobat',
                r'(.+?) - Adobe Acrobat'
            ],
            'TextEdit': [
                r'(.+?)\.txt — Edited',
                r'(.+?) — Edited',
                r'(.+?)\.txt'
            ],
            'Preview': [
                r'(.+?)\.(png|jpg|jpeg|pdf|tiff) - Preview',
                r'(.+?) - Preview'
            ],
            'Pages': [
                r'(.+?) - Pages',
                r'(.+?)'  # Pages often just shows document name
            ],
            'Finder': [
                r'(.+)'  # Finder shows folder/file names directly
            ]
        }
    
    async def test_generic_window_detection(self) -> Dict[str, Any]:
        """Test what we can extract using generic System Events AppleScript."""
        script = '''
        tell application "System Events"
            set frontProcess to first process whose frontmost is true
            set frontAppName to name of frontProcess
            set frontAppId to bundle identifier of frontProcess
            
            if (count of windows of frontProcess) > 0 then
                set frontWindow to window 1 of frontProcess
                set winTitle to name of frontWindow
                return frontAppName & "|" & winTitle & "|" & frontAppId
            else
                return frontAppName & "|No Window|" & frontAppId
            end if
        end tell
        '''
        
        try:
            process = await asyncio.create_subprocess_exec(
                'osascript', '-e', script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                output = stdout.decode().strip()
                parts = output.split('|')
                return {
                    'success': True,
                    'app_name': parts[0] if len(parts) > 0 else 'Unknown',
                    'window_title': parts[1] if len(parts) > 1 else 'Unknown',
                    'bundle_id': parts[2] if len(parts) > 2 else 'Unknown',
                    'raw_output': output
                }
            else:
                return {
                    'success': False,
                    'error': stderr.decode()
                }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def extract_filename_from_title(self, app_name: str, window_title: str) -> Optional[str]:
        """Extract potential filename from window title using app-specific patterns."""
        if app_name not in self.app_patterns:
            return None
        
        patterns = self.app_patterns[app_name]
        for pattern in patterns:
            match = re.search(pattern, window_title)
            if match:
                return match.group(1).strip()
        
        return None
    
    async def test_word_specific_detection(self) -> Dict[str, Any]:
        """Test Microsoft Word specific file path detection."""
        script = '''
        tell application "Microsoft Word"
            if (count of documents) > 0 then
                set activeDoc to active document
                try
                    set docPath to full name of activeDoc
                    set docName to name of activeDoc
                    return "SUCCESS|" & docPath & "|" & docName
                on error errMsg
                    return "ERROR|" & errMsg & "|"
                end try
            else
                return "NO_DOCS||"
            end if
        end tell
        '''
        
        return await self._execute_app_specific_script(script, "Microsoft Word")
    
    async def test_acrobat_specific_detection(self) -> Dict[str, Any]:
        """Test Adobe Acrobat specific file path detection."""
        script = '''
        tell application "Adobe Acrobat Pro"
            if (count of documents) > 0 then
                try
                    set activeDoc to active document
                    set docPath to file path of activeDoc
                    set docName to name of activeDoc
                    return "SUCCESS|" & docPath & "|" & docName
                on error errMsg
                    return "ERROR|" & errMsg & "|"
                end try
            else
                return "NO_DOCS||"
            end if
        end tell
        '''
        
        return await self._execute_app_specific_script(script, "Adobe Acrobat Pro")
    
    async def test_finder_specific_detection(self) -> Dict[str, Any]:
        """Test Finder specific selected file detection."""
        script = '''
        tell application "Finder"
            set selectedItems to selection
            if (count of selectedItems) > 0 then
                try
                    set selectedFile to item 1 of selectedItems
                    set filePath to POSIX path of (selectedFile as alias)
                    set fileName to name of selectedFile
                    return "SUCCESS|" & filePath & "|" & fileName
                on error errMsg
                    return "ERROR|" & errMsg & "|"
                end try
            else
                return "NO_SELECTION||"
            end if
        end tell
        '''
        
        return await self._execute_app_specific_script(script, "Finder")
    
    async def _execute_app_specific_script(self, script: str, app_name: str) -> Dict[str, Any]:
        """Execute application-specific AppleScript and parse results."""
        try:
            process = await asyncio.create_subprocess_exec(
                'osascript', '-e', script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                output = stdout.decode().strip()
                parts = output.split('|')
                status = parts[0] if len(parts) > 0 else 'UNKNOWN'
                
                if status == 'SUCCESS':
                    return {
                        'success': True,
                        'app_name': app_name,
                        'file_path': parts[1] if len(parts) > 1 else '',
                        'file_name': parts[2] if len(parts) > 2 else '',
                        'method': 'app_specific'
                    }
                elif status == 'NO_DOCS' or status == 'NO_SELECTION':
                    return {
                        'success': False,
                        'app_name': app_name,
                        'reason': 'no_documents_open',
                        'method': 'app_specific'
                    }
                else:  # ERROR
                    return {
                        'success': False,
                        'app_name': app_name,
                        'error': parts[1] if len(parts) > 1 else 'Unknown error',
                        'method': 'app_specific'
                    }
            else:
                return {
                    'success': False,
                    'app_name': app_name,
                    'error': stderr.decode(),
                    'method': 'app_specific'
                }
        except Exception as e:
            return {
                'success': False,
                'app_name': app_name,
                'error': str(e),
                'method': 'app_specific'
            }

async def test_current_window_file_detection():
    """Test file detection capabilities on whatever window is currently active."""
    tester = WindowFileDetectionTester()
    
    print("🔍 Testing Window File Detection Capabilities")
    print("=" * 60)
    
    # Test 1: Generic window detection
    print("\n📋 GENERIC WINDOW DETECTION (System Events)")
    generic_result = await tester.test_generic_window_detection()
    
    if generic_result['success']:
        print(f"✅ App: {generic_result['app_name']}")
        print(f"✅ Window Title: {generic_result['window_title']}")
        print(f"✅ Bundle ID: {generic_result['bundle_id']}")
        
        # Try to extract filename from window title
        filename = tester.extract_filename_from_title(
            generic_result['app_name'], 
            generic_result['window_title']
        )
        
        if filename:
            print(f"✅ Extracted Filename: {filename}")
        else:
            print(f"⚠️  Could not extract filename from title pattern")
    else:
        print(f"❌ Generic detection failed: {generic_result['error']}")
        return
    
    # Test 2: Application-specific detection based on detected app
    app_name = generic_result['app_name']
    print(f"\n🎯 APPLICATION-SPECIFIC DETECTION ({app_name})")
    
    if 'Microsoft Word' in app_name:
        app_result = await tester.test_word_specific_detection()
    elif 'Adobe Acrobat' in app_name:
        app_result = await tester.test_acrobat_specific_detection()
    elif 'Finder' in app_name:
        app_result = await tester.test_finder_specific_detection()
    else:
        print(f"⚠️  No specific detection available for {app_name}")
        app_result = None
    
    if app_result:
        if app_result['success']:
            print(f"✅ File Path: {app_result['file_path']}")
            print(f"✅ File Name: {app_result['file_name']}")
        else:
            print(f"❌ App-specific detection failed: {app_result.get('error', app_result.get('reason', 'Unknown'))}")
    
    # Test 3: Comparison and recommendations
    print(f"\n📊 DETECTION STRATEGY RECOMMENDATIONS")
    print(f"Generic window title method: {'✅ Success' if filename else '❌ Failed'}")
    print(f"App-specific method: {'✅ Success' if app_result and app_result['success'] else '❌ Failed/Not Available'}")
    
    if filename and app_result and app_result['success']:
        print(f"🎯 BOTH methods work - can use generic as fallback")
        print(f"   Generic extracted: '{filename}'")
        print(f"   App-specific got: '{app_result['file_path']}'")
    elif filename:
        print(f"🎯 GENERIC method sufficient - window title parsing works")
    elif app_result and app_result['success']:
        print(f"🎯 APP-SPECIFIC method required - window title insufficient")
    else:
        print(f"🎯 NEED FALLBACK - neither method worked reliably")

if __name__ == "__main__":
    print("🚀 Window File Detection Test")
    print("Open a document in any supported app, then run this script")
    print()
    
    asyncio.run(test_current_window_file_detection()) 