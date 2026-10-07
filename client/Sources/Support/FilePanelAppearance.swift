import AppKit

extension NSSavePanel {
    /// Web-hosted windows are pinned to Aqua, and sheets inherit their parent's appearance, so file dialogs would otherwise render light under a dark theme. Setting it here scopes the override to the dialog and leaves window chrome alone. `NSOpenPanel` inherits this.
    @MainActor
    func applyBasilThemedAppearance() {
        appearance = NativeModelPickerPopoverSupport.themedAppearance()
    }
}
