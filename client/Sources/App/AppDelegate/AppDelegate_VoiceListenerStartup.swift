import Foundation

// MARK: - Voice Listener Startup Helper

extension AppDelegate {
    /// Waits for backend to become available, then enables voice listener
    private func enableVoiceListenerWhenBackendReady() async {
        let maxWaitTime: TimeInterval = 30.0 // 30 second timeout
        let checkInterval: TimeInterval = 0.5 // Check every 500ms
        let startTime = Date()

        #if DEBUG
        DevLogger.shared.info("🔄 STARTUP: Waiting for backend availability (timeout: \(maxWaitTime)s)...", context: "AppDelegate")
        #endif

        while Date().timeIntervalSince(startTime) < maxWaitTime {
            if APIClient.shared.isBackendAvailable {
                #if DEBUG
                DevLogger.shared.info("✅ STARTUP: Backend is now available. Enabling Voice Listener...", context: "AppDelegate")
                #endif

                do {
                    let voiceSettings = try await APIClient.shared.updateVoiceListenerSettings(enabled: true)
                    #if DEBUG
                    if voiceSettings.voiceListenerEnabled {
                        DevLogger.shared.info("✅ STARTUP: Voice Listener successfully enabled via API.", context: "AppDelegate")
                    } else {
                        DevLogger.shared.warning("⚠️ STARTUP: Voice Listener API call made, but backend reported not enabled.", context: "AppDelegate")
                    }
                    #endif
                } catch {
                    #if DEBUG
                    DevLogger.shared.error("❌ STARTUP: Failed to enable Voice Listener via API: \(error.localizedDescription)", context: "AppDelegate")
                    #endif
                }
                return
            }

            // Wait before next check
            try? await Task.sleep(nanoseconds: UInt64(checkInterval * 1_000_000_000))
        }

        #if DEBUG
        DevLogger.shared.error("⏰ STARTUP: Timeout waiting for backend availability (\(maxWaitTime)s). Voice Listener not enabled.", context: "AppDelegate")
        #endif
    }
}
