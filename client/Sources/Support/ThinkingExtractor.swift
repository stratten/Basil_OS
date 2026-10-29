import Foundation

/// Extracts `<think>...</think>` segments from raw model output so they can
/// be presented to the user as a separate, collapsible "Thinking" block
/// rather than leaking into the rendered final output.
///
/// The AssistantSession widget historically does this via
/// `AssistantSessionViewModel.extractThinkingContent`, but that lives on the live
/// view model and isn't reachable from views that render persisted history
/// rows (sidebar preview, history detail, refinement entries). Those rows
/// store the raw model output verbatim, including any `<think>` blocks the
/// model emitted, so without this helper the tags leak into the UI.
///
/// This utility deliberately mirrors the parsing rules of the live
/// extractor: multiple `<think>...</think>` segments are concatenated
/// (separated by a blank line) into the `thinking` return value, and an
/// unterminated trailing `<think>` (the streaming-mid-thought case) is
/// treated as all-thinking-no-content for that fragment. Whitespace is
/// trimmed at the end so empty thinking returns `nil` rather than `""`.
enum ThinkingExtractor {

    private static let openTag = "<think>"
    private static let closeTag = "</think>"

    /// Splits raw model output into its thinking and visible-content parts.
    ///
    /// - Parameter rawText: The raw response text potentially containing
    ///   `<think>...</think>` segments.
    /// - Returns: A tuple `(thinking, content)`. `thinking` is `nil` when
    ///   the input contained no think tags or only whitespace inside them.
    static func split(_ rawText: String) -> (thinking: String?, content: String) {
        guard rawText.contains(openTag) else {
            return (nil, rawText)
        }

        var thinking = ""
        var content = ""
        var remaining = rawText

        while let startRange = remaining.range(of: openTag) {
            // Anything before the opening tag is visible content.
            content += String(remaining[..<startRange.lowerBound])

            let afterOpen = remaining[startRange.upperBound...]
            if let endRange = afterOpen.range(of: closeTag) {
                let segment = String(afterOpen[..<endRange.lowerBound])
                thinking += (thinking.isEmpty ? "" : "\n\n") + segment
                remaining = String(afterOpen[endRange.upperBound...])
            } else {
                // Streaming case: opening tag with no closing tag yet --
                // treat the entire trailing fragment as in-progress thinking.
                let segment = String(afterOpen)
                thinking += (thinking.isEmpty ? "" : "\n\n") + segment
                remaining = ""
                break
            }
        }

        content += remaining

        let trimmedThinking = thinking.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedContent = content.trimmingCharacters(in: .whitespacesAndNewlines)

        return (
            trimmedThinking.isEmpty ? nil : trimmedThinking,
            trimmedContent
        )
    }

    /// Convenience accessor for callers that only need the user-visible
    /// content stripped of thinking blocks (e.g. sidebar previews).
    static func stripThinking(_ rawText: String) -> String {
        split(rawText).content
    }

    /// Convenience accessor for callers that only need the thinking
    /// content (e.g. rendering a collapsible "Thinking" disclosure).
    static func thinkingOnly(_ rawText: String) -> String? {
        split(rawText).thinking
    }
}
