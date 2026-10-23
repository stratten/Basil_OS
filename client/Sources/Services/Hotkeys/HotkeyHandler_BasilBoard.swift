import AppKit
import Foundation

extension HotkeyService {
    @MainActor
    func handleHomeBoardHotkey() async {
        guard let appDelegate = NSApplication.shared.delegate as? AppDelegate,
              let coordinator = appDelegate.statusBarManager?.windowCoordinator else {
            #if DEBUG
            DevLogger.shared.error("Could not access AppDelegate or StatusBarManager for home board hotkey", context: "HotkeyService")
            #endif
            return
        }

        coordinator.toggleBasilBoard()
    }
}
