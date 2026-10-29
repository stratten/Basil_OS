import AppKit

/// A pane of the macOS System Settings Privacy & Security page, addressed by its URL anchor.
enum SystemSettingsPrivacyPane: String, CaseIterable {
    case general = "Privacy"
    case microphone = "Privacy_Microphone"
    case accessibility = "Privacy_Accessibility"
    case inputMonitoring = "Privacy_ListenEvent"
    case appleEvents = "Privacy_Automation"
    case screenRecording = "Privacy_ScreenCapture"

    /// Maps the permission kind strings used by the web bridges. Returns nil for an unknown kind.
    init?(permissionKind: String) {
        switch permissionKind {
        case "microphone": self = .microphone
        case "accessibility": self = .accessibility
        case "input_monitoring": self = .inputMonitoring
        case "apple_events": self = .appleEvents
        case "screen_recording": self = .screenRecording
        default: return nil
        }
    }

    var url: URL {
        URL(string: "x-apple.systempreferences:com.apple.preference.security?\(rawValue)")!
    }

    @MainActor
    @discardableResult
    func open() -> Bool {
        NSWorkspace.shared.open(url)
    }
}
