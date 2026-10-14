import AppKit

/// Whether a floating widget window applies the transparent chrome (no shadow, non-opaque, clear background) itself.
///
/// Windows that later call `WebKitWindowChromeAppearance.apply(to:)` use `.inherited`, because that helper sets the same triple.
enum FloatingWidgetTransparency {
    case inherited
    case clearWithoutShadow
}

extension NSWindow {
    /// Applies the property block shared by Basil's floating widget windows.
    ///
    /// The window is placed at the floating level, joins every space, ignores window cycling, does not hide on deactivate, and can be dragged by its background.
    ///
    /// - Parameters:
    ///   - title: Assigned only when non-nil.
    ///   - releasedWhenClosed: Assigned only when non-nil. Pass `nil` to keep the AppKit default, which some windows rely on.
    ///   - includesStationary: Adds `.stationary` to the collection behavior so the window does not move when switching spaces.
    ///   - ignoresWindowCycling: Adds `.ignoresCycle` so the window is skipped when cycling windows. Defaults to `true`.
    ///   - transparency: `.clearWithoutShadow` also clears the shadow, opacity, and background color.
    ///
    /// `delegate`, size limits, content view, appearance, and panel-only properties stay at the call site.
    @MainActor
    func configureFloatingWidget(
        title: String? = nil,
        releasedWhenClosed: Bool? = nil,
        includesStationary: Bool = false,
        ignoresWindowCycling: Bool = true,
        transparency: FloatingWidgetTransparency = .inherited
    ) {
        if let title {
            self.title = title
        }
        if let releasedWhenClosed {
            isReleasedWhenClosed = releasedWhenClosed
        }
        level = .floating
        var behavior: NSWindow.CollectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        if ignoresWindowCycling {
            behavior.insert(.ignoresCycle)
        }
        if includesStationary {
            behavior.insert(.stationary)
        }
        collectionBehavior = behavior
        hidesOnDeactivate = false
        isMovableByWindowBackground = true
        if transparency == .clearWithoutShadow {
            hasShadow = false
            isOpaque = false
            backgroundColor = .clear
        }
    }
}
