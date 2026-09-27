import AppKit
import Combine

/// Imperative instruction bus the SwiftUI parent holds (typically as `@StateObject`).
///
/// All `toggle*` methods are no-ops if no editor is currently bound, so it is safe
/// to wire toolbar buttons before the underlying `NSTextView` is materialized.
final class RichTextEditorController: ObservableObject {
    weak var textView: BasilEditableTextView?
    var configuration: RichTextEditorConfiguration = RichTextEditorConfiguration()

    // MARK: Trait toggles

    func toggleBold()      { toggleFontTrait(.boldFontMask) }
    func toggleItalic()    { toggleFontTrait(.italicFontMask) }

    func toggleUnderline() {
        guard let textView = textView, let storage = textView.textStorage else { return }
        let range = textView.selectedRange()

        if range.length > 0 {
            let isOn = isUnderlineActive(in: storage, range: range)
            storage.beginEditing()
            if isOn {
                storage.removeAttribute(.underlineStyle, range: range)
            } else {
                storage.addAttribute(.underlineStyle, value: NSUnderlineStyle.single.rawValue, range: range)
            }
            storage.endEditing()
        } else {
            var attrs = textView.typingAttributes
            let currentRaw = (attrs[.underlineStyle] as? Int) ?? 0
            if currentRaw == 0 {
                attrs[.underlineStyle] = NSUnderlineStyle.single.rawValue
            } else {
                attrs.removeValue(forKey: .underlineStyle)
            }
            textView.typingAttributes = attrs
        }
        textView.didChangeText()
        textView.basilDidEditAttributes()
    }

    // MARK: Code

    /// Toggles inline code styling (monospaced font + marker) on the current selection.
    /// If there is no selection, flips the typing attributes for upcoming text.
    func toggleInlineCode() {
        guard let textView = textView, let storage = textView.textStorage else { return }
        let range = textView.selectedRange()
        let monospaced = configuration.monospacedFont
        let baseFont = configuration.font

        if range.length > 0 {
            let isOn = isInlineCodeActive(in: storage, range: range)
            storage.beginEditing()
            if isOn {
                storage.removeAttribute(.basilInlineCode, range: range)
                storage.enumerateAttribute(.font, in: range, options: []) { value, subrange, _ in
                    let restored = restoreToBaseFont(value as? NSFont, base: baseFont)
                    storage.addAttribute(.font, value: restored, range: subrange)
                }
            } else {
                storage.addAttribute(.basilInlineCode, value: true, range: range)
                storage.enumerateAttribute(.font, in: range, options: []) { value, subrange, _ in
                    let traits = (value as? NSFont).map { NSFontManager.shared.traits(of: $0) } ?? []
                    var newFont = monospaced
                    if traits.contains(.boldFontMask) {
                        newFont = NSFontManager.shared.convert(newFont, toHaveTrait: .boldFontMask)
                    }
                    if traits.contains(.italicFontMask) {
                        newFont = NSFontManager.shared.convert(newFont, toHaveTrait: .italicFontMask)
                    }
                    storage.addAttribute(.font, value: newFont, range: subrange)
                }
            }
            storage.endEditing()
        } else {
            var attrs = textView.typingAttributes
            if (attrs[.basilInlineCode] as? Bool) == true {
                attrs.removeValue(forKey: .basilInlineCode)
                attrs[.font] = restoreToBaseFont(attrs[.font] as? NSFont, base: baseFont)
            } else {
                attrs[.basilInlineCode] = true
                attrs[.font] = monospaced
            }
            textView.typingAttributes = attrs
        }
        textView.didChangeText()
        textView.basilDidEditAttributes()
    }

    /// Toggles the current paragraph(s) between a fenced code block style and normal style.
    func toggleCodeBlock() {
        guard let textView = textView, let storage = textView.textStorage else { return }
        let paragraphRange = (storage.string as NSString).paragraphRange(for: textView.selectedRange())
        let monospaced = configuration.monospacedFont
        let baseFont = configuration.font

        let isOn = (storage.length > 0)
            ? (storage.attribute(.basilCodeBlock, at: paragraphRange.location, effectiveRange: nil) as? Bool) == true
            : (textView.typingAttributes[.basilCodeBlock] as? Bool) == true

        storage.beginEditing()
        if paragraphRange.length > 0 {
            if isOn {
                storage.removeAttribute(.basilCodeBlock, range: paragraphRange)
                storage.enumerateAttribute(.font, in: paragraphRange, options: []) { value, subrange, _ in
                    storage.addAttribute(.font, value: restoreToBaseFont(value as? NSFont, base: baseFont), range: subrange)
                }
                storage.enumerateAttribute(.paragraphStyle, in: paragraphRange, options: []) { value, subrange, _ in
                    let style = (value as? NSParagraphStyle)?.mutableCopy() as? NSMutableParagraphStyle ?? NSMutableParagraphStyle()
                    style.firstLineHeadIndent = 0
                    style.headIndent = 0
                    storage.addAttribute(.paragraphStyle, value: style, range: subrange)
                }
            } else {
                storage.addAttribute(.basilCodeBlock, value: true, range: paragraphRange)
                storage.addAttribute(.font, value: monospaced, range: paragraphRange)
                let style = NSMutableParagraphStyle()
                style.firstLineHeadIndent = 12
                style.headIndent = 12
                style.paragraphSpacing = 4
                storage.addAttribute(.paragraphStyle, value: style, range: paragraphRange)
            }
        }
        storage.endEditing()

        // Update typing attributes so newly typed text continues the toggle state.
        var attrs = textView.typingAttributes
        if isOn {
            attrs.removeValue(forKey: .basilCodeBlock)
            attrs[.font] = baseFont
            attrs[.paragraphStyle] = NSParagraphStyle.default
        } else {
            attrs[.basilCodeBlock] = true
            attrs[.font] = monospaced
            let style = NSMutableParagraphStyle()
            style.firstLineHeadIndent = 12
            style.headIndent = 12
            style.paragraphSpacing = 4
            attrs[.paragraphStyle] = style
        }
        textView.typingAttributes = attrs

        textView.didChangeText()
        textView.basilDidEditAttributes()
    }

