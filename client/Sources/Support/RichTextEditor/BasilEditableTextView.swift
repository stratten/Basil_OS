import AppKit

protocol BasilEditableTextViewHandler: AnyObject {
    func basilTextViewDidEditAttributes(_ textView: BasilEditableTextView)
    func basilTextView(_ textView: BasilEditableTextView, shouldHandleKeyDown event: NSEvent) -> Bool
    func basilTextView(_ textView: BasilEditableTextView, shouldPasteImages images: [NSImage]) -> Bool
}

final class BasilEditableTextView: NSTextView {
    weak var basilHandler: BasilEditableTextViewHandler?
    var placeholderString: String = "" { didSet { needsDisplay = true } }
    var placeholderColor: NSColor = NSColor.tertiaryLabelColor { didSet { needsDisplay = true } }
    var enforcedTextColor: NSColor = .textColor
    var baselineFont: NSFont = NSFont.systemFont(ofSize: 14)

    func basilResetToBaseline(font: NSFont, textColor: NSColor) {
        textStorage?.setAttributedString(NSAttributedString())
        self.font = font
        self.textColor = textColor
        self.enforcedTextColor = textColor
        self.baselineFont = font
        typingAttributes = [
            .font: font,
            .foregroundColor: textColor,
            .paragraphStyle: NSParagraphStyle.default
        ]
        setSelectedRange(NSRange(location: 0, length: 0))
        undoManager?.removeAllActions()
        needsDisplay = true
    }

    // Never allow this view to participate in drag-by-background promotion.
    // This ensures mouse interactions inside the editor always behave like text
    // editing gestures (selection, double-click word select, drag highlight).
    override var mouseDownCanMoveWindow: Bool {
        false
    }

    /// Called by `RichTextEditorController` when it mutates attributes directly so
    /// the SwiftUI binding can be refreshed (NSTextView's delegate `textDidChange`
    /// only fires for text-content edits, not attribute-only edits).
    func basilDidEditAttributes() {
        basilHandler?.basilTextViewDidEditAttributes(self)
        needsDisplay = true
    }

    override func keyDown(with event: NSEvent) {
        if basilHandler?.basilTextView(self, shouldHandleKeyDown: event) == true { return }
        super.keyDown(with: event)
    }

    override func validateUserInterfaceItem(_ item: NSValidatedUserInterfaceItem) -> Bool {
        if item.action == #selector(paste(_:)),
           !extractPasteboardImages(from: NSPasteboard.general).isEmpty {
            return true
        }
        return super.validateUserInterfaceItem(item)
    }

    override func paste(_ sender: Any?) {
        let pasteboard = NSPasteboard.general
        if containsPasteableText(in: pasteboard) {
            super.paste(sender)
            return
        }

        let images = extractPasteboardImages(from: pasteboard)
        if !images.isEmpty,
           basilHandler?.basilTextView(self, shouldPasteImages: images) == true {
            return
        }

        super.paste(sender)
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        guard string.isEmpty, !placeholderString.isEmpty else { return }
        let attrs: [NSAttributedString.Key: Any] = [
            .font: font ?? NSFont.systemFont(ofSize: 14),
            .foregroundColor: placeholderColor
        ]
        let inset = textContainerInset
        let origin = NSPoint(x: inset.width + 5, y: inset.height)
        (placeholderString as NSString).draw(at: origin, withAttributes: attrs)
    }

    override func didChangeText() {
        super.didChangeText()
        if string.isEmpty {
            basilResetToBaseline(font: baselineFont, textColor: enforcedTextColor)
            basilDidEditAttributes()
            return
        }
        // Keep newly inserted text runs anchored to the configured editor color.
        // This avoids dynamic color remapping regressions under dark-mode hosts.
        if let storage = textStorage {
            let range = storage.editedRange
            if range.location != NSNotFound, range.length > 0 {
                storage.addAttribute(.foregroundColor, value: enforcedTextColor, range: range)
            }
        }
        var attrs = typingAttributes
        attrs[.foregroundColor] = enforcedTextColor
        typingAttributes = attrs
        needsDisplay = true
    }

    private func containsPasteableText(in pasteboard: NSPasteboard) -> Bool {
        pasteboard.availableType(from: [.string, .rtf, .html]) != nil
    }

    private func extractPasteboardImages(from pasteboard: NSPasteboard) -> [NSImage] {
        var images: [NSImage] = []
        let supportedImageTypes: [NSPasteboard.PasteboardType] = [
            .png,
            .tiff,
            NSPasteboard.PasteboardType("public.jpeg"),
            NSPasteboard.PasteboardType("public.file-url"),
        ]

        for item in pasteboard.pasteboardItems ?? [] {
            if let fileURLString = item.string(forType: .fileURL),
               let url = URL(string: fileURLString),
               let image = NSImage(contentsOf: url) {
                images.append(image)
                continue
            }

            for type in supportedImageTypes {
                guard let data = item.data(forType: type),
                      let image = NSImage(data: data)
                else { continue }
                images.append(image)
                break
            }
        }

        if images.isEmpty, let image = NSImage(pasteboard: pasteboard) {
            images.append(image)
        }
        return images
    }
}
