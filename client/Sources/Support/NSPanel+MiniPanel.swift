import AppKit

extension NSPanel {
    /// Applies the property block shared by Basil's non-activating mini panels.
    ///
    /// On top of the floating-widget block (with `.stationary`), the panel is a floating panel, becomes key only when needed, and keeps working while a modal is up.
    ///
    /// - Parameters:
    ///   - title: The panel title.
    ///   - ignoresWindowCycling: Pass `false` for a panel that should stay in window cycling. Defaults to `true`.
    ///   - releasedWhenClosed: Assigned only when non-nil.
    ///   - transparency: `.clearWithoutShadow` also clears the shadow, opacity, and background color.
    ///
    /// `delegate`, size limits, content view, alpha, and appearance stay at the call site.
    @MainActor
    func configureMiniPanel(
        title: String,
        ignoresWindowCycling: Bool = true,
        releasedWhenClosed: Bool? = nil,
        transparency: FloatingWidgetTransparency = .inherited
    ) {
        configureFloatingWidget(
            title: title,
            releasedWhenClosed: releasedWhenClosed,
            includesStationary: true,
            ignoresWindowCycling: ignoresWindowCycling,
            transparency: transparency
        )
        isFloatingPanel = true
        becomesKeyOnlyIfNeeded = true
        worksWhenModal = true
    }
}
