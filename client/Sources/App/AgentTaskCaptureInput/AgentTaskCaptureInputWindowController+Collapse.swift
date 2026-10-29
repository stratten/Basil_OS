import AppKit

/// Collapsing the capture window to its header strip and expanding it back. The page keeps its content mounted while collapsed, so a typed draft is never cleared, and the saved expanded frame brings the window back to the exact size it had.
extension AgentTaskCaptureInputWindowController {
    /// Header height before the page has reported its own, matching the 16pt close glyph stacked over a 16pt spacer plus the 3pt gap.
    static let defaultHeaderExtent: CGFloat = 36
    /// Space kept under the header row when collapsed, matching the widget's bottom padding.
    static let collapsedBottomInset: CGFloat = 8
    /// How close a resize notification must be to the animation's target to count as arriving.
    static let collapseTargetTolerance: CGFloat = 1

    /// Narrowest collapsed width. The text area is hidden while collapsed, so this sits below the 280 text-entry minimum yet still fits the close and collapse buttons, the agent name and the two trailing buttons.
    static let collapsedWidth: CGFloat = 200

    /// The collapsed window: a narrow strip tall enough for the header row only.
    static func collapsedSize(headerExtent: CGFloat) -> NSSize {
        NSSize(
            width: collapsedWidth,
            height: max(headerExtent, 1) + collapsedBottomInset
        )
    }

    /// Whether a resize notification is part of a collapse or expand animation. Reaching the target ends the transition, so the next resize is treated normally. Without a transition in flight nothing is ours.
    func isCollapseTransitionResize(frameSize: NSSize) -> Bool {
        guard let target = collapseTransitionTargetSize else { return false }
        if abs(frameSize.width - target.width) <= Self.collapseTargetTolerance,
           abs(frameSize.height - target.height) <= Self.collapseTargetTolerance {
            collapseTransitionTargetSize = nil
        }
        return true
    }

    /// Collapses or expands from the page. Collapsing is offered only for text entry, where a long draft is worth keeping out of the way.
    func applyWindowCollapse(_ collapsed: Bool, viewModel: AgentTaskCaptureViewModel) {
        guard let panel, let collapseController, collapseController.isCollapsed != collapsed else { return }

        if collapsed {
            guard viewModel.isTextEntryMode else { return }
            expandedSizeBeforeCollapse = panel.frame.size
            userExpandedSizeBeforeCollapse = userExpandedSizeValue
            let compact = Self.collapsedSize(headerExtent: captureHeaderExtent)
            collapseTransitionTargetSize = NSSize(width: min(panel.frame.width, compact.width), height: compact.height)
            collapseController.setCollapsed(true, preferredCompactSize: compact)
            return
        }

        collapseTransitionTargetSize = expandedSizeBeforeCollapse
        collapseController.setCollapsed(false)
        userExpandedSizeValue = userExpandedSizeBeforeCollapse
        expandedSizeBeforeCollapse = nil
        userExpandedSizeBeforeCollapse = nil
        if hasPendingResizeWhileCollapsed {
            hasPendingResizeWhileCollapsed = false
            viewModel.requestCapturePanelResizeForCurrentState()
        }
    }
}
