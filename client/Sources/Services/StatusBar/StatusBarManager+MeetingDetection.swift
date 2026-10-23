import AppKit

extension StatusBarManager {
    /// Manually start/stop the mechanical meeting-detection monitor. Mirrors the
    /// Proactive Suggestions manual-initiation pattern: enabling in Settings only
    /// makes the control available; the loop runs when the user starts it.
    @objc func toggleMeetingDetection() {
        Task { @MainActor in
            do {
                if isMeetingDetectionRunning {
                    _ = try await APIClient.shared.stopMeetingDetection()
                } else {
                    _ = try await APIClient.shared.startMeetingDetection()
                }
            } catch {
                #if DEBUG
                DevLogger.shared.error("Failed to toggle Meeting Detection: \(error.localizedDescription)", context: "StatusBarManager")
                #endif
            }
            await refreshMeetingDetectionState()
        }
    }

    @MainActor
    func refreshMeetingDetectionState() async {
        do {
            let status = try await APIClient.shared.getMeetingDetectionStatus()
            isMeetingDetectionEnabled = status.enabled
            isMeetingDetectionRunning = status.isRunning ?? false
            updateMeetingDetectionMenuState()
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to refresh Meeting Detection status: \(error.localizedDescription)", context: "StatusBarManager")
            #endif
        }
    }

    @MainActor
    func updateMeetingDetectionMenuState() {
        if let menu = statusBarItem.statusMenu {
            StatusBarMenuUpdater.updateMenuItems(menu: menu, hotkeyService: hotkeyService, statusBarManager: self)
        }
        statusBarItem.updateIconForCurrentState()
    }
}
