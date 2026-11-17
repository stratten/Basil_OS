import AppKit

/// Pure window arithmetic for the task pane that opens to the right of the setup flow. Kept free of AppKit state so it can be unit tested.
enum SetupTaskPaneFrames {
    static let preferredPaneWidth: CGFloat = 520
    /// Narrowest pane the task view stays usable in (conversation column plus its follow-up box).
    static let minimumPaneWidth: CGFloat = 360

    struct Plan: Equatable {
        /// Frame the setup window takes while the pane is open. Its left edge stays put unless the screen forces it left.
        let windowFrame: NSRect
        /// Width given to the pane. The setup flow keeps `windowFrame.width - paneWidth`.
        let paneWidth: CGFloat
    }

    /// Plans the window for opening the pane. The window grows to the right by the pane's width. If the screen is too narrow for that, the pane takes what is left after the setup flow's minimum width. Returns nil when even the narrowest pane would squeeze the setup flow below its minimum, and the caller falls back to a floating task window.
    static func openingPlan(
        currentFrame: NSRect,
        minimumSetupWidth: CGFloat,
        visibleFrame: NSRect,
        preferredPaneWidth: CGFloat = SetupTaskPaneFrames.preferredPaneWidth,
        minimumPaneWidth: CGFloat = SetupTaskPaneFrames.minimumPaneWidth
    ) -> Plan? {
        let totalWidth = min(currentFrame.width + preferredPaneWidth, visibleFrame.width)
        let paneWidth = min(preferredPaneWidth, totalWidth - minimumSetupWidth)
        guard paneWidth >= minimumPaneWidth else { return nil }
        let x = min(max(currentFrame.minX, visibleFrame.minX), visibleFrame.maxX - totalWidth)
        let frame = NSRect(x: x, y: currentFrame.minY, width: totalWidth, height: currentFrame.height)
        return Plan(windowFrame: frame, paneWidth: paneWidth)
    }

    /// The frame to restore when the pane closes: the window gives back the pane's width, keeps its left edge, and never goes below `minimumWindowWidth`.
    static func closingFrame(
        currentFrame: NSRect,
        paneWidth: CGFloat,
        minimumWindowWidth: CGFloat
    ) -> NSRect {
        let width = max(currentFrame.width - paneWidth, minimumWindowWidth)
        return NSRect(x: currentFrame.minX, y: currentFrame.minY, width: width, height: currentFrame.height)
    }
}
