import Foundation

/// Joins live transcript fragments with the space a reader expects.
///
/// Local streaming engines (Parakeet) send bare words with no leading space, so a plain `left + right` runs words together at every batch boundary. Whisper-style tokens carry their own leading space and are left untouched.
enum TranscriptFragmentJoin {
    private static let attachesToPrevious: Set<Character> = [",", ".", ";", ":", "!", "?", ")", "]", "}", "%"]

    static func join(_ left: String, _ right: String) -> String {
        guard let leftLast = left.last else { return right }
        guard let rightFirst = right.first else { return left }
        if leftLast.isWhitespace || rightFirst.isWhitespace || attachesToPrevious.contains(rightFirst) {
            return left + right
        }
        return left + " " + right
    }
}
