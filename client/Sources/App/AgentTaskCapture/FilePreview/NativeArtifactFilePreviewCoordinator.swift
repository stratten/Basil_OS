import AppKit
import Foundation
import PDFKit

/// Host-agnostic native file-preview state machine shared by the Agent Task
/// result widget and the Basil Board conversation webview. Each host
/// supplies its own `emit` (wraps that host's existing JS-callback dispatch,
/// e.g. `callJS("window.basilAgentTask.\(name)", args:)` or
/// `emitBridgeCallback(name, payload:)`) and `hostView` (the `WKWebView`
/// that anchors the native PDF overlay). Everything else — request
/// bookkeeping, live-file observation, and inline PDF overlay lifecycle — is
/// identical for both hosts, which is why this type previously existed only
/// on `AgentTaskResultWebView` and had to be duplicated by hand for the
/// Basil Board conversation sidebar before this extraction.
@MainActor
final class NativeArtifactFilePreviewCoordinator {
    private let emit: (_ callbackName: String, _ payload: [String: Any]) -> Void
    private let hostView: () -> NSView

    private var nativePreviewOverlay: AgentTaskNativePreviewOverlay?
    private var pendingInlinePDFPreviews: [String: PDFDocument] = [:]
    private var activeInlinePDFRequestId: String?
    private var activeFilePreviewRequestId: String?
    private var activeFilePreviewURL: URL?
    private var activeFilePreviewKind: String?
    private var activeFilePreviewRevision: AgentTaskPreviewFileRevision?
    private var activeFilePreviewObserver: AgentTaskPreviewFileObserver?

    init(
        emit: @escaping (_ callbackName: String, _ payload: [String: Any]) -> Void,
        hostView: @escaping () -> NSView
    ) {
        self.emit = emit
        self.hostView = hostView
    }

    // MARK: - Incoming request handling

