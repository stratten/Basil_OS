import AppKit

// MARK: - Local Key Monitor
extension AppDelegate {
    func setupLocalKeyMonitor() {
        // Remove any existing monitor
        if let monitor = localKeyMonitor {
            NSEvent.removeMonitor(monitor)
            localKeyMonitor = nil
        }
        
        // Create a LOCAL (not global) monitor for all key events
        localKeyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            // Log all key events for diagnostic purposes
            // Use print statements that will definitely show up in the console
            let keyChar = event.charactersIgnoringModifiers ?? "Unknown"
            let keyCode = event.keyCode
            
            // Print conspicuous message that will be very visible
            print("⌨️⌨️⌨️ KEY DETECTED IN LOCAL MONITOR: '\(keyChar)' (code: \(keyCode)) ⌨️⌨️⌨️")
            
            if event.keyCode == 53 {
                print("🚨🚨🚨 ESCAPE KEY PRESSED - LOCAL MONITOR 🚨🚨🚨")
            }
            
            // Always return the event for normal processing
            return event
        }
        
        print("🎮 Diagnostic local key monitor set up - SHOULD DETECT ALL KEYSTROKES IN APP")
    }
    
    @MainActor
    @objc func checkMicrophonePermissions() -> String {
        return AudioCaptureService.checkMicrophonePermissions()
    }
    
    /// Toggle the force permission verification setting
    /// This is a simpler method for manual testing when needed
    @MainActor
    func toggleForcePermissionVerification() -> Bool {
        #if DEBUG
        DevLogger.shared.info("🔄 Using tccutil to reset permissions is the recommended approach instead of this method", context: "permissions")
        #endif
        
        // Use tccutil in Terminal instead:
        // tccutil reset SystemAudioRecording com.stratten.basil
        
        Task {
            await checkSystemAudioPermissions()
        }
        
        return true
    }
} 