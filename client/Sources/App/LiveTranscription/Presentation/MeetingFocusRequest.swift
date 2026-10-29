import Foundation

/// Which surface a focus request scrolls: the transcript in the Notetaker, or a card in the Companion.
enum MeetingFocusTarget: String {
    case transcript
    case companion
}

/// A validated request, from either window, to bring something into view in the other.
struct MeetingFocusRequest: Equatable {
    static let maximumItemIdLength = 128

    let target: MeetingFocusTarget
    let itemId: String
    let startSeconds: Double?
    let endSeconds: Double?

    /// Returns nil for anything malformed: a missing or oversized item id, or (for the transcript) a range that is absent, negative, not finite, or reversed. A Companion request carries no range.
    init?(target: MeetingFocusTarget, payload: [String: Any]) {
        guard let itemId = payload["itemId"] as? String,
              !itemId.isEmpty,
              itemId.count <= Self.maximumItemIdLength else { return nil }
        self.target = target
        self.itemId = itemId
        switch target {
        case .companion:
            self.startSeconds = nil
            self.endSeconds = nil
        case .transcript:
            guard let start = Self.seconds(payload["startSeconds"]),
                  let end = Self.seconds(payload["endSeconds"]),
                  end >= start else { return nil }
            self.startSeconds = start
            self.endSeconds = end
        }
    }

    private static func seconds(_ value: Any?) -> Double? {
        guard let number = value as? NSNumber, !(value is Bool) else { return nil }
        let seconds = number.doubleValue
        return seconds.isFinite && seconds >= 0 ? seconds : nil
    }
}
