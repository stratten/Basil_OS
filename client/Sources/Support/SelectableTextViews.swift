import AppKit
import SwiftUI
import Combine

// MARK: - Selectable Text Views (shared)
//
// Cross-cutting selectable-text primitives used by widgets that render
// model output the user is likely to copy/paste. Lives in `Support/`
// rather than any single feature folder because both the unified
// AssistantSession (AssistantSession) result view and any future widget
// rendering plain text consume `SelectableSwiftUIText` directly. The
// AppKit-backed `SelectableText` below is kept alongside as the legacy
// fallback the SwiftUI variant was introduced to replace -- preserved
// verbatim from the pre-AssistantSession `Suggestion/` module so any future
// caller that needs justified text or numbered-list bolding can still
// reach for it without reinventing the NSTextView plumbing.

/// SwiftUI-native selectable text that mirrors the markdown branch's layout
/// geometry, so plain-text suggestions resize the same way markdown ones do.
///
/// Why this exists: the legacy `SelectableText` below wraps `NSTextView` inside
/// `NSScrollView`, which has no SwiftUI intrinsic size. Inside a parent that
/// uses `idealHeight: viewModel.currentIdealTextHeight` (a heuristic), the
/// AppKit view fills whatever frame SwiftUI hands it but never reports back a
/// real height — so when the heuristic is wrong, the container can't
/// compensate, and the widget either over- or under-sizes.
///
/// `SelectableSwiftUIText` mirrors the structure already proven to work for
/// markdown: an outer `ScrollView` with the inner `Text` carrying
/// `.fixedSize(horizontal: false, vertical: true)`. The inner `Text` reports
/// its real intrinsic height up the SwiftUI hierarchy, so the parent's
/// `idealHeight` becomes a starting hint that the layout system can override
/// when content is shorter or taller than the heuristic predicted.
///
/// Native `.textSelection(.enabled)` gives us word/character/line selection
/// and Cmd+C of partial selections without any AppKit responder plumbing.
struct SelectableSwiftUIText: View {
    let text: String
    let font: Font
    let textColor: Color

    init(
        text: String,
        font: Font = .custom(AestheticSystem.Typography.preferredFontName, size: 14),
        textColor: Color = .black
    ) {
        self.text = text
        self.font = font
        self.textColor = textColor
    }

    var body: some View {
        ScrollView {
            Text(text)
                .font(font)
                .foregroundColor(textColor)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .padding(AestheticSystem.Layout.paddingS)
                .frame(maxWidth: .infinity, alignment: .topLeading)
                .multilineTextAlignment(.leading)
        }
    }
}

struct SelectableText: NSViewRepresentable {
    var text: String
    var backgroundColor: NSColor
    var font: NSFont = NSFont.systemFont(ofSize: NSFont.systemFontSize)
    var textAlignment: NSTextAlignment = .justified
    
    func makeNSView(context: Context) -> NSScrollView {
        let scrollView = NSTextView.scrollableTextView()
        
        // Configure scroll view properties
        scrollView.hasVerticalScroller = true
        scrollView.hasHorizontalScroller = false // Typically, horizontal scrolling is not desired for text views
        scrollView.autohidesScrollers = true
        
        if let textView = scrollView.documentView as? NSTextView {
            // Configure the text view for read-only selection
            textView.string = text
            textView.isEditable = false
            textView.isSelectable = true
            textView.isRichText = false
            textView.font = font
            textView.backgroundColor = backgroundColor
            textView.drawsBackground = true
            textView.textColor = .textColor
            textView.allowsUndo = false
            
            // Enable proper text selection behaviors
            textView.isGrammarCheckingEnabled = false
            textView.isContinuousSpellCheckingEnabled = false
            textView.textContainerInset = NSSize(width: 8, height: 8)
            
            // Configure paragraph style with justification
            let paragraphStyle = NSMutableParagraphStyle()
            paragraphStyle.paragraphSpacing = 1
            paragraphStyle.lineSpacing = 1
            paragraphStyle.alignment = textAlignment
            // Remove the indentation
            paragraphStyle.headIndent = 0
            paragraphStyle.firstLineHeadIndent = 0
            
            // Apply the default attributes
            let attributes: [NSAttributedString.Key: Any] = [
                .font: font,
                .foregroundColor: NSColor.textColor,
                .paragraphStyle: paragraphStyle
            ]
            
            // Create an attributed string
            let attributedString = NSMutableAttributedString(string: text, attributes: attributes)
            
            // Apply specific formatting for numbered lists (1. 2. 3. etc.)
            let listPattern = "\\d+\\."
            do {
                let regex = try NSRegularExpression(pattern: listPattern)
                let nsString = text as NSString
                let range = NSRange(location: 0, length: nsString.length)
                
                regex.enumerateMatches(in: text, range: range) { match, _, _ in
                    if let matchRange = match?.range {
                        // Make numbered list items bold
                        let boldFont = NSFontManager.shared.convert(font, toHaveTrait: .boldFontMask)
                        attributedString.addAttribute(.font, 
                                                     value: boldFont,
                                                     range: matchRange)
                    }
                }
            } catch {
                print("Regex error: \(error)")
            }
            
            textView.textStorage?.setAttributedString(attributedString)
        }
        
        return scrollView
    }
    
    func updateNSView(_ nsView: NSScrollView, context: Context) {
        if let textView = nsView.documentView as? NSTextView {
            // Only update if content changed to avoid losing selection
            if textView.string != text {
                // Configure paragraph style with justification
                let paragraphStyle = NSMutableParagraphStyle()
                paragraphStyle.paragraphSpacing = 1
                paragraphStyle.lineSpacing = 1
                paragraphStyle.alignment = textAlignment
                // Remove the indentation
                paragraphStyle.headIndent = 0
                paragraphStyle.firstLineHeadIndent = 0
                
                let attributes: [NSAttributedString.Key: Any] = [
                    .font: font,
                    .foregroundColor: NSColor.textColor,
                    .paragraphStyle: paragraphStyle
                ]
                
                let attributedString = NSMutableAttributedString(string: text, attributes: attributes)
                
                // Apply specific formatting for numbered lists
                let listPattern = "\\d+\\."
                do {
                    let regex = try NSRegularExpression(pattern: listPattern)
                    let nsString = text as NSString
                    let range = NSRange(location: 0, length: nsString.length)
                    
                    regex.enumerateMatches(in: text, range: range) { match, _, _ in
                        if let matchRange = match?.range {
                            let boldFont = NSFontManager.shared.convert(font, toHaveTrait: .boldFontMask)
                            attributedString.addAttribute(.font, 
                                                         value: boldFont,
                                                         range: matchRange)
                        }
                    }
                } catch {
                    print("Regex error: \(error)")
                }
                
                textView.textStorage?.setAttributedString(attributedString)
            }
        }
    }
}
