import SwiftUI

struct BasilApp: App {
    // Store status bar manager as a state object to keep it alive
    @StateObject private var appState = AppState()
    
    var body: some Scene {
        WindowGroup {
            EmptyView()
        }
        .windowStyle(.hiddenTitleBar)
        
        // Note: Settings are handled through the status bar menu
    }
    
    init() {
        // Note: NSApplication.shared.setActivationPolicy(.accessory) is now handled in AppDelegate
    }
}

// AppState to manage our application's state
@MainActor
final class AppState: ObservableObject {
    private let statusBarManager: StatusBarServiceProtocol
    @Published private(set) var isActive: Bool = false
    
    init(statusBarManager: StatusBarServiceProtocol? = nil) {
        self.statusBarManager = statusBarManager ?? StatusBarManager()
        
        // Set initial status bar icon on the main actor
        Task { @MainActor in
            if let icon = NSImage(named: "StatusBarIcon") {
                // Since we're already on the main actor, this is safe
                self.statusBarManager.updateIcon(icon)
            }
        }
    }
    
    func setActive(_ active: Bool) {
        isActive = active
        // Since we're already on the main actor, this is safe
        statusBarManager.setActive(active)
    }
} 