import AppKit
import PDFKit
import SwiftUI
@preconcurrency import WebKit

enum AgentTaskResultResizeIntent: String {
    case content
    case collapsed
    case expanded
    case layout
}

struct AgentTaskResultResizeRequest {
    let size: NSSize
    let intent: AgentTaskResultResizeIntent
    let minimumWidth: CGFloat?
}

/// Hosts the React-based agentTask result widget via WKWebView.
/// Handles bidirectional communication between Swift and the web layer.
@MainActor
final class AgentTaskResultWebView: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    let instanceId = UUID().uuidString
    let webView: WKWebView
    private let userContentController: WKUserContentController
    var dragAreaView: WindowDragAreaView?
    private var dragAreaHeightConstraint: NSLayoutConstraint?
    var hasReceivedReadyAck = false
    var initRetryGeneration = UUID()
    let maxInitAckRetries = 20
    var filePreviewCoordinator: NativeArtifactFilePreviewCoordinator!
    
    var onClose: (() -> Void)?
    var onMinimize: (() -> Void)?
    var onReady: (() -> Void)?
    var onResize: ((AgentTaskResultResizeRequest) -> Void)?
    var onStartFollowUpCapture: ((_ rootTaskId: String, _ previousTaskId: String?) -> Void)?
    var onStopFollowUpCapture: (() -> Void)?
    var onCancelFollowUpCapture: (() -> Void)?
    var onStartNewAgentTaskCapture: ((_ preGeneratedId: String) -> Void)?
    var onStopNewAgentTaskCapture: (() -> Void)?
    var onCancelNewAgentTaskCapture: (() -> Void)?
    var onStartRefinementRecording: (() -> Void)?
    var onStopRefinementRecording: (() -> Void)?
    var onCancelRunningAgentTask: ((_ agentTaskId: String) -> Void)?
    var onReportAgentTaskCancellationStage: ((_ agentTaskId: String, _ stage: String) -> Void)?
    var onOpenDetachedAgentTask: ((_ rootTaskId: String) -> Void)?
    var onOpenAgentTaskOrigin: ((_ originType: String, _ originId: String) -> Void)?
    var onAgentStatusChanged: ((_ agentTaskId: String?, _ isProcessing: Bool, _ hasResult: Bool, _ isTerminal: Bool, _ supportsFollowUp: Bool) -> Void)?
    var onFocusedAgentTaskCompleted: (() -> Void)?
    var onValidationRunFocused: ((AgentTaskValidationRunFocusState) -> Void)?
    var lastReportedFocusedAgentStatus: (agentTaskId: String?, isProcessing: Bool)?
    
    var initiallyProcessing: Bool = false
    var initialAgentTaskId: String?
    var initialAgentTask: String?
    var initialReferencePaths: [URL] = []
    var initialSidebarExpanded: Bool = false
    var detachedRootTaskId: String?
    var isEmbedded: Bool = false
    
    override init() {
        let configuration = WKWebViewConfiguration()
        
        configuration.preferences.setValue(true, forKey: "developerExtrasEnabled")
        configuration.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        configuration.setValue(true, forKey: "allowUniversalAccessFromFileURLs")
        
        let consoleScript = WKUserScript(
            source: """
                (function() {
                    var originalLog = console.log;
                    var originalError = console.error;
                    var originalWarn = console.warn;
                    console.log = function() {
                        window.webkit.messageHandlers.jsLog.postMessage({level: 'log', message: Array.from(arguments).join(' ')});
                        originalLog.apply(console, arguments);
                    };
                    console.error = function() {
                        window.webkit.messageHandlers.jsLog.postMessage({level: 'error', message: Array.from(arguments).join(' ')});
                        originalError.apply(console, arguments);
                    };
                    console.warn = function() {
                        window.webkit.messageHandlers.jsLog.postMessage({level: 'warn', message: Array.from(arguments).join(' ')});
                        originalWarn.apply(console, arguments);
                    };
                    window.onerror = function(msg, url, line, col, error) {
                        window.webkit.messageHandlers.jsLog.postMessage({level: 'error', message: 'JS Error: ' + msg + ' at ' + url + ':' + line + ':' + col});
                        return false;
                    };
                })();
                """,
            injectionTime: .atDocumentStart,
            forMainFrameOnly: false
        )
        configuration.userContentController.addUserScript(consoleScript)

        // Registered once, scoped to the filesystem root rather than a
        // single artifact's directory: this webview is long-lived and
        // shared across every agent task/artifact opened in this window,
        // and WebKit only allows setting a URL scheme handler before the
        // WKWebView is created -- it cannot be re-scoped per artifact the
        // way the detached AgentTaskLocalWebPreviewWindow does. This matches
        // the existing, already-unscoped native file-read path used by
        // AgentTaskFilePreviewWindow, so it is not a new security posture.
        let inlinePreviewSchemeHandler = LocalPreviewFileSchemeHandler(allowedDirectory: URL(fileURLWithPath: "/"))
        configuration.setURLSchemeHandler(inlinePreviewSchemeHandler, forURLScheme: "basil-inline-preview")

        let webView = FirstClickWebView(frame: .zero, configuration: configuration)
        self.webView = webView
        self.userContentController = configuration.userContentController
        
        super.init()
        
        let contentController = configuration.userContentController
        contentController.add(self, name: "agentTaskBridge")
        contentController.add(self, name: "jsLog")
        
        webView.navigationDelegate = self
        
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }

        filePreviewCoordinator = NativeArtifactFilePreviewCoordinator(
            emit: { [weak self] name, payload in
                self?.callJS("window.basilAgentTask.\(name)", args: payload)
            },
            hostView: { [weak self] in self?.webView ?? NSView() }
        )

        // Funnel native file drops through the same JS callback the file
        // picker uses (``window.basilAgentTask.onFilesPicked``). Both the
        // ScheduledAgentTaskDetail Attached Files editor and TextFollowUp
        // already register handlers on that channel, so this single wiring
        // makes drag-and-drop work in every drop-target React surface
        // without needing per-component bridge plumbing.
        webView.onFilesDropped = { [weak self] paths in
            self?.callJS("window.basilAgentTask.onFilesPicked", args: paths)
        }
    }
    
    func installDragArea() {
        // 44 is only a pre-layout fallback (matches the CSS `.widget-header`
        // height once fonts/theme are applied). ``updateDragAreaHeight`` below
        // corrects it once React measures and reports the real header height,
        // mirroring how AgentTaskFilePreviewWindow's `chromeHeight` is
        // corrected via `reportFilePreviewChromeHeight`. Without this
        // correction, a header shorter than 44 on first paint lets the
        // drag strip's bottom edge bleed into the sidebar's own header row,
        // where a mousedown starts a native window drag instead of reaching
        // the sidebar toggle button's click handler.
        let headerHeight: CGFloat = 44
        let dragView = WindowDragAreaView()
        dragView.translatesAutoresizingMaskIntoConstraints = false
        webView.addSubview(dragView)
        let heightConstraint = dragView.heightAnchor.constraint(equalToConstant: headerHeight)
        NSLayoutConstraint.activate([
            dragView.topAnchor.constraint(equalTo: webView.topAnchor),
            dragView.leadingAnchor.constraint(equalTo: webView.leadingAnchor),
            dragView.trailingAnchor.constraint(equalTo: webView.trailingAnchor),
            heightConstraint,
        ])
        self.dragAreaView = dragView
        self.dragAreaHeightConstraint = heightConstraint
    }

    /// Invoked when React reports the real, laid-out height of
    /// `.widget-header` via the `widgetHeaderHeight` bridge message.
    func updateDragAreaHeight(_ height: CGFloat) {
        guard height > 0, dragAreaHeightConstraint?.constant != height else { return }
        dragAreaHeightConstraint?.constant = height
    }
    
    func prepareEmbeddedPresentation() {
        isEmbedded = true
        userContentController.addUserScript(WKUserScript(
            source: "document.documentElement.dataset.agentTaskEmbedded = 'true';",
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        ))
    }

    func loadContent() {
        guard let resourceURL = Bundle.main.resourceURL else {
            #if DEBUG
            DevLogger.shared.error("[AgentTaskResultWebView] Could not get bundle resource URL", context: "AgentTaskCapture")
            #endif
            return
        }
        
        let webAssetsFolder = resourceURL.appendingPathComponent("AgentTaskWebAssets")
        let htmlURL = webAssetsFolder.appendingPathComponent("src/entries/agent-task-result.html")
        
        #if DEBUG
        DevLogger.shared.info("[AgentTaskResultWebView \(instanceId)] Loading HTML from: \(htmlURL.path)", context: "AgentTaskCapture")
        #endif
        
        if FileManager.default.fileExists(atPath: htmlURL.path) {
            webView.loadFileURL(htmlURL, allowingReadAccessTo: webAssetsFolder)
        } else {
            #if DEBUG
            DevLogger.shared.error("[AgentTaskResultWebView \(instanceId)] HTML file NOT found at: \(htmlURL.path)", context: "AgentTaskCapture")
            #endif
        }
    }

    func tearDown() {
        filePreviewCoordinator.tearDown()
        initRetryGeneration = UUID()
        hasReceivedReadyAck = true
        webView.navigationDelegate = nil
        userContentController.removeScriptMessageHandler(forName: "agentTaskBridge")
        userContentController.removeScriptMessageHandler(forName: "jsLog")
    }
}
