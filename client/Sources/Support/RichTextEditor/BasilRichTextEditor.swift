import AppKit
import Combine
import SwiftUI

// MARK: - Public types
//
// Standalone, reusable rich-text editing surface for the Swift portions of the app.
//
// This file exposes:
//
//   - `BasilRichTextEditor`            -- SwiftUI `NSViewRepresentable` wrapping `NSTextView`.
//   - `RichTextFormattingState`        -- snapshot of which formatting is active at the caret/selection.
//   - `RichTextEditorController`       -- imperative instruction bus for SwiftUI parents (toolbar buttons, etc).
//   - `RichTextEditorConfiguration`    -- pure-data configuration (placeholder, sizing, fonts, callbacks).
//   - `RichTextEditorToolbar`          -- optional companion toolbar; consumers may build their own.
//
// The utility deliberately has NO knowledge of agentTasks, view models, or any
// other consumer-specific concerns. Any view in the app can drop it in.

// MARK: - SwiftUI representable

struct BasilRichTextEditor: NSViewRepresentable {
    @Binding var text: NSAttributedString
    var formattingState: Binding<RichTextFormattingState>?
    var controller: RichTextEditorController?
    var configuration: RichTextEditorConfiguration

    init(
        text: Binding<NSAttributedString>,
        formattingState: Binding<RichTextFormattingState>? = nil,
        controller: RichTextEditorController? = nil,
        configuration: RichTextEditorConfiguration = RichTextEditorConfiguration()
    ) {
        self._text = text
        self.formattingState = formattingState
        self.controller = controller
        self.configuration = configuration
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    // MARK: List marker recognition

    /// Detects the length, in UTF-16 code units, of a list marker prefix this
    /// editor would have inserted. Recognized patterns:
    ///
    ///   - Bullet: `"• "` (U+2022 + space) -> 2
    ///   - Numbered: one or more decimal digits, then `". "` -> digits + 2
    ///
    /// Returns `nil` if the paragraph does not start with a recognized marker.
    /// `static` so the markdown serializer (`MarkdownUtils`) and the Coordinator's
    /// Return-key handler can share the exact same recognizer that `toggleList`
    /// uses internally — single source of truth for what counts as a list marker.
    static func leadingListMarkerLength(in paragraph: String) -> Int? {
        if paragraph.hasPrefix("• ") { return 2 }
        var digits = 0
        var idx = paragraph.startIndex
        while idx < paragraph.endIndex,
              let scalar = paragraph[idx].unicodeScalars.first,
              CharacterSet.decimalDigits.contains(scalar) {
            digits += 1
            idx = paragraph.index(after: idx)
        }
        guard digits > 0, idx < paragraph.endIndex, paragraph[idx] == "." else { return nil }
        let afterDot = paragraph.index(after: idx)
        guard afterDot < paragraph.endIndex, paragraph[afterDot] == " " else { return nil }
        return digits + 2
    }

    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSScrollView()
        scroll.borderType = .noBorder
        scroll.hasVerticalScroller = configuration.isScrollable
        scroll.hasHorizontalScroller = false
        scroll.autohidesScrollers = true
        scroll.drawsBackground = false
        scroll.backgroundColor = configuration.backgroundColor

        let textView = BasilEditableTextView(frame: .zero)
        textView.delegate = context.coordinator
        textView.basilHandler = context.coordinator
        textView.allowsUndo = true
        textView.isRichText = true
        textView.isEditable = true
        textView.isSelectable = true
        textView.usesFindBar = false
        textView.importsGraphics = false
        textView.isAutomaticQuoteSubstitutionEnabled = false
        textView.isAutomaticDashSubstitutionEnabled = false
        textView.isAutomaticTextReplacementEnabled = false
        textView.smartInsertDeleteEnabled = false
        textView.isAutomaticSpellingCorrectionEnabled = false
        // Restore the previously stable NSTextView sizing/container setup.
        textView.isHorizontallyResizable = false
        textView.isVerticallyResizable = true
        textView.autoresizingMask = [.width]
        textView.minSize = NSSize(width: 0, height: configuration.minHeight)
        textView.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        if let textContainer = textView.textContainer {
            textContainer.widthTracksTextView = true
            textContainer.containerSize = NSSize(
                width: scroll.contentSize.width,
                height: CGFloat.greatestFiniteMagnitude
            )
        }
        textView.font = configuration.font
        textView.textColor = configuration.textColor
        // Prevent AppKit from remapping explicit editor text colors when the
        // host system is in dark mode.
        textView.usesAdaptiveColorMappingForDarkAppearance = false
        // Keep the caret visible against light editor backgrounds, even when the
        // host system is in dark mode.
        textView.insertionPointColor = configuration.textColor
        textView.drawsBackground = false
        textView.backgroundColor = .clear
        textView.textContainerInset = configuration.insets
        textView.placeholderString = configuration.placeholder
        textView.placeholderColor = configuration.placeholderColor
        textView.enforcedTextColor = configuration.textColor
        textView.baselineFont = configuration.font
        textView.typingAttributes = [
            .font: configuration.font,
            .foregroundColor: configuration.textColor
        ]

        // Bind initial document.
        if text.length > 0 {
            textView.textStorage?.setAttributedString(normalizedTextColor(in: text, color: configuration.textColor))
        }

        scroll.documentView = textView

        // Expose the underlying view to the controller (if provided).
        if let controller = controller {
            controller.textView = textView
            controller.configuration = configuration
        }

        if configuration.focusOnAppear {
            DispatchQueue.main.async { [weak textView] in
                textView?.window?.makeFirstResponder(textView)
            }
        }

        // Prime the parent with an initial content height. Without this,
        // callers wiring `onContentHeightChange` to a `@State` would have to
        // hard-code a sensible default for the first frame; here we hand them
        // the real measurement (placeholder line height + insets) immediately.
        // Done async so layout has had a chance to run inside the scroll view.
        DispatchQueue.main.async { [weak textView, weak coordinator = context.coordinator] in
            guard let textView, let coordinator else { return }
            coordinator.reportContentHeightIfNeeded(textView)
        }

        return scroll
    }

