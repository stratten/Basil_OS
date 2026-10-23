import Foundation

/// Pure sentence-boundary detection for the live transcript merge.
///
/// The streaming decoder commits 1-3 token deltas at a time; left alone, a
/// single source accretes whole paragraphs into one bubble because a line only
/// closes on a silence signal (backend `lineComplete` after >2s, or the global
/// line-break timer). Closing a line when its accumulated text reaches a
/// sentence boundary lets each new sentence start a fresh, wall-clock-stamped
/// line, so the two sources interleave at sentence granularity (mirroring the
/// offline retranscription) without reverting to per-second fragmentation.
///
/// Kept as a pure function so the boundary rules can be unit-tested without the
/// view model or any audio/recording machinery.
enum TranscriptSentenceBreak {

    /// Sentence-ending punctuation we treat as a potential line break.
    private static let terminators: Set<Character> = [".", "!", "?"]

    /// Trailing characters that may follow a terminator and still leave the text
    /// at a sentence boundary (closing quotes/brackets), e.g. `she said."`
    private static let trailingClosers: Set<Character> = ["\"", "'", ")", "]", "”", "’", "»"]

    /// Whether `text` ends at a sentence boundary and is long enough to close.
    ///
    /// Returns true only when both hold:
    /// - the last meaningful character (after stripping trailing whitespace and
    ///   closing quotes/brackets) is `.`, `!`, or `?`, and
    /// - the whitespace-split word count is at least `minWords`.
    ///
    /// The word gate keeps short backchannels ("Okay.", "Yeah.") merged with
    /// surrounding content rather than fragmenting them. To avoid false breaks, a
    /// terminal `.` is ignored when it directly follows a digit (decimals like
    /// `3.5`) or a lone capital letter (initials/abbreviations like `B.` / `U.S.`).
    static func endsAtSentenceBoundary(_ text: String, minWords: Int) -> Bool {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }

        // Strip trailing closing quotes/brackets so `."` resolves to `.`.
        var chars = Array(trimmed)
        while let last = chars.last, trailingClosers.contains(last) {
            chars.removeLast()
        }

        guard let terminator = chars.last, terminators.contains(terminator) else {
            return false
        }

        // Guard period-specific false positives (decimals, single-letter initials).
        if terminator == "." && chars.count >= 2 {
            let preceding = chars[chars.count - 2]
            if preceding.isNumber {
                return false
            }
            if preceding.isLetter && preceding.isUppercase {
                // A lone capital before the period (e.g. "B." or the final "S."
                // of "U.S.") is an initial/abbreviation, not a sentence end. It
                // is "lone" when nothing or a non-letter precedes it.
                let isLoneCapital = chars.count == 2 || !chars[chars.count - 3].isLetter
                if isLoneCapital {
                    return false
                }
            }
        }

        let wordCount = trimmed.split(whereSeparator: { $0.isWhitespace }).count
        return wordCount >= minWords
    }
}
