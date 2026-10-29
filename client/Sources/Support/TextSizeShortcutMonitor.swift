import AppKit
import Foundation

/// A text size keyboard command: larger (Cmd+= or Cmd++), smaller (Cmd+-), or back to 100% (Cmd+0).
enum TextSizeShortcut: Equatable {
    case larger
    case smaller
    case reset

    /// Resolves a key press to a text size command, or nil when it is not one.
    ///
    /// Command must be held. Option and Control never qualify, so Cmd+Option+- and similar system and app shortcuts keep working. Shift is accepted only for the two keys that need it on a US layout, because Cmd++ is Shift+= and Cmd+_ is Shift+-.
    static func resolve(charactersIgnoringModifiers: String?, modifierFlags: NSEvent.ModifierFlags) -> TextSizeShortcut? {
        let held = modifierFlags.intersection([.command, .shift, .option, .control])
        guard held.contains(.command), !held.contains(.option), !held.contains(.control) else { return nil }
        let shiftHeld = held.contains(.shift)
        switch charactersIgnoringModifiers {
        case "=", "+":
            return .larger
        case "-", "_":
            return .smaller
        case "0":
            return shiftHeld ? nil : .reset
        default:
            return nil
        }
    }

    /// The step this command moves to from `current`.
    func target(from current: Double) -> Double {
        switch self {
        case .larger: return TextScaleStep.larger(than: current)
        case .smaller: return TextScaleStep.smaller(than: current)
        case .reset: return TextScaleStep.defaultScale
        }
    }
}

/// Changes the app-wide text size from the keyboard in every Basil window, Settings included.
///
/// A press applies the new size at once by caching the updated appearance settings, which reloads `AestheticSystem` and notifies every open window, then saves it to the backend after a short pause. The pause means a burst of presses produces a single save of the final size instead of one request per press. While the Settings appearance draft is unsaved the shortcut changes the draft's size instead, so the preview that window is showing is not discarded; that size is saved with the rest of the draft.
@MainActor
final class TextSizeShortcutMonitor {
    nonisolated static let defaultSaveDelayNanoseconds: UInt64 = 300_000_000

    private var eventMonitor: Any?
    private var pendingSave: Task<Void, Never>?
    private let currentSettings: () -> AppearanceSettings?
    private let applySettings: (AppearanceSettings) -> Void
    private let persistSettings: (AppearanceSettings) async throws -> Void
    private let applyToUnsavedDraft: @MainActor (TextSizeShortcut) -> Bool
    private let saveDelayNanoseconds: UInt64

    init(
        currentSettings: @escaping () -> AppearanceSettings? = { APIClient.shared.cachedAppearanceSettings },
        applySettings: @escaping (AppearanceSettings) -> Void = { APIClient.shared.cacheAppearanceSettings($0) },
        persistSettings: @escaping (AppearanceSettings) async throws -> Void = TextSizeShortcutMonitor.persistToBackend,
        applyToUnsavedDraft: @escaping @MainActor (TextSizeShortcut) -> Bool = TextSizeShortcutMonitor.applyToSettingsDraft,
        saveDelayNanoseconds: UInt64 = TextSizeShortcutMonitor.defaultSaveDelayNanoseconds
    ) {
        self.currentSettings = currentSettings
        self.applySettings = applySettings
        self.persistSettings = persistSettings
        self.applyToUnsavedDraft = applyToUnsavedDraft
        self.saveDelayNanoseconds = saveDelayNanoseconds
    }

    func start() {
        guard eventMonitor == nil else { return }
        eventMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            self?.handleKeyDown(event) ?? event
        }
    }

    func stop() {
        if let eventMonitor {
            NSEvent.removeMonitor(eventMonitor)
            self.eventMonitor = nil
        }
    }

    /// True while the user is composing text with an input method, where Cmd+- and friends belong to the composition.
    static func isComposingText(in responder: NSResponder?) -> Bool {
        (responder as? NSTextInputClient)?.hasMarkedText() ?? false
    }

    static func applyToSettingsDraft(_ shortcut: TextSizeShortcut) -> Bool {
        SettingsShellWindowController.shared.applyTextSizeShortcutToDraft(shortcut)
    }

    static func persistToBackend(_ settings: AppearanceSettings) async throws {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let data = try encoder.encode(settings)
        _ = try await APIClient.shared.put("/settings/appearance", data: data)
    }

    private func handleKeyDown(_ event: NSEvent) -> NSEvent? {
        guard let shortcut = TextSizeShortcut.resolve(
            charactersIgnoringModifiers: event.charactersIgnoringModifiers,
            modifierFlags: event.modifierFlags
        ) else { return event }
        guard !Self.isComposingText(in: NSApp.keyWindow?.firstResponder) else { return event }
        return handle(shortcut) ? nil : event
    }

    /// Applies `shortcut` and schedules the save. Returns whether the key press was consumed; it is left to the system only when the settings are not loaded yet.
    @discardableResult
    func handle(_ shortcut: TextSizeShortcut) -> Bool {
        guard let settings = currentSettings() else { return false }
        if applyToUnsavedDraft(shortcut) { return true }
        let target = shortcut.target(from: settings.textScale)
        guard target != TextScaleStep.snapped(settings.textScale) else { return true }
        var updated = settings
        updated.textScale = target
        applySettings(updated)
        scheduleSave()
        return true
    }

    /// Resolves once the save scheduled by the latest key press has finished, so tests can wait on the real completion instead of sleeping.
    func waitForPendingSave() async {
        await pendingSave?.value
    }

    private func scheduleSave() {
        pendingSave?.cancel()
        let delay = saveDelayNanoseconds
        // Strong capture on purpose: a save still pending when the monitor is stopped at termination must run to completion.
        pendingSave = Task { @MainActor in
            try? await Task.sleep(nanoseconds: delay)
            guard !Task.isCancelled, let latest = self.currentSettings() else { return }
            do {
                try await self.persistSettings(latest)
            } catch {
                #if DEBUG
                DevLogger.shared.error("Failed to save the text size: \(error.localizedDescription)", context: "TextSizeShortcutMonitor")
                #endif
            }
        }
    }
}