    // MARK: Lists

    func toggleBulletList()  { toggleList(format: .disc) }
    func toggleNumberedList(){ toggleList(format: .decimal) }

    // MARK: Text accessors

    func plainText() -> String {
        textView?.string ?? ""
    }

    func attributedText() -> NSAttributedString {
        textView?.attributedString() ?? NSAttributedString()
    }

    func setText(_ text: String) {
        guard let textView = textView else { return }
        if text.isEmpty {
            textView.basilResetToBaseline(font: configuration.font, textColor: configuration.textColor)
            textView.didChangeText()
            textView.basilDidEditAttributes()
            return
        }
        let attrs: [NSAttributedString.Key: Any] = [
            .font: configuration.font,
            .foregroundColor: configuration.textColor,
            .paragraphStyle: NSParagraphStyle.default
        ]
        textView.textStorage?.setAttributedString(NSAttributedString(string: text, attributes: attrs))
        textView.didChangeText()
        textView.basilDidEditAttributes()
    }

    func clear() {
        setText("")
    }

    func focus() {
        guard let textView = textView else { return }
        textView.window?.makeFirstResponder(textView)
    }

    // MARK: - Internals

    private func toggleFontTrait(_ trait: NSFontTraitMask) {
        guard let textView = textView, let storage = textView.textStorage else { return }
        let range = textView.selectedRange()

        if range.length > 0 {
            storage.beginEditing()
            storage.enumerateAttribute(.font, in: range, options: []) { value, subrange, _ in
                let currentFont = (value as? NSFont) ?? configuration.font
                let traits = NSFontManager.shared.traits(of: currentFont)
                let newFont: NSFont = traits.contains(trait)
                    ? NSFontManager.shared.convert(currentFont, toNotHaveTrait: trait)
                    : NSFontManager.shared.convert(currentFont, toHaveTrait: trait)
                storage.addAttribute(.font, value: newFont, range: subrange)
            }
            storage.endEditing()
        } else {
            var attrs = textView.typingAttributes
            let currentFont = (attrs[.font] as? NSFont) ?? configuration.font
            let traits = NSFontManager.shared.traits(of: currentFont)
            let newFont: NSFont = traits.contains(trait)
                ? NSFontManager.shared.convert(currentFont, toNotHaveTrait: trait)
                : NSFontManager.shared.convert(currentFont, toHaveTrait: trait)
            attrs[.font] = newFont
            textView.typingAttributes = attrs
        }
        textView.didChangeText()
        textView.basilDidEditAttributes()
    }

