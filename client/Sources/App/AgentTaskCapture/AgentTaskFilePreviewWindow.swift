import AppKit
import PDFKit
import SwiftUI
@preconcurrency import WebKit

@MainActor
final class AgentTaskFilePreviewWindowController {
    static let shared = AgentTaskFilePreviewWindowController()

    private var hosts: [AgentTaskFilePreviewWindowHost] = []

    func open(path: String, agentTaskId: String? = nil, rootTaskId: String? = nil) {
        let resolvedPath = FilePathUtility.convertToUnixPath(path)
        #if DEBUG
        DevLogger.shared.info("[AgentTaskFilePreviewWindow] Opening preview for \(resolvedPath)", context: "AgentTaskCapture")
        #endif

        let host = AgentTaskFilePreviewWindowHost(path: resolvedPath, agentTaskId: agentTaskId, rootTaskId: rootTaskId)
        host.onClose = { [weak self, weak host] in
            guard let host else { return }
            self?.hosts.removeAll { $0 === host }
        }
        hosts.append(host)
        host.show()
    }
}

@MainActor
private final class AgentTaskFilePreviewWindowHost: NSObject, WKScriptMessageHandler, WKNavigationDelegate, NSWindowDelegate {
    private let initialPath: String
    private let agentTaskId: String?
    private let rootTaskId: String?
    private let webView: WKWebView
    private var dragAreaView: FilePreviewDragAreaView?
    private var nativePreviewOverlay: AgentTaskNativePreviewOverlay?
    private var windowPDFView: PDFView?
    private var activeFilePreviewRequestId: String?
    private var activeFilePreviewURL: URL?
    private var activeFilePreviewKind: String?
    private var activeFilePreviewRevision: AgentTaskPreviewFileRevision?
    private var activeFilePreviewObserver: AgentTaskPreviewFileObserver?
    // Fallback matches header (~50) + path bar (~34); replaced by the exact
    // value React reports via `filePreviewChromeHeight` once laid out.
    private var chromeHeight: CGFloat = 86
    private var window: NSWindow?
    private var keyboardShortcuts: WindowKeyboardShortcuts?

    // `didFinish` can fire before the deferred `type="module"` bundle has
    // executed and defined `window.basilAgentTask`, so a single init send
    // races the bundle and is silently dropped (the "stuck on Loading
    // preview..." bug). Mirror AgentTaskResultWebView's retry-until-acked
    // approach: re-send init on a short timer until React proves it received
    // it by issuing its first `previewFile` request.
    private var hasReceivedPreviewRequest = false
    private let maxInitAttempts = 40
    private let maximumPreviewBytes: UInt64 = 1_000_000

    var onClose: (() -> Void)?

