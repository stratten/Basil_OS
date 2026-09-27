import AppKit
import AVFoundation
import ApplicationServices
import CoreGraphics

// MARK: - Permission Management
extension AppDelegate {
    
    @MainActor
    func checkMicrophonePermissions() async {
        let status = AVCaptureDevice.authorizationStatus(for: .audio)
        #if DEBUG
        DevLogger.shared.info("Initial audio permission check", context: "permissions")
        DevLogger.shared.info("Current authorization status: \(status.rawValue)", context: "permissions")
        #endif
        
        switch status {
        case .authorized:
            #if DEBUG
            DevLogger.shared.info("✅ Microphone access is already authorized", context: "permissions")
            #endif
            return  // Exit early if already authorized
            
        case .notDetermined:
            #if DEBUG
            DevLogger.shared.info("🎤 Requesting initial microphone access...", context: "permissions")
            #endif
            // Do not proactively request microphone access at startup.
            // Defer the prompt to onboarding or the first feature use.
            
        case .denied:
            #if DEBUG
            DevLogger.shared.warning("❌ Microphone access is denied in system settings", context: "permissions")
            #endif
            
        case .restricted:
            #if DEBUG
            DevLogger.shared.warning("⚠️ Microphone access is restricted by system policy", context: "permissions")
            #endif
            
        @unknown default:
            #if DEBUG
            DevLogger.shared.error("❓ Unknown microphone permission status: \(status.rawValue)", context: "permissions")
            #endif
        }
    }
    
    @MainActor
    func checkScreenRecordingPermissions() async {
        #if DEBUG
        DevLogger.shared.info("🖥️ Checking screen recording permissions without prompting", context: "permissions")
        #endif
        
        let hasPermission = CGPreflightScreenCaptureAccess()
        
        #if DEBUG
        DevLogger.shared.info("Screen recording permission final status: \(hasPermission ? "granted" : "not granted")", context: "permissions")
        #endif
    }
    
