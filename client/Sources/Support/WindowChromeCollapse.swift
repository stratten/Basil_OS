import AppKit

/// Shared compact-chrome frame planning for movable floating windows.
///
/// Windows collapse in place by retaining their top edge and the horizontal
/// edge nearest their pre-collapse position. If the compact window is moved,
/// expansion uses its current screen and chooses a visible anchor instead of
/// assuming the original origin is still appropriate.
enum WindowChromeCollapse {
    static let compactWidthCap: CGFloat = 400
    private static let movementTolerance: CGFloat = 1
    private static var inFlightExpandFrames: [ObjectIdentifier: NSRect] = [:]

    struct State {
        let expandedFrame: NSRect
        let minSize: NSSize
        let maxSize: NSSize
        let contentMinSize: NSSize
        let contentMaxSize: NSSize
        let initialCompactFrame: NSRect
    }

    enum Anchor: CaseIterable, Equatable {
        case topLeft
        case topRight
        case bottomLeft
        case bottomRight
    }

    /// Collapse to the compact size with an animated reframe. Use for
    /// user-initiated minimize, where the glide reads as intentional motion.
    static func collapse(
        window: NSWindow,
        preferredCompactSize: NSSize,
        state: inout State?
    ) {
        performCollapse(
            window: window,
            preferredCompactSize: preferredCompactSize,
            state: &state,
            animated: true
        )
    }

    /// Collapse to the compact size WITHOUT animating the reframe. Use when a
    /// window must simply appear already-compact (e.g. establishing the initial
    /// minimized state on first show) so there is no visible glide/shake. The
    /// geometry, clamping, and saved `state` are identical to ``collapse``; only
    /// the final `setFrame` animation differs.
    static func collapseWithoutAnimation(
        window: NSWindow,
        preferredCompactSize: NSSize,
        state: inout State?
    ) {
        performCollapse(
            window: window,
            preferredCompactSize: preferredCompactSize,
            state: &state,
            animated: false
        )
    }

    private static func performCollapse(
        window: NSWindow,
        preferredCompactSize: NSSize,
        state: inout State?,
        animated: Bool
    ) {
        let currentFrame = window.frame
        let visibleFrame = visibleFrame(for: window, frame: currentFrame)
        let compactSize = compactSize(
            preferredCompactSize,
            visibleFrame: visibleFrame
        )
        let compactFrame = frame(
            anchoredAt: collapseAnchor(frame: currentFrame, visibleFrame: visibleFrame),
            compactFrame: currentFrame,
            size: compactSize
        )
        let clampedCompactFrame = clamp(compactFrame, inside: visibleFrame)

        let inFlightExpandFrame = inFlightExpandFrames.removeValue(forKey: ObjectIdentifier(window))
        if inFlightExpandFrame != nil {
            // A later setFrame does not cancel an in-flight animator animation,
            // which would otherwise resume and re-expand the collapsed window.
            NSAnimationContext.runAnimationGroup { context in
                context.duration = 0
                context.allowsImplicitAnimation = false
                window.animator().setFrame(window.frame, display: true)
            }
        }
        if state == nil {
            state = State(
                expandedFrame: inFlightExpandFrame ?? currentFrame,
                minSize: window.minSize,
                maxSize: window.maxSize,
                contentMinSize: window.contentMinSize,
                contentMaxSize: window.contentMaxSize,
                initialCompactFrame: clampedCompactFrame
            )
        }

        window.minSize = compactSize
        window.maxSize = compactSize
        window.contentMinSize = compactSize
        window.contentMaxSize = compactSize
        window.setFrame(clampedCompactFrame, display: true, animate: animated)
    }

    static func expand(
        window: NSWindow,
        state: inout State?,
        fallbackSize: NSSize,
        overrideSize: NSSize? = nil
    ) {
        let currentFrame = window.frame
        guard let savedState = state else {
            applyContentResize(window: window, requestedSize: fallbackSize)
            return
        }

        restoreConstraints(window: window, state: savedState)
        let visibleFrame = visibleFrame(for: window, frame: currentFrame)
        let targetFrame: NSRect
        if let overrideSize {
            let clampedSize = NSSize(
                width: min(max(overrideSize.width, currentFrame.width), visibleFrame.width),
                height: min(max(overrideSize.height, currentFrame.height), visibleFrame.height)
            )
            targetFrame = frame(anchoredAt: .topLeft, compactFrame: currentFrame, size: clampedSize)
        } else {
            targetFrame = expandedFrame(
                savedFrame: savedState.expandedFrame,
                initialCompactFrame: savedState.initialCompactFrame,
                currentCompactFrame: currentFrame,
                visibleFrame: visibleFrame
            )
        }
        applyFrame(window: window, frame: targetFrame, visibleFrame: visibleFrame, animatesWithoutBlocking: true)
        restoreConstraints(window: window, state: savedState)
        state = nil
    }