    init(path: String, agentTaskId: String? = nil, rootTaskId: String? = nil) {
        self.initialPath = path
        self.agentTaskId = agentTaskId
        self.rootTaskId = rootTaskId

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

        let webView = FirstClickWebView(frame: .zero, configuration: configuration)
        self.webView = webView

        super.init()

        let contentController = configuration.userContentController
        contentController.add(self, name: "agentTaskBridge")
        contentController.add(self, name: "jsLog")

        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }
    }

    func show() {
        let window = CustomBorderlessWindow(
            contentRect: NSRect(x: 0, y: 0, width: 880, height: 680),
            styleMask: [.borderless, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = URL(fileURLWithPath: initialPath).lastPathComponent
        window.minSize = NSSize(width: 400, height: 300)
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

    // The React window (`.file-preview-window`) does not fill the web view:
    // the shared WebKit frame supplies a 3pt inset and the window itself has a
    // 16px radius plus a hairline border. The PDF overlay must sit inside that
    // inset window, not flush to the web view, otherwise it spills past the
    // left/right edges and covers the rounded bottom corners and border.
    private let previewWindowInset = WebKitWindowChromeAppearance.frameInset
    private let previewWindowCornerRadius = WebKitWindowChromeAppearance.cornerRadius

    private func showPDF(document: PDFDocument) {
        let view = AgentTaskNativePDFPreview.makeView(
            document: document,
            cornerRadius: previewWindowCornerRadius
        )
        view.layer?.maskedCorners = [.layerMinXMinYCorner, .layerMaxXMinYCorner]
        windowPDFView = view

        let overlay = nativePreviewOverlay ?? AgentTaskNativePreviewOverlay(hostView: webView)
        nativePreviewOverlay = overlay
        updatePDFFrame()
    }

    private func hidePDF() {
        nativePreviewOverlay?.hide()
        nativePreviewOverlay = nil
        windowPDFView = nil
    }

    private func updatePDFFrame() {
        guard let windowPDFView else { return }
        guard let frame = AgentTaskNativePreviewGeometry.filePreviewWindowFrame(
            hostBounds: webView.bounds,
            chromeHeight: chromeHeight,
            inset: previewWindowInset,
            hostIsFlipped: webView.isFlipped
        ) else {
            nativePreviewOverlay?.hide()
            return
        }
        let overlay = nativePreviewOverlay ?? AgentTaskNativePreviewOverlay(hostView: webView)
        nativePreviewOverlay = overlay
        if overlay.currentView === windowPDFView {
            overlay.update(frame: frame)
        } else {
            overlay.present(windowPDFView, frame: frame)
        }
    }

    private func updateChromeHeight(_ height: CGFloat) {
        guard height > 0 else { return }
        chromeHeight = height
        updatePDFFrame()
    }

    private func loadContent() {
        guard let resourceURL = Bundle.main.resourceURL else {
            #if DEBUG
            DevLogger.shared.error("[AgentTaskFilePreviewWindow] Could not get bundle resource URL", context: "AgentTaskCapture")
            #endif
            return
        }

        let webAssetsFolder = resourceURL.appendingPathComponent("AgentTaskWebAssets")
        let htmlURL = webAssetsFolder.appendingPathComponent("src/entries/file-preview.html")

        if FileManager.default.fileExists(atPath: htmlURL.path) {
            webView.loadFileURL(htmlURL, allowingReadAccessTo: webAssetsFolder)
        } else {
            #if DEBUG
            DevLogger.shared.error("[AgentTaskFilePreviewWindow] HTML file NOT found at: \(htmlURL.path)", context: "AgentTaskCapture")
            #endif
        }
    }

    private func sendInitWithRetry(attempt: Int) {
        guard !hasReceivedPreviewRequest else { return }
        guard attempt < maxInitAttempts else {
            #if DEBUG
            DevLogger.shared.error("[AgentTaskFilePreviewWindow] init never acknowledged after \(attempt) attempts", context: "AgentTaskCapture")
            #endif
            return
        }
        sendInit()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
            self?.sendInitWithRetry(attempt: attempt + 1)
        }
    }

    private func sendInit() {
        var config: [String: Any] = [
            "path": initialPath,
            "port": APIClient.shared.currentPort,
            "theme": currentThemePayload(),
            "fonts": currentFontPayload(),
        ]
        if let agentTaskId, !agentTaskId.isEmpty {
            config["agentTaskId"] = agentTaskId
        }
        if let rootTaskId, !rootTaskId.isEmpty {
            config["rootTaskId"] = rootTaskId
        }
        callJS("window.basilAgentTask.onFilePreviewInit", args: config)
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

        webView.evaluateJavaScript(js) { _, error in
            if let error = error {
                #if DEBUG
                DevLogger.shared.error("[AgentTaskFilePreviewWindow] JS eval error: \(error)", context: "AgentTaskCapture")
                #endif
            }
        }
    }

    private func sendFilePreviewPayload(
        requestId: String,
        path: String,
        name: String,
        kind: String,
        content: String? = nil,
        error: String? = nil
    ) {
        var payload: [String: Any] = [
            "requestId": requestId,
            "path": path,
            "name": name,
            "kind": kind,
        ]
        if let content = content {
            payload["content"] = content
        }
        if let error = error {
            payload["error"] = error
        }
        callJS("window.basilAgentTask.onFilePreviewReady", args: payload)
    }

    private func sendFilePreviewUpdate(
        requestId: String,
        path: String,
        kind: String,
        content: String? = nil
    ) {
        let url = URL(fileURLWithPath: path)
        var payload: [String: Any] = [
            "requestId": requestId,
            "path": path,
            "name": url.lastPathComponent.isEmpty ? "File" : url.lastPathComponent,
            "kind": kind,
        ]
        if let content {
            payload["content"] = content
        }
        callJS("window.basilAgentTask.onFilePreviewUpdated", args: payload)
    }

    private func startFilePreviewObservation(requestId: String, path: String, kind: String) {
        let url = URL(fileURLWithPath: path)
        activeFilePreviewObserver?.invalidate()
        activeFilePreviewRequestId = requestId
        activeFilePreviewURL = url
        activeFilePreviewKind = kind
        activeFilePreviewRevision = AgentTaskPreviewFileRevision(url: url)
        activeFilePreviewObserver = AgentTaskPreviewFileObserver(url: url) { [weak self] in
            self?.reloadActiveFilePreviewIfChanged()
        }
    }

    private func clearActiveFilePreview(requestId: String? = nil) {
        guard requestId == nil || requestId == activeFilePreviewRequestId else { return }
        activeFilePreviewObserver?.invalidate()
        activeFilePreviewObserver = nil
        activeFilePreviewRequestId = nil
        activeFilePreviewURL = nil
        activeFilePreviewKind = nil
        activeFilePreviewRevision = nil
    }

    private func reloadActiveFilePreviewIfChanged() {
        guard let requestId = activeFilePreviewRequestId,
              let url = activeFilePreviewURL,
              let kind = activeFilePreviewKind,
              let currentRevision = AgentTaskPreviewFileRevision(url: url),
              currentRevision != activeFilePreviewRevision else {
            return
        }

        if kind == "pdf" {
            guard let document = AgentTaskNativePDFPreview.loadDocument(at: url),
                  document.pageCount > 0,
                  AgentTaskPreviewFileRevision(url: url) == currentRevision else {
                return
            }
            nativePreviewOverlay?.replaceDocument(document)
            windowPDFView?.document = document
            activeFilePreviewRevision = currentRevision
            sendFilePreviewUpdate(requestId: requestId, path: url.path, kind: kind)
            return
        }

        guard let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
              ((attributes[.size] as? NSNumber)?.uint64Value ?? 0) <= maximumPreviewBytes,
              let content = try? String(contentsOf: url, encoding: .utf8),
              AgentTaskPreviewFileRevision(url: url) == currentRevision else {
            return
        }
        activeFilePreviewRevision = currentRevision
        sendFilePreviewUpdate(requestId: requestId, path: url.path, kind: kind, content: content)
    }

    private func previewKind(forExtension fileExtension: String) -> String {
        switch fileExtension.lowercased() {
        case "md", "markdown":
            return "markdown"
        case "html", "htm":
            return "htmlSource"
        case "js", "ts", "tsx", "py", "swift", "sh", "sql", "css", "json", "yaml", "yml", "xml":
            return "code"
        case "txt", "log", "csv":
            return "text"
        case "pdf":
            return "pdf"
        default:
            return "unsupported"
        }
    }

    private func handleFilePreviewRequest(requestId: String, path: String) {
        let posixPath = FilePathUtility.convertToUnixPath(path)
        let url = URL(fileURLWithPath: posixPath)
        let name = url.lastPathComponent.isEmpty ? "File" : url.lastPathComponent
        let kind = previewKind(forExtension: url.pathExtension)
        clearActiveFilePreview()
        hidePDF()

        #if DEBUG
        DevLogger.shared.info("[AgentTaskFilePreviewWindow] previewFile request path=\(posixPath), kind=\(kind)", context: "AgentTaskCapture")
        #endif

        guard FileManager.default.fileExists(atPath: posixPath) else {
            sendFilePreviewPayload(
                requestId: requestId,
                path: posixPath,
                name: name,
                kind: "unsupported",
                error: "The file could not be found."
            )
            return
        }

        do {
            let attributes = try FileManager.default.attributesOfItem(atPath: posixPath)
            if let fileType = attributes[.type] as? FileAttributeType, fileType == .typeDirectory {
                sendFilePreviewPayload(
                    requestId: requestId,
                    path: posixPath,
                    name: name,
                    kind: "unsupported",
                    error: "Folders cannot be previewed here."
                )
                return
            }

            // PDFs render natively (PDFKit) and are not read as UTF-8 text, so
            // they skip the text-oriented byte cap. Validate the document loads
            // before telling React it is a PDF; otherwise fall back to the
            // standard unsupported message.
            if kind == "pdf" {
                guard let document = AgentTaskNativePDFPreview.loadDocument(at: url) else {
                    sendFilePreviewPayload(
                        requestId: requestId,
                        path: posixPath,
                        name: name,
                        kind: "unsupported",
                        error: "This PDF could not be opened for preview."
                    )
                    return
                }
                showPDF(document: document)
                sendFilePreviewPayload(
                    requestId: requestId,
                    path: posixPath,
                    name: name,
                    kind: "pdf"
                )
                startFilePreviewObservation(requestId: requestId, path: posixPath, kind: kind)
                return
            }

            let fileSize = (attributes[.size] as? NSNumber)?.uint64Value ?? 0
            if fileSize > maximumPreviewBytes {
                sendFilePreviewPayload(
                    requestId: requestId,
                    path: posixPath,
                    name: name,
                    kind: "unsupported",
                    error: "This file is too large to preview in the window."
                )
                return
            }
        } catch {
            sendFilePreviewPayload(
                requestId: requestId,
                path: posixPath,
                name: name,
                kind: "unsupported",
                error: "The file metadata could not be read."
            )
            return
        }

        guard kind != "unsupported" else {
            sendFilePreviewPayload(
                requestId: requestId,
                path: posixPath,
                name: name,
                kind: kind,
                error: "This file type is not supported by the in-app preview."
            )
            return
        }

        do {
            let content = try String(contentsOf: url, encoding: .utf8)
            sendFilePreviewPayload(
                requestId: requestId,
                path: posixPath,
                name: name,
                kind: kind,
                content: content
            )
            startFilePreviewObservation(requestId: requestId, path: posixPath, kind: kind)
        } catch {
            sendFilePreviewPayload(
                requestId: requestId,
                path: posixPath,
                name: name,
                kind: kind,
                error: "The file could not be read as UTF-8 text."
            )
        }
    }

    private func openFile(path: String) {
        let posixPath = FilePathUtility.convertToUnixPath(path)
        let success = NSWorkspace.shared.open(URL(fileURLWithPath: posixPath))
        #if DEBUG
        DevLogger.shared.info("[AgentTaskFilePreviewWindow] openFile path=\(posixPath), success=\(success)", context: "AgentTaskCapture")
        #endif
    }

    private func openContainingFolder(path: String) {
        let posixPath = FilePathUtility.convertToUnixPath(path)
        let url = URL(fileURLWithPath: posixPath)
        NSWorkspace.shared.activateFileViewerSelecting([url])
        #if DEBUG
        DevLogger.shared.info("[AgentTaskFilePreviewWindow] openContainingFolder path=\(posixPath)", context: "AgentTaskCapture")
        #endif
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
        guard let rgbColor = color.usingColorSpace(.sRGB) else {
            return "#000000"
        }
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
            handleMessage(name: message.name, body: message.body)
        }
    }

    private func handleMessage(name: String, body: Any) {
        if name == "jsLog" {
            if let dict = body as? [String: String] {
                let level = dict["level"] ?? "log"
                let msg = dict["message"] ?? ""
                #if DEBUG
                DevLogger.shared.info("[AgentTaskFilePreviewWindow JS \(level.uppercased())] \(msg)", context: "AgentTaskCapture")
                #endif
            }
            return
        }

        guard name == "agentTaskBridge",
              let dict = body as? [String: Any],
              let type = dict["type"] as? String else {
            return
        }

        switch type {
        case "closeWidget":
            #if DEBUG
            DevLogger.shared.info("[AgentTaskFilePreviewWindow] close requested", context: "AgentTaskCapture")
            #endif
            window?.close()
        case "minimizeWidget":
            #if DEBUG
            DevLogger.shared.info("[AgentTaskFilePreviewWindow] minimize requested", context: "AgentTaskCapture")
            #endif
            window?.miniaturize(nil)
        case "previewFile":
            // Proof that React received the init and is now driving the
            // preview; stop the init retry loop.
            hasReceivedPreviewRequest = true
            if let requestId = dict["requestId"] as? String,
               let path = dict["path"] as? String {
                handleFilePreviewRequest(requestId: requestId, path: path)
            }
        case "openFile":
            if let path = dict["path"] as? String {
                openFile(path: path)
            }
        case "openContainingFolder":
            if let path = dict["path"] as? String {
                openContainingFolder(path: path)
            }
        case "openExternalUrl":
            if let urlString = dict["url"] as? String, let url = URL(string: urlString) {
                NSWorkspace.shared.open(url)
            }
        case "filePreviewChromeHeight":
            if let height = dict["height"] as? NSNumber {
                updateChromeHeight(CGFloat(truncating: height))
            }
        case "clearFilePreview":
            if let requestId = dict["requestId"] as? String, !requestId.isEmpty {
                clearActiveFilePreview(requestId: requestId)
            }
        default:
            break
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        sendInitWithRetry(attempt: 0)
    }

    func windowDidResize(_ notification: Notification) {
        updatePDFFrame()
    }

    func windowWillClose(_ notification: Notification) {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "agentTaskBridge")
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "jsLog")
        clearActiveFilePreview()
        hidePDF()
        onClose?()
    }
}
