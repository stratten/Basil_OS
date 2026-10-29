import AppKit

extension NSWindow {
    /// Applies the property block shared by Basil's standard custom-chrome windows.
    ///
    /// These windows keep the default level and collection behavior; they only share a title, an explicit `isReleasedWhenClosed`, and background dragging.
    ///
    /// - Parameters:
    ///   - title: The window title.
    ///   - releasedWhenClosed: Required, because the choice changes close behavior: `false` for windows owned by a strong reference, `true` only for a window that keeps itself alive through a retained controller.
    @MainActor
    func configureCustomChromeWindow(title: String, releasedWhenClosed: Bool) {
        self.title = title
        isReleasedWhenClosed = releasedWhenClosed
        isMovableByWindowBackground = true
        // Tells the window's pages when it goes out of sight and comes back, so the blueprint reveal replays on every appearance.
        BlueprintRevealVisibilityReporter.install(on: self)
    }
}
