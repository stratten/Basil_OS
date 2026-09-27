import AppKit

extension AgentTaskResultWidgetController {
    func positionPanel(
        _ panel: NSWindow,
        size: NSSize,
        placement: Placement
    ) {
        let frame = frameForPlacement(size: size, placement: placement, fallbackFrame: panel.frame)
        panel.setFrameOrigin(frame.origin)
    }

    func resizedFrame(
        for panel: NSWindow,
        width: CGFloat,
        height: CGFloat,
        placement: Placement
    ) -> NSRect {
        frameForPlacement(
            size: NSSize(width: width, height: height),
            placement: placement,
            fallbackFrame: panel.frame
        )
    }

    func frameForPlacement(
        size: NSSize,
        placement: Placement,
        fallbackFrame: NSRect
    ) -> NSRect {
        let interPanelGap: CGFloat = 12
        switch placement {
        case .anchoredLeftOfFrame(let captureFrame):
            // Anchored just to the LEFT of the capture widget,
            // top-aligned, with a small visual gap.
            let originX = captureFrame.minX - interPanelGap - size.width
            let originY = captureFrame.maxY - size.height
            return NSRect(x: originX, y: originY, width: size.width, height: size.height)
        case .topRightScreenContainingFrame(let anchorFrame):
            let anchorPoint = NSPoint(x: anchorFrame.midX, y: anchorFrame.midY)
            let anchoredScreen = NSScreen.screens.first { screen in
                NSMouseInRect(anchorPoint, screen.frame, false)
            } ?? NSScreen.screens.first { screen in
                screen.frame.intersects(anchorFrame)
            } ?? NSScreen.main ?? NSScreen.screens.first!
            let screenFrame = anchoredScreen.visibleFrame
            let margin: CGFloat = 20
            let originX = screenFrame.maxX - margin - size.width
            let originY = screenFrame.maxY - margin - size.height
            return NSRect(x: originX, y: originY, width: size.width, height: size.height)
        case .topRightCurrentScreen, .topRightLeavingCaptureSpace:
            let currentScreen = NSScreen.screens.first { screen in
                NSMouseInRect(NSPoint(x: fallbackFrame.midX, y: fallbackFrame.midY), screen.frame, false)
            } ?? NSScreen.screens.first { screen in
                NSMouseInRect(NSEvent.mouseLocation, screen.frame, false)
            } ?? NSScreen.main ?? NSScreen.screens.first!
            let screenFrame = currentScreen.visibleFrame
            let margin: CGFloat = 20
            let captureWidgetWidthReserve: CGFloat = {
                if case .topRightLeavingCaptureSpace = placement { return 160 }
                return 0
            }()
            let reservedGap = captureWidgetWidthReserve > 0 ? interPanelGap : 0
            let originX = screenFrame.maxX - margin - captureWidgetWidthReserve - reservedGap - size.width
            let originY = screenFrame.maxY - margin - size.height
            return NSRect(x: originX, y: originY, width: size.width, height: size.height)
        }
    }
}