    func updateNSView(_ nsView: NSScrollView, context: Context) {
        guard let textView = nsView.documentView as? BasilEditableTextView else { return }

        // SwiftUI rebuilds this struct on every parent re-render. Keep the
        // coordinator pointing at the latest copy so its delegate callbacks
        // read fresh bindings/configuration.
        context.coordinator.parent = self

        // Keep controller wired to the latest configuration so toolbar actions
        // see updated fonts/colors if the parent recreates the configuration.
        controller?.textView = textView
        controller?.configuration = configuration
        textView.placeholderString = configuration.placeholder
        textView.placeholderColor = configuration.placeholderColor
        textView.textContainerInset = configuration.insets
        textView.textColor = configuration.textColor
        textView.usesAdaptiveColorMappingForDarkAppearance = false
        textView.insertionPointColor = configuration.textColor
        textView.minSize = NSSize(width: 0, height: configuration.minHeight)
        textView.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        if let textContainer = textView.textContainer {
            textContainer.widthTracksTextView = true
            textContainer.containerSize = NSSize(
                width: nsView.contentSize.width,
                height: CGFloat.greatestFiniteMagnitude
            )
        }
        textView.enforcedTextColor = configuration.textColor
        textView.baselineFont = configuration.font
        var attrs = textView.typingAttributes
        attrs[.font] = attrs[.font] ?? configuration.font
        attrs[.foregroundColor] = configuration.textColor
        textView.typingAttributes = attrs

        // Avoid clobbering the user's caret/selection on every parent re-render.
        // Only push the bound document back into the text storage if it differs.
        if !context.coordinator.isApplyingExternalUpdate,
           textView.attributedString() != text {
            context.coordinator.isApplyingExternalUpdate = true
            let selected = textView.selectedRange()
            if text.length == 0 {
                textView.basilResetToBaseline(font: configuration.font, textColor: configuration.textColor)
            } else {
                textView.textStorage?.setAttributedString(normalizedTextColor(in: text, color: configuration.textColor))
                // Best-effort restore selection.
                let clamped = NSRange(
                    location: min(selected.location, textView.string.utf16.count),
                    length: 0
                )
                textView.setSelectedRange(clamped)
            }
            context.coordinator.isApplyingExternalUpdate = false
            context.coordinator.pushFormattingState(from: textView)
            // Programmatic storage replacements (e.g. the conversation
            // widget clearing the draft after send) don't fire the
            // delegate's `textDidChange`, so we report the new height here
            // explicitly. Otherwise the parent would keep the editor's
            // frame at the prior, larger height after sending.
            context.coordinator.reportContentHeightIfNeeded(textView)
        }
    }

    private func normalizedTextColor(in source: NSAttributedString, color: NSColor) -> NSAttributedString {
        let normalized = NSMutableAttributedString(attributedString: source)
        guard normalized.length > 0 else { return normalized }
        normalized.addAttribute(.foregroundColor, value: color, range: NSRange(location: 0, length: normalized.length))
        return normalized
    }

    // MARK: Coordinator