    static func applyContentResize(window: NSWindow, requestedSize: NSSize) {
        let currentFrame = window.frame
        let visibleFrame = visibleFrame(for: window, frame: currentFrame)
        let targetSize = NSSize(
            width: min(max(max(requestedSize.width, currentFrame.width), window.minSize.width), visibleFrame.width),
            height: min(max(max(requestedSize.height, currentFrame.height), window.minSize.height), visibleFrame.height)
        )
        let targetFrame = frame(
            anchoredAt: .topLeft,
            compactFrame: currentFrame,
            size: targetSize
        )
        applyFrame(window: window, frame: targetFrame, visibleFrame: visibleFrame)
    }

    static func applyLayoutResize(window: NSWindow, requestedSize: NSSize) {
        let currentFrame = window.frame
        let visibleFrame = visibleFrame(for: window, frame: currentFrame)
        let targetFrame = layoutResizeFrame(
            currentFrame: currentFrame,
            requestedSize: requestedSize,
            minSize: window.minSize,
            visibleFrame: visibleFrame
        )
        applyFrame(window: window, frame: targetFrame, visibleFrame: visibleFrame)
    }

    static func layoutResizeFrame(
        currentFrame: NSRect,
        requestedSize: NSSize,
        minSize: NSSize,
        visibleFrame: NSRect
    ) -> NSRect {
        let targetSize = constrainedSize(
            requestedSize: requestedSize,
            minSize: minSize,
            visibleFrame: visibleFrame
        )
        return clamp(
            frame(
                anchoredAt: .topLeft,
                compactFrame: currentFrame,
                size: targetSize
            ),
            inside: visibleFrame
        )
    }

    static func centeredFrame(
        requestedSize: NSSize,
        minSize: NSSize,
        visibleFrame: NSRect
    ) -> NSRect {
        let targetSize = constrainedSize(
            requestedSize: requestedSize,
            minSize: minSize,
            visibleFrame: visibleFrame
        )
        return NSRect(
            x: visibleFrame.midX - targetSize.width / 2,
            y: visibleFrame.midY - targetSize.height / 2,
            width: targetSize.width,
            height: targetSize.height
        )
    }

    static func expandedFrame(
        savedFrame: NSRect,
        initialCompactFrame: NSRect,
        currentCompactFrame: NSRect,
        visibleFrame: NSRect
    ) -> NSRect {
        if approximatelyEqual(initialCompactFrame, currentCompactFrame) {
            return clamp(savedFrame, inside: visibleFrame)
        }

        let constrainedSize = NSSize(
            width: min(savedFrame.width, visibleFrame.width),
            height: min(savedFrame.height, visibleFrame.height)
        )
        let preferredAnchor = anchorAwayFromNearestEdge(
            frame: currentCompactFrame,
            visibleFrame: visibleFrame
        )
        let candidates = [preferredAnchor] + Anchor.allCases.filter { $0 != preferredAnchor }
        let frames = candidates.map {
            frame(anchoredAt: $0, compactFrame: currentCompactFrame, size: constrainedSize)
        }

        if let fullyVisible = frames.first(where: { contains(visibleFrame, frame: $0) }) {
            return fullyVisible
        }

        return frames
            .max(by: { intersectionArea($0, visibleFrame) < intersectionArea($1, visibleFrame) })
            .map { clamp($0, inside: visibleFrame) }
            ?? clamp(savedFrame, inside: visibleFrame)
    }

    private static func compactSize(_ preferredSize: NSSize, visibleFrame: NSRect) -> NSSize {
        NSSize(
            width: min(max(preferredSize.width, 1), compactWidthCap, visibleFrame.width),
            height: min(max(preferredSize.height, 1), visibleFrame.height)
        )
    }

    private static func constrainedSize(
        requestedSize: NSSize,
        minSize: NSSize,
        visibleFrame: NSRect
    ) -> NSSize {
        NSSize(
            width: min(max(requestedSize.width, minSize.width), visibleFrame.width),
            height: min(max(requestedSize.height, minSize.height), visibleFrame.height)
        )
    }

    private static func visibleFrame(for window: NSWindow, frame: NSRect) -> NSRect {
        resolvedVisibleFrame(
            currentScreenVisibleFrame: window.screen?.visibleFrame,
            frame: frame,
            screenVisibleFrames: NSScreen.screens.map(\.visibleFrame),
            fallbackVisibleFrame: NSScreen.main?.visibleFrame
        )
    }

    static func resolvedVisibleFrame(
        currentScreenVisibleFrame: NSRect?,
        frame: NSRect,
        screenVisibleFrames: [NSRect],
        fallbackVisibleFrame: NSRect?
    ) -> NSRect {
        let frameCenter = NSPoint(x: frame.midX, y: frame.midY)
        if let currentScreenVisibleFrame,
           currentScreenVisibleFrame.contains(frameCenter) {
            return currentScreenVisibleFrame
        }
        if let intersectingFrame = screenVisibleFrames.max(by: {
            intersectionArea($0, frame) < intersectionArea($1, frame)
        }), intersectionArea(intersectingFrame, frame) > 0 {
            return intersectingFrame
        }
        return fallbackVisibleFrame ?? frame
    }

