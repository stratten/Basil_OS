import AppKit
import ObjectiveC
@preconcurrency import WebKit

/// The rules the blueprint reveal needs from the native side, kept pure so they can be tested without a window.
@MainActor
enum BlueprintRevealPolicy {
    /// True when the user can see the window as an appearance: it is on screen and not minimized. Being covered by another app's window is deliberately not counted. A normal-level window is covered every time the user switches apps, and redrawing the blueprint on every app switch would be a nuisance.
    nonisolated static func isEffectivelyVisible(isVisible: Bool, isMiniaturized: Bool) -> Bool {
        isVisible && !isMiniaturized
    }

    /// Resizes animate, except the first one after the window opens while the blueprint reveal is on. That first resize happens while the page is still hidden and measuring, so it jumps straight to the final size: measuring a window that is still animating would trace the wrong size.
    nonisolated static func shouldAnimateResize(hasResizedBefore: Bool, blueprintReveal: Bool) -> Bool {
        hasResizedBefore || !blueprintReveal
    }

    /// `shouldAnimateResize(hasResizedBefore:blueprintReveal:)` with the user's current setting.
    static func shouldAnimateResize(hasResizedBefore: Bool) -> Bool {
        shouldAnimateResize(hasResizedBefore: hasResizedBefore, blueprintReveal: AestheticSystem.blueprintReveal)
    }

    /// The event detail the pages read: whether the window is in sight, and the setting at that moment so a change in Settings applies to the next appearance.
    nonisolated static func visibilityDetail(visible: Bool, blueprintReveal: Bool) -> [String: Any] {
        ["visible": visible, "blueprintReveal": blueprintReveal]
    }

    /// Source of the document-start script that tells a page whether to play the blueprint reveal. The web side reads `window.basilBlueprintReveal === true`.
    nonisolated static func firstPaintScriptSource(enabled: Bool) -> String {
        "window.basilBlueprintReveal = \(enabled ? "true" : "false");"
    }
}

/// Tells every web page in a window when the window goes out of sight (ordered out, minimized, its app hidden) and when it comes back, so the blueprint reveal replays on every appearance and not only the first. One reporter per window; installing twice does nothing.
@MainActor
final class BlueprintRevealVisibilityReporter: NSObject {
    /// The page's window event, `basil-window-visibility`, carrying the detail. Called with the detail as its one argument.
    static let dispatchFunction = "(detail) => window.dispatchEvent(new CustomEvent('basil-window-visibility', { detail }))"

    private static var associationKey: UInt8 = 0

    private weak var window: NSWindow?
    /// Whether the pages were last told their window is in sight. A new window starts in sight: the page plays its own first reveal, so only later changes are reported.
    private var lastReportedVisible = true

    /// Starts reporting for `window` if it is not already being reported. The reporter lives as long as the window does, so a window that is closed and shown again keeps reporting.
    static func install(on window: NSWindow) {
        guard installedReporter(on: window) == nil else { return }
        objc_setAssociatedObject(window, &associationKey, BlueprintRevealVisibilityReporter(window: window), .OBJC_ASSOCIATION_RETAIN_NONATOMIC)
    }

    /// The reporter already installed on `window`, if any.
    static func installedReporter(on window: NSWindow) -> BlueprintRevealVisibilityReporter? {
        objc_getAssociatedObject(window, &associationKey) as? BlueprintRevealVisibilityReporter
    }

    /// Every web view in the window, including ones nested inside container views.
    static func webViews(in view: NSView?) -> [WKWebView] {
        guard let view else { return [] }
        let own = (view as? WKWebView).map { [$0] } ?? []
        return own + view.subviews.flatMap { webViews(in: $0) }
    }

    private init(window: NSWindow) {
        self.window = window
        super.init()
        let center = NotificationCenter.default
        center.addObserver(self, selector: #selector(reevaluate), name: NSWindow.didMiniaturizeNotification, object: window)
        center.addObserver(self, selector: #selector(reevaluate), name: NSWindow.didDeminiaturizeNotification, object: window)
        // Fires for ordering a window out and back in as well as for being covered; `reevaluate` tells them apart by the window's own visibility.
        center.addObserver(self, selector: #selector(reevaluate), name: NSWindow.didChangeOcclusionStateNotification, object: window)
        center.addObserver(self, selector: #selector(reevaluate), name: NSApplication.didHideNotification, object: nil)
        center.addObserver(self, selector: #selector(reevaluate), name: NSApplication.didUnhideNotification, object: nil)
    }

    @objc private func reevaluate() {
        guard let window else { return }
        let visible = BlueprintRevealPolicy.isEffectivelyVisible(isVisible: window.isVisible, isMiniaturized: window.isMiniaturized)
        guard visible != lastReportedVisible else { return }
        lastReportedVisible = visible
        let detail = BlueprintRevealPolicy.visibilityDetail(visible: visible, blueprintReveal: AestheticSystem.blueprintReveal)
        for webView in Self.webViews(in: window.contentView) {
            webView.callBasilEventHandler(
                Self.dispatchFunction,
                event: detail,
                logTag: "BLUEPRINT_REVEAL",
                logContext: "BlueprintRevealVisibilityReporter"
            )
        }
    }
}
