import AppKit

extension NSAlert {
    /// Shows a modal prompt whose first button opens a System Settings privacy pane and whose second button declines.
    ///
    /// Returns true only when the first button was chosen and the pane opened. The `present` and `open` parameters exist so tests can drive the flow without UI.
    @MainActor
    @discardableResult
    static func runSystemSettingsPrompt(
        title: String,
        message: String,
        style: NSAlert.Style = .warning,
        declineTitle: String,
        pane: SystemSettingsPrivacyPane,
        present: @MainActor (NSAlert) -> NSApplication.ModalResponse = { $0.runModal() },
        open: @MainActor (SystemSettingsPrivacyPane) -> Bool = { $0.open() }
    ) -> Bool {
        let alert = NSAlert(
            title: title,
            message: message,
            style: style,
            buttons: ["Open System Settings", declineTitle]
        )
        guard present(alert) == .alertFirstButtonReturn else { return false }
        return open(pane)
    }
}
