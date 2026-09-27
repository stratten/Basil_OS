import Foundation
import AppKit

/// Service for capturing window screenshots using AppleScript executed directly in Swift
/// This eliminates the Python subprocess permission issues by using app-level permissions
@MainActor
class WindowCaptureService: ObservableObject {
    static let shared = WindowCaptureService()
    
    // MARK: - Result Types
    
    struct CaptureResult {
        let success: Bool
        let imagePath: String?
        let appName: String
        let windowTitle: String
        let bundleIdentifier: String?
        let policySkipped: Bool
        let error: String?
        let perceptualHash: String?
        
        static func success(
            imagePath: String,
            appName: String,
            windowTitle: String,
            bundleIdentifier: String?,
            perceptualHash: String? = nil
        ) -> CaptureResult {
            CaptureResult(
                success: true,
                imagePath: imagePath,
                appName: appName,
                windowTitle: windowTitle,
                bundleIdentifier: bundleIdentifier,
                policySkipped: false,
                error: nil,
                perceptualHash: perceptualHash
            )
        }
        
        static func failure(
            appName: String,
            windowTitle: String,
            bundleIdentifier: String? = nil,
            error: String
        ) -> CaptureResult {
            CaptureResult(
                success: false,
                imagePath: nil,
                appName: appName,
                windowTitle: windowTitle,
                bundleIdentifier: bundleIdentifier,
                policySkipped: false,
                error: error,
                perceptualHash: nil
            )
        }

        static func skipped(appName: String, bundleIdentifier: String, reason: String) -> CaptureResult {
            CaptureResult(
                success: false,
                imagePath: nil,
                appName: appName,
                windowTitle: "",
                bundleIdentifier: bundleIdentifier,
                policySkipped: true,
                error: reason,
                perceptualHash: nil
            )
        }
    }

    static func escapedAppleScriptString(_ value: String) -> String {
        value
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
    }

    static func automaticCaptureExcludedBundleIDs(
        captureReason: String,
        rawBundleIDs: [String]
    ) -> Set<String> {
        guard captureReason == "automatic activity capture" else { return [] }

        var normalizedByKey: [String: String] = [:]
        for rawBundleID in rawBundleIDs {
            let trimmed = rawBundleID.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { continue }
            let parentBundleID = AudioAppNameResolver.parentBundleID(from: trimmed)
            let key = parentBundleID.lowercased()
            if normalizedByKey[key] == nil {
                normalizedByKey[key] = parentBundleID
            }
        }
        return Set(normalizedByKey.values)
    }
    
