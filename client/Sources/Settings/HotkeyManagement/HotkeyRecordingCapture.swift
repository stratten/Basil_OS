import AppKit

/// Drives native hotkey-combo capture for the React Hotkeys tab. WKWebView can
/// reclaim first-responder status from an embedded NSTextField during a React
/// re-render, so the capture owns local event monitors instead of depending on
/// an off-screen text field remaining focused.
@MainActor
final class HotkeyRecordingCapture {
    static let shared = HotkeyRecordingCapture()

    private var eventMonitor: Any?
    private var onCaptured: ((String) -> Void)?
    private var onCancelled: (() -> Void)?
    private var isCapturing = false
    private var lastModifierPress: (flag: NSEvent.ModifierFlags, timestamp: TimeInterval)?
    private var previousModifierFlags: NSEvent.ModifierFlags = []

    private init() {}

    /// Begins capturing the next key combo from the Settings window. Calling
    /// this while already capturing for a different row is a caller error.
    func startCapture(in _: NSView, onCaptured: @escaping (String) -> Void, onCancelled: @escaping () -> Void) {
        guard !isCapturing else { return }
        isCapturing = true
        self.onCaptured = onCaptured
        self.onCancelled = onCancelled
        lastModifierPress = nil
        previousModifierFlags = []
        HotkeyService.shared.suspendListeners()
        eventMonitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .flagsChanged]) { [weak self] event in
            guard let self else { return event }
            return self.handleCaptureEvent(event) ? nil : event
        }
    }

    /// Cancels an in-progress capture without producing a binding.
    func cancelCapture() {
        guard isCapturing else { return }
        let callback = onCancelled
        finishCapture()
        callback?()
    }

    private func handleCaptureEvent(_ event: NSEvent) -> Bool {
        guard isCapturing else { return false }
        if event.type == .flagsChanged {
            return handleModifierEvent(event)
        }
        guard let value = displayString(for: event) else { return false }
        let callback = onCaptured
        finishCapture()
        callback?(value)
        return true
    }

    private func handleModifierEvent(_ event: NSEvent) -> Bool {
        let currentFlags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
        let now = Date().timeIntervalSince1970
        let modifiers: [(NSEvent.ModifierFlags, String)] = [(.option, "⌥"), (.command, "⌘"), (.control, "⌃"), (.shift, "⇧")]

        for (flag, symbol) in modifiers where !previousModifierFlags.contains(flag) && currentFlags.contains(flag) {
            if let lastModifierPress, lastModifierPress.flag == flag, now - lastModifierPress.timestamp <= 0.3 {
                let callback = onCaptured
                finishCapture()
                callback?("\(symbol)+\(symbol)")
                return true
            }
            lastModifierPress = (flag, now)
        }

        previousModifierFlags = currentFlags
        return true
    }

    private func displayString(for event: NSEvent) -> String? {
        let modifiers = [
            event.modifierFlags.contains(.command) ? "⌘" : "",
            event.modifierFlags.contains(.control) ? "⌃" : "",
            event.modifierFlags.contains(.option) ? "⌥" : "",
            event.modifierFlags.contains(.shift) ? "⇧" : "",
        ].joined()
        let key: String
        switch event.keyCode {
        case 36: key = "↩"
        case 48: key = "⇥"
        case 49: key = "Space"
        case 51: key = "⌫"
        case 53: key = "⎋"
        case 123: key = "←"
        case 124: key = "→"
        case 125: key = "↓"
        case 126: key = "↑"
        default:
            guard let characters = event.charactersIgnoringModifiers?.uppercased(), !characters.isEmpty else { return nil }
            key = characters
        }
        return modifiers + key
    }

    private func finishCapture() {
        if let eventMonitor {
            NSEvent.removeMonitor(eventMonitor)
            self.eventMonitor = nil
        }
        isCapturing = false
        onCaptured = nil
        onCancelled = nil
        lastModifierPress = nil
        previousModifierFlags = []
        HotkeyService.shared.resumeListeners()
    }
}
