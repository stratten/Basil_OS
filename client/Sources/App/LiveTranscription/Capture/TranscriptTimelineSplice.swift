import Foundation

/// Pure timeline math for incremental, mid-recording window re-transcription.
///
/// Mirrors the backend `windowed_retranscription` helpers (`next_checkpoint_end`
/// and `splice_segments`) so the cadence trigger and the range-replace splice can
/// be unit-tested without the audio/recording/networking machinery.
enum TranscriptTimelineSplice {

    /// The next chunk boundary at/under `elapsed` that lies past `lastCheckpoint`,
    /// or `nil` when no full `interval` of new audio has elapsed since the last
    /// checkpoint. Callers trigger a window only when this returns a value, so a
    /// window fires once per completed `interval` and never re-covers ground the
    /// last checkpoint already upgraded.
    static func nextCheckpointEnd(elapsed: Double, interval: Double, lastCheckpoint: Double) -> Double? {
        guard interval > 0, elapsed > 0 else { return nil }
        let completedChunks = floor(elapsed / interval)
        let boundary = completedChunks * interval
        guard boundary > lastCheckpoint + 1e-6 else { return nil }
        return (boundary * 1000).rounded() / 1000
    }

    /// Closed `[start, end)` to re-transcribe when recording stops. With cadence
    /// enabled only the tail `[lastCheckpoint, total)` remains un-upgraded;
    /// otherwise the whole recording is re-transcribed. Mirrors the backend
    /// `plan_on_stop_window`.
    static func planOnStopWindow(
        thresholdsEnabled: Bool,
        lastCheckpoint: Double,
        total: Double
    ) -> (start: Double, end: Double) {
        guard total > 0 else { return (0, 0) }
        if thresholdsEnabled && lastCheckpoint > 0 {
            let start = min(max(0, lastCheckpoint), total)
            return (start, total)
        }
        return (0, total)
    }

    /// Replace existing lines overlapping `[start, end)` with `newLines`, then
    /// sort by timeline position. Lines whose timeline position cannot be
    /// resolved are treated as outside the range (always kept) so unrelated
    /// content is never dropped by a boundary. Mirrors the backend
    /// `splice_segments`.
    static func spliceByRange(
        existing: [TranscriptionLine],
        newLines: [TranscriptionLine],
        start: Double,
        end: Double
    ) -> [TranscriptionLine] {
        let kept = existing.filter { !overlaps($0, start: start, end: end) }
        let merged = kept + newLines
        return merged.enumerated().sorted { lhs, rhs in
            let leftSeconds = startSeconds(lhs.element)
            let rightSeconds = startSeconds(rhs.element)
            switch (leftSeconds, rightSeconds) {
            case let (left?, right?):
                if left == right { return lhs.offset < rhs.offset }
                return left < right
            case (_?, nil):
                return true
            case (nil, _?):
                return false
            case (nil, nil):
                return lhs.offset < rhs.offset
            }
        }.map(\.element)
    }

    /// Stable row identity for post-processed segments. Backend window results
    /// may arrive repeatedly for the same timeline span; deriving ids from the
    /// source and timeline keeps equivalent replacements from looking like an
    /// all-new transcript to SwiftUI.
    static func deterministicSegmentID(
        source: AudioSource,
        timelineStartSeconds: Double,
        timelineEndSeconds: Double,
        speakerID: String?
    ) -> String {
        let startMilliseconds = Int((timelineStartSeconds * 1000).rounded())
        let endMilliseconds = Int((timelineEndSeconds * 1000).rounded())
        let speaker = normalizedIDComponent(speakerID ?? "speakerless")
        return "post-\(source.rawValue)-\(startMilliseconds)-\(endMilliseconds)-\(speaker)"
    }

    /// True when the line's resolved `[start, end]` overlaps `[start, end)`.
    private static func overlaps(_ line: TranscriptionLine, start: Double, end: Double) -> Bool {
        guard let lineStart = startSeconds(line) else { return false }
        let lineEnd = endSeconds(line) ?? lineStart
        return lineEnd > start && lineStart < end
    }

    /// Resolve a line's start in absolute seconds: prefer the canonical timeline
    /// value, falling back to parsing the legacy display string.
    static func startSeconds(_ line: TranscriptionLine) -> Double? {
        line.timelineStartSeconds ?? line.start.flatMap(parseTimeString)
    }

    /// Resolve a line's end in absolute seconds (see `startSeconds`).
    static func endSeconds(_ line: TranscriptionLine) -> Double? {
        line.timelineEndSeconds ?? line.end.flatMap(parseTimeString)
    }

    /// Parse "H:MM:SS", "MM:SS", or "SS" elapsed strings to seconds.
    static func parseTimeString(_ timeString: String) -> Double? {
        let parts = timeString.split(separator: ":").compactMap { Double($0) }
        switch parts.count {
        case 3: return parts[0] * 3600 + parts[1] * 60 + parts[2]
        case 2: return parts[0] * 60 + parts[1]
        case 1: return parts[0]
        default: return nil
        }
    }

    private static func normalizedIDComponent(_ value: String) -> String {
        let normalized = value
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .map { character -> Character in
                character.isLetter || character.isNumber || character == "-" || character == "_"
                    ? character
                    : "-"
            }
        let component = String(normalized).trimmingCharacters(in: CharacterSet(charactersIn: "-_"))
        return component.isEmpty ? "unknown" : component
    }
}
