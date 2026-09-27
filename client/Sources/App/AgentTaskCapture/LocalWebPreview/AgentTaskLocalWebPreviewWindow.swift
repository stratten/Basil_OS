import AppKit
import SwiftUI
@preconcurrency import WebKit

@MainActor
final class AgentTaskLocalWebPreviewWindowController {
    static let shared = AgentTaskLocalWebPreviewWindowController()

    private var hosts: [AgentTaskLocalWebPreviewWindowHost] = []

    func open(
        mode: String,
        targetUrl: String,
        artifactId: String,
        agentTaskId: String,
        rootTaskId: String? = nil,
        canonicalPath: String? = nil,
        sessionId: String?,
        displayName: String? = nil
    ) {
        _ = openHost(
            mode: mode,
            targetUrl: targetUrl,
            artifactId: artifactId,
            agentTaskId: agentTaskId,
            rootTaskId: rootTaskId,
            canonicalPath: canonicalPath,
            sessionId: sessionId,
            displayName: displayName
        )
    }

    func submitValidationHTMLPreviewFeedback() {
        guard let sessionRoot = BasilRuntimeProfile.sessionRootURL else {
            presentValidationAlert("The validation session is unavailable.")
            return
        }
        let htmlURL = sessionRoot
            .appendingPathComponent("fixtures/documents/report.html")
            .standardizedFileURL
        guard FileManager.default.fileExists(atPath: htmlURL.path) else {
            presentValidationAlert("The HTML validation fixture is unavailable.")
            return
        }
        let host = openHost(
            mode: "static",
            targetUrl: htmlURL.absoluteString,
            artifactId: "validation-report",
            agentTaskId: "validation-html-live",
            sessionId: nil,
            displayName: "report.html"
        )
        host.submitValidationFeedback(
            "Validate the current rendered HTML state and retain the automatic screenshot as reference."
        )
    }

    /// Closes the most recently opened preview window. Exists only for the
    /// isolated accessibility validation suite: the window is `.borderless`
    /// with no titlebar close button (matching AgentTaskFilePreviewWindow),
    /// so its only real close path is the React-rendered "closeWidget"
    /// bridge message inside the WKWebView -- content that WebKit does not
    /// reliably expose to System Events' accessibility traversal in this
    /// app. This mirrors that same `window.close()` call without depending
    /// on AX-tree access into web content.
    func closeMostRecentValidationPreviewWindow() {
        hosts.last?.closeWindowForValidation()
    }

    func openValidationLocalServerPreview() {
        guard let sessionRoot = BasilRuntimeProfile.sessionRootURL else {
            presentValidationAlert("The validation session is unavailable.")
            return
        }
        let projectURL = sessionRoot
            .appendingPathComponent("fixtures/documents/local-preview")
            .standardizedFileURL
        let htmlURL = projectURL.appendingPathComponent("index.html")
        let serverURL = projectURL.appendingPathComponent("server.py")
        guard FileManager.default.fileExists(atPath: htmlURL.path),
              FileManager.default.fileExists(atPath: serverURL.path) else {
            presentValidationAlert("The local-server validation fixture is unavailable.")
            return
        }
        let host = openHost(
            mode: "devServer",
            targetUrl: htmlURL.absoluteString,
            artifactId: "validation-index",
            agentTaskId: "validation-local-preview",
            sessionId: nil,
            displayName: "index.html"
        )
        host.startValidationServer(
            command: "python3",
            args: ["server.py", "--host", "127.0.0.1", "--port", "43123"],
            cwd: projectURL.path,
            port: 43123
        )
    }

    /// Submits feedback against the most recently opened devServer-mode
    /// preview window rather than opening a fresh static host, matching how
    /// submitValidationHTMLPreviewFeedback() targets the static fixture --
    /// this proves acceptance step 6 (feedback against the server-preview
    /// fixture specifically, not just the static one).
    func submitValidationLocalServerPreviewFeedback() {
        guard let host = hosts.last(where: { $0.mode == "devServer" }) else {
            presentValidationAlert("No local-server preview window is open.")
            return
        }
        host.submitValidationFeedback(
            "Validate the current server-preview lifecycle state and retain the automatic screenshot as reference."
        )
    }

