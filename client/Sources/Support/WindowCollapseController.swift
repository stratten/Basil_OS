import AppKit

/// Shared per-window collapse/expand controller. Wraps `WindowChromeCollapse`
/// (the geometry engine) plus the small piece of state every existing
/// collapsible window controller previously duplicated by hand
/// (`collapseState`, `isCollapsed`, and a named toggle method). Constructing
/// one of these for a given `NSWindow` is the single "enable collapse for
/// this window" switch; a window that should never collapse simply never
/// constructs one.
@MainActor
final class WindowCollapseController {
    private weak var window: NSWindow?
    private var state: WindowChromeCollapse.State?
    private let compactSize: NSSize
    private let fallbackExpandedSize: NSSize

    /// Whether the window is currently collapsed. Callers that need to
    /// suppress frame-size persistence while collapsed (as
    /// `ConversationWindowController` does today) should check this before
    /// saving `window.frame.size`.
    private(set) var isCollapsed = false

    /// - Parameters:
    ///   - window: The window this controller collapses/expands in place.
    ///   - compactSize: Preferred collapsed size. The width is clamped to
    ///     the window's current width at collapse time, matching every
    ///     existing hand-rolled implementation (`min(window.frame.width,
    ///     compactWidth)`), so a narrower window never collapses wider than
    ///     it already was.
    ///   - fallbackExpandedSize: Size to restore to if no prior expanded
    ///     frame was recorded (mirrors `WindowChromeCollapse.expand`'s own
    ///     `fallbackSize` parameter).
    init(window: NSWindow, compactSize: NSSize, fallbackExpandedSize: NSSize) {
        self.window = window
        self.compactSize = compactSize
        self.fallbackExpandedSize = fallbackExpandedSize
    }

    /// - Parameters:
    ///   - preferredCompactSize: Overrides the constructor's `compactSize`
    ///     for this call only. Pass this when the caller (e.g. a
    ///     React-driven resize request) knows a better collapsed size than
    ///     the fixed default. When `nil`, behavior is unchanged from
    ///     before this parameter existed.
    ///   - fallbackExpandedSize: Overrides the constructor's
    ///     `fallbackExpandedSize` for this expand call only. Ignored when
    ///     `collapsed` is `true`.
    func setCollapsed(
        _ collapsed: Bool,
        preferredCompactSize: NSSize? = nil,
        fallbackExpandedSize: NSSize? = nil,
        animated: Bool = true
    ) {
        guard let window else { return }
        isCollapsed = collapsed
        if collapsed {
            let requestedSize = preferredCompactSize ?? compactSize
            let clampedSize = NSSize(
                width: min(window.frame.width, requestedSize.width),
                height: requestedSize.height
            )
            if animated {
                WindowChromeCollapse.collapse(window: window, preferredCompactSize: clampedSize, state: &state)
            } else {
                WindowChromeCollapse.collapseWithoutAnimation(window: window, preferredCompactSize: clampedSize, state: &state)
            }
        } else {
            let resolvedFallback = fallbackExpandedSize ?? self.fallbackExpandedSize
            WindowChromeCollapse.expand(window: window, state: &state, fallbackSize: resolvedFallback, overrideSize: fallbackExpandedSize, animated: animated)
        }
    }

    func toggle() {
        setCollapsed(!isCollapsed)
    }
}
