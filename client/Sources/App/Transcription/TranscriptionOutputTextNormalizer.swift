import Foundation

struct TranscriptionTextReplacementRule: Codable, Equatable {
    let source: String
    let replacement: String
}

enum TranscriptionOutputTextNormalizer {
    static func apply(
        _ text: String,
        rules: [TranscriptionTextReplacementRule]
    ) -> String {
        guard !text.isEmpty, !rules.isEmpty else { return text }

        let orderedRules = rules.enumerated().sorted { left, right in
            let leftLength = left.element.source.unicodeScalars.count
            let rightLength = right.element.source.unicodeScalars.count
            if leftLength != rightLength {
                return leftLength > rightLength
            }
            return left.offset < right.offset
        }

        var patternParts: [String] = []
        var replacementsByGroup: [String: String] = [:]
        for (position, entry) in orderedRules.enumerated() {
            let words = entry.element.source.split(
                separator: " ",
                omittingEmptySubsequences: true
            )
            guard !words.isEmpty else { continue }

            let groupName = "rule\(position)"
            let phrasePattern = words
                .map { NSRegularExpression.escapedPattern(for: String($0)) }
                .joined(separator: "\\s+")
            patternParts.append("(?<\(groupName)>\(phrasePattern))")
            replacementsByGroup[groupName] = entry.element.replacement
        }

        guard !patternParts.isEmpty else { return text }

        let pattern = "(?<!\\w)(?:" + patternParts.joined(separator: "|") + ")(?!\\w)"
        guard let regex = try? NSRegularExpression(
            pattern: pattern,
            options: [.caseInsensitive]
        ) else {
            return text
        }

        let range = NSRange(text.startIndex..<text.endIndex, in: text)
        var result = ""
        var previousEnd = text.startIndex
        let groupNames = Array(replacementsByGroup.keys)

        regex.enumerateMatches(in: text, options: [], range: range) { match, _, _ in
            guard let match, let matchRange = Range(match.range, in: text) else {
                return
            }
            result += text[previousEnd..<matchRange.lowerBound]

            if let groupName = groupNames.first(where: {
                match.range(withName: $0).location != NSNotFound
            }), let replacement = replacementsByGroup[groupName] {
                result += replacement
            } else {
                result += text[matchRange]
            }
            previousEnd = matchRange.upperBound
        }

        result += text[previousEnd...]
        return result
    }
}