    func previewKind(forExtension fileExtension: String) -> String {
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

    func handleFilePreviewRequest(requestId: String, path: String) {
        clearCurrentFilePreview()
        let posixPath = FilePathUtility.convertToUnixPath(path)
        let url = URL(fileURLWithPath: posixPath)
        let name = url.lastPathComponent.isEmpty ? "File" : url.lastPathComponent
        let requestedKind = previewKind(forExtension: url.pathExtension)
        let maxPreviewBytes: UInt64 = 1_000_000

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

            if requestedKind == "pdf" {
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

                prepareInlinePDFPreview(requestId: requestId, path: posixPath, document: document)
                sendFilePreviewPayload(
                    requestId: requestId,
                    path: posixPath,
                    name: name,
                    kind: "pdf"
                )
                return
            }

            let fileSize = attributes[.size] as? UInt64 ?? 0
            if fileSize > maxPreviewBytes {
                sendFilePreviewPayload(
                    requestId: requestId,
                    path: posixPath,
                    name: name,
                    kind: "unsupported",
                    error: "This file is too large to preview in the widget."
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

        do {
            let content = try String(contentsOf: url, encoding: .utf8)
            let resolvedKind = requestedKind == "unsupported" ? "text" : requestedKind
            sendFilePreviewPayload(
                requestId: requestId,
                path: posixPath,
                name: name,
                kind: resolvedKind,
                content: content
            )
            startTextPreviewObservation(requestId: requestId, path: posixPath, kind: resolvedKind)
        } catch {
            sendFilePreviewPayload(
                requestId: requestId,
                path: posixPath,
                name: name,
                kind: "unsupported",
                error: "The file could not be read as UTF-8 text."
            )
        }
    }

    func rejectFilePreviewRequest(requestId: String, path: String?) {
        clearCurrentFilePreview()
        let displayPath = path ?? ""
        let url = URL(fileURLWithPath: displayPath)
        sendFilePreviewPayload(
            requestId: requestId,
            path: displayPath,
            name: url.lastPathComponent.isEmpty ? "File" : url.lastPathComponent,
            kind: "unsupported",
            error: "The file path is invalid."
        )
    }

    // MARK: - Outgoing payloads

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
        if let content { payload["content"] = content }
        if let error { payload["error"] = error }
        emit("onFilePreviewReady", payload)
    }

    private func sendFilePreviewUpdate(
        requestId: String,
        path: String,
        kind: String,
        content: String?,
        error: String?
    ) {
        let url = URL(fileURLWithPath: path)
        var payload: [String: Any] = [
            "requestId": requestId,
            "path": path,
            "name": url.lastPathComponent.isEmpty ? "File" : url.lastPathComponent,
            "kind": kind,
        ]
        if let content { payload["content"] = content }
        if let error { payload["error"] = error }
        emit("onFilePreviewUpdated", payload)
    }

    // MARK: - Live observation

    private func prepareInlinePDFPreview(requestId: String, path: String, document: PDFDocument) {
        clearCurrentFilePreview()
        activeInlinePDFRequestId = requestId
        pendingInlinePDFPreviews[requestId] = document
        let url = URL(fileURLWithPath: path)
        activeFilePreviewRequestId = requestId
        activeFilePreviewURL = url
        activeFilePreviewKind = "pdf"
        activeFilePreviewRevision = AgentTaskPreviewFileRevision(url: url)
        activeFilePreviewObserver = AgentTaskPreviewFileObserver(url: url) { [weak self] in
            self?.reloadActiveFilePreviewIfChanged()
        }
    }

    private func startTextPreviewObservation(requestId: String, path: String, kind: String) {
        guard ["markdown", "text", "code", "htmlSource"].contains(kind) else { return }
        clearCurrentFilePreview()

        let url = URL(fileURLWithPath: path)
        activeFilePreviewRequestId = requestId
        activeFilePreviewURL = url
        activeFilePreviewKind = kind
        activeFilePreviewRevision = AgentTaskPreviewFileRevision(url: url)
        activeFilePreviewObserver = AgentTaskPreviewFileObserver(url: url) { [weak self] in
            self?.reloadActiveFilePreviewIfChanged()
        }
    }

    func clearActiveFilePreview(requestId: String) {
        guard activeFilePreviewRequestId == requestId else { return }
        let ownsInlinePDFOverlay = activeInlinePDFRequestId == requestId
        activeFilePreviewObserver?.invalidate()
        activeFilePreviewObserver = nil
        activeFilePreviewRequestId = nil
        activeFilePreviewURL = nil
        activeFilePreviewKind = nil
        activeFilePreviewRevision = nil
        if ownsInlinePDFOverlay {
            clearInlineNativePreview(requestId: requestId)
        }
    }

    func clearCurrentFilePreview() {
        if let activeFilePreviewRequestId {
            clearActiveFilePreview(requestId: activeFilePreviewRequestId)
        } else {
            clearInlineNativePreview()
        }
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
            pendingInlinePDFPreviews[requestId] = document
            nativePreviewOverlay?.replaceDocument(document)
            activeFilePreviewRevision = currentRevision
            sendFilePreviewUpdate(requestId: requestId, path: url.path, kind: kind, content: nil, error: nil)
            return
        }

        guard let content = try? String(contentsOf: url, encoding: .utf8),
              AgentTaskPreviewFileRevision(url: url) == currentRevision else {
            return
        }
        activeFilePreviewRevision = currentRevision
        sendFilePreviewUpdate(requestId: requestId, path: url.path, kind: kind, content: content, error: nil)
    }

    // MARK: - Inline native PDF overlay

    func presentInlinePDFPreview(requestId: String, frame: AgentTaskNativePreviewFrame) {
        guard activeInlinePDFRequestId == requestId,
              let document = pendingInlinePDFPreviews[requestId] else {
            return
        }

        let overlay = nativePreviewOverlay ?? AgentTaskNativePreviewOverlay(hostView: hostView())
        nativePreviewOverlay = overlay
        if overlay.currentView != nil {
            overlay.update(frame: frame)
            return
        }

        overlay.present(AgentTaskNativePDFPreview.makeView(document: document), frame: frame)
    }

    func hideInlineNativePreview(requestId: String) {
        guard activeInlinePDFRequestId == requestId else { return }
        nativePreviewOverlay?.hide()
    }

    func clearInlineNativePreview(requestId: String? = nil) {
        guard requestId == nil || requestId == activeInlinePDFRequestId else { return }
        nativePreviewOverlay?.hide()
        nativePreviewOverlay = nil
        pendingInlinePDFPreviews.removeAll()
        activeInlinePDFRequestId = nil
    }

    func inlineNativePreviewFrame(
        left: CGFloat,
        top: CGFloat,
        width: CGFloat,
        height: CGFloat,
        viewportWidth: CGFloat,
        viewportHeight: CGFloat
    ) -> AgentTaskNativePreviewFrame? {
        let view = hostView()
        return AgentTaskNativePreviewGeometry.convertInlinePreviewFrame(
            left: left,
            top: top,
            width: width,
            height: height,
            viewportWidth: viewportWidth,
            viewportHeight: viewportHeight,
            hostBounds: view.bounds,
            hostIsFlipped: view.isFlipped
        )
    }

    func tearDown() {
        clearCurrentFilePreview()
    }
}
