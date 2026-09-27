import AppKit

/// A custom NSWindow subclass that allows a borderless window to become the key window and receive keyboard input.
///
/// Standard borderless windows cannot become the key window by default, which prevents controls like `TextEditor`
/// from receiving focus and keyboard events. By overriding `canBecomeKey` and `canBecomeMain`, we enable this functionality.
class CustomBorderlessWindow: NSWindow {
    /// Overridden to return `true` to allow the window to become the key window for input.
    override var canBecomeKey: Bool {
        return true
    }
    
    /// Overridden to return `true` to allow the window to become the main window of the application.
    override var canBecomeMain: Bool {
        return true
    }
}

/// A custom NSPanel subclass that allows a borderless panel to become the key window and receive keyboard input.
///
/// Standard borderless panels cannot become the key window by default, which prevents controls like `TextEditor`
/// from receiving focus and keyboard events. By overriding `canBecomeKey`, we enable this functionality.
class CustomBorderlessPanel: NSPanel {
    /// Overridden to return `true` to allow the panel to become the key window for input.
    override var canBecomeKey: Bool {
        return true
    }
} 