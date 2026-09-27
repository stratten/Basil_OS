import AVFoundation
import AppKit

extension AudioCaptureService {
    // Static method to check permissions without requesting
    static func checkMicrophonePermissions() -> String {
        let authStatus = AVCaptureDevice.authorizationStatus(for: .audio)
        switch authStatus {
        case .authorized:
            return "✓ Microphone access authorized"
        case .denied:
            return "✗ Microphone access denied"
        case .restricted:
            return "⚠️ Microphone access restricted by system"
        case .notDetermined:
            return "? Microphone access not yet determined"
        @unknown default:
            return "❌ Unknown microphone permission state"
        }
    }

    @MainActor
    func checkPermissionsAndSetup() async throws {
        if validationSyntheticAudioSource != nil {
            permissionGranted = true
            return
        }

        // If already granted, no need to check again
        if permissionGranted {
            #if DEBUG
                DevLogger.shared.info("✅ Microphone permissions already granted, proceeding", context: "permissions")
            #endif
            return
        }
        
        let status = AVCaptureDevice.authorizationStatus(for: .audio)
        
        switch status {
        case .authorized:
            permissionGranted = true
            #if DEBUG
                DevLogger.shared.info("✅ Microphone access already authorized", context: "permissions")
            #endif
            
        case .notDetermined:
            // This should rarely happen since AppDelegate should have handled it,
            // but we'll handle it just in case
            #if DEBUG
                DevLogger.shared.info("🎤 Requesting microphone access (fallback)...", context: "permissions")
            #endif
            permissionGranted = await AVCaptureDevice.requestAccess(for: .audio)
            if permissionGranted {
                #if DEBUG
                    DevLogger.shared.info("✅ Microphone access granted", context: "permissions")
                #endif
            } else {
                #if DEBUG
                    DevLogger.shared.error("❌ Microphone access denied by user", context: "permissions")
                #endif
                throw AudioCaptureError.permissionDenied
            }
            
        case .denied:
            #if DEBUG
                DevLogger.shared.error("❌ Microphone access denied - please check System Settings", context: "permissions")
            #endif
            throw AudioCaptureError.permissionDenied
            
        case .restricted:
            #if DEBUG
                DevLogger.shared.error("⚠️ Microphone access restricted by system policy", context: "permissions")
            #endif
            throw AudioCaptureError.permissionDenied
            
        @unknown default:
            #if DEBUG
                DevLogger.shared.error("❓ Unknown microphone permission status: \(status.rawValue)", context: "permissions")
            #endif
            throw AudioCaptureError.permissionDenied
        }
    }
    
    @MainActor
    func showSystemSettingsPrompt() {
        self.error = "Microphone access required. Click here to open System Settings."
        self.permissionGranted = false
        
        // Create an alert to guide the user
        let alert = NSAlert()
        alert.messageText = "Microphone Access Required"
        alert.informativeText = "Basil needs microphone access to transcribe audio. Would you like to open System Settings to grant access?"
        alert.alertStyle = NSAlert.Style.warning
        alert.addButton(withTitle: "Open System Settings")
        alert.addButton(withTitle: "Cancel")
        
        if alert.runModal() == .alertFirstButtonReturn {
            // Open System Settings directly to the Privacy & Security > Microphone section
            if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone") {
                NSWorkspace.shared.open(url)
            }
        }
    }
}

