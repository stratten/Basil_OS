import SwiftUI

extension AgentTaskCaptureViewModel {
    enum CapturePanelLayout {
        // These four match the archived `AgentTaskCaptureWidget.swift`
        // (native SwiftUI widget)'s own `dynamicHeight`/`.frame` values
        // exactly — voiceWidth/voiceBaseHeight from its
        // `minWidth/maxWidth: 160` and `dynamicHeight` base of 206 when
        // `!isTextEntryMode`, textWidth/textBaseHeight from its
        // `minWidth: 280` and `dynamicHeight` base of 235 when
        // `isTextEntryMode`. The WK-hosted capture widget (`AgentTaskCaptureInputWindowController`)
        // is meant to be pixel-identical to that widget apart from the
        // reasoning-model selector it adds, so these must stay in sync with
        // it rather than drift independently.
        static let voiceWidth: CGFloat = 160
        static let voiceBaseHeight: CGFloat = 206
        static let voiceReferenceModeMinHeight: CGFloat = 206

        static let textWidth: CGFloat = 280
        static let textBaseHeight: CGFloat = 235

        static let referenceHeaderHeight: CGFloat = 12
        static let referenceRowHeight: CGFloat = 18
        static let referenceRowSpacing: CGFloat = 2
        static let referenceContainerVerticalPadding: CGFloat = 10
        static let referenceSectionTopSpacing: CGFloat = 6
        static let maxVisibleReferenceRows: Int = 3
    }

    func requestCapturePanelResizeForCurrentState() {
        let referenceHeight = calculatedReferenceSectionHeight()

        if isTextEntryMode {
            sizeUpdateRequest.send((
                width: CapturePanelLayout.textWidth,
                height: CapturePanelLayout.textBaseHeight + referenceHeight
            ))
            return
        }

        if referenceHeight > 0 {
            sizeUpdateRequest.send((
                width: CapturePanelLayout.voiceWidth,
                height: max(CapturePanelLayout.voiceBaseHeight, CapturePanelLayout.voiceReferenceModeMinHeight) + referenceHeight
            ))
        } else {
            sizeUpdateRequest.send((
                width: CapturePanelLayout.voiceWidth,
                height: CapturePanelLayout.voiceBaseHeight
            ))
        }
    }

    func calculatedReferenceSectionHeight() -> CGFloat {
        guard !referencePaths.isEmpty else { return 0 }

        let visibleRows = min(referencePaths.count, CapturePanelLayout.maxVisibleReferenceRows)
        let rowsHeight = CGFloat(visibleRows) * CapturePanelLayout.referenceRowHeight
        let interRowSpacing = CGFloat(max(0, visibleRows - 1)) * CapturePanelLayout.referenceRowSpacing

        return CapturePanelLayout.referenceSectionTopSpacing
            + CapturePanelLayout.referenceHeaderHeight
            + CapturePanelLayout.referenceContainerVerticalPadding
            + rowsHeight
            + interRowSpacing
    }
}
