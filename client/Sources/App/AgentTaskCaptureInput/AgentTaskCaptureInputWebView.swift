import AppKit
import WebKit
import UniformTypeIdentifiers

/// WKWebView host for the React Agent Task capture input surface. Mirrors
/// `AgentTaskResultWebView`'s shape (staged-resource loading, FirstClickWebView,
/// jsLog console forwarding, a dedicated message-handler name) at the smaller
/// scale of the capture widget.
@MainActor
final class AgentTaskCaptureInputWebView: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    let instanceId = UUID().uuidString
    let webView: DropTargetWebView
    private let userContentController: WKUserContentController
    var dragAreaView: WindowDragAreaView?
    var dragAreaHeightConstraint: NSLayoutConstraint?

    var isPageLoaded = false
    var isReactReady = false

    /// Fired once the page signals `captureInputReady`. The window controller
    /// uses this to send the first `CaptureInitMessage`.
    var onReactReady: (() -> Void)?
    /// Forwarded intents. The window controller assigns this and dispatches
    /// on `CaptureInputMessage` cases.
    var onMessage: ((CaptureInputMessage) -> Void)?
    /// Absolute paths recovered from the system pasteboard on drop — see
    /// `DropTargetWebView`'s doc comment. Showing/hiding the "Drop files
    /// here" overlay is handled entirely on the React side (`App.tsx`,
    /// mirroring `TextFollowUp.tsx`) via plain DOM drag events; this webview
    /// only needs to supply the paths JS can't read itself.
    var onFilesDropped: (([URL]) -> Void)?

    override init() {
        let configuration = WKWebViewConfiguration()
        configuration.preferences.setValue(true, forKey: "developerExtrasEnabled")
        configuration.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        configuration.setValue(true, forKey: "allowUniversalAccessFromFileURLs")

        let consoleScript = WKUserScript(
            source: """
            (function() {
                const forward = (level) => (...args) => {
                    window.webkit.messageHandlers.jsLog.postMessage({ level, args: args.map(String) });
                };
                console.log = forward('log');
                console.warn = forward('warn');
                console.error = forward('error');
            })();
            """,
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        )
        configuration.userContentController.addUserScript(consoleScript)
        configuration.userContentController.addUserScript(WKUserScript(
            source: "document.documentElement.dataset.agentTaskCaptureEmbedded = 'true';",
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        ))

        let webView = DropTargetWebView(frame: .zero, configuration: configuration)
        self.webView = webView
        self.userContentController = configuration.userContentController

        super.init()

        webView.navigationDelegate = self
        webView.onFilesDropped = { [weak self] paths in
            self?.onFilesDropped?(paths.map { URL(fileURLWithPath: $0) })
        }

        userContentController.add(AgentTaskCaptureWeakScriptMessageHandler(self), name: "agentTaskCaptureBridge")
        userContentController.add(AgentTaskCaptureWeakScriptMessageHandler(self), name: "jsLog")

        webView.wantsLayer = true
        webView.layer?.backgroundColor = NSColor.clear.cgColor
        webView.setValue(false, forKey: "drawsBackground")
    }

    func tearDown() {
        userContentController.removeScriptMessageHandler(forName: "agentTaskCaptureBridge")
        userContentController.removeScriptMessageHandler(forName: "jsLog")
        webView.navigationDelegate = nil
        webView.onFilesDropped = nil
        onReactReady = nil
        onMessage = nil
        onFilesDropped = nil
    }

    // MARK: - WKNavigationDelegate

    nonisolated func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        Task { @MainActor in
            isPageLoaded = true
            installDragArea()
        }
    }
}

private final class AgentTaskCaptureWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: AgentTaskCaptureInputWebView?

    init(_ target: AgentTaskCaptureInputWebView) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.userContentController(userContentController, didReceive: message)
    }
}

/// `FirstClickWebView.performDragOperation` (in
/// `AgentTaskResultWebViewSupportViews.swift`) already reads dropped
/// filesystem paths off the pasteboard, calls `onFilesDropped`, and always
/// falls through to `super` so WebKit still dispatches a real JS `drop`
/// event — exactly what this widget needs too. This subclass adds nothing;
/// it exists only as a named type for call sites and the drop-target test
/// below.
///
/// Two things this widget must *not* re-add, learned the hard way tonight:
///   - Calling `registerForDraggedTypes` again on this view (even with only
///     `.fileURL`) replaces `WKWebView`'s own broader internal drag-type
///     registration, which changes which internal WebKit code path handles
///     the drag session and reintroduces the "only the first drop of the
///     app's run ever registers" bug. `FirstClickWebView` never calls
///     `registerForDraggedTypes` itself and does not need to — WKWebView is
///     already registered for file drags by default.
///   - A separate `NSView` overlay in front of the webview to intercept
///     `draggingEntered`/`Updated`/`Exited` for showing a "Drop files here"
///     highlight. The highlight is React's job — see `App.tsx`, which
///     mirrors `TextFollowUp.tsx`'s plain `dragover`/`dragleave`/`drop` DOM
///     event handling — and an overlay's mouse-forwarding dance to keep
///     clicks working on the real page underneath is unnecessary complexity
///     that risked (and, per manual testing, caused) dead click zones on
///     header buttons.
final class DropTargetWebView: FirstClickWebView {
    static func fileURLs(from pasteboard: NSPasteboard) -> [URL] {
        guard pasteboard.types?.contains(.fileURL) == true else { return [] }
        return pasteboard.readObjects(forClasses: [NSURL.self], options: nil) as? [URL] ?? []
    }
}