    final class Coordinator: NSObject, NSTextViewDelegate, BasilEditableTextViewHandler {
        var parent: BasilRichTextEditor
        var isApplyingExternalUpdate: Bool = false
        /// Last value handed to `configuration.onContentHeightChange`. Used to
        /// suppress no-op callbacks (e.g. selection changes that don't alter
        /// layout) so SwiftUI state bindings on the parent only update when
        /// the editor's effective height has actually moved.
        private var lastReportedContentHeight: CGFloat = -1

        init(parent: BasilRichTextEditor) {
            self.parent = parent
        }

        func textDidChange(_ notification: Notification) {
            guard let textView = notification.object as? BasilEditableTextView else { return }
            pushTextBinding(from: textView)
            pushFormattingState(from: textView)
            reportContentHeightIfNeeded(textView)
        }

        func textViewDidChangeSelection(_ notification: Notification) {
            guard let textView = notification.object as? BasilEditableTextView else { return }
            pushFormattingState(from: textView)
        }

        // MARK: BasilEditableTextViewHandler

        func basilTextViewDidEditAttributes(_ textView: BasilEditableTextView) {
            pushTextBinding(from: textView)
            pushFormattingState(from: textView)
            // Toolbar actions (lists, code blocks, font traits with different
            // line metrics) can change layout height without going through
            // `textDidChange`, so report from this code path too.
            reportContentHeightIfNeeded(textView)
        }

        /// Measures the NSTextView's laid-out content height (using the layout
        /// manager's `usedRect` for its text container, plus vertical
        /// container insets) and forwards it to the configuration's
        /// `onContentHeightChange` callback if and only if the value differs
        /// from the last reported one. Always dispatched async to the main
        /// queue so the callback can safely mutate SwiftUI `@State`.
        ///
        /// Public-on-the-coordinator (no `private`) so the representable's
        /// `makeNSView` can prime the parent with an initial height as soon
        /// as the text view is wired up; without that priming, the editor
        /// would sit at its placeholder height until the user typed.
        func reportContentHeightIfNeeded(_ textView: BasilEditableTextView) {
            guard let callback = parent.configuration.onContentHeightChange,
                  let layoutManager = textView.layoutManager,
                  let textContainer = textView.textContainer
            else { return }
            layoutManager.ensureLayout(for: textContainer)
            let usedRect = layoutManager.usedRect(for: textContainer)
            let inset = textView.textContainerInset
            let height = ceil(usedRect.height + inset.height * 2)
            guard height != lastReportedContentHeight else { return }
            lastReportedContentHeight = height
            DispatchQueue.main.async {
                callback(height)
            }
        }

        func basilTextView(_ textView: BasilEditableTextView, shouldHandleKeyDown event: NSEvent) -> Bool {
            // Cmd+Return -> submit
            let isReturn = event.keyCode == 36 || event.keyCode == 76
            if isReturn, event.modifierFlags.contains(.command), let submit = parent.configuration.submitOnCommandReturn {
                submit()
                return true
            }
            // Plain Return inside a list paragraph -> auto-continue (insert next
            // marker on the new line) or auto-exit (strip the marker and drop
            // back to plain text) when the current item is empty.
            //
            // We deliberately ignore Shift+Return so Shift+Enter remains a soft
            // newline that does NOT continue the list (matches Notes/Mail).
            // Option+Return also falls through unchanged.
            if isReturn,
               !event.modifierFlags.contains(.shift),
               !event.modifierFlags.contains(.option),
               !event.modifierFlags.contains(.command),
               handleReturnInList(textView) {
                return true
            }
            // Escape -> cancel
            if event.keyCode == 53, let cancel = parent.configuration.cancelOnEscape {
                cancel()
                return true
            }
            return false
        }

        func basilTextView(_ textView: BasilEditableTextView, shouldPasteImages images: [NSImage]) -> Bool {
            guard let onPasteImages = parent.configuration.onPasteImages else { return false }
            return onPasteImages(images)
        }

        // MARK: List auto-continue

