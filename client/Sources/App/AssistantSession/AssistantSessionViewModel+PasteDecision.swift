import AppKit
import Foundation

/// When completed AssistantSession output is pasted into the app the session started from.
enum AssistantOutputPasteMode: String, Codable {
    case always
    case auto
    case never
}

/// What the widget reports under a completed response about the automatic paste.
enum AssistantSessionPasteOutcome: String {
    case pasted
    case shown
    case switchedApps
    case targetUnavailable
}

enum AssistantSessionPastePlan: Equatable {
    case skip(AssistantSessionPasteOutcome?)
    case pasteNow
    case reactivateThenPaste
}

/// Output is only ever pasted into the app that was frontmost when the session hotkey fired. When Basil itself is frontmost (the user typed or clicked in the widget) that app is re-activated first; any other frontmost app means the user moved on, so nothing is pasted.
func resolveAssistantSessionPastePlan(
    mode: AssistantOutputPasteMode,
    decision: String?,
    hasOutput: Bool,
    sourceProcessIdentifier: pid_t?,
    frontmostProcessIdentifier: pid_t?,
    basilProcessIdentifier: pid_t
) -> AssistantSessionPastePlan {
    guard hasOutput else { return .skip(nil) }
    switch mode {
    case .never:
        return .skip(nil)
    case .auto where decision != "insert":
        return .skip(.shown)
    case .auto, .always:
        break
    }
    guard let sourceProcessIdentifier else { return .skip(.targetUnavailable) }
    if frontmostProcessIdentifier == sourceProcessIdentifier { return .pasteNow }
    if frontmostProcessIdentifier == basilProcessIdentifier { return .reactivateThenPaste }
    return .skip(.switchedApps)
}

extension AssistantSessionViewModel {
    /// Applies the paste mode and the source-app safeguard to the completed output and records the outcome for the widget. Returns true only when the output was pasted.
    @discardableResult
    func performCompletionPaste(mode: AssistantOutputPasteMode) async -> Bool {
        let source = pasteSourceApplication.flatMap { $0.isTerminated ? nil : $0 }
        pasteTargetApplicationName = pasteSourceApplication?.localizedName
        let plan = resolveAssistantSessionPastePlan(
            mode: mode,
            decision: pasteDecision,
            hasOutput: !assistantOutput.isEmpty,
            sourceProcessIdentifier: source?.processIdentifier,
            frontmostProcessIdentifier: NSWorkspace.shared.frontmostApplication?.processIdentifier,
            basilProcessIdentifier: ProcessInfo.processInfo.processIdentifier
        )
        #if DEBUG
        DevLogger.shared.info("[ASSISTANT_SESSION] Completion paste plan=\(plan) mode=\(mode.rawValue) decision=\(pasteDecision ?? "none") target=\(pasteTargetApplicationName ?? "none")", context: "AssistantSessionViewModel")
        #endif
        switch plan {
        case .skip(let outcome):
            pasteOutcome = outcome
            return false
        case .reactivateThenPaste:
            guard let source, await activateAndAwaitFrontmost(source) else {
                pasteOutcome = .targetUnavailable
                return false
            }
        case .pasteNow:
            break
        }
        if MarkdownUtils.containsMarkdown(assistantOutput) {
            pasteRichAssistantSession(assistantOutput)
        } else {
            pasteAssistantSession(assistantOutput)
        }
        pasteOutcome = .pasted
        return true
    }

    /// Activates `application` and waits for macOS to report it frontmost, giving up after 1.5 seconds.
    private func activateAndAwaitFrontmost(_ application: NSRunningApplication) async -> Bool {
        let targetProcessIdentifier = application.processIdentifier
        let activations = NSWorkspace.shared.notificationCenter.notifications(named: NSWorkspace.didActivateApplicationNotification)
        let requested: Bool
        if #available(macOS 14.0, *) {
            requested = application.activate()
        } else {
            requested = application.activate(options: [.activateIgnoringOtherApps])
        }
        guard requested else { return false }
        if NSWorkspace.shared.frontmostApplication?.processIdentifier == targetProcessIdentifier { return true }
        let activated = await withTaskGroup(of: Bool.self) { group -> Bool in
            group.addTask {
                for await notification in activations {
                    let activatedApplication = notification.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
                    if activatedApplication?.processIdentifier == targetProcessIdentifier { return true }
                }
                return false
            }
            group.addTask {
                try? await Task.sleep(nanoseconds: 1_500_000_000)
                return false
            }
            let first = await group.next() ?? false
            group.cancelAll()
            return first
        }
        return activated || NSWorkspace.shared.frontmostApplication?.processIdentifier == targetProcessIdentifier
    }
}
