import Foundation
import AppKit

@preconcurrency
protocol StatusBarServiceProtocol: AnyObject {
    /// Indicates whether the status bar item is currently enabled
    var isEnabled: Bool { get async }
    
    /// Enables and shows the status bar item
    func enableStatusItem() async
    
    /// Disables and removes the status bar item
    func disableStatusItem() async
    
    /// Updates the status bar icon with a custom image
    /// - Parameter icon: The image to use as the status bar icon
    @MainActor
    func updateIcon(_ icon: NSImage)
    
    /// Updates the status bar title
    /// - Parameter title: The text to display in the status bar
    @MainActor
    func updateTitle(_ title: String)
    
    /// Sets the active state of the status bar
    @MainActor
    func setActive(_ active: Bool)
}

/// Errors that can occur in status bar operations
enum StatusBarError: Error {
    /// Failed to create the status bar item
    case statusItemCreationFailed
    /// Could not find the specified icon image
    case iconNotFound
    /// Failed to create or configure the menu
    case menuCreationFailed
    /// Failed to update the status bar item's state
    case statusUpdateFailed
    /// Invalid operation attempted while status bar is disabled
    case statusBarDisabled
} 