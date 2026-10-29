import AppKit

enum DetachedAgentTaskWindowPlacement {
    private static let gap: CGFloat = 24
    private static let cascadeStep: CGFloat = 28

    static func resolvedVisibleFrame(
        originatingScreenVisibleFrame: NSRect?,
        sourceFrame: NSRect,
        screenVisibleFrames: [NSRect],
        fallbackVisibleFrame: NSRect?
    ) -> NSRect {
        if let originatingScreenVisibleFrame {
            return originatingScreenVisibleFrame
        }
        return WindowChromeCollapse.resolvedVisibleFrame(
            currentScreenVisibleFrame: nil,
            frame: sourceFrame,
            screenVisibleFrames: screenVisibleFrames,
            fallbackVisibleFrame: fallbackVisibleFrame
        )
    }

    static func frame(
        windowSize: NSSize,
        sourceFrame: NSRect,
        visibleFrame: NSRect,
        occupiedFrames: [NSRect]
    ) -> NSRect {
        let size = NSSize(
            width: min(windowSize.width, visibleFrame.width),
            height: min(windowSize.height, visibleFrame.height)
        )
        let candidates = rawCandidates(size: size, sourceFrame: sourceFrame)
            .map { clamp($0, inside: visibleFrame) }

        if let collisionFree = candidates.first(where: { overlapArea(of: $0, with: occupiedFrames) == 0 }) {
            return collisionFree
        }

        return candidates.min { lhs, rhs in
            let lhsOverlap = overlapArea(of: lhs, with: occupiedFrames)
            let rhsOverlap = overlapArea(of: rhs, with: occupiedFrames)
            if lhsOverlap != rhsOverlap {
                return lhsOverlap < rhsOverlap
            }
            return distance(from: lhs, to: sourceFrame) < distance(from: rhs, to: sourceFrame)
        } ?? clamp(NSRect(origin: sourceFrame.origin, size: size), inside: visibleFrame)
    }

    private static func rawCandidates(size: NSSize, sourceFrame: NSRect) -> [NSRect] {
        let baseOrigins = [
            NSPoint(x: sourceFrame.maxX + gap, y: sourceFrame.maxY - size.height),
            NSPoint(x: sourceFrame.minX - size.width - gap, y: sourceFrame.maxY - size.height),
            NSPoint(x: sourceFrame.maxX + gap, y: sourceFrame.minY),
            NSPoint(x: sourceFrame.minX - size.width - gap, y: sourceFrame.minY),
        ]
        let cascadeOffsets: [NSPoint] = [
            .zero,
            NSPoint(x: cascadeStep, y: -cascadeStep),
            NSPoint(x: -cascadeStep, y: cascadeStep),
            NSPoint(x: cascadeStep * 2, y: -cascadeStep * 2),
            NSPoint(x: -cascadeStep * 2, y: cascadeStep * 2),
        ]

        return cascadeOffsets.flatMap { offset in
            baseOrigins.map { origin in
                NSRect(
                    x: origin.x + offset.x,
                    y: origin.y + offset.y,
                    width: size.width,
                    height: size.height
                )
            }
        }
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

    private static func overlapArea(of frame: NSRect, with occupiedFrames: [NSRect]) -> CGFloat {
        occupiedFrames.reduce(0) { total, occupiedFrame in
            let intersection = frame.intersection(occupiedFrame)
            return total + max(0, intersection.width) * max(0, intersection.height)
        }
    }

    private static func distance(from lhs: NSRect, to rhs: NSRect) -> CGFloat {
        hypot(lhs.midX - rhs.midX, lhs.midY - rhs.midY)
    }
}
