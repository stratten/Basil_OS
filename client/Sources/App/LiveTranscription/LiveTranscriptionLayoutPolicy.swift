import AppKit

enum LiveTranscriptionLayoutPolicy {
    static let compactWidth: CGFloat = 300
    static let compactHeight: CGFloat = 70
    static let expandedRootMinimumHeight: CGFloat = 600
    static let fullLayoutRootWidth: CGFloat = 820
    static let outerInset: CGFloat = 3

    static func panelMinimumSize(sidebarCollapsed: Bool) -> NSSize {
        NSSize(
            width: (sidebarCollapsed ? 474 : fullLayoutRootWidth) + (outerInset * 2),
            height: expandedRootMinimumHeight + (outerInset * 2)
        )
    }

    static var compactSize: NSSize {
        NSSize(width: compactWidth, height: compactHeight)
    }

    static func constrainedExpandedSize(
        _ proposedSize: NSSize,
        sidebarCollapsed: Bool
    ) -> NSSize {
        let minimumSize = panelMinimumSize(sidebarCollapsed: sidebarCollapsed)
        return NSSize(
            width: max(proposedSize.width, minimumSize.width),
            height: max(proposedSize.height, minimumSize.height)
        )
    }
}
