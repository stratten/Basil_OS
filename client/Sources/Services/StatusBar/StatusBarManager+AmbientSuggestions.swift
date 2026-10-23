import AppKit

extension StatusBarManager {
    @objc func openAmbientSuggestions() {
        Task { @MainActor in
            if let appDelegate = NSApplication.shared.delegate as? AppDelegate {
                appDelegate.showAmbientSuggestionsPanel()
            }
            await refreshAmbientSuggestionState()
        }
    }

    @MainActor
    func refreshAmbientSuggestionState() async {
        do {
            let status = try await APIClient.shared.getAmbientSuggestionStatus()
            isAmbientSuggestionsEnabled = status.enabled
            isAmbientSuggestionsRunning = status.isRunning ?? false
            updateAmbientSuggestionsMenuState()
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to refresh Proactive Suggestions status: \(error.localizedDescription)", context: "StatusBarManager")
            #endif
        }
    }

    @MainActor
    func updateAmbientSuggestionsMenuState() {
        if let menu = statusBarItem.statusMenu {
            StatusBarMenuUpdater.updateMenuItems(menu: menu, hotkeyService: hotkeyService, statusBarManager: self)
        }
        statusBarItem.updateIconForCurrentState()
    }
}