        /// Handles a plain `Return` when the caret is inside a list paragraph.
        /// Returns `true` if the event was consumed (and storage mutated), or
        /// `false` to let the text view perform its default newline insertion.
        private func handleReturnInList(_ textView: BasilEditableTextView) -> Bool {
            guard let storage = textView.textStorage, storage.length > 0 else { return false }
            let selRange = textView.selectedRange()
            let nsString = storage.string as NSString
            let pRange = nsString.paragraphRange(for: selRange)
            guard pRange.location < storage.length else { return false }

            // Is this paragraph actually a list paragraph?
            guard
                let style = storage.attribute(.paragraphStyle, at: pRange.location, effectiveRange: nil) as? NSParagraphStyle,
                let listFormat = style.textLists.first?.markerFormat,
                listFormat == .disc || listFormat == .decimal
            else { return false }

            // Strip the trailing newline (if any) so length math reflects the
            // visible content of the paragraph, not its delimiter.
            let paragraphWithNL = nsString.substring(with: pRange)
            let paragraphText = paragraphWithNL.hasSuffix("\n") ? String(paragraphWithNL.dropLast()) : paragraphWithNL
            let markerLen = BasilRichTextEditor.leadingListMarkerLength(in: paragraphText) ?? 0
            let bodyLen = (paragraphText as NSString).length - markerLen

            if bodyLen <= 0 {
                // Empty list item -> exit the list at this paragraph.
                return exitList(at: pRange, markerLen: markerLen, in: textView)
            }
            // Non-empty -> insert newline + the next marker for this list type.
            return continueList(
                at: selRange,
                listFormat: listFormat,
                previousParagraphText: paragraphText,
                in: textView
            )
        }

        /// Removes the list-marker prefix from `pRange`, clears its list
        /// paragraph style, and parks the caret at what is now a plain
        /// paragraph. Used when the user presses Return on an empty list item.
        private func exitList(at pRange: NSRange, markerLen: Int, in textView: BasilEditableTextView) -> Bool {
            guard let storage = textView.textStorage else { return false }
            storage.beginEditing()
            if markerLen > 0, pRange.location + markerLen <= storage.length {
                storage.deleteCharacters(in: NSRange(location: pRange.location, length: markerLen))
            }
            let plainStyle = NSMutableParagraphStyle()
            plainStyle.textLists = []
            plainStyle.firstLineHeadIndent = 0
            plainStyle.headIndent = 0
            let newLength = max(0, pRange.length - markerLen)
            if newLength > 0 {
                storage.addAttribute(
                    .paragraphStyle,
                    value: plainStyle,
                    range: NSRange(location: pRange.location, length: newLength)
                )
            }
            storage.endEditing()

            // Typing attributes need to forget the list state too, otherwise the
            // very next keystroke would inherit it and re-indent.
            var typing = textView.typingAttributes
            typing[.paragraphStyle] = plainStyle
            textView.typingAttributes = typing

            textView.setSelectedRange(NSRange(location: pRange.location, length: 0))
            textView.didChangeText()
            textView.basilDidEditAttributes()
            return true
        }

        /// Inserts a newline plus the next list marker at `selRange`. For
        /// numbered lists the next marker is parsed from the previous item
        /// (`"3. " -> "4. "`). The freshly inserted second paragraph has the
        /// list paragraph style explicitly applied so list state survives the
        /// split (NSTextStorage doesn't always propagate it across `\n`
        /// insertions on its own).
        private func continueList(
            at selRange: NSRange,
            listFormat: NSTextList.MarkerFormat,
            previousParagraphText: String,
            in textView: BasilEditableTextView
        ) -> Bool {
            guard let storage = textView.textStorage else { return false }

            let markerString: String
            switch listFormat {
            case .decimal:
                // Parse leading digits of the previous paragraph's marker.
                // `previousParagraphText` is something like "3. apple"; if the
                // marker can't be parsed we fall back to "1. " so the new line
                // still gets a sensible marker.
                var prev = 0
                var sawDigit = false
                for ch in previousParagraphText {
                    if let scalar = ch.unicodeScalars.first, CharacterSet.decimalDigits.contains(scalar),
                       let digit = ch.wholeNumberValue {
                        prev = prev * 10 + digit
                        sawDigit = true
                    } else {
                        break
                    }
                }
                markerString = "\((sawDigit ? prev : 0) + 1). "
            default:
                markerString = "• "
            }

            // Inherit run attributes from the character preceding the caret so
            // font / color / etc. carry forward, but force-strip inline-code so
            // the marker doesn't render monospaced.
            let inheritIndex: Int = {
                if selRange.location > 0 { return selRange.location - 1 }
                if selRange.location < storage.length { return selRange.location }
                return -1
            }()
            var attrs: [NSAttributedString.Key: Any]
            if inheritIndex >= 0 {
                attrs = storage.attributes(at: inheritIndex, effectiveRange: nil)
            } else {
                attrs = textView.typingAttributes
            }
            attrs[.font] = parent.configuration.font
            attrs.removeValue(forKey: .basilInlineCode)

            let listStyle = NSMutableParagraphStyle()
            listStyle.textLists = [NSTextList(markerFormat: listFormat, options: 0)]
            listStyle.firstLineHeadIndent = 0
            listStyle.headIndent = 16
            attrs[.paragraphStyle] = listStyle

            let insertion = NSAttributedString(string: "\n" + markerString, attributes: attrs)

            storage.beginEditing()
            if selRange.length > 0 {
                storage.deleteCharacters(in: selRange)
            }
            storage.insert(insertion, at: selRange.location)

            // Force the new (second) paragraph to carry the list paragraph
            // style. Without this, attribute normalization can hand the new
            // paragraph the trailing style from before the split.
            let cursorAfter = selRange.location + insertion.length
            let newParagraphRange = (storage.string as NSString).paragraphRange(
                for: NSRange(location: cursorAfter, length: 0)
            )
            if newParagraphRange.length > 0 {
                storage.addAttribute(.paragraphStyle, value: listStyle, range: newParagraphRange)
            }
            storage.endEditing()

            textView.setSelectedRange(NSRange(location: cursorAfter, length: 0))
            textView.typingAttributes = attrs

            textView.didChangeText()
            textView.basilDidEditAttributes()
            return true
        }

