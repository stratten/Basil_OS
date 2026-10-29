import AppKit
import Foundation

extension WebSocketService {
    /// The backend changed activity capture settings without the Settings window (for example an approved
    /// setup receipt), so the menu item and status icon must re-read the authoritative state.
    @MainActor
    func handleActivityCaptureUpdated() {
        guard let appDelegate = NSApplication.shared.delegate as? AppDelegate else { return }
        Task { @MainActor in
            await appDelegate.statusBarManager?.refreshActivityCaptureState()
        }
    }
}
