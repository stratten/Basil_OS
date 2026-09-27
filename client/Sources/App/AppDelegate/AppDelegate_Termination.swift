import AppKit
import Foundation

// MARK: - Application Termination

@MainActor
extension AppDelegate {
    func applicationWillTerminate(_ notification: Notification) {
        #if DEBUG
        DevLogger.shared.info("📢 Application will terminate - performing comprehensive cleanup", context: "AppDelegate")
        #endif

        // Create a dispatch group to coordinate shutdown tasks
        let group = DispatchGroup()

        // Close model download mini widget if open
        if let controller = modelDownloadWindowController, controller.isVisible {
            controller.dismiss()
            modelDownloadWindowController = nil
        }

        // Hide the scheduled-run mini panel and detach its NotificationCenter
        // observer so WS frames arriving during shutdown don't try to bring
        // a torn-down panel back to the front.
        if let controller = scheduledRunMiniPanelController, controller.isVisible {
            controller.hide()
        }
        scheduledRunMiniPanelController = nil
        if let token = scheduledRunMiniPanelObserverToken {
            NotificationCenter.default.removeObserver(token)
            scheduledRunMiniPanelObserverToken = nil
        }

        // Same teardown for the meeting-detected mini panel.
        if let controller = meetingDetectedMiniPanelController, controller.isVisible {
            controller.hide()
        }
        meetingDetectedMiniPanelController = nil
        if let token = meetingDetectedObserverToken {
            NotificationCenter.default.removeObserver(token)
            meetingDetectedObserverToken = nil
        }
        if let token = recordingDidStartObserverToken {
            NotificationCenter.default.removeObserver(token)
            recordingDidStartObserverToken = nil
        }

        // Small wait for any cleanup to complete (with a short timeout)
        _ = group.wait(timeout: .now() + 0.5)

        // Send shutdown request to backend - it will handle all backend cleanup and logging
        group.enter()

        Task {
            do {
                // First check if backend is available
                let healthData = try await APIClient.shared.get("/health")
                if let _ = try? JSONSerialization.jsonObject(with: healthData, options: []) as? [String: Any] {
                    // Backend is available, send shutdown request - backend handles all cleanup

                    // Set the flag indicating backend shutdown is in progress
                    APIClient.isBackendShuttingDown = true
                    #if DEBUG
                    DevLogger.shared.info("🚩 Setting APIClient.isBackendShuttingDown = true", context: "AppDelegate")
                    #endif

                    let response = try await APIClient.shared.post("/shutdown")
                    #if DEBUG
                    DevLogger.shared.info("🛑 Backend comprehensive shutdown request sent: \(response.status)", context: "AppDelegate")
                    #endif
                } else {
                    #if DEBUG
                    DevLogger.shared.warning("⚠️ Backend health check failed, backend may already be down", context: "AppDelegate")
                    #endif
                }
            } catch {
                #if DEBUG
                DevLogger.shared.warning("⚠️ Backend not available via API: \(error.localizedDescription)", context: "AppDelegate")
                #endif
            }

            // Clean up status bar
            await statusBarManager.disableStatusItem()

            group.leave()
        }

        // Wait for the shutdown request to complete (with a timeout)
        _ = group.wait(timeout: .now() + 2.0)  // Increased timeout for backend cleanup

        // Clean up the escape key monitor
        if let monitor = escapeKeyMonitor {
            NSEvent.removeMonitor(monitor)
            escapeKeyMonitor = nil
        }

        // Clean up the local key monitor
        if let monitor = localKeyMonitor {
            NSEvent.removeMonitor(monitor)
            localKeyMonitor = nil
        }

        plainTextPasteShortcutMonitor?.stop()
        plainTextPasteShortcutMonitor = nil

        #if DEBUG
        DevLogger.shared.info("🏁 Frontend cleanup complete - backend handles its own comprehensive cleanup", context: "AppDelegate")
        #endif
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        #if DEBUG
        DevLogger.shared.info("📢 Application should terminate called", context: "AppDelegate")
        #endif
        return .terminateNow
    }
}
