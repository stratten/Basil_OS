import AppKit

extension NSAlert {
    /// Builds an alert from the property block every Basil alert repeats.
    ///
    /// - Parameters:
    ///   - title: The alert's `messageText`.
    ///   - message: The alert's `informativeText`.
    ///   - style: The alert style. Defaults to `.warning`, the AppKit default.
    ///   - buttons: Button titles in the order they are added. The first is the default button.
    ///   - destructiveButtonIndex: The index in `buttons` whose `hasDestructiveAction` is set, or nil for none.
    ///
    /// The run method (`runModal` or `beginSheetModal`) and the response handling stay at the call site.
    ///
    /// Not annotated `@MainActor`, because `NSAlert()` was already callable from nonisolated code (`ModelsSettingsAlertFactory`) and the helper must not tighten that.
    convenience init(
        title: String,
        message: String,
        style: NSAlert.Style = .warning,
        buttons: [String],
        destructiveButtonIndex: Int? = nil
    ) {
        self.init()
        messageText = title
        informativeText = message
        alertStyle = style
        for (index, buttonTitle) in buttons.enumerated() {
            let button = addButton(withTitle: buttonTitle)
            if index == destructiveButtonIndex {
                button.hasDestructiveAction = true
            }
        }
    }
}