    private func openHost(
        mode: String,
        targetUrl: String,
        artifactId: String,
        agentTaskId: String,
        rootTaskId: String? = nil,
        canonicalPath: String? = nil,
        sessionId: String?,
        displayName: String?
    ) -> AgentTaskLocalWebPreviewWindowHost {
        let host = AgentTaskLocalWebPreviewWindowHost(
            mode: mode,
            targetUrl: targetUrl,
            artifactId: artifactId,
            agentTaskId: agentTaskId,
            rootTaskId: rootTaskId,
            canonicalPath: canonicalPath,
            sessionId: sessionId,
            displayName: displayName
        )
        host.onClose = { [weak self, weak host] in
            guard let host else { return }
            self?.hosts.removeAll { $0 === host }
        }
        hosts.append(host)
        host.show()
        return host
    }

    private func presentValidationAlert(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Validation fixture unavailable"
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }
}

@MainActor
private final class AgentTaskLocalWebPreviewWindowHost: NSObject, WKScriptMessageHandler, WKNavigationDelegate, NSWindowDelegate {
    let mode: String
    private let targetUrl: String
    private let previewContentUrl: String?
    private let artifactId: String
    private let agentTaskId: String
    private let rootTaskId: String?
    private let canonicalPath: String?
    private let sessionId: String?
    private var activeSessionId: String?
    private var lastDeniedError: String?
    private let displayName: String?
    private let webView: WKWebView
    private let fileSchemeHandler: LocalPreviewFileSchemeHandler?
    private var dragAreaView: FilePreviewDragAreaView?
    private var window: NSWindow?
    private var appShellURL: URL?
    private var keyboardShortcuts: WindowKeyboardShortcuts?
    private var hasReceivedInitAck = false
    private let maxInitAttempts = 240
    private var consoleEvidenceTail = ""
    private let maxConsoleEvidenceChars = 8_000
    private var consoleEvidenceMessageCount = 0
    private let maxConsoleEvidenceMessages = 200
    private var pendingValidationActions: [() -> Void] = []
    private var lastValidationScreenshotPath: String?

    var onClose: (() -> Void)?

    init(
        mode: String,
        targetUrl: String,
        artifactId: String,
        agentTaskId: String,
        rootTaskId: String? = nil,
        canonicalPath: String? = nil,
        sessionId: String?,
        displayName: String?
    ) {
        self.mode = mode
        self.targetUrl = targetUrl
        let sourceURL = URL(string: targetUrl)
        if mode == "static", let sourceURL, sourceURL.isFileURL {
            let directory = sourceURL.deletingLastPathComponent()
            let filename = sourceURL.lastPathComponent.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed)
                ?? sourceURL.lastPathComponent
            self.previewContentUrl = "basil-preview-file://preview/\(filename)"
            self.fileSchemeHandler = LocalPreviewFileSchemeHandler(allowedDirectory: directory)
        } else {
            self.previewContentUrl = nil
            self.fileSchemeHandler = nil
        }
        self.artifactId = artifactId
        self.agentTaskId = agentTaskId
        self.rootTaskId = rootTaskId
        self.canonicalPath = canonicalPath
        self.sessionId = sessionId
        self.activeSessionId = sessionId
        self.displayName = displayName