    private func toggleList(format: NSTextList.MarkerFormat) {
        guard let textView = textView, let storage = textView.textStorage else { return }
        let nsString = storage.string as NSString
        let paragraphRange = nsString.paragraphRange(for: textView.selectedRange())
        guard paragraphRange.length > 0 || storage.length == 0 else { return }

        // Determine on/off from the FIRST paragraph in the selection. "On" here
        // means "this paragraph is already in the requested format"; clicking the
        // same format toggles it off, clicking the OTHER format swaps the marker.
        let isOn: Bool = {
            guard storage.length > 0 else { return false }
            let style = storage.attribute(.paragraphStyle, at: paragraphRange.location, effectiveRange: nil) as? NSParagraphStyle
            return style?.textLists.first?.markerFormat == format
        }()

        // Enumerate every paragraph fully or partially covered by the selection.
        // We process this list in REVERSE so that insert/delete operations on
        // earlier paragraphs don't invalidate the locations of later ones.
        var paragraphRanges: [NSRange] = []
        var cursor = paragraphRange.location
        let rangeEnd = NSMaxRange(paragraphRange)
        while cursor < rangeEnd {
            let pRange = nsString.paragraphRange(for: NSRange(location: cursor, length: 0))
            paragraphRanges.append(pRange)
            let next = NSMaxRange(pRange)
            if next <= cursor { break }
            cursor = next
        }

        storage.beginEditing()
        if storage.length > 0 {
            // Numbered lists count from 1 starting at the FIRST paragraph in the
            // selection. Since we iterate in reverse, the counter starts at the
            // total count and decrements after each iteration, so the first
            // paragraph (processed last) ends up labeled "1.".
            var itemNumber = paragraphRanges.count
            for original in paragraphRanges.reversed() {
                var pRange = original

                // Strip any existing list marker first. This handles BOTH the
                // disable path AND the swap-from-other-format path uniformly.
                let paragraphText = (storage.string as NSString).substring(with: pRange)
                if let existingMarkerLen = BasilRichTextEditor.leadingListMarkerLength(in: paragraphText), existingMarkerLen <= pRange.length {
                    storage.deleteCharacters(in: NSRange(location: pRange.location, length: existingMarkerLen))
                    pRange = NSRange(location: pRange.location, length: pRange.length - existingMarkerLen)
                }

                let style = NSMutableParagraphStyle()
                if isOn {
                    // Disable list formatting on this paragraph.
                    style.textLists = []
                    style.firstLineHeadIndent = 0
                    style.headIndent = 0
                    if pRange.length > 0 {
                        storage.addAttribute(.paragraphStyle, value: style, range: pRange)
                    }
                } else {
                    // Enable the requested list format. Insert a visible marker
                    // character at the start of the paragraph (NSTextView does
                    // not auto-render NSTextList markers for programmatically
                    // created list paragraphs), and set the paragraph style so
                    // the toolbar's active-state probe and the markdown
                    // serializer can identify this paragraph as a list item.
                    let markerString: String
                    switch format {
                    case .decimal: markerString = "\(itemNumber). "
                    default:       markerString = "• "
                    }

                    // Inherit run attributes from the paragraph (or the typing
                    // attributes if it's empty) so the marker uses the same
                    // font/color as the body text. Strip inline-code so the
                    // marker isn't rendered monospace mid-bullet.
                    var markerAttrs: [NSAttributedString.Key: Any]
                    if pRange.length > 0, pRange.location < storage.length {
                        markerAttrs = storage.attributes(at: pRange.location, effectiveRange: nil)
                    } else {
                        markerAttrs = textView.typingAttributes
                    }
                    markerAttrs[.font] = configuration.font
                    markerAttrs.removeValue(forKey: .basilInlineCode)

                    let markerAttr = NSAttributedString(string: markerString, attributes: markerAttrs)
                    storage.insert(markerAttr, at: pRange.location)
                    pRange = NSRange(location: pRange.location, length: pRange.length + markerString.count)

                    style.textLists = [NSTextList(markerFormat: format, options: 0)]
                    style.firstLineHeadIndent = 0
                    style.headIndent = 16
                    storage.addAttribute(.paragraphStyle, value: style, range: pRange)
                }

                itemNumber -= 1
            }
        }
        storage.endEditing()

        // Update typing attributes so the next paragraph the user types keeps
        // the chosen list state. We do NOT auto-insert a marker on Return here;
        // the user re-clicks the toolbar button to add another list item. Auto-
        // continue is a future enhancement.
        var attrs = textView.typingAttributes
        let style = (attrs[.paragraphStyle] as? NSParagraphStyle)?.mutableCopy() as? NSMutableParagraphStyle ?? NSMutableParagraphStyle()
        if isOn {
            style.textLists = []
            style.firstLineHeadIndent = 0
            style.headIndent = 0
        } else {
            style.textLists = [NSTextList(markerFormat: format, options: 0)]
            style.firstLineHeadIndent = 0
            style.headIndent = 16
        }
        attrs[.paragraphStyle] = style
        textView.typingAttributes = attrs

        textView.didChangeText()
        textView.basilDidEditAttributes()
    }

    private func isUnderlineActive(in storage: NSTextStorage, range: NSRange) -> Bool {
        var allOn = true
        storage.enumerateAttribute(.underlineStyle, in: range, options: []) { value, _, stop in
            let raw = (value as? Int) ?? 0
            if raw == 0 { allOn = false; stop.pointee = true }
        }
        return allOn
    }

    private func isInlineCodeActive(in storage: NSTextStorage, range: NSRange) -> Bool {
        var allOn = true
        storage.enumerateAttribute(.basilInlineCode, in: range, options: []) { value, _, stop in
            if (value as? Bool) != true { allOn = false; stop.pointee = true }
        }
        return allOn
    }

    private func restoreToBaseFont(_ font: NSFont?, base: NSFont) -> NSFont {
        let traits = font.map { NSFontManager.shared.traits(of: $0) } ?? []
        var result = base
        if traits.contains(.boldFontMask)   { result = NSFontManager.shared.convert(result, toHaveTrait: .boldFontMask) }
        if traits.contains(.italicFontMask) { result = NSFontManager.shared.convert(result, toHaveTrait: .italicFontMask) }
        return result
    }
}
