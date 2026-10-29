import Foundation

/// Decides whether a Paprika task the setup assistant launched has really finished, or is about to be revised.
///
/// When a task's first pass comes back partial but names one closable gap, the backend schedules a continuation turn on the same task chain and adds a sentence beginning with `continuationMarker` to the partial result. That first status is terminal, so reporting it as the outcome makes the setup agent describe a half-finished answer as final while the task is already revising itself. This policy keeps the setup assistant waiting for the revision, and says when to tell the setup agent that a revision is under way.
enum SetupAgentTaskRevisionPolicy {
    /// The opening words of the note the backend appends (`apply_continuation_note` in `gap_continuation.py`).
    static let continuationMarker = "Basil is continuing automatically"

    static let terminalStatuses: Set<String> = ["completed", "failed", "canceled"]

    /// How long to wait for the scheduled continuation to appear in the task chain before accepting the partial result as final.
    static let announcementGraceSeconds: TimeInterval = 90

    struct ChainItem: Equatable {
        let status: String
        let resultMessage: String?
    }

    enum Decision: Equatable {
        case revising
        case settled(status: String, resultMessage: String?)
    }

    /// Call only once the root task itself has reached a terminal status.
    /// `chain` is the task's follow-up turns in order; `secondsSinceRootSettled` is how long the root has been terminal.
    static func decide(
        rootStatus: String,
        rootResultMessage: String?,
        chain: [ChainItem],
        secondsSinceRootSettled: TimeInterval
    ) -> Decision {
        if chain.contains(where: { !terminalStatuses.contains($0.status.lowercased()) }) {
            return .revising
        }
        let latestStatus = chain.last?.status ?? rootStatus
        let latestMessage = chain.last?.resultMessage ?? rootResultMessage
        if announcesContinuation(latestMessage), secondsSinceRootSettled < announcementGraceSeconds {
            return .revising
        }
        return .settled(status: latestStatus, resultMessage: latestMessage)
    }

    static func announcesContinuation(_ resultMessage: String?) -> Bool {
        guard let resultMessage else { return false }
        return resultMessage.range(of: continuationMarker) != nil
    }

    /// The gap the continuation is trying to close, taken from the backend's note, or nil when the note has none.
    static func gapBeingClosed(in resultMessage: String?) -> String? {
        guard let resultMessage,
              let markerRange = resultMessage.range(of: continuationMarker),
              let colon = resultMessage[markerRange.upperBound...].firstIndex(of: ":") else {
            return nil
        }
        let afterColon = resultMessage[resultMessage.index(after: colon)...]
        let firstLine = afterColon.split(whereSeparator: \.isNewline).first.map(String.init) ?? ""
        let trimmed = firstLine.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        return String(trimmed.prefix(300))
    }

    /// The progress text the setup agent receives once, when a revision is first seen.
    static func revisionAnnouncement(rootResultMessage: String?) -> String {
        var text = "Paprika's first pass came back partial and it is now revising its work on its own, so the result so far is not final. The setup conversation can wait for it or move on in the meantime."
        if let gap = gapBeingClosed(in: rootResultMessage) {
            text += " Gap it is working on: \(gap)"
        }
        return text
    }
}