        let configuration = WKWebViewConfiguration()
        configuration.preferences.setValue(true, forKey: "developerExtrasEnabled")
        configuration.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        configuration.setValue(true, forKey: "allowUniversalAccessFromFileURLs")
        if let fileSchemeHandler {
            configuration.setURLSchemeHandler(fileSchemeHandler, forURLScheme: "basil-preview-file")
        }

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
                    window.addEventListener('error', function(event) {
                        var target = event.target;
                        if (target && (target.tagName === 'SCRIPT' || target.tagName === 'LINK')) {
                            window.webkit.messageHandlers.jsLog.postMessage({
                                level: 'error',
                                message: 'Resource load failed: ' + (target.src || target.href || '<unknown resource>')
                            });
                        }
                    }, true);
                    window.addEventListener('unhandledrejection', function(event) {
                        var reason = event.reason && event.reason.stack ? event.reason.stack : String(event.reason);
                        window.webkit.messageHandlers.jsLog.postMessage({
                            level: 'error',
                            message: 'Unhandled promise rejection: ' + reason
                        });
                    });
                    if (window.top === window) {
                        var bootLocalPreviewModule = function() {
                            var moduleScript = document.querySelector('script[type="module"]');
                            if (!moduleScript || !moduleScript.src) return false;
                            import(moduleScript.src)
                                .then(function() {
                                    window.webkit.messageHandlers.localWebPreviewBridge.postMessage({
                                        type: 'rendererReady'
                                    });
                                })
                                .catch(function(error) {
                                    window.webkit.messageHandlers.jsLog.postMessage({
                                        level: 'error',
                                        message: 'Local preview module bootstrap failed: ' + (error && error.stack ? error.stack : String(error))
                                    });
                                });
                            return true;
                        };
                        if (!bootLocalPreviewModule()) {
                            new MutationObserver(function() {
                                if (bootLocalPreviewModule()) this.disconnect();
                            }).observe(document, {childList: true, subtree: true});
                        }
                    }
                })();
                """,
            injectionTime: .atDocumentStart,
            forMainFrameOnly: false
        )
        configuration.userContentController.addUserScript(consoleScript)

        let webView = FirstClickWebView(frame: .zero, configuration: configuration)
        self.webView = webView

        super.init()

        if #available(macOS 13.3, *) {
            webView.isInspectable = validationEvidenceURL() != nil
        }

        let contentController = configuration.userContentController
        contentController.add(self, name: "localWebPreviewBridge")
        contentController.add(self, name: "jsLog")

        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }
    }

    func show() {
        let window = CustomBorderlessWindow(
            contentRect: NSRect(x: 0, y: 0, width: 960, height: 720),
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = displayName ?? URL(string: targetUrl)?.lastPathComponent ?? "Local Web Preview"
        window.minSize = NSSize(width: 480, height: 360)
        window.isReleasedWhenClosed = false
        window.level = .floating
        window.collectionBehavior = [
            .canJoinAllSpaces,
            .fullScreenAuxiliary,
            .ignoresCycle
        ]
        window.hidesOnDeactivate = false
        window.alphaValue = 1.0
        window.isMovableByWindowBackground = true
        window.contentView = webView
        WebKitWindowChromeAppearance.apply(to: window)
        window.delegate = self
        window.center()
        keyboardShortcuts = WindowKeyboardShortcuts(window: window)

        self.window = window
        installDragArea()
        loadContent()
        window.makeKeyAndOrderFront(nil)
    }

    private func installDragArea() {
        let headerHeight: CGFloat = 54
        let dragView = FilePreviewDragAreaView()
        dragView.translatesAutoresizingMaskIntoConstraints = false
        webView.addSubview(dragView)
        NSLayoutConstraint.activate([
            dragView.topAnchor.constraint(equalTo: webView.topAnchor),
            dragView.leadingAnchor.constraint(equalTo: webView.leadingAnchor),
            dragView.trailingAnchor.constraint(equalTo: webView.trailingAnchor),
            dragView.heightAnchor.constraint(equalToConstant: headerHeight),
        ])
        self.dragAreaView = dragView
    }

    private func loadContent() {
        guard let resourceURL = Bundle.main.resourceURL else { return }
        let webAssetsFolder = resourceURL.appendingPathComponent("AgentTaskWebAssets")
        let htmlURL = webAssetsFolder.appendingPathComponent("src/entries/local-web-preview.html")
        if FileManager.default.fileExists(atPath: htmlURL.path) {
            appShellURL = htmlURL.standardizedFileURL
            webView.loadFileURL(htmlURL, allowingReadAccessTo: webAssetsFolder)
        }
    }

    private func sendInitWithRetry(attempt: Int) {
        guard !hasReceivedInitAck else { return }
        guard attempt < maxInitAttempts else { return }
        sendInit()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
            self?.sendInitWithRetry(attempt: attempt + 1)
        }
    }

    private func sendInit() {
        var config: [String: Any] = [
            "mode": mode,
            "targetUrl": targetUrl,
            "artifactId": artifactId,
            "agentTaskId": agentTaskId,
            "theme": currentThemePayload(),
            "fonts": currentFontPayload(),
        ]
        if let rootTaskId, !rootTaskId.isEmpty {
            config["rootTaskId"] = rootTaskId
        }
        if let canonicalPath, !canonicalPath.isEmpty {
            config["canonicalPath"] = canonicalPath
        }
        if let displayName, !displayName.isEmpty {
            config["displayName"] = displayName
        }
        if let sessionId, !sessionId.isEmpty {
            config["sessionId"] = sessionId
        }
        if let previewContentUrl {
            config["previewContentUrl"] = previewContentUrl
        }
        let port = APIClient.shared.currentPort
        config["port"] = port
        config["wsUrl"] = "ws://localhost:\(port)/ws"
        callJS("window.basilLocalWebPreview.onInit", args: config)
    }

    private func callJS(_ function: String, args: Any...) {
        guard let argsData = args.map({ value -> String? in
            if let data = try? JSONSerialization.data(withJSONObject: value),
               let str = String(data: data, encoding: .utf8) {
                return str
            }
            return nil
        }) as? [String] else { return }

        let argsString = argsData.joined(separator: ", ")
        let js = "\(function)(\(argsString))"
        webView.evaluateJavaScript(js) { [weak self] _, error in
            guard let error else { return }
            self?.appendConsoleEvidence(
                level: "native",
                message: "JavaScript call \(function) failed: \(error.localizedDescription)"
            )
        }
    }

    private func appendConsoleEvidence(level: String, message: String) {
        guard consoleEvidenceMessageCount < maxConsoleEvidenceMessages else { return }
        let line = "[\(level.uppercased())] \(message)\n"
        if consoleEvidenceTail.count + line.count > maxConsoleEvidenceChars { return }
        consoleEvidenceTail += line
        consoleEvidenceMessageCount += 1
        persistValidationEvidence()
    }

    private func recordRendererDiagnostics(stage: String) {
        guard validationEvidenceURL() != nil else { return }
        let script = """
            (() => {
                const moduleScript = document.querySelector('script[type="module"]');
                const snapshot = {
                    readyState: document.readyState,
                    location: window.location.href,
                    bridgeType: typeof window.basilLocalWebPreview,
                    moduleScript: moduleScript?.src ?? null,
                    resources: performance.getEntriesByType('resource').slice(-30).map((entry) => entry.name)
                };
                if (!moduleScript?.src) return JSON.stringify(snapshot);
                fetch(moduleScript.src)
                    .then((response) => response.text().then((text) => {
                        window.webkit.messageHandlers.jsLog.postMessage({
                            level: 'native',
                            message: 'Module fetch diagnostic: ' + JSON.stringify({
                                status: response.status,
                                contentType: response.headers.get('content-type'),
                                bytes: text.length
                            })
                        });
                    }))
                    .catch((error) => {
                        window.webkit.messageHandlers.jsLog.postMessage({
                            level: 'native',
                            message: 'Module fetch diagnostic failed: ' + String(error)
                        });
                    });
                import(moduleScript.src)
                    .then(() => {
                        window.webkit.messageHandlers.jsLog.postMessage({
                            level: 'native',
                            message: 'Module import diagnostic: succeeded'
                        });
                    })
                    .catch((error) => {
                        window.webkit.messageHandlers.jsLog.postMessage({
                            level: 'native',
                            message: 'Module import diagnostic failed: ' + (error?.stack || String(error))
                        });
                    });
                return JSON.stringify(snapshot);
            })()
            """
        webView.evaluateJavaScript(script) { [weak self] result, error in
            guard let self else { return }
            if let error {
                self.appendConsoleEvidence(
                    level: "native",
                    message: "Renderer diagnostic at \(stage) failed: \(error.localizedDescription)"
                )
                return
            }
            self.appendConsoleEvidence(
                level: "native",
                message: "Renderer diagnostic at \(stage): \(result as? String ?? "<missing>")"
            )
        }
    }

    private func screenshotsDirectory() -> URL {
        // NSHomeDirectory() resolves the account's real home via directory
        // services and ignores a process-level HOME override, so it must not
        // be used here: a validation run's screenshots would land in the
        // real user's ~/.basil/data instead of the isolated session home
        // that the backend's matching screenshot-path allowlist expects.
        let dataDirectory = ProcessInfo.processInfo.environment["BASIL_DATA_DIR"]
            .flatMap { $0.isEmpty ? nil : URL(fileURLWithPath: $0, isDirectory: true) }
            ?? BasilRuntimeProfile.localHomeURL.appendingPathComponent(".basil/data", isDirectory: true)
        let root = dataDirectory.appendingPathComponent("local_web_preview/screenshots", isDirectory: true)
        try? FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }

    private func captureScreenshot() {
        webView.takeSnapshot(with: nil) { [weak self] image, error in
            guard let self else { return }
            if let error {
                self.callJS("window.basilLocalWebPreview.onScreenshotCaptured", args: [
                    "error": error.localizedDescription
                ])
                return
            }
            guard let image, let tiff = image.tiffRepresentation,
                  let bitmap = NSBitmapImageRep(data: tiff),
                  let png = bitmap.representation(using: .png, properties: [:]) else {
                self.callJS("window.basilLocalWebPreview.onScreenshotCaptured", args: [
                    "error": "Screenshot capture failed."
                ])
                return
            }
            let path = self.screenshotsDirectory().appendingPathComponent("\(UUID().uuidString).png")
            do {
                try png.write(to: path)
                self.lastValidationScreenshotPath = path.path
                self.persistValidationEvidence()
                self.callJS("window.basilLocalWebPreview.onScreenshotCaptured", args: [
                    "path": path.path
                ])
            } catch {
                self.callJS("window.basilLocalWebPreview.onScreenshotCaptured", args: [
                    "error": error.localizedDescription
                ])
            }
        }
    }

    func submitValidationFeedback(_ text: String) {
        queueValidationAction {
            self.callJS(
                "window.basilLocalWebPreview.onValidationFeedback",
                args: ["text": text]
            )
        }
    }

    func startValidationServer(
        command: String,
        args: [String],
        cwd: String,
        port: Int
    ) {
        queueValidationAction {
            self.callJS(
                "window.basilLocalWebPreview.onValidationStartServer",
                args: [
                    "command": command,
                    "args": args,
                    "cwd": cwd,
                    "port": port,
                ]
            )
        }
    }

    /// See closeMostRecentValidationPreviewWindow's doc comment on the
    /// controller: mirrors the "closeWidget" bridge handler's window.close()
    /// without requiring System Events to traverse into WKWebView content.
    func closeWindowForValidation() {
        guard validationEvidenceURL() != nil else {
            return
        }
        window?.close()
    }

    private func queueValidationAction(_ action: @escaping () -> Void) {
        guard validationEvidenceURL() != nil else {
            return
        }
        if hasReceivedInitAck {
            action()
        } else {
            pendingValidationActions.append(action)
        }
    }

    private func performPendingValidationActions() {
        let actions = pendingValidationActions
        pendingValidationActions.removeAll()
        DispatchQueue.main.async {
            actions.forEach { $0() }
        }
    }

    private func validationEvidenceURL() -> URL? {
        guard let sessionRoot = BasilRuntimeProfile.sessionRootURL else {
            return nil
        }
        return sessionRoot
            .appendingPathComponent("local-web-preview-evidence.json")
            .standardizedFileURL
    }

    /// Multiple local-preview windows (e.g. the static HTML fixture and the
    /// local-server fixture) can be open concurrently during validation, each
    /// with its own native diagnostics. The evidence file is shared for the
    /// whole session, so entries are keyed by this window's agentTaskID and
    /// merged into any existing entries rather than overwriting the file --
    /// otherwise a later window's diagnostics would clobber an earlier
    /// window's screenshot/console evidence before the smoke test reads it.
    private func persistValidationEvidence() {
        guard let evidenceURL = validationEvidenceURL() else {
            return
        }
        var document: [String: Any] = [:]
        if let existingData = try? Data(contentsOf: evidenceURL),
           let existingObject = try? JSONSerialization.jsonObject(with: existingData) as? [String: Any] {
            document = existingObject
        }
        var entry: [String: Any] = [
            "agentTaskID": agentTaskId,
            "artifactID": artifactId,
            "consoleEvidence": consoleEvidenceTail,
            "updatedAt": ISO8601DateFormatter().string(from: Date()),
        ]
        if let activeSessionId {
            entry["sessionID"] = activeSessionId
        }
        if let lastDeniedError {
            entry["deniedReason"] = lastDeniedError
        }
        if let lastValidationScreenshotPath {
            entry["screenshotPath"] = lastValidationScreenshotPath
        }
        document[agentTaskId] = entry
        guard JSONSerialization.isValidJSONObject(document),
              let data = try? JSONSerialization.data(withJSONObject: document, options: [.sortedKeys]) else {
            return
        }
        try? data.write(to: evidenceURL, options: .atomic)
    }

    private func currentThemePayload() -> [String: String] {
        [
            "backgroundPrimary": colorToHex(AestheticSystem.Colors.backgroundPrimary),
            "primary": colorToHex(AestheticSystem.Colors.primary),
            "secondary": colorToHex(AestheticSystem.Colors.secondary),
            "textPrimary": colorToHex(AestheticSystem.Colors.textPrimary),
            "recordingBase": colorToHex(AestheticSystem.Colors.recordingBase),
            "recordingAccent": colorToHex(AestheticSystem.Colors.recordingAccent),
            "processingBase": colorToHex(AestheticSystem.Colors.processingBase),
            "processingAccent": colorToHex(AestheticSystem.Colors.processingAccent),
            "surfaceFinish": AestheticSystem.surfaceFinish,
        ]
    }

    private func currentFontPayload() -> [String: String] {
        let baseFontName = AestheticSystem.Typography.preferredFontName
        let mediumFontName = baseFontName == "Helvetica-Light"
            ? "Helvetica"
            : baseFontName.replacingOccurrences(of: "-Light", with: "")
        let boldFontName = baseFontName == "Helvetica-Light"
            ? "Helvetica-Bold"
            : baseFontName.replacingOccurrences(of: "-Light", with: "-Bold")
        return [
            "fontFamily": baseFontName,
            "fontFamilyMedium": mediumFontName,
            "fontFamilyBold": boldFontName,
        ]
    }

    private func colorToHex(_ color: NSColor) -> String {
        guard let rgbColor = color.usingColorSpace(.sRGB) else { return "#000000" }
        let r = Int(rgbColor.redComponent * 255)
        let g = Int(rgbColor.greenComponent * 255)
        let b = Int(rgbColor.blueComponent * 255)
        return String(format: "#%02X%02X%02X", r, g, b)
    }

    private func colorToHex(_ color: SwiftUI.Color) -> String {
        colorToHex(NSColor(color))
    }

    nonisolated func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        Task { @MainActor in
            handleMessage(name: message.name, body: message.body, isMainFrame: message.frameInfo.isMainFrame)
        }
    }

    private func handleMessage(name: String, body: Any, isMainFrame: Bool) {
        if name == "jsLog" {
            if let dict = body as? [String: String] {
                appendConsoleEvidence(level: dict["level"] ?? "log", message: dict["message"] ?? "")
            }
            return
        }

        guard isMainFrame else {
            return
        }
        guard name == "localWebPreviewBridge",
              let dict = body as? [String: Any],
              let type = dict["type"] as? String else {
            return
        }

        switch type {
        case "initAck":
            hasReceivedInitAck = true
            performPendingValidationActions()
        case "rendererReady":
            sendInitWithRetry(attempt: 0)
        case "closeWidget":
            window?.close()
        case "minimizeWidget":
            window?.miniaturize(nil)
        case "openExternalUrl":
            if let urlString = dict["url"] as? String, let url = URL(string: urlString) {
                NSWorkspace.shared.open(url)
            }
        case "captureScreenshot":
            hasReceivedInitAck = true
            captureScreenshot()
        case "getConsoleEvidence":
            hasReceivedInitAck = true
            callJS("window.basilLocalWebPreview.onConsoleEvidence", args: ["text": consoleEvidenceTail])
        case "filePreviewChromeHeight":
            break
        case "previewWindowWillClose":
            stopLocalPreviewSessionOnClose()
        case "previewServerSessionStarted":
            activeSessionId = dict["sessionId"] as? String
            lastDeniedError = nil
            persistValidationEvidence()
        case "previewServerSessionDenied":
            activeSessionId = dict["sessionId"] as? String
            lastDeniedError = dict["lastError"] as? String
            persistValidationEvidence()
        default:
            break
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        recordRendererDiagnostics(stage: "didFinish")
        sendInitWithRetry(attempt: 0)
    }

    func webView(
        _ webView: WKWebView,
        didFailProvisionalNavigation navigation: WKNavigation!,
        withError error: Error
    ) {
        appendConsoleEvidence(
            level: "native",
            message: "Provisional navigation failed for \(webView.url?.absoluteString ?? "<unknown>"): \(error.localizedDescription)"
        )
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        appendConsoleEvidence(
            level: "native",
            message: "Navigation failed for \(webView.url?.absoluteString ?? "<unknown>"): \(error.localizedDescription)"
        )
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.cancel)
            return
        }
        if url.standardizedFileURL == appShellURL {
            decisionHandler(.allow)
            return
        }
        decisionHandler(allowsLocalPreviewNavigation(url, mode: mode) ? .allow : .cancel)
    }

    private func stopLocalPreviewSessionOnClose() {
        guard mode == "devServer", let activeSessionId, !activeSessionId.isEmpty else { return }
        let port = APIClient.shared.currentPort
        guard port > 0 else { return }
        var components = URLComponents()
        components.scheme = "http"
        components.host = "127.0.0.1"
        components.port = port
        let encodedAgentTaskId = agentTaskId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? agentTaskId
        let encodedArtifactId = artifactId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? artifactId
        let encodedSessionId = activeSessionId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? activeSessionId
        components.path = "/api/v1/agent-tasks/\(encodedAgentTaskId)/artifacts/\(encodedArtifactId)/local-preview/sessions/\(encodedSessionId)/stop"
        guard let url = components.url else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        URLSession.shared.dataTask(with: request).resume()
    }

    func windowWillClose(_ notification: Notification) {
        stopLocalPreviewSessionOnClose()
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "localWebPreviewBridge")
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "jsLog")
        onClose?()
    }
}
