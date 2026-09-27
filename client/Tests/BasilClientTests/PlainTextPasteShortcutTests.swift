import AppKit
import WebKit
import XCTest
@testable import BasilClient

@MainActor
final class PlainTextPasteShortcutTests: XCTestCase {
    func testRecognizesCommandShiftV() {
        XCTAssertTrue(
            PlainTextPasteShortcutMonitor.isPlainTextPasteShortcut(
                keyEvent(characters: "v", modifiers: [.command, .shift])
            )
        )
    }

    func testRejectsPlainPasteAndAdditionalModifiers() {
        XCTAssertFalse(
            PlainTextPasteShortcutMonitor.isPlainTextPasteShortcut(
                keyEvent(characters: "v", modifiers: [.command])
            )
        )
        XCTAssertFalse(
            PlainTextPasteShortcutMonitor.isPlainTextPasteShortcut(
                keyEvent(characters: "v", modifiers: [.command, .shift, .option])
            )
        )
        XCTAssertFalse(
            PlainTextPasteShortcutMonitor.isPlainTextPasteShortcut(
                keyEvent(characters: "c", modifiers: [.command, .shift])
            )
        )
    }

    func testReturnsOnlyEditableTextViewResponders() {
        let editableTextView = NSTextView()
        editableTextView.isEditable = true
        XCTAssertTrue(
            PlainTextPasteShortcutMonitor.editableTextView(for: editableTextView) === editableTextView
        )

        editableTextView.isEditable = false
        XCTAssertNil(PlainTextPasteShortcutMonitor.editableTextView(for: editableTextView))
        XCTAssertNil(PlainTextPasteShortcutMonitor.editableTextView(for: NSView()))
    }

    func testWebBridgeInsertsIntoRichTextComposerEditorOnly() {
        let contentController = WKUserContentController()
        PlainTextPasteWebSupport.install(in: contentController)
        let configuration = WKWebViewConfiguration()
        configuration.userContentController = contentController

        let webView = WKWebView(frame: .zero, configuration: configuration)
        let loadDelegate = WebViewLoadDelegate()
        let pageLoaded = expectation(description: "WebKit test page loads")
        loadDelegate.didFinish = {
            pageLoaded.fulfill()
        }
        webView.navigationDelegate = loadDelegate
        webView.loadHTMLString(
            """
            <input id="plain-input" value="existing">
            <div id="rich-editor" class="rich-text-composer-editor" contenteditable="true"><strong>existing</strong></div>
            <div id="legacy-editor" contenteditable="true">legacy</div>
            <div id="disabled-rich-editor" class="rich-text-composer-editor" contenteditable="false">disabled</div>
            """,
            baseURL: nil
        )
        wait(for: [pageLoaded], timeout: 5)

        let richEditorResult = evaluateJavaScript(
            """
            (function() {
                var editor = document.getElementById('rich-editor');
                var inputEvents = 0;
                editor.addEventListener('input', function() { inputEvents += 1; });
                editor.focus();
                var range = document.createRange();
                range.selectNodeContents(editor);
                var selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
                var handled = window.__basilPlainTextPaste.insert('plain text');
                return JSON.stringify({
                    handled: handled,
                    text: editor.textContent,
                    html: editor.innerHTML,
                    inputEvents: inputEvents
                });
            })()
            """,
            in: webView
        ) as? String
        XCTAssertEqual(
            richEditorResult,
            "{\"handled\":true,\"text\":\"plain text\",\"html\":\"plain text\",\"inputEvents\":1}"
        )

        let plainInputResult = evaluateJavaScript(
            """
            (function() {
                var input = document.getElementById('plain-input');
                input.focus();
                var handled = window.__basilPlainTextPaste.insert('ignored');
                return JSON.stringify({ handled: handled, value: input.value });
            })()
            """,
            in: webView
        ) as? String
        XCTAssertEqual(plainInputResult, "{\"handled\":false,\"value\":\"existing\"}")

        let legacyEditorResult = evaluateJavaScript(
            """
            (function() {
                var editor = document.getElementById('legacy-editor');
                editor.focus();
                var handled = window.__basilPlainTextPaste.insert('ignored');
                return JSON.stringify({ handled: handled, text: editor.textContent });
            })()
            """,
            in: webView
        ) as? String
        XCTAssertEqual(legacyEditorResult, "{\"handled\":false,\"text\":\"legacy\"}")

        let disabledRichEditorResult = evaluateJavaScript(
            """
            (function() {
                var editor = document.getElementById('disabled-rich-editor');
                editor.focus();
                var handled = window.__basilPlainTextPaste.insert('ignored');
                return JSON.stringify({ handled: handled, text: editor.textContent });
            })()
            """,
            in: webView
        ) as? String
        XCTAssertEqual(disabledRichEditorResult, "{\"handled\":false,\"text\":\"disabled\"}")

        let shortcutDefaultResults = evaluateJavaScript(
            """
            (function() {
                function shortcutDefaultAllowed(id) {
                    var element = document.getElementById(id);
                    element.focus();
                    return element.dispatchEvent(new KeyboardEvent('keydown', {
                        bubbles: true,
                        cancelable: true,
                        key: 'v',
                        metaKey: true,
                        shiftKey: true
                    }));
                }
                return JSON.stringify({
                    rich: shortcutDefaultAllowed('rich-editor'),
                    plainInput: shortcutDefaultAllowed('plain-input'),
                    legacy: shortcutDefaultAllowed('legacy-editor'),
                    disabledRich: shortcutDefaultAllowed('disabled-rich-editor')
                });
            })()
            """,
            in: webView
        ) as? String
        XCTAssertEqual(
            shortcutDefaultResults,
            "{\"rich\":false,\"plainInput\":true,\"legacy\":true,\"disabledRich\":true}"
        )
    }

