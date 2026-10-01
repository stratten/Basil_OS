import AppKit
import SwiftUI

enum NativeModelPickerPopoverSupport {
    /// Converts a WebKit `getBoundingClientRect()` rect (top-left origin, y grows downward) into the host view's coordinate space. WKWebView reports `isFlipped == true`, so its rect passes through unchanged; flipping it again mirrors the anchor vertically.
    static func anchorRect(
        webX: CGFloat,
        webY: CGFloat,
        width: CGFloat,
        height: CGFloat,
        hostBounds: NSRect,
        hostIsFlipped: Bool
    ) -> NSRect {
        NSRect(
            x: webX,
            y: hostIsFlipped ? webY : hostBounds.height - webY - height,
            width: width,
            height: height
        )
    }

    static func appearanceName(for colorScheme: ColorScheme) -> NSAppearance.Name {
        colorScheme == .dark ? .darkAqua : .aqua
    }

    static func themedAppearance() -> NSAppearance? {
        NSAppearance(named: appearanceName(for: AestheticSystem.effectiveColorScheme))
    }

    /// NSPopover has no public background-color API. The popover frame view clips its subviews to the bubble shape, arrow included, so a fill view inserted beneath the content paints the arrow too. Call after `show(relativeTo:of:preferredEdge:)`; if AppKit's hierarchy differs this is a no-op and the system material remains.
    @MainActor
    static func paintFrameBackground(of popover: NSPopover, color: NSColor) {
        guard let windowContentView = popover.contentViewController?.view.window?.contentView,
              let frameView = windowContentView.superview else {
            return
        }
        if let existing = frameView.subviews.compactMap({ $0 as? ThemedPopoverBackgroundView }).first {
            existing.layer?.backgroundColor = color.cgColor
            return
        }
        let backgroundView = ThemedPopoverBackgroundView(frame: frameView.bounds)
        backgroundView.wantsLayer = true
        backgroundView.layer?.backgroundColor = color.cgColor
        backgroundView.autoresizingMask = [.width, .height]
        frameView.addSubview(backgroundView, positioned: .below, relativeTo: windowContentView)
    }

    @MainActor
    static func paintThemedFrameBackground(of popover: NSPopover) {
        paintFrameBackground(of: popover, color: NSColor(AestheticSystem.Colors.backgroundPrimary))
    }
}

final class ThemedPopoverBackgroundView: NSView {}
