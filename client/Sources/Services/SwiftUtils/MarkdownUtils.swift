import Foundation
import AppKit

struct MarkdownUtils {
    /// Converts simple markdown formatting to HTML
    static func markdownToHTML(_ markdown: String) -> String {
        var html = markdown
        
        // Process headers BEFORE converting line breaks to avoid regex conflicts
        // Convert ### headers to <h3>header</h3> (process h3 before h2 to avoid conflicts)
        html = html.replacingOccurrences(
            of: #"(^|\n)###\s*(.+?)(\n|$)"#,
            with: "$1<h3>$2</h3>$3",
            options: .regularExpression
        )
        
        // Convert ## headers to <h2>header</h2>  
        // Updated regex to handle headers with special characters like "## - H@"
        html = html.replacingOccurrences(
            of: #"(^|\n)##\s*(.+?)(\n|$)"#,
            with: "$1<h2>$2</h2>$3",
            options: .regularExpression
        )
        
        // Convert **bold** to <strong>bold</strong>
        html = html.replacingOccurrences(
            of: #"\*\*([^*]+)\*\*"#,
            with: "<strong>$1</strong>",
            options: .regularExpression
        )
        
        // Convert *italic* to <em>italic</em> (but not if it's part of **bold**)
        html = html.replacingOccurrences(
            of: #"(?<!\*)\*([^*]+)\*(?!\*)"#,
            with: "<em>$1</em>",
            options: .regularExpression
        )
        
        // Convert `code` to <code>code</code>
        html = html.replacingOccurrences(
            of: #"`([^`]+)`"#,
            with: "<code>$1</code>",
            options: .regularExpression
        )
        
        // Convert line breaks to <br> tags AFTER processing headers
        html = html.replacingOccurrences(of: "\n", with: "<br>")
        
        return html
    }
    
    /// Checks if text contains markdown formatting
    static func containsMarkdown(_ text: String) -> Bool {
        let markdownPatterns = [
            #"(^|\n)###\s*.+"#,      // ### headers
            #"(^|\n)##\s*.+"#,       // ## headers  
            #"\*\*[^*]+\*\*"#,       // **bold**
            #"(?<!\*)\*[^*]+\*(?!\*)"#, // *italic* (not part of **bold**)
            #"`[^`]+`"#              // `code`
        ]
        
        for pattern in markdownPatterns {
            if text.range(of: pattern, options: .regularExpression) != nil {
                return true
            }
        }
        
        return false
    }
    