    func testWebBridgeRejectsEmptyOrNonStringInput() {
        let contentController = WKUserContentController()
        PlainTextPasteWebSupport.install(in: contentController)
        let configuration = WKWebViewConfiguration()
        configuration.userContentController = contentController

        let webView = WKWebView(frame: .zero, configuration: configuration)
        let loadDelegate = WebViewLoadDelegate()
        let pageLoaded = expectation(description: "WebKit test page loads")
        loadDelegate.didFinish = {
            pageLoaded.fulfill()
        }
        webView.navigationDelegate = loadDelegate
        webView.loadHTMLString(
            """
            <div id="rich-editor" class="rich-text-composer-editor" contenteditable="true">existing</div>
            """,
            baseURL: nil
        )
        wait(for: [pageLoaded], timeout: 5)

        let emptyStringResult = evaluateJavaScript(
            """
            (function() {
                document.getElementById('rich-editor').focus();
                return window.__basilPlainTextPaste.insert('');
            })()
            """,
            in: webView
        ) as? Bool
        XCTAssertEqual(emptyStringResult, false)

        let nonStringResult = evaluateJavaScript(
            """
            (function() {
                document.getElementById('rich-editor').focus();
                return window.__basilPlainTextPaste.insert(null);
            })()
            """,
            in: webView
        ) as? Bool
        XCTAssertEqual(nonStringResult, false)
    }

    func testEnclosingWebViewWalksResponderHierarchyToTheWebView() {
        let webView = WKWebView(frame: NSRect(x: 0, y: 0, width: 200, height: 200))
        let nestedResponderView = NSView(frame: NSRect(x: 0, y: 0, width: 50, height: 50))
        webView.addSubview(nestedResponderView)

        XCTAssertTrue(
            PlainTextPasteShortcutMonitor.enclosingWebView(for: nestedResponderView) === webView
        )
        XCTAssertTrue(
            PlainTextPasteShortcutMonitor.enclosingWebView(for: webView) === webView
        )
        XCTAssertNil(PlainTextPasteShortcutMonitor.enclosingWebView(for: NSView()))
        XCTAssertNil(PlainTextPasteShortcutMonitor.enclosingWebView(for: NSTextView()))
        XCTAssertNil(PlainTextPasteShortcutMonitor.enclosingWebView(for: nil))
    }

    func testInsertPlainTextEscapesSpecialCharactersSafely() {
        let contentController = WKUserContentController()
        PlainTextPasteWebSupport.install(in: contentController)
        let configuration = WKWebViewConfiguration()
        configuration.userContentController = contentController

        let webView = WKWebView(frame: .zero, configuration: configuration)
        let loadDelegate = WebViewLoadDelegate()
        let pageLoaded = expectation(description: "WebKit test page loads")
        loadDelegate.didFinish = {
            pageLoaded.fulfill()
        }
        webView.navigationDelegate = loadDelegate
        webView.loadHTMLString(
            """
            <div id="rich-editor" class="rich-text-composer-editor" contenteditable="true"></div>
            """,
            baseURL: nil
        )
        wait(for: [pageLoaded], timeout: 5)

        _ = evaluateJavaScript("document.getElementById('rich-editor').focus();", in: webView)

        let specialText = "quote \" backslash \\ newline\nend"
        let insertionFinished = expectation(description: "insertPlainText completes")
        var handled = false
        PlainTextPasteShortcutMonitor.insertPlainText(specialText, into: webView) { result in
            handled = result
            insertionFinished.fulfill()
        }
        wait(for: [insertionFinished], timeout: 5)
        XCTAssertTrue(handled)

        let insertedText = evaluateJavaScript(
            "document.getElementById('rich-editor').textContent",
            in: webView
        ) as? String
        XCTAssertEqual(insertedText, specialText)
    }

    private func evaluateJavaScript(_ script: String, in webView: WKWebView) -> Any? {
        let evaluationFinished = expectation(description: "JavaScript evaluation completes")
        var result: Any?
        var evaluationError: Error?
        webView.evaluateJavaScript(script) { value, error in
            result = value
            evaluationError = error
            evaluationFinished.fulfill()
        }
        wait(for: [evaluationFinished], timeout: 5)
        XCTAssertNil(evaluationError)
        return result
    }

    private func keyEvent(
        characters: String,
        modifiers: NSEvent.ModifierFlags
    ) -> NSEvent {
        guard let event = NSEvent.keyEvent(
            with: .keyDown,
            location: .zero,
            modifierFlags: modifiers,
            timestamp: 0,
            windowNumber: 0,
            context: nil,
            characters: characters,
            charactersIgnoringModifiers: characters.lowercased(),
            isARepeat: false,
            keyCode: 9
        ) else {
            XCTFail("Could not construct a keyboard event.")
            fatalError("Could not construct a keyboard event.")
        }
        return event
    }
}

private final class WebViewLoadDelegate: NSObject, WKNavigationDelegate {
    var didFinish: (() -> Void)?

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        didFinish?()
    }
}
