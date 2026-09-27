import AppKit

// MARK: Formatting state

struct RichTextFormattingState: Equatable {
    var isBold: Bool = false
    var isItalic: Bool = false
    var isUnderline: Bool = false
    var isInlineCode: Bool = false
    var isCodeBlock: Bool = false
    var isBulletList: Bool = false
    var isNumberedList: Bool = false
}

// MARK: Configuration

struct RichTextEditorConfiguration {
    var placeholder: String = ""
    var minHeight: CGFloat = 80
    var maxHeight: CGFloat? = nil
    var font: NSFont = AestheticSystem.Typography.NSFonts.body
    var monospacedFont: NSFont = AestheticSystem.Typography.NSFonts.code
    var textColor: NSColor = .textColor
    var placeholderColor: NSColor = NSColor.tertiaryLabelColor
    var backgroundColor: NSColor = .clear
    var insets: NSSize = NSSize(width: 8, height: 6)
    var isScrollable: Bool = true
    var focusOnAppear: Bool = false
    /// Invoked when the user presses Cmd+Return inside the editor.
    var submitOnCommandReturn: (() -> Void)? = nil
    /// Invoked when the user presses Escape inside the editor.
    var cancelOnEscape: (() -> Void)? = nil
    /// Invoked when the pasteboard contains images but no pasteable text. Return
    /// true to consume the paste; return false to let AppKit handle it normally.
    var onPasteImages: (([NSImage]) -> Bool)? = nil
    /// Invoked whenever the editor's laid-out content height changes (text
    /// inserted/deleted, attributes that change line metrics applied, etc.).
    /// The reported value is the NSTextView's `usedRect` height plus the
    /// vertical text-container insets, in points. Callers typically bind this
    /// to a `@State` and feed it back through a `.frame(height:)` on the
    /// editor (and any enclosing fixed-height container) so the editor can
    /// grow in place with content up to whatever cap the caller enforces.
    ///
    /// Always dispatched to the main queue, and only fires when the height
    /// actually changes, so it's safe to drive SwiftUI state from it without
    /// "modifying state during view update" warnings.
    var onContentHeightChange: ((CGFloat) -> Void)? = nil
}

// MARK: Custom attribute keys

extension NSAttributedString.Key {
    /// Marker applied to runs that should render as inline code (monospaced + subtle background).
    static let basilInlineCode = NSAttributedString.Key("BasilInlineCode")
    /// Marker applied to paragraphs that should render as fenced code blocks.
    static let basilCodeBlock = NSAttributedString.Key("BasilCodeBlock")
}
