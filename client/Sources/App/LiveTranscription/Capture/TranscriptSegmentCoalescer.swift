import Foundation

// MARK: - TranscriptSegmentCoalescer
//
// Pure batch reconstruction of sentence-level lines from persisted,
// fine-grained transcript segments. During live recording,
// `LiveTranscriptionViewModel+LiveLineMerge.swift` folds 1-3 token deltas into
// sentence-level lines using signals (backend `lineComplete`, a sentence
// boundary, a 3s global timer) that are never written to `transcript.json` -
// only the raw per-delta segments are persisted. On reload those raw segments
// were previously mapped 1:1 to display lines, fragmenting the transcript
// into per-token bubbles. This coalescer reconstructs the same sentence-level
// granularity from the persisted segments alone, using their timeline gaps as
// a proxy for the missing silence/timer signals.
//
// Deliberately free of view-model / network state so it can be unit-tested in
// isolation (mirrors `TranscriptSentenceBreak` and `GroupedTranscriptMerge`).
enum TranscriptSegmentCoalescer {

    /// Merge consecutive lines in `lines` (assumed already in one source's
    /// chronological order) into sentence-level lines.
    ///
    /// The in-progress line closes and a new one starts when any of:
    /// - its accumulated text reaches a sentence boundary at `minWords`
    ///   (`TranscriptSentenceBreak.endsAtSentenceBoundary`, the same rule the
    ///   live merge uses);
    /// - the timeline gap to the next segment exceeds `silenceGapSeconds`
    ///   (proxy for the backend's >2s-silence `lineComplete` signal and the
    ///   live 3s global line-break timer, neither of which is persisted);
    /// - the next segment's `speakerID` differs from the current line's
    ///   (defensive: the live merge never switches speaker within a single
    ///   source array, so a change here should not be absorbed into one line).
    ///
    /// A `nil` timeline second on either side of a boundary is treated as a
    /// zero gap (extend rather than split), since a missing timestamp is not
    /// evidence of a silence gap.
    static func coalesce(
        _ lines: [TranscriptionLine],
        minWords: Int,
        silenceGapSeconds: Double,
        normalize: (String) -> String
    ) -> [TranscriptionLine] {
        guard !lines.isEmpty else { return [] }

        var result: [TranscriptionLine] = []
        var current = lines[0]

        for next in lines.dropFirst() {
            let gap = (next.timelineStartSeconds ?? current.timelineEndSeconds ?? 0)
                - (current.timelineEndSeconds ?? next.timelineStartSeconds ?? 0)
            let speakerChanged = next.speakerID != current.speakerID
            let boundaryReached = TranscriptSentenceBreak.endsAtSentenceBoundary(current.text, minWords: minWords)

            if boundaryReached || gap > silenceGapSeconds || speakerChanged {
                result.append(closed(current, normalize: normalize))
                current = next
            } else {
                current = merged(current, appending: next, normalize: normalize)
            }
        }
        result.append(closed(current, normalize: normalize))
        return result
    }

    /// Extend `current` with `next`'s text, keeping `current`'s start and
    /// `next`'s end as the merged line's bounds.
    private static func merged(
        _ current: TranscriptionLine,
        appending next: TranscriptionLine,
        normalize: (String) -> String
    ) -> TranscriptionLine {
        let text = normalize(current.text + " " + next.text)
        let startSeconds = current.timelineStartSeconds ?? next.timelineStartSeconds
        let endSeconds = next.timelineEndSeconds ?? current.timelineEndSeconds
        return TranscriptionLine(
            id: current.id,
            text: text,
            speakerID: current.speakerID,
            isInterim: false,
            start: current.start,
            end: next.end,
            diff: diffSeconds(start: startSeconds, end: endSeconds),
            timelineStartSeconds: startSeconds,
            timelineEndSeconds: endSeconds,
            source: current.source,
            lineComplete: true
        )
    }

    /// Finalize a line for emission: normalize its text and mark it complete.
    private static func closed(_ line: TranscriptionLine, normalize: (String) -> String) -> TranscriptionLine {
        TranscriptionLine(
            id: line.id,
            text: normalize(line.text),
            speakerID: line.speakerID,
            isInterim: false,
            start: line.start,
            end: line.end,
            diff: line.diff,
            timelineStartSeconds: line.timelineStartSeconds,
            timelineEndSeconds: line.timelineEndSeconds,
            source: line.source,
            lineComplete: true
        )
    }

    private static func diffSeconds(start: Double?, end: Double?) -> Double? {
        guard let start, let end else { return nil }
        return end - start
    }
}