    static func collapseAnchor(frame: NSRect, visibleFrame: NSRect) -> Anchor {
        let distanceToLeftEdge = abs(frame.minX - visibleFrame.minX)
        let distanceToRightEdge = abs(visibleFrame.maxX - frame.maxX)
        return distanceToLeftEdge <= distanceToRightEdge ? .topLeft : .topRight
    }

    private static func anchorAwayFromNearestEdge(frame: NSRect, visibleFrame: NSRect) -> Anchor {
        let useLeft = frame.midX <= visibleFrame.midX
        let useTop = frame.midY >= visibleFrame.midY
        switch (useLeft, useTop) {
        case (true, true): return .topLeft
        case (false, true): return .topRight
        case (true, false): return .bottomLeft
        case (false, false): return .bottomRight
        }
    }

    private static func frame(anchoredAt anchor: Anchor, compactFrame: NSRect, size: NSSize) -> NSRect {
        switch anchor {
        case .topLeft:
            return NSRect(x: compactFrame.minX, y: compactFrame.maxY - size.height, width: size.width, height: size.height)
        case .topRight:
            return NSRect(x: compactFrame.maxX - size.width, y: compactFrame.maxY - size.height, width: size.width, height: size.height)
        case .bottomLeft:
            return NSRect(x: compactFrame.minX, y: compactFrame.minY, width: size.width, height: size.height)
        case .bottomRight:
            return NSRect(x: compactFrame.maxX - size.width, y: compactFrame.minY, width: size.width, height: size.height)
        }
    }

    /// `setFrame(_:display:animate:)` runs its animation in a blocking loop that
    /// starves the main run loop, so a hosted WKWebView cannot receive the
    /// repaint for each new size until the animation ends and the window looks
    /// like it pops to full size. Expanding is the case where the page must
    /// paint new area as the window grows, so it uses the animator proxy, which
    /// keeps the main run loop serviced. Collapse only clips existing content
    /// and keeps the blocking form.
    private static func applyFrame(
        window: NSWindow,
        frame: NSRect,
        visibleFrame: NSRect,
        animatesWithoutBlocking: Bool = false
    ) {
        let effectiveMinSize = NSSize(
            width: min(window.minSize.width, visibleFrame.width),
            height: min(window.minSize.height, visibleFrame.height)
        )
        let effectiveMaxSize = NSSize(
            width: max(window.maxSize.width, frame.width),
            height: max(window.maxSize.height, frame.height)
        )
        window.minSize = effectiveMinSize
        window.maxSize = effectiveMaxSize
        window.contentMinSize = effectiveMinSize
        let targetFrame = clamp(frame, inside: visibleFrame)
        guard animatesWithoutBlocking else {
            window.setFrame(targetFrame, display: true, animate: true)
            return
        }

        let windowID = ObjectIdentifier(window)
        inFlightExpandFrames[windowID] = targetFrame
        NSAnimationContext.runAnimationGroup({ context in
            context.duration = window.animationResizeTime(targetFrame)
            context.allowsImplicitAnimation = true
            window.animator().setFrame(targetFrame, display: true)
        }, completionHandler: {
            if inFlightExpandFrames[windowID] == targetFrame {
                inFlightExpandFrames[windowID] = nil
            }
        })
    }

    private static func restoreConstraints(window: NSWindow, state: State) {
        window.minSize = state.minSize
        window.maxSize = state.maxSize
        window.contentMinSize = state.contentMinSize
        window.contentMaxSize = state.contentMaxSize
    }

    private static func clamp(_ frame: NSRect, inside visibleFrame: NSRect) -> NSRect {
        let width = min(frame.width, visibleFrame.width)
        let height = min(frame.height, visibleFrame.height)
        return NSRect(
            x: min(max(frame.minX, visibleFrame.minX), visibleFrame.maxX - width),
            y: min(max(frame.minY, visibleFrame.minY), visibleFrame.maxY - height),
            width: width,
            height: height
        )
    }

    private static func contains(_ outer: NSRect, frame: NSRect) -> Bool {
        outer.contains(frame)
    }

    private static func approximatelyEqual(_ lhs: NSRect, _ rhs: NSRect) -> Bool {
        abs(lhs.origin.x - rhs.origin.x) <= movementTolerance
            && abs(lhs.origin.y - rhs.origin.y) <= movementTolerance
            && abs(lhs.width - rhs.width) <= movementTolerance
            && abs(lhs.height - rhs.height) <= movementTolerance
    }

    private static func intersectionArea(_ lhs: NSRect, _ rhs: NSRect) -> CGFloat {
        let intersection = lhs.intersection(rhs)
        return max(0, intersection.width) * max(0, intersection.height)
    }
}