    /// Converts markdown to HTML Data for pasting to pasteboard
    /// This version intentionally doesn't specify fonts, allowing target applications
    /// to apply their own fonts while preserving formatting (bold, italic, etc.)
    static func markdownToHTMLData(_ markdown: String) -> Data? {
        // Convert markdown to basic HTML using existing method
        let htmlContent = markdownToHTML(markdown)
        
        // Wrap in minimal HTML structure without font specifications
        // This allows target apps like Outlook/Mail to apply their own fonts
        let htmlDocument = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body { 
                    margin: 0;
                    padding: 0;
                }
                /* No font-family specified - let target app use its own fonts */
                h2 { font-weight: bold; margin: 0; }
                h3 { font-weight: bold; margin: 0; }
                strong { font-weight: bold; }
                em { font-style: italic; }
                code { 
                    font-family: monospace;
                    background-color: #f0f0f0;
                    padding: 2px 4px;
                    border-radius: 3px;
                }
            </style>
        </head>
        <body>
        \(htmlContent)
        </body>
        </html>
        """
        
        return htmlDocument.data(using: .utf8)
    }
    
    /// Converts markdown to NSAttributedString with minimal formatting (for copying/pasting)
    /// NOTE: This creates RTF with only bold/italic traits, no explicit font families.
    /// This should allow target applications to use their own fonts.
    static func markdownToAttributedString(_ markdown: String) -> NSAttributedString {
        let mutableAttributedString = NSMutableAttributedString(string: markdown)
        
        // DO NOT apply a base font - let the target app use its own default
        // We'll only apply traits (bold/italic) where markdown specifies them
        
        // Process **bold** patterns - apply only the bold trait, no explicit font
        do {
            let boldRegex = try NSRegularExpression(pattern: #"\*\*([^*]+)\*\*"#)
            let matches = boldRegex.matches(in: markdown, range: NSRange(location: 0, length: markdown.count))
            
            // Process matches in reverse order to maintain correct indices
            for match in matches.reversed() {
                let fullRange = match.range
                let contentRange = match.range(at: 1)
                
                if let contentSwiftRange = Range(contentRange, in: markdown) {
                    let contentText = String(markdown[contentSwiftRange])
                    
                    // Replace the entire **text** with just the content
                    mutableAttributedString.replaceCharacters(in: fullRange, with: contentText)
                    
                    // Apply only bold trait using NSFontDescriptor symbolic traits
                    let newRange = NSRange(location: fullRange.location, length: contentText.count)
                    
                    // Create a font descriptor with bold trait but no specific font family
                    let descriptor = NSFontDescriptor().withSymbolicTraits(.bold)
                    if let font = NSFont(descriptor: descriptor, size: 0) { // size 0 means use default
                        mutableAttributedString.addAttribute(.font, value: font, range: newRange)
                    }
                }
            }
        } catch {
            print("Error processing bold markdown: \(error)")
        }
        
        // Process *italic* patterns (excluding already processed bold text)
        do {
            let italicRegex = try NSRegularExpression(pattern: #"(?<!\*)\*([^*]+)\*(?!\*)"#)
            let currentString = mutableAttributedString.string
            let matches = italicRegex.matches(in: currentString, range: NSRange(location: 0, length: currentString.count))
            
            // Process matches in reverse order to maintain correct indices
            for match in matches.reversed() {
                let fullRange = match.range
                let contentRange = match.range(at: 1)
                
                if let contentSwiftRange = Range(contentRange, in: currentString) {
                    let contentText = String(currentString[contentSwiftRange])
                    
                    // Replace the entire *text* with just the content
                    mutableAttributedString.replaceCharacters(in: fullRange, with: contentText)
                    
                    // Apply only italic trait
                    let newRange = NSRange(location: fullRange.location, length: contentText.count)
                    
                    // Check if there's already a font (e.g., from bold processing)
                    if let existingFont = mutableAttributedString.attribute(.font, at: newRange.location, effectiveRange: nil) as? NSFont {
                        // Add italic to existing font
                        let italicFont = NSFontManager.shared.convert(existingFont, toHaveTrait: .italicFontMask)
                        mutableAttributedString.addAttribute(.font, value: italicFont, range: newRange)
                    } else {
                        // Create font with just italic trait
                        let descriptor = NSFontDescriptor().withSymbolicTraits(.italic)
                        if let font = NSFont(descriptor: descriptor, size: 0) {
                            mutableAttributedString.addAttribute(.font, value: font, range: newRange)
                        }
                    }
                }
            }
        } catch {
            print("Error processing italic markdown: \(error)")
        }
        
        // Process `code` patterns
        // Note: Monospace requires a font family specification, but we use system monospace
        do {
            let codeRegex = try NSRegularExpression(pattern: #"`([^`]+)`"#)
            let currentString = mutableAttributedString.string
            let matches = codeRegex.matches(in: currentString, range: NSRange(location: 0, length: currentString.count))
            
            // Process matches in reverse order to maintain correct indices
            for match in matches.reversed() {
                let fullRange = match.range
                let contentRange = match.range(at: 1)
                
                if let contentSwiftRange = Range(contentRange, in: currentString) {
                    let contentText = String(currentString[contentSwiftRange])
                    
                    // Replace the entire `text` with just the content
                    mutableAttributedString.replaceCharacters(in: fullRange, with: contentText)
                    
                    // For code, we still need monospace but use system default size (0)
                    let newRange = NSRange(location: fullRange.location, length: contentText.count)
                    let codeFont = NSFont.monospacedSystemFont(ofSize: 0, weight: .regular) // size 0 = default
                    mutableAttributedString.addAttribute(.font, value: codeFont, range: newRange)
                    mutableAttributedString.addAttribute(.backgroundColor, value: NSColor.controlBackgroundColor, range: newRange)
                }
            }
        } catch {
            print("Error processing code markdown: \(error)")
        }
        
        return mutableAttributedString
    }

    // MARK: - Attributed-string -> markdown
    //
    // Inverse of `markdownToAttributedString` for the constrained set of attributes
    // that `BasilRichTextEditor` / `RichTextEditorController` can produce:
    //
    //   - Bold / italic via `NSFontManager` font traits
    //   - Underline via `.underlineStyle`
    //   - Inline code via custom `.basilInlineCode` marker (paired monospaced font)
    //   - Code blocks via custom `.basilCodeBlock` marker on the whole paragraph
    //   - Bullet lists  -> paragraph style with `NSTextList(markerFormat: .disc, ...)`
    //   - Numbered lists -> paragraph style with `NSTextList(markerFormat: .decimal, ...)`
    //
    // The output is plain markdown text intended for sending over the wire as a single
    // string and rendering with a markdown renderer (e.g. MarkdownUI) on the receiving
    // side. Constructs the toolbar cannot create are simply not emitted, so the producer
    // and consumer of this serializer remain symmetric.

    /// Serializes an `NSAttributedString` produced by `BasilRichTextEditor` into markdown.
    /// The result has no leading/trailing newlines beyond what is necessary; callers should
    /// still trim with `.whitespacesAndNewlines` before sending.
    static func attributedToMarkdown(_ attr: NSAttributedString) -> String {
        guard attr.length > 0 else { return "" }

        let paragraphs = splitIntoParagraphs(attr)
        var lines: [String] = []
        var i = 0
        while i < paragraphs.count {
            let kind = paragraphKind(paragraphs[i])
            switch kind {
            case .codeBlock:
                var blockLines: [String] = []
                while i < paragraphs.count, paragraphKind(paragraphs[i]) == .codeBlock {
                    blockLines.append(paragraphs[i].string)
                    i += 1
                }
                lines.append("```")
                lines.append(contentsOf: blockLines)
                lines.append("```")
            case .numbered:
                var counter = 1
                while i < paragraphs.count, paragraphKind(paragraphs[i]) == .numbered {
                    let stripped = stripLeadingListMarker(paragraphs[i])
                    lines.append("\(counter). \(renderInline(stripped))")
                    counter += 1
                    i += 1
                }
            case .bullet:
                while i < paragraphs.count, paragraphKind(paragraphs[i]) == .bullet {
                    let stripped = stripLeadingListMarker(paragraphs[i])
                    lines.append("- \(renderInline(stripped))")
                    i += 1
                }
            case .regular:
                lines.append(renderInline(paragraphs[i]))
                i += 1
            }
        }

        return lines.joined(separator: "\n")
    }

    // MARK: Paragraph splitting

    /// Splits an attributed string into per-paragraph attributed substrings on hard
    /// `\n` boundaries. The newline characters themselves are NOT included in the
    /// returned substrings (they are reintroduced by `joined(separator:"\n")` in the
    /// main serializer).
    private static func splitIntoParagraphs(_ attr: NSAttributedString) -> [NSAttributedString] {
        let nsString = attr.string as NSString
        var paragraphs: [NSAttributedString] = []
        var location = 0
        while location <= attr.length {
            let remaining = NSRange(location: location, length: attr.length - location)
            let nlRange = nsString.range(of: "\n", range: remaining)
            let endExclusive = (nlRange.location == NSNotFound) ? attr.length : nlRange.location
            let paragraphRange = NSRange(location: location, length: endExclusive - location)
            paragraphs.append(attr.attributedSubstring(from: paragraphRange))
            if nlRange.location == NSNotFound { break }
            location = nlRange.location + 1
        }
        return paragraphs
    }

    // MARK: Paragraph classification

    private enum ParagraphKind {
        case regular
        case codeBlock
        case bullet
        case numbered
    }

    private static func paragraphKind(_ paragraph: NSAttributedString) -> ParagraphKind {
        guard paragraph.length > 0 else { return .regular }
        let attrs = paragraph.attributes(at: 0, effectiveRange: nil)
        if (attrs[.basilCodeBlock] as? Bool) == true { return .codeBlock }
        if let style = attrs[.paragraphStyle] as? NSParagraphStyle,
           let firstList = style.textLists.first {
            if firstList.markerFormat == .disc { return .bullet }
            if firstList.markerFormat == .decimal { return .numbered }
        }
        return .regular
    }

    // MARK: Inline emission

    /// Walks attribute runs in `paragraph` and emits markdown for the toolbar's
    /// supported inline traits (bold, italic, underline, inline code).
    private static func renderInline(_ paragraph: NSAttributedString) -> String {
        guard paragraph.length > 0 else { return "" }
        let plain = paragraph.string as NSString
        var out = ""
        paragraph.enumerateAttributes(
            in: NSRange(location: 0, length: paragraph.length),
            options: []
        ) { attrs, range, _ in
            let runText = plain.substring(with: range)
            out.append(formatRun(runText, attrs: attrs))
        }
        return out
    }

    /// Emits a single attribute-run with the appropriate markdown / HTML wrapping.
    /// Inline code wins over emphasis (matches the toolbar's mutual-exclusion behavior).
    /// Underline has no native markdown equivalent so we fall back to `<u>...</u>`,
    /// which renders fine in MarkdownUI and is preserved on round-trip in HTML.
    private static func formatRun(_ runText: String, attrs: [NSAttributedString.Key: Any]) -> String {
        let isInlineCode = (attrs[.basilInlineCode] as? Bool) == true
        let underlineRaw = (attrs[.underlineStyle] as? Int) ?? 0
        let isUnderline = underlineRaw != 0

        if isInlineCode {
            // Use double-backtick fences if the run itself contains a backtick so the
            // markdown parser doesn't mis-terminate the span.
            let body: String
            if runText.contains("`") {
                body = "`` \(runText) ``"
            } else {
                body = "`\(runText)`"
            }
            return isUnderline ? wrapWithTags(body, open: "<u>", close: "</u>") : body
        }

        let traits = (attrs[.font] as? NSFont).map { NSFontManager.shared.traits(of: $0) } ?? []
        let isBold = traits.contains(.boldFontMask)
        let isItalic = traits.contains(.italicFontMask)

        let marker: String
        if isBold && isItalic { marker = "***" }
        else if isBold        { marker = "**" }
        else if isItalic      { marker = "*" }
        else                  { marker = "" }

        var emitted = marker.isEmpty ? runText : wrapEmphasis(runText, marker: marker)
        if isUnderline { emitted = wrapWithTags(emitted, open: "<u>", close: "</u>") }
        return emitted
    }

    /// Wraps `text` with the given markdown emphasis `marker`, hoisting any leading
    /// or trailing whitespace OUTSIDE the marker. This matters because most markdown
    /// parsers refuse to interpret `** foo **` as emphasis (the inner edges must be
    /// non-whitespace), so we keep the visible whitespace correct without breaking
    /// rendering.
    private static func wrapEmphasis(_ text: String, marker: String) -> String {
        guard !text.isEmpty else { return "" }
        let leading = text.prefix { $0.isWhitespace }
        let trailing = String(text.reversed().prefix { $0.isWhitespace }.reversed())
        let coreStartIdx = text.index(text.startIndex, offsetBy: leading.count)
        let coreEndIdx = text.index(text.endIndex, offsetBy: -trailing.count)
        guard coreStartIdx < coreEndIdx else { return text }
        let core = String(text[coreStartIdx..<coreEndIdx])
        return "\(leading)\(marker)\(core)\(marker)\(trailing)"
    }

    /// Wraps `text` with literal opener/closer tags without any whitespace hoisting.
    /// Used for HTML tags like `<u>` where surrounding whitespace doesn't break parsing.
    private static func wrapWithTags(_ text: String, open: String, close: String) -> String {
        guard !text.isEmpty else { return "" }
        return "\(open)\(text)\(close)"
    }

    // MARK: List marker stripping
    //
    // `BasilRichTextEditor.toggleList` inserts visible marker characters
    // ("• " for bullets, "1. " / "2. " / ... for numbered items) at the start of
    // each list paragraph because NSTextView does not auto-render NSTextList
    // markers for programmatically edited text. When serializing back to
    // markdown we must drop those characters; otherwise a bullet paragraph
    // round-trips as `"- • Buy milk"` instead of `"- Buy milk"`.
    //
    // The recognizer lives on `BasilRichTextEditor` itself so the insert path
    // and the strip path can never drift apart.

    /// Returns `paragraph` with any leading list-marker characters removed.
    /// If the paragraph does not start with a recognized marker the input is
    /// returned unchanged.
    private static func stripLeadingListMarker(_ paragraph: NSAttributedString) -> NSAttributedString {
        guard let stripCount = BasilRichTextEditor.leadingListMarkerLength(in: paragraph.string),
              stripCount > 0,
              stripCount <= paragraph.length
        else {
            return paragraph
        }
        return paragraph.attributedSubstring(
            from: NSRange(location: stripCount, length: paragraph.length - stripCount)
        )
    }
}
