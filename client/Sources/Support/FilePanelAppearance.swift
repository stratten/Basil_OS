import AppKit

extension NSSavePanel {
    /// Web-hosted windows are pinned to Aqua, and sheets inherit their parent's appearance, so file dialogs would otherwise render light under a dark theme. Setting it here scopes the override to the dialog and leaves window chrome alone. `NSOpenPanel` inherits this.
    @MainActor
    func applyBasilThemedAppearance() {
        appearance = NativeModelPickerPopoverSupport.themedAppearance()
    }

    /// Presents a standalone (non-sheet) file dialog above Basil's floating widgets.
    ///
    /// Basil's floating widgets sit at `.floating` (see `NSWindow.configureFloatingWidget`), and a dialog opened with a plain `begin` stays at the default window level, so the widget that launched it covers it. The dialog is raised to `.modalPanel`, which is above `.floating`, and the app is activated so the dialog is key. The level is reapplied after `begin` in case AppKit resets it while presenting. Dialogs presented as sheets (`beginSheetModal`) attach to their parent window and do not need this.
    @MainActor
    func beginAboveFloatingWindows(completionHandler: @escaping (NSApplication.ModalResponse) -> Void) {
        level = .modalPanel
        NSApp.activate(ignoringOtherApps: true)
        begin(completionHandler: completionHandler)
        level = .modalPanel
    }
}