        // MARK: helpers

        private func pushTextBinding(from textView: BasilEditableTextView) {
            guard !isApplyingExternalUpdate else { return }
            let snapshot = textView.attributedString().copy() as? NSAttributedString
                ?? textView.attributedString()
            // Avoid re-entrancy: SwiftUI can re-render synchronously which would call
            // updateNSView with the new value during this same delegate cycle.
            isApplyingExternalUpdate = true
            parent.text = snapshot
            isApplyingExternalUpdate = false
        }

        func pushFormattingState(from textView: BasilEditableTextView) {
            guard let binding = parent.formattingState else { return }
            let state = formattingState(for: textView)
            if binding.wrappedValue != state {
                binding.wrappedValue = state
            }
        }

        private func formattingState(for textView: BasilEditableTextView) -> RichTextFormattingState {
            var state = RichTextFormattingState()
            let storage = textView.textStorage
            let range = textView.selectedRange()
            let probeRange: NSRange? = {
                if range.length > 0 { return range }
                guard let storage = storage, storage.length > 0 else { return nil }
                let probeLoc = max(0, min(range.location, storage.length - 1))
                return NSRange(location: probeLoc, length: 1)
            }()

            // Trait-derived flags
            if let storage = storage, let probeRange = probeRange {
                var allBold = true
                var allItalic = true
                var allUnderline = true
                var allInlineCode = true
                storage.enumerateAttribute(.font, in: probeRange, options: []) { value, _, _ in
                    let traits = (value as? NSFont).map { NSFontManager.shared.traits(of: $0) } ?? []
                    if !traits.contains(.boldFontMask)   { allBold = false }
                    if !traits.contains(.italicFontMask) { allItalic = false }
                }
                storage.enumerateAttribute(.underlineStyle, in: probeRange, options: []) { value, _, _ in
                    let raw = (value as? Int) ?? 0
                    if raw == 0 { allUnderline = false }
                }
                storage.enumerateAttribute(.basilInlineCode, in: probeRange, options: []) { value, _, _ in
                    if (value as? Bool) != true { allInlineCode = false }
                }
                state.isBold = allBold
                state.isItalic = allItalic
                state.isUnderline = allUnderline
                state.isInlineCode = allInlineCode

                if let style = storage.attribute(.paragraphStyle, at: probeRange.location, effectiveRange: nil) as? NSParagraphStyle {
                    if let firstList = style.textLists.first {
                        state.isBulletList = firstList.markerFormat == .disc
                        state.isNumberedList = firstList.markerFormat == .decimal
                    }
                }
                state.isCodeBlock = (storage.attribute(.basilCodeBlock, at: probeRange.location, effectiveRange: nil) as? Bool) == true
            } else {
                // Empty storage -- read typing attributes.
                let attrs = textView.typingAttributes
                let traits = (attrs[.font] as? NSFont).map { NSFontManager.shared.traits(of: $0) } ?? []
                state.isBold      = traits.contains(.boldFontMask)
                state.isItalic    = traits.contains(.italicFontMask)
                state.isUnderline = ((attrs[.underlineStyle] as? Int) ?? 0) != 0
                state.isInlineCode = (attrs[.basilInlineCode] as? Bool) == true
                state.isCodeBlock  = (attrs[.basilCodeBlock] as? Bool) == true
                if let style = attrs[.paragraphStyle] as? NSParagraphStyle, let firstList = style.textLists.first {
                    state.isBulletList = firstList.markerFormat == .disc
                    state.isNumberedList = firstList.markerFormat == .decimal
                }
            }
            return state
        }
    }
}