    /// Base AppleScript template; exclusion list is injected via `makeAppleScript`.
    private let appleScriptTemplate = """
    tell application "System Events"
        -- Get frontmost process
        set frontProcess to first process whose frontmost is true
        set frontAppName to name of frontProcess

        set frontBundleID to "unknown"
        try
            set frontBundleID to bundle identifier of frontProcess
        end try

        set excludedBundleIDs to __EXCLUDED_BUNDLE_IDS__
        ignoring case
            if excludedBundleIDs contains frontBundleID then
                return frontAppName & "||" & frontBundleID & "|policy_skip:excluded_app"
            end if
        end ignoring

        -- Check if process has windows
        if (count of windows of frontProcess) is 0 then
            return frontAppName & "|No Window|" & frontBundleID & "|no_capture"
        end if

        -- Get window info
        set frontWindow to window 1 of frontProcess
        set winTitle to "Unknown"
        try
            set winTitle to name of frontWindow
        on error errMsg
            -- Continue with "Unknown" title
        end try
        
        -- CRITICAL: Check for missing value (Chrome/Edge PWAs return missing value instead of string)
        if winTitle is missing value then
            set winTitle to "Unknown"
        end if
        
        -- Replace pipe characters in window title to prevent parsing issues
        set AppleScript's text item delimiters to "|"
        set winTitleParts to every text item of winTitle
        set AppleScript's text item delimiters to "⎮"  -- Use a visually similar but different character
        set winTitle to winTitleParts as string
        set AppleScript's text item delimiters to ""  -- Reset delimiters
        
        -- Get window position and size
        try
            set windowPosition to position of frontWindow
            set windowSize to size of frontWindow
            
            set xPos to item 1 of windowPosition
            set yPos to item 2 of windowPosition
            set winWidth to item 1 of windowSize
            set winHeight to item 2 of windowSize
            
            set timestamp to do shell script "/bin/date +%Y%m%d_%H%M%S"
            set tempDir to POSIX path of (path to home folder) & "/.basil/data/temp/"
            do shell script "/bin/mkdir -p " & quoted form of tempDir
            set capturePath to tempDir & "capture_" & timestamp & ".png"
            
            -- Use coordinates method - most reliable and non-interactive
            set captureCmd to "screencapture -x -R " & xPos & "," & yPos & "," & winWidth & "," & winHeight & " " & quoted form of capturePath
            
            -- Execute screencapture and capture any error output
            try
                set captureResult to do shell script captureCmd & " 2>&1"
                delay 0.2
                
                -- Check if file was created and get its size
                try
                    set fileExists to do shell script "[ -f " & quoted form of capturePath & " ] && echo 'true' || echo 'false'"
                    if fileExists is "true" then
                        set fileSize to do shell script "/usr/bin/stat -f%z " & quoted form of capturePath
                        -- Check if file is suspiciously small (likely a permission issue)
                        if (fileSize as integer) < 1000 then
                            -- Try to detect if it's a blank/desktop capture due to permissions
                            return frontAppName & "|" & winTitle & "|" & frontBundleID & "|error: screen recording permission likely denied - captured file too small (" & fileSize & " bytes)"
                        else
                            return frontAppName & "|" & winTitle & "|" & frontBundleID & "|" & capturePath
                        end if
                    else
                        return frontAppName & "|" & winTitle & "|" & frontBundleID & "|error: capture file not created, screencapture output: " & captureResult
                    end if
                on error fileCheckErr
                    return frontAppName & "|" & winTitle & "|" & frontBundleID & "|error: file check failed: " & fileCheckErr
                end try
                
            on error captureErr
                -- Check if error message contains permission-related keywords
                if captureErr contains "authorization" or captureErr contains "permission" or captureErr contains "denied" then
                    return frontAppName & "|" & winTitle & "|" & frontBundleID & "|error: screen recording permission denied - " & captureErr
                else
                    return frontAppName & "|" & winTitle & "|" & frontBundleID & "|error: screencapture failed: " & captureErr
                end if
            end try
            
        on error errMsg
            return frontAppName & "|" & winTitle & "|" & frontBundleID & "|error: window region capture failed: " & errMsg
        end try
    end tell
    """
    
    func makeAppleScript(excludedBundleIDs: Set<String>) -> String {
        let sortedIDs = excludedBundleIDs.sorted { $0.caseInsensitiveCompare($1) == .orderedAscending }
        let listLiteral: String
        if sortedIDs.isEmpty {
            listLiteral = "{}"
        } else {
            listLiteral = "{" + sortedIDs.map { "\"\(Self.escapedAppleScriptString($0))\"" }.joined(separator: ", ") + "}"
        }
        return appleScriptTemplate.replacingOccurrences(of: "__EXCLUDED_BUNDLE_IDS__", with: listLiteral)
    }

    // MARK: - Public Interface
    
    /// Capture the active window using AppleScript executed directly in Swift
    /// Returns a CaptureResult with success/failure and relevant information
    func captureActiveWindow(excludedBundleIDs: Set<String> = []) async -> CaptureResult {
        #if DEBUG
        DevLogger.shared.info("🔍 Swift WindowCaptureService: Starting window capture", context: "WindowCaptureService")
        #endif
        
        return await withCheckedContinuation { continuation in
            DispatchQueue.main.async {
                let result = self.executeAppleScript(excludedBundleIDs: excludedBundleIDs)
                continuation.resume(returning: result)
            }
        }
    }
    