    @MainActor
    private func showScreenRecordingPermissionAlert() {
        let alert = NSAlert()
        alert.messageText = "Screen Recording Permission Required"
        alert.informativeText = """
        Basil needs screen recording permission to capture window content for suggestions.
        
        Please grant permission in System Settings > Privacy & Security > Screen & System Audio Recording.
        
        After granting permission, you may need to restart Basil.
        """
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Open System Settings")
        alert.addButton(withTitle: "Continue Without Permission")
        
        let response = alert.runModal()
        
        if response == .alertFirstButtonReturn {
            // Open System Settings to Screen Recording
            if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture") {
                NSWorkspace.shared.open(url)
            }
        }
        // Don't terminate the app - let user continue even without permission
    }
    
    @MainActor
    func checkSystemAudioPermissions() async {
        // Log bundle identifier information to help diagnose permission issues
        let bundleID = Bundle.main.bundleIdentifier ?? "unknown"
        let bundlePath = Bundle.main.bundlePath
        let executablePath = Bundle.main.executablePath ?? "unknown"
        
        #if DEBUG
        DevLogger.shared.info("🔍 PERMISSIONS CHECK: Current bundle identifier: \(bundleID)", context: "permissions")
        DevLogger.shared.info("🔍 PERMISSIONS CHECK: Bundle path: \(bundlePath)", context: "permissions")
        DevLogger.shared.info("🔍 PERMISSIONS CHECK: Executable path: \(executablePath)", context: "permissions")
        DevLogger.shared.info("🔍 PERMISSIONS CHECK: Process path: \(ProcessInfo.processInfo.processName)", context: "permissions")
        DevLogger.shared.info("Checking system audio recording permissions", context: "permissions")
        #endif
        
        let permissionVerified = CGPreflightScreenCaptureAccess()
        
        #if DEBUG
        DevLogger.shared.info("System audio/screen recording passive permission status: \(permissionVerified ? "granted" : "not granted")", context: "permissions")
        #endif
    }
    
    @MainActor
    func checkAndRequestAccessibilityPermissions() async {
        #if DEBUG
        DevLogger.shared.info("Checking Accessibility permissions...", context: "Permissions")
        #endif

        // First check if we already have permissions (without prompting)
        let accessibilityEnabled = AXIsProcessTrusted()

        if accessibilityEnabled {
            #if DEBUG
            DevLogger.shared.info("✅ Accessibility permissions are already granted.", context: "Permissions")
            #endif
        } else {
            #if DEBUG
            DevLogger.shared.info("❌ AXIsProcessTrusted() reports no accessibility permission", context: "Permissions")
            DevLogger.shared.info("🔍 This could be a dev mode bundle identifier mismatch - testing actual functionality...", context: "Permissions")
            #endif
            
            // In development mode, AXIsProcessTrusted() may return false even when permission is granted
            // due to bundle identifier mismatches. Let's test if accessibility actually works.
            let systemWideElement = AXUIElementCreateSystemWide()
            var frontmostApp: CFTypeRef?
            let testResult = AXUIElementCopyAttributeValue(systemWideElement, kAXFocusedApplicationAttribute as CFString, &frontmostApp)
            
            if testResult == AXError.success {
                #if DEBUG
                DevLogger.shared.info("✅ ACCESSIBILITY WORKING: Despite AXIsProcessTrusted()=false, accessibility API actually works!", context: "Permissions")
                DevLogger.shared.info("🔧 This is likely a dev mode bundle identifier mismatch - continuing with working accessibility", context: "Permissions")
                #endif
                return // Accessibility is actually working, no need to request permission
            }
            
            #if DEBUG
            DevLogger.shared.info("❌ Accessibility API test failed with error: \(testResult.rawValue)", context: "Permissions")
            DevLogger.shared.info("🔧 Need to request accessibility permission...", context: "Permissions")
            #endif
            
            // For dev builds, we need to be more aggressive about triggering permission prompts
            // Since permissions are cleared each time, we should immediately request them
            
            // Primary method: Use AXIsProcessTrustedWithOptions to trigger permission dialog
            let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true]
            let promptResult = AXIsProcessTrustedWithOptions(options as CFDictionary)
            
            #if DEBUG
            DevLogger.shared.info("🔔 AXIsProcessTrustedWithOptions result: \(promptResult)", context: "Permissions")
            #endif
            
            // Secondary method: Also try to trigger via AppleScript to ensure dialog appears
            let testScript = """
            tell application "System Events"
                try
                    set frontApp to name of first application process whose frontmost is true
                    return frontApp
                on error errMsg
                    return "permission_test_failed: " & errMsg
                end try
            end tell
            """
            
            var error: NSDictionary?
            if let appleScript = NSAppleScript(source: testScript) {
                let result = appleScript.executeAndReturnError(&error)
                
                if let error = error {
                    let errorCode = error["NSAppleScriptErrorNumber"] as? Int ?? 0
                    #if DEBUG
                    DevLogger.shared.info("AppleScript accessibility test result - Error code: \(errorCode)", context: "Permissions")
                    if let errorMessage = error["NSAppleScriptErrorMessage"] as? String {
                        DevLogger.shared.info("AppleScript error message: \(errorMessage)", context: "Permissions")
                    }
                    #endif
                    
                    if errorCode == -25211 {
                        #if DEBUG
                        DevLogger.shared.info("🔧 Accessibility permission error (-25211) - checking if already granted in System Settings", context: "Permissions")
                        #endif
                        
                        // Show alert explaining the restart requirement
                        showAccessibilityRestartAlert()
                    }
                } else if let resultString = result.stringValue {
                    #if DEBUG
                    DevLogger.shared.info("✅ Accessibility test successful: \(resultString)", context: "Permissions")
                    #endif
                }
            }
        }
    }
    
    @MainActor
    private func showAccessibilityRestartAlert() {
        let alert = NSAlert()
        alert.messageText = "App Restart Required"
        alert.informativeText = """
        If you've already granted Accessibility permission in System Settings but are still seeing this error, macOS requires the app to be restarted after granting accessibility permission.
        
        This is a normal macOS security requirement.
        
        Please:
        1. Stop the current dev run (Ctrl+C in terminal)
        2. Run ./dev.sh again
        
        If you haven't granted permission yet:
        • Go to System Settings > Privacy & Security > Accessibility
        • Find "BasilClient" in the list and enable it
        • Then restart the app
        """
        alert.alertStyle = .informational
        alert.addButton(withTitle: "Open System Settings")
        alert.addButton(withTitle: "I'll Restart Manually")
        
        let response = alert.runModal()
        if response == .alertFirstButtonReturn {
            // Open System Settings to Accessibility panel
            if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
                NSWorkspace.shared.open(url)
            }
        }
    }

    @MainActor
    private func showAccessibilityPermissionAlert() {
        let alert = NSAlert()
        alert.messageText = "Accessibility Permission Required"
        alert.informativeText = """
        Basil requires Accessibility permission to:
        • Capture screen content for suggestions
        • Simulate keystrokes for text insertion
        • Control UI elements for automation
        
        Please grant permission in System Settings > Privacy & Security > Accessibility.
        The app should appear in the list after this dialog.
        
        Note: After granting permission, you'll need to restart the app.
        """
        alert.alertStyle = .informational
        alert.addButton(withTitle: "Open System Settings")
        alert.addButton(withTitle: "Continue Without Permission")
        
        let response = alert.runModal()
        if response == .alertFirstButtonReturn {
            // Open System Settings to Accessibility panel
            if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
                NSWorkspace.shared.open(url)
            }
        }
    }

    @MainActor
    func checkAndRequestAppleEventsPermissions() async {
        #if DEBUG
        DevLogger.shared.info("Checking Apple Events permissions...", context: "Permissions")
        #endif
        
        // Try to trigger Apple Events permission by sending a simple event to System Events
        // This will show the permission dialog if not already granted
        let script = """
        tell application "System Events"
            return "permission_test"
        end tell
        """
        
        var error: NSDictionary?
        if let appleScript = NSAppleScript(source: script) {
            let result = appleScript.executeAndReturnError(&error)
            
            if let error = error {
                let errorCode = error["NSAppleScriptErrorNumber"] as? Int ?? 0
                #if DEBUG
                DevLogger.shared.info("Apple Events permission check result - Error code: \(errorCode)", context: "Permissions")
                #endif
                
                if errorCode == -1743 {
                    #if DEBUG
                    DevLogger.shared.warning("Apple Events permission denied (-1743). User needs to grant permission in System Settings.", context: "Permissions")
                    #endif
                } else {
                    #if DEBUG
                    DevLogger.shared.warning("Apple Events error: \(error)", context: "Permissions")
                    #endif
                }
            } else if result.stringValue == "permission_test" {
                #if DEBUG
                DevLogger.shared.info("✅ Apple Events permission granted", context: "Permissions")
                #endif
            }
        }
    }
} 