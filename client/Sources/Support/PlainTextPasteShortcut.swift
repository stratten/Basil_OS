import AppKit
import Foundation
@preconcurrency import WebKit

@MainActor
final class PlainTextPasteShortcutMonitor {
    private var eventMonitor: Any?

    init() {
        start()
    }

    func start() {
        guard eventMonitor == nil else { return }
        eventMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            self?.handleKeyDown(event) ?? event
        }
    }

    func stop() {
        if let eventMonitor {
            NSEvent.removeMonitor(eventMonitor)
            self.eventMonitor = nil
        }
    }

    static func isPlainTextPasteShortcut(_ event: NSEvent) -> Bool {
        let shortcutModifiers = event.modifierFlags.intersection([.command, .shift, .option, .control])
        return shortcutModifiers == [.command, .shift]
            && event.charactersIgnoringModifiers?.lowercased() == "v"
    }

    static func editableTextView(for responder: NSResponder?) -> NSTextView? {
        guard let textView = responder as? NSTextView, textView.isEditable else {
            return nil
        }
        return textView
    }

    /// Walks the responder's view hierarchy to find the enclosing ``WKWebView``.
    /// WKWebView's actual first responder on macOS is a private content view
    /// nested inside it, so matching `responder as? WKWebView` directly never
    /// succeeds -- the ancestor chain must be walked instead.
    static func enclosingWebView(for responder: NSResponder?) -> WKWebView? {
        var current = responder as? NSView
        while let node = current {
            if let webView = node as? WKWebView {
                return webView
            }
            current = node.superview
        }
        return nil
    }

    /// Sends the pasteboard's plain-text string to the shared rich-editor
    /// bridge installed by ``PlainTextPasteWebSupport``. The bridge decides
    /// whether the currently focused element qualifies (see
    /// ``PlainTextPasteWebSupport/scriptSource``), so this call is safe to
    /// make unconditionally whenever a WKWebView holds keyboard focus. The
    /// `completion` parameter exists only so tests can synchronize on the
    /// asynchronous `evaluateJavaScript` round trip; production call sites
    /// intentionally fire-and-forget by leaving it `nil`.
    static func insertPlainText(
        _ text: String,
        into webView: WKWebView,
        completion: ((Bool) -> Void)? = nil
    ) {
        guard let payload = try? JSONEncoder().encode(text),
              let encodedText = String(data: payload, encoding: .utf8) else {
            completion?(false)
            return
        }
        webView.evaluateJavaScript(
            "window.__basilPlainTextPaste && window.__basilPlainTextPaste.insert(\(encodedText));"
        ) { result, _ in
            completion?(result as? Bool ?? false)
        }
    }

    private func handleKeyDown(_ event: NSEvent) -> NSEvent? {
        guard Self.isPlainTextPasteShortcut(event) else { return event }
        let responder = NSApp.keyWindow?.firstResponder

        if let textView = Self.editableTextView(for: responder) {
            textView.pasteAsPlainText(nil)
            return nil
        }

        if let webView = Self.enclosingWebView(for: responder),
           let plainText = NSPasteboard.general.string(forType: .string) {
            Self.insertPlainText(plainText, into: webView)
        }

        return event
    }
}

/// Installs the DOM-side half of the plain-text-paste bridge. The native
/// ``PlainTextPasteShortcutMonitor`` owns the keyboard shortcut and the
/// system pasteboard; this script exposes an insertion primitive that operates
/// on whatever element currently has focus. Its only shortcut listener
/// prevents WebKit's normal paste for a matching rich editor, so the
/// asynchronous native insertion cannot race or duplicate the browser's
/// default insertion. It does not listen for `keyup` or `paste`, and it never
/// reads `navigator.clipboard` -- both were the source of the shortcut's prior
/// unreliability (silently-rejected clipboard-read permission and a
/// keydown/keyup timing race in WKWebView).
///
/// The insertion primitive only acts on elements matching
/// `.rich-text-composer-editor`, the class every editor rendered by the
/// shared `RichTextComposer` React component carries
/// (`web-components/shared/RichTextComposer.tsx`). Plain
/// `<input>`/`<textarea>` fields, and any contenteditable surface that does
/// not use `RichTextComposer`, are left to WebKit's normal paste behavior --
/// those legacy contenteditable surfaces are being migrated onto
/// `RichTextComposer` over time and will pick up this behavior automatically
/// once they do, without further native changes.
enum PlainTextPasteWebSupport {
    static func install(in contentController: WKUserContentController) {
        contentController.addUserScript(
            WKUserScript(
                source: scriptSource,
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            )
        )
    }

    static let scriptSource = """
        (function() {
            if (window.__basilPlainTextPasteInstalled) return;
            window.__basilPlainTextPasteInstalled = true;

            function activeRichTextComposerEditor() {
                var active = document.activeElement;
                var target = active instanceof Element ? active.closest('.rich-text-composer-editor') : null;
                if (!target || target.hasAttribute('disabled') || !target.isContentEditable) return null;
                return target;
            }

            function dispatchInput(target, text) {
                try {
                    target.dispatchEvent(new InputEvent('input', {
                        bubbles: true,
                        composed: true,
                        data: text,
                        inputType: 'insertFromPaste'
                    }));
                } catch (_) {
                    target.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
                }
            }

            window.__basilPlainTextPaste = {
                insert: function(text) {
                    if (typeof text !== 'string' || text.length === 0) return false;
                    var target = activeRichTextComposerEditor();
                    if (!target) return false;

                    var selection = window.getSelection();
                    var range = null;
                    if (selection && selection.rangeCount > 0 && target.contains(selection.anchorNode)) {
                        range = selection.getRangeAt(0);
                    }
                    if (!range) {
                        range = document.createRange();
                        range.selectNodeContents(target);
                        range.collapse(false);
                    }
                    range.deleteContents();
                    var textNode = document.createTextNode(text);
                    range.insertNode(textNode);
                    range.setStartAfter(textNode);
                    range.collapse(true);
                    if (selection) {
                        selection.removeAllRanges();
                        selection.addRange(range);
                    }
                    dispatchInput(target, text);
                    return true;
                }
            };

            document.addEventListener('keydown', function(event) {
                if (
                    event.metaKey
                    && event.shiftKey
                    && !event.altKey
                    && !event.ctrlKey
                    && event.key.toLowerCase() === 'v'
                    && activeRichTextComposerEditor()
                ) {
                    event.preventDefault();
                }
            }, true);
        })();
        """
}
