import AppKit

enum LiveTranscriptionLayoutPolicy {
    static let compactWidth: CGFloat = 300
    static let compactHeight: CGFloat = 70
    static let expandedRootMinimumHeight: CGFloat = 600
    static let fullLayoutRootWidth: CGFloat = 820
    static let outerInset: CGFloat = 3

    /// - Parameter companionExtent: Width the right-edge Companion column has
    ///   added to the window (see `companionResizedFrame`); the main column keeps its own floor.
    static func panelMinimumSize(sidebarCollapsed: Bool, companionExtent: CGFloat = 0) -> NSSize {
        NSSize(
            width: (sidebarCollapsed ? 474 : fullLayoutRootWidth) + (outerInset * 2) + max(companionExtent, 0),
            height: expandedRootMinimumHeight + (outerInset * 2)
        )
    }

    static var compactSize: NSSize {
        NSSize(width: compactWidth, height: compactHeight)
    }

    static func constrainedExpandedSize(
        _ proposedSize: NSSize,
        sidebarCollapsed: Bool,
        companionExtent: CGFloat = 0
    ) -> NSSize {
        let minimumSize = panelMinimumSize(sidebarCollapsed: sidebarCollapsed, companionExtent: companionExtent)
        return NSSize(
            width: max(proposedSize.width, minimumSize.width),
            height: max(proposedSize.height, minimumSize.height)
        )
    }

    /// The frame that gives the Companion column room by moving only the window's right edge, so the main column keeps its width.
    ///
    /// Growing extends to the right; if that would pass the screen's visible edge the window slides left just enough, and if the screen is still too narrow the growth is capped at the visible width. Shrinking never goes below `minimumWidth` and keeps the left edge.
    /// - Returns: The target frame and the width change actually achieved, which the caller must remember to reverse later.
    static func companionResizedFrame(
        frame: NSRect,
        delta: CGFloat,
        visibleFrame: NSRect,
        minimumWidth: CGFloat
    ) -> (frame: NSRect, achievedDelta: CGFloat) {
        var target = frame
        if delta >= 0 {
            target.size.width = min(frame.width + delta, max(visibleFrame.width, frame.width))
            if target.maxX > visibleFrame.maxX {
                target.origin.x = max(visibleFrame.minX, visibleFrame.maxX - target.width)
            }
        } else {
            target.size.width = max(frame.width + delta, min(minimumWidth, frame.width))
        }
        return (target, target.width - frame.width)
    }
}
