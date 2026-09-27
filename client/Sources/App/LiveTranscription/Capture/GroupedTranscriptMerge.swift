import Foundation

// MARK: - GroupedTranscriptMerge
//
// Pure timeline-merge helpers for reconstructing a grouped (multi-source,
// multi-part) meeting transcript and for placing resumed live lines on the
// logical meeting timeline. Deliberately free of view-model / network state so
// it can be unit-tested in isolation (mirrors `TranscriptTimelineSplice`).
enum GroupedTranscriptMerge {

    /// One member recording of a grouped meeting, already decoded into lines
    /// whose `timelineStartSeconds`/`timelineEndSeconds` carry the PERSISTED
    /// (authoritative) position. For resumed parts the persisted position
    /// already includes the resume timeline offset, so the merge must not
    /// re-add any global wall-clock offset.
    struct MemberInput {
        let source: AudioSource
        let recordingPartIndex: Int
        let startDate: Date?
        let lines: [TranscriptionLine]
    }

    /// Merge all members of a grouped meeting into per-source line arrays.
    ///
    /// - Accumulates (appends) every member's lines per source in member order,
    ///   so multi-part (resumed) meetings keep ALL parts instead of only the
    ///   last one (the prior overwrite bug dropped earlier parts entirely).
    /// - Applies only intra-part cross-track skew: each member's lines are
    ///   shifted by `(member.startDate - earliest startDate among members that
    ///   share the same recordingPartIndex)`. The large resume offset is already
    ///   baked into the persisted line times, so adding a global wall-clock
    ///   offset here would double-count it.
    ///
    /// Legacy single-part meetings (all `recordingPartIndex == 0`) reduce to the
    /// historical behavior: skew relative to the earliest member start.
    static func merge(_ members: [MemberInput]) -> (microphone: [TranscriptionLine], systemAudio: [TranscriptionLine]) {
        // Earliest start per recording part = the cross-track skew origin.
        var partOrigin: [Int: Date] = [:]
        for member in members {
            guard let start = member.startDate else { continue }
            if let existing = partOrigin[member.recordingPartIndex] {
                if start < existing { partOrigin[member.recordingPartIndex] = start }
            } else {
                partOrigin[member.recordingPartIndex] = start
            }
        }

        var microphone: [TranscriptionLine] = []
        var systemAudio: [TranscriptionLine] = []

        for member in members {
            var skew = 0.0
            if let start = member.startDate, let origin = partOrigin[member.recordingPartIndex] {
                skew = max(0.0, start.timeIntervalSince(origin))
            }
            let shifted = skew == 0.0 ? member.lines : member.lines.map { shift($0, by: skew) }
            switch member.source {
            case .microphone:
                microphone.append(contentsOf: shifted)
            case .systemAudio:
                systemAudio.append(contentsOf: shifted)
            }
        }
        return (microphone, systemAudio)
    }

    /// Shift a line's canonical timeline seconds by `delta` (text/speaker kept).
    private static func shift(_ line: TranscriptionLine, by delta: Double) -> TranscriptionLine {
        let newStart = line.timelineStartSeconds.map { $0 + delta }
        let newEnd = line.timelineEndSeconds.map { $0 + delta }
        return TranscriptionLine(
            id: line.id,
            text: line.text,
            speakerID: line.speakerID,
            isInterim: line.isInterim,
            start: newStart.map { format(seconds: $0) } ?? line.start,
            end: newEnd.map { format(seconds: $0) } ?? line.end,
            diff: line.diff,
            timelineStartSeconds: newStart,
            timelineEndSeconds: newEnd,
            source: line.source,
            lineComplete: line.lineComplete
        )
    }

    /// Place a resumed live line on the logical meeting timeline: parse the
    /// part-relative `start`/`end` string and add the resume offset. Returns nil
    /// when there is no parseable time (the caller then leaves the field unset).
    static func liveResumeTimelineSeconds(startString: String?, offset: Double) -> Double? {
        guard let parsed = parseTimeString(startString) else { return nil }
        return parsed + offset
    }

    /// Parse "H:MM:SS", "MM:SS", or "SS(.fff)" into seconds. Matches the backend
    /// `format_time` output (`str(timedelta(...))`, e.g. "0:02:05") and the
    /// formats used by the combined-transcript sort.
    static func parseTimeString(_ timeString: String?) -> Double? {
        guard let timeString = timeString else { return nil }
        let parts = timeString.split(separator: ":").map(String.init)
        let nums = parts.compactMap { Double($0) }
        guard nums.count == parts.count, !nums.isEmpty else { return nil }
        switch nums.count {
        case 3: return nums[0] * 3600 + nums[1] * 60 + nums[2]
        case 2: return nums[0] * 60 + nums[1]
        case 1: return nums[0]
        default: return nil
        }
    }

    private static func format(seconds: Double) -> String {
        return String(format: "%.2f", seconds)
    }
}