    /// Test screen recording permission by attempting a small test capture
    /// This is more reliable for sandboxed apps than CGPreflightScreenCaptureAccess
    private func checkScreenRecordingPermission() async -> Bool {
        // For sandboxed apps, the API can be unreliable even when permission is granted
        // Always try a test capture to get the real permission status
        #if DEBUG
        DevLogger.shared.info("🧪 Performing actual screen capture test for permission verification", context: "WindowCaptureService")
        #endif
        
        let testPath = "/tmp/basil_permission_test_\(UUID().uuidString).png"
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
        task.arguments = ["-x", "-C", testPath]
        
        do {
            try task.run()
            task.waitUntilExit()
            
            // Check if capture succeeded and file exists with reasonable size
            if task.terminationStatus == 0 && FileManager.default.fileExists(atPath: testPath) {
                // Get file size to ensure it's not empty
                let attributes = try FileManager.default.attributesOfItem(atPath: testPath)
                let fileSize = attributes[.size] as? Int ?? 0
                
                #if DEBUG
                DevLogger.shared.info("✅ Test capture succeeded, file size: \(fileSize) bytes", context: "WindowCaptureService")
                #endif
                
                // Clean up test file
                try? FileManager.default.removeItem(atPath: testPath)
                
                // Consider permission granted if file is reasonably sized
                let hasPermission = fileSize > 1000
                
                if hasPermission {
                    #if DEBUG
                    DevLogger.shared.info("✅ Screen recording permission confirmed via test capture", context: "WindowCaptureService")
                    #endif
                } else {
                    #if DEBUG
                    DevLogger.shared.info("❌ Test capture file too small (\(fileSize) bytes) - permission likely denied", context: "WindowCaptureService")
                    #endif
                }
                
                return hasPermission
            } else {
                #if DEBUG
                DevLogger.shared.info("❌ Test capture failed with status: \(task.terminationStatus)", context: "WindowCaptureService")
                #endif
                return false
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to run test capture: \(error)", context: "WindowCaptureService")
            #endif
            return false
        }
    }
    
    // MARK: - Private Implementation
    
    /// Execute the AppleScript and parse the results
    /// Returns a CaptureResult with the outcome
    private func executeAppleScript(excludedBundleIDs: Set<String>) -> CaptureResult {
        #if DEBUG
        DevLogger.shared.info("🔍 Starting AppleScript execution diagnostics", context: "WindowCaptureService")
        
        // Log app bundle information
        if let bundleId = Bundle.main.bundleIdentifier {
            DevLogger.shared.info("📱 App Bundle ID: \(bundleId)", context: "WindowCaptureService")
        }
        
        // Log code signature status
        let executableURL = Bundle.main.executableURL
        DevLogger.shared.info("📦 Executable path: \(executableURL?.path ?? "unknown")", context: "WindowCaptureService")
        
        // Check if System Events is running
        let systemEventsRunning = NSWorkspace.shared.runningApplications.contains { app in
            app.bundleIdentifier == "com.apple.systemevents"
        }
        DevLogger.shared.info("🖥️ System Events running: \(systemEventsRunning)", context: "WindowCaptureService")
        
        // Test a simple AppleScript first
        let testScript = """
        tell application "System Events"
            return "test connection"
        end tell
        """
        
        DevLogger.shared.info("🧪 Testing basic System Events connection...", context: "WindowCaptureService")
        if let simpleScript = NSAppleScript(source: testScript) {
            var testError: NSDictionary?
            let testResult = simpleScript.executeAndReturnError(&testError)
            
            if let error = testError {
                DevLogger.shared.error("❌ Simple test failed: \(error)", context: "WindowCaptureService")
            } else {
                DevLogger.shared.info("✅ Simple test succeeded: \(testResult.stringValue ?? "no result")", context: "WindowCaptureService")
            }
        }
        #endif
        
        guard let script = NSAppleScript(source: makeAppleScript(excludedBundleIDs: excludedBundleIDs)) else {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to create NSAppleScript object", context: "WindowCaptureService")
            #endif
            return CaptureResult.failure(appName: "Unknown", windowTitle: "Unknown", error: "Failed to create AppleScript object")
        }
        
        #if DEBUG
        DevLogger.shared.info("📝 AppleScript object created successfully", context: "WindowCaptureService")
        DevLogger.shared.info("🚀 Executing main AppleScript...", context: "WindowCaptureService")
        #endif
        
        var errorDict: NSDictionary?
        let result = script.executeAndReturnError(&errorDict)
        
        if let error = errorDict {
            let errorMessage = error.description
            #if DEBUG
            DevLogger.shared.error("❌ AppleScript execution failed: \(errorMessage)", context: "WindowCaptureService")
            
            // Log specific error details
            if let errorNumber = error["NSAppleScriptErrorNumber"] as? Int {
                DevLogger.shared.error("🔢 Error Number: \(errorNumber)", context: "WindowCaptureService")
                
                // Handle accessibility permission error specifically
                if errorNumber == -25211 {
                    DevLogger.shared.info("🔧 Accessibility permission denied - opening System Settings", context: "WindowCaptureService")
                    DispatchQueue.main.async {
                        self.openAccessibilitySettings()
                    }
                }
            }
            if let errorRange = error["NSAppleScriptErrorRange"] as? NSRange {
                DevLogger.shared.error("📍 Error Range: \(errorRange)", context: "WindowCaptureService")
                
                // Try to show what's at that position in the script
                let scriptLines = appleScriptTemplate.components(separatedBy: .newlines)
                var charCount = 0
                for (lineIndex, line) in scriptLines.enumerated() {
                    if charCount + line.count >= errorRange.location {
                        let positionInLine = errorRange.location - charCount
                        DevLogger.shared.error("📄 Error at line \(lineIndex + 1), position \(positionInLine): '\(line)'", context: "WindowCaptureService")
                        break
                    }
                    charCount += line.count + 1 // +1 for newline
                }
            }
            if let errorApp = error["NSAppleScriptErrorAppName"] as? String {
                DevLogger.shared.error("🖥️ Error App: \(errorApp)", context: "WindowCaptureService")
            }
            #endif
            return CaptureResult.failure(appName: "Unknown", windowTitle: "Unknown", error: "AppleScript execution failed: \(errorMessage)")
        }
        
        guard let outputString = result.stringValue else {
            #if DEBUG
            DevLogger.shared.error("❌ AppleScript returned no string value", context: "WindowCaptureService")
            #endif
            return CaptureResult.failure(appName: "Unknown", windowTitle: "Unknown", error: "AppleScript returned no output")
        }
        
        #if DEBUG
        DevLogger.shared.info("📋 AppleScript output: \(outputString)", context: "WindowCaptureService")
        #endif
        
        return parseAppleScriptOutput(outputString)
    }
    
    /// Parse the AppleScript output string into a CaptureResult
    /// Expected format: "AppName|WindowTitle|BundleIdentifier|ImagePath" or policy/error variants
    func parseAppleScriptOutput(_ output: String) -> CaptureResult {
        #if DEBUG
        DevLogger.shared.info("🔍 [DEBUG] Parsing AppleScript output: \(output)", context: "WindowCaptureService")
        #endif
        
        // `omittingEmptySubsequences: false` is REQUIRED: apps like Microsoft
        // Outlook report an empty window title, producing output shaped like
        // "AppName||/path/to/capture.png". With the default (true), the empty
        // middle field is dropped, yielding only 2 components, which fails the
        // `>= 3` guard below and aborts the whole capture -- silently killing
        // the assistant-session recording start for any empty-title window.
        let components = output.split(separator: "|", maxSplits: 3, omittingEmptySubsequences: false).map(String.init)
        
        #if DEBUG
        DevLogger.shared.info("🔍 [DEBUG] Split into \(components.count) components:", context: "WindowCaptureService")
        for (index, component) in components.enumerated() {
            DevLogger.shared.info("🔍 [DEBUG] Component \(index): '\(component)'", context: "WindowCaptureService")
        }
        #endif
        
        guard components.count == 4 else {
            #if DEBUG
            DevLogger.shared.error("❌ Invalid AppleScript output format: \(output)", context: "WindowCaptureService")
            DevLogger.shared.error("❌ Expected 4 components, got \(components.count)", context: "WindowCaptureService")
            #endif
            return CaptureResult.failure(appName: "Unknown", windowTitle: "Unknown", error: "Invalid AppleScript output format")
        }

        let appName = components[0]
        let windowTitle = components[1]
        let bundleIdentifier = components[2].isEmpty ? nil : components[2]
        let result = components[3]
        
        #if DEBUG
        DevLogger.shared.info("🔍 [DEBUG] Parsed values:", context: "WindowCaptureService")
        DevLogger.shared.info("🔍 [DEBUG] - appName: '\(appName)'", context: "WindowCaptureService")
        DevLogger.shared.info("🔍 [DEBUG] - windowTitle: '\(windowTitle)'", context: "WindowCaptureService")
        DevLogger.shared.info("🔍 [DEBUG] - bundleIdentifier: '\(bundleIdentifier ?? "nil")'", context: "WindowCaptureService")
        DevLogger.shared.info("🔍 [DEBUG] - result: '\(result)'", context: "WindowCaptureService")
        #endif

        if result == "policy_skip:excluded_app", let bundleIdentifier {
            return CaptureResult.skipped(appName: appName, bundleIdentifier: bundleIdentifier, reason: "excluded_app")
        }

        // Handle error cases
        if result.starts(with: "error:") {
            let errorMessage = String(result.dropFirst(6)) // Remove "error:" prefix
            #if DEBUG
            DevLogger.shared.error("❌ AppleScript reported error: \(errorMessage)", context: "WindowCaptureService")
            #endif
            
            // Check if this is a permission-related error
            if errorMessage.lowercased().contains("permission") || 
               errorMessage.lowercased().contains("authorization") ||
               errorMessage.contains("too small") {
                #if DEBUG
                DevLogger.shared.error("🔐 Screen recording permission issue detected", context: "WindowCaptureService")
                #endif
                
                // Open System Settings to the screen recording pane
                DispatchQueue.main.async {
                    self.openScreenRecordingSettings()
                }
                
                return CaptureResult.failure(
                    appName: appName,
                    windowTitle: windowTitle,
                    bundleIdentifier: bundleIdentifier,
                    error: "Screen recording permission required. Please grant permission in System Settings and restart the app."
                )
            }
            
            return CaptureResult.failure(appName: appName, windowTitle: windowTitle, bundleIdentifier: bundleIdentifier, error: errorMessage)
        } else if result == "no_capture" {
            #if DEBUG
            DevLogger.shared.warning("⚠️ No window available to capture for app: \(appName), trying fallback full screen capture", context: "WindowCaptureService")
            #endif
            
            // Fallback to full screen capture for apps with non-standard windows (wrappers, PWAs, etc.)
            let fallbackPath = NSHomeDirectory() + "/.basil/data/temp/fallback_capture_\(Int(Date().timeIntervalSince1970 * 1000)).png"
            
            // Create directory if needed
            let tempDir = NSHomeDirectory() + "/.basil/data/temp"
            do {
                try FileManager.default.createDirectory(atPath: tempDir, withIntermediateDirectories: true, attributes: nil)
            } catch {
                #if DEBUG
                DevLogger.shared.error("❌ Could not create temp directory: \(error)", context: "WindowCaptureService")
                #endif
            }
            
            let task = Process()
            task.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
            task.arguments = ["-x", fallbackPath]
            
            do {
                try task.run()
                task.waitUntilExit()
                
                if task.terminationStatus == 0 && FileManager.default.fileExists(atPath: fallbackPath) {
                    #if DEBUG
                    DevLogger.shared.info("✅ Fallback full screen capture successful for \(appName)", context: "WindowCaptureService")
                    #endif
                    // Continue with the fallback path as the result
                    let fallbackImagePath = fallbackPath
                    
                    // Verify file size
                    do {
                        let attributes = try FileManager.default.attributesOfItem(atPath: fallbackImagePath)
                        let fileSize = attributes[.size] as? Int ?? 0
                        
                        #if DEBUG
                        DevLogger.shared.info("📊 Fallback capture file created: \(fileSize) bytes (\(fileSize/1024)KB)", context: "WindowCaptureService")
                        #endif
                        
                        return CaptureResult.success(
                            imagePath: fallbackImagePath,
                            appName: appName,
                            windowTitle: windowTitle,
                            bundleIdentifier: bundleIdentifier,
                            perceptualHash: PerceptualHashService.differenceHash(imagePath: fallbackImagePath)
                        )
                    } catch {
                        #if DEBUG
                        DevLogger.shared.warning("⚠️ Could not get fallback file attributes: \(error)", context: "WindowCaptureService")
                        #endif
                        return CaptureResult.success(
                            imagePath: fallbackImagePath,
                            appName: appName,
                            windowTitle: windowTitle,
                            bundleIdentifier: bundleIdentifier,
                            perceptualHash: PerceptualHashService.differenceHash(imagePath: fallbackImagePath)
                        )
                    }
                } else {
                    #if DEBUG
                    DevLogger.shared.error("❌ Fallback capture failed with status: \(task.terminationStatus)", context: "WindowCaptureService")
                    #endif
                    return CaptureResult.failure(appName: appName, windowTitle: windowTitle, bundleIdentifier: bundleIdentifier, error: "No window available to capture and fallback failed")
                }
            } catch {
                #if DEBUG
                DevLogger.shared.error("❌ Fallback capture exception: \(error)", context: "WindowCaptureService")
                #endif
                return CaptureResult.failure(appName: appName, windowTitle: windowTitle, bundleIdentifier: bundleIdentifier, error: "No window available to capture and fallback failed")
            }
        }
        
        // Verify the captured file exists
        let imagePath = result
        guard FileManager.default.fileExists(atPath: imagePath) else {
            #if DEBUG
            DevLogger.shared.error("❌ Capture file not found at path: \(imagePath)", context: "WindowCaptureService")
            #endif
            return CaptureResult.failure(appName: appName, windowTitle: windowTitle, bundleIdentifier: bundleIdentifier, error: "Capture file not found at expected location")
        }
        
        // Check file size to ensure meaningful capture
        do {
            let attributes = try FileManager.default.attributesOfItem(atPath: imagePath)
            let fileSize = attributes[.size] as? Int ?? 0
            
            #if DEBUG
            DevLogger.shared.info("📊 Capture file created: \(fileSize) bytes (\(fileSize/1024)KB)", context: "WindowCaptureService")
            #endif
            
            if fileSize < 1000 {
                #if DEBUG
                DevLogger.shared.warning("⚠️ Very small capture file (\(fileSize) bytes) - may be partial capture", context: "WindowCaptureService")
                #endif
            }
        } catch {
            #if DEBUG
            DevLogger.shared.warning("⚠️ Could not get file attributes: \(error)", context: "WindowCaptureService")
            #endif
        }
        
        #if DEBUG
        DevLogger.shared.info("✅ Window capture successful for \(appName) - \(windowTitle)", context: "WindowCaptureService")
        #endif
        
        return CaptureResult.success(
            imagePath: imagePath,
            appName: appName,
            windowTitle: windowTitle,
            bundleIdentifier: bundleIdentifier,
            perceptualHash: PerceptualHashService.differenceHash(imagePath: imagePath)
        )
    }
    
    /// Opens System Settings to the Accessibility privacy pane when permission is denied
    private func openAccessibilitySettings() {
        #if DEBUG
        DevLogger.shared.info("🔧 Opening Accessibility settings for user to grant permission", context: "WindowCaptureService")
        #endif
        
        // Try the modern System Settings URL first (macOS 13+)
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
            NSWorkspace.shared.open(url)
        }
    }
    
    /// Opens System Settings to the screen recording pane when permission is denied
    private func openScreenRecordingSettings() {
        #if DEBUG
        DevLogger.shared.info("🔧 Opening Screen Recording settings for user to grant permission", context: "WindowCaptureService")
        #endif
        
        // Try the modern System Settings URL first (macOS 13+)
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenRecording") {
            NSWorkspace.shared.open(url)
        }
    }
}

// MARK: - Extensions for Convenience

extension WindowCaptureService.CaptureResult {
    /// Returns true if the capture was successful and has a valid image path
    var hasValidCapture: Bool {
        return success && imagePath != nil
    }
    
    /// Returns a user-friendly error message for display
    var displayError: String {
        return error ?? "Unknown capture error"
    }
} 