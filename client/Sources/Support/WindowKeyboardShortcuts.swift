import AppKit

/// Utility class that adds standard keyboard shortcuts (Cmd+W to close, Cmd+M to minimize)
/// to NSWindow or NSPanel instances. Handles local event monitoring for borderless windows.
final class WindowKeyboardShortcuts {
    private var localKeyMonitor: Any?
    private weak var window: NSWindow?
    
    /// Initialize with a window to monitor
    /// - Parameter window: The window to add keyboard shortcuts to
    init(window: NSWindow) {
        self.window = window
        setupMonitor()
    }
    
    private func setupMonitor() {
        localKeyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self = self,
                  let window = self.window,
                  window.isKeyWindow || window.isMainWindow else {
                return event
            }
            
            // Check for Command modifier
            if event.modifierFlags.contains(.command) {
                switch event.charactersIgnoringModifiers?.lowercased() {
                case "w":
                    // Cmd+W: Close window
                    window.close()
                    return nil // Consume the event
                case "m":
                    // Cmd+M: Minimize window
                    window.miniaturize(nil)
                    return nil // Consume the event
                default:
                    break
                }
            }
            return event
        }
    }
    
    /// Remove the keyboard monitor. Call this when the window is closing.
    func cleanup() {
        if let monitor = localKeyMonitor {
            NSEvent.removeMonitor(monitor)
            localKeyMonitor = nil
        }
    }
    
    deinit {
        cleanup()
    }
}
