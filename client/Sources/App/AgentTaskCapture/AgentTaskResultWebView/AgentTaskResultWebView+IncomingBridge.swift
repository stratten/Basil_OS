import AppKit
import Foundation
@preconcurrency import WebKit

struct AgentTaskValidationRunFocusState: Codable, Equatable {
    let requestId: String
    let rootTaskId: String
    let runId: String
    let requestText: String
    let resultText: String
    let documentPaths: [String]
    let artifactIds: [String]
    let previewArtifactId: String?
    let isOverviewOpen: Bool

    init?(bridgePayload: [String: Any]) {
        guard
            let requestId = Self.identifier(bridgePayload["requestId"]),
            let rootTaskId = Self.identifier(bridgePayload["rootTaskId"]),
            let runId = Self.identifier(bridgePayload["runId"]),
            let requestText = Self.text(bridgePayload["requestText"]),
            let resultText = Self.text(bridgePayload["resultText"]),
            let documentPaths = Self.stringArray(bridgePayload["documentPaths"]),
            let artifactIds = Self.stringArray(bridgePayload["artifactIds"]),
            let isOverviewOpen = bridgePayload["isOverviewOpen"] as? Bool
        else {
            return nil
        }

        let previewArtifactId: String?
        if bridgePayload["previewArtifactId"] is NSNull {
            previewArtifactId = nil
        } else if let rawPreviewArtifactId = bridgePayload["previewArtifactId"] {
            guard let validPreviewArtifactId = Self.identifier(rawPreviewArtifactId) else {
                return nil
            }
            previewArtifactId = validPreviewArtifactId
        } else {
            return nil
        }

        self.requestId = requestId
        self.rootTaskId = rootTaskId
        self.runId = runId
        self.requestText = requestText
        self.resultText = resultText
        self.documentPaths = documentPaths
        self.artifactIds = artifactIds
        self.previewArtifactId = previewArtifactId
        self.isOverviewOpen = isOverviewOpen
    }

    private static func identifier(_ value: Any?) -> String? {
        guard let value = value as? String, !value.isEmpty, value.count <= 160 else {
            return nil
        }
        return value
    }

    private static func text(_ value: Any?) -> String? {
        guard let value = value as? String, !value.isEmpty, value.count <= 65_536 else {
            return nil
        }
        return value
    }

    private static func stringArray(_ value: Any?) -> [String]? {
        guard let values = value as? [Any], values.count <= 128 else {
            return nil
        }
        let strings = values.compactMap { $0 as? String }
        guard strings.count == values.count else {
            return nil
        }
        return strings
    }
}

extension AgentTaskResultWebView {
    // MARK: - WKScriptMessageHandler
    
    nonisolated func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        Task { @MainActor in
            guard message.frameInfo.isMainFrame || message.name == "jsLog" else { return }
            handleMessage(name: message.name, body: message.body)
        }
    }
    
    func handleMessage(name: String, body: Any) {
        if name == "jsLog" {
            if let dict = body as? [String: String] {
                let level = dict["level"] ?? "log"
                let msg = dict["message"] ?? ""
                #if DEBUG
                DevLogger.shared.info("[AgentTaskResultWebView JS \(level.uppercased())] \(msg)", context: "AgentTaskCapture")
                #endif
            }
            return
        }
        
        guard name == "agentTaskBridge", let dict = body as? [String: Any], let type = dict["type"] as? String else {
            return
        }
        
        switch type {
        case "resultWidgetReady":
            markReadyFromReact()
        case "closeWidget":
            onClose?()
        case "minimizeWidget":
            onMinimize?()
        case "widgetHeaderHeight":
            if let height = dict["height"] as? CGFloat {
                updateDragAreaHeight(height)
            }
        case "requestResize":
            if let width = dict["width"] as? CGFloat, let height = dict["height"] as? CGFloat {
                let intent = AgentTaskResultResizeIntent(
                    rawValue: dict["resizeIntent"] as? String ?? ""
                ) ?? .content
                onResize?(
                    AgentTaskResultResizeRequest(
                        size: NSSize(width: width, height: height),
                        intent: intent,
                        minimumWidth: dict["minimumWidth"] as? CGFloat
                    )
                )
            }
        case "startFollowUpCapture":
            if let rootTaskId = dict["rootTaskId"] as? String {
                onStartFollowUpCapture?(
                    rootTaskId,
                    dict["previousTaskId"] as? String
                )
            }
        case "stopFollowUpCapture":
            onStopFollowUpCapture?()
        case "cancelFollowUpCapture":
            onCancelFollowUpCapture?()
        case "startNewAgentTaskCapture":
            if let preId = dict["preGeneratedId"] as? String {
                onStartNewAgentTaskCapture?(preId)
            }
        case "stopNewAgentTaskCapture":
            onStopNewAgentTaskCapture?()
        case "cancelNewAgentTaskCapture":
            onCancelNewAgentTaskCapture?()
        case "startRefinementRecording":
            onStartRefinementRecording?()
        case "stopRefinementRecording":
            onStopRefinementRecording?()
        case "cancelRunningAgentTask":
            if let agentTaskId = decodeAgentTaskCancellationIdentifier(from: dict) {
                onCancelRunningAgentTask?(agentTaskId)
            }
        case "reportAgentTaskCancellationStage":
            if let agentTaskId = dict["agentTaskId"] as? String,
               let stage = dict["stage"] as? String,
               !agentTaskId.isEmpty,
               !stage.isEmpty {
                onReportAgentTaskCancellationStage?(agentTaskId, stage)
            }
        case "copyToClipboard":
            if let text = dict["text"] as? String {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(text, forType: .string)
            }
        case "copyRichTextToClipboard":
            if let text = dict["text"] as? String {
                let pasteboard = NSPasteboard.general
                pasteboard.clearContents()

                let attributedString = MarkdownUtils.markdownToAttributedString(text)
                pasteboard.setString(attributedString.string, forType: .string)

                if MarkdownUtils.containsMarkdown(text),
                   let rtfData = attributedString.rtf(
                    from: NSRange(location: 0, length: attributedString.length),
                    documentAttributes: [:]
                   ) {
                    pasteboard.setData(rtfData, forType: .rtf)
                }
            }
        case "openFile":
            if let path = dict["path"] as? String,
               let posixPath = FilePathUtility.resolveBridgeArtifactPath(path) {
                BridgeOpenPolicy.openLocalFile(URL(fileURLWithPath: posixPath))
            }
        case "openLocalWebPreview":
            guard let mode = dict["mode"] as? String,
                  let targetUrl = dict["targetUrl"] as? String,
                  let artifactId = dict["artifactId"] as? String,
                  let agentTaskId = dict["agentTaskId"] as? String else {
                return
            }
            AgentTaskLocalWebPreviewWindowController.shared.open(
                mode: mode,
                targetUrl: targetUrl,
                artifactId: artifactId,
                agentTaskId: agentTaskId,
                rootTaskId: dict["rootTaskId"] as? String,
                canonicalPath: dict["canonicalPath"] as? String,
                sessionId: dict["sessionId"] as? String,
                displayName: dict["displayName"] as? String
            )
        case "previewFile":
            guard let requestId = dict["requestId"] as? String,
                  !requestId.isEmpty,
                  requestId.count <= 160 else {
                return
            }
            guard let path = dict["path"] as? String,
                  let posixPath = FilePathUtility.resolveBridgeArtifactPath(path) else {
                filePreviewCoordinator.rejectFilePreviewRequest(
                    requestId: requestId,
                    path: dict["path"] as? String
                )
                return
            }
            filePreviewCoordinator.handleFilePreviewRequest(requestId: requestId, path: posixPath)
        case "checkFilePreviewAvailability":
            guard let requestId = dict["requestId"] as? String,
                  !requestId.isEmpty,
                  requestId.count <= 160,
                  let paths = dict["paths"] as? [String],
                  paths.count <= 32 else {
                return
            }
            let availablePaths = paths.compactMap { path -> String? in
                guard let posixPath = FilePathUtility.resolveBridgeArtifactPath(path) else {
                    return nil
                }
                var isDirectory: ObjCBool = false
                return FileManager.default.fileExists(atPath: posixPath, isDirectory: &isDirectory)
                    && !isDirectory.boolValue
                    ? path
                    : nil
            }
            callJS(
                "window.basilAgentTask.onFilePreviewAvailability",
                args: ["requestId": requestId, "availablePaths": availablePaths]
            )
        case "setInlineNativePreviewFrame":
            guard let requestId = dict["requestId"] as? String,
                  !requestId.isEmpty,
                  let frame = dict["frame"] as? [String: Any],
                  let left = finiteCGFloat(frame["left"]),
                  let top = finiteCGFloat(frame["top"]),
                  let width = finitePositiveCGFloat(frame["width"]),
                  let height = finitePositiveCGFloat(frame["height"]),
                  let viewportWidth = finitePositiveCGFloat(frame["viewportWidth"]),
                  let viewportHeight = finitePositiveCGFloat(frame["viewportHeight"]),
                  let nativeFrame = filePreviewCoordinator.inlineNativePreviewFrame(
                    left: left,
                    top: top,
                    width: width,
                    height: height,
                    viewportWidth: viewportWidth,
                    viewportHeight: viewportHeight
                  ) else {
                return
            }
            filePreviewCoordinator.presentInlinePDFPreview(requestId: requestId, frame: nativeFrame)
        case "hideInlineNativePreview":
            if let requestId = dict["requestId"] as? String, !requestId.isEmpty {
                filePreviewCoordinator.hideInlineNativePreview(requestId: requestId)
            }
        case "clearFilePreview":
            if let requestId = dict["requestId"] as? String, !requestId.isEmpty {
                filePreviewCoordinator.clearActiveFilePreview(requestId: requestId)
            }
        case "clearInlineNativePreview":
            if let requestId = dict["requestId"] as? String, !requestId.isEmpty {
                filePreviewCoordinator.clearInlineNativePreview(requestId: requestId)
            }
        case "openFilePreviewWindow":
            if let path = dict["path"] as? String,
               let posixPath = FilePathUtility.resolveBridgeArtifactPath(path) {
                AgentTaskFilePreviewWindowController.shared.open(
                    path: posixPath,
                    agentTaskId: dict["agentTaskId"] as? String,
                    rootTaskId: dict["rootTaskId"] as? String
                )
            }
        case "openContainingFolder":
            if let path = dict["path"] as? String,
               let posixPath = FilePathUtility.resolveBridgeArtifactPath(path) {
                let url = URL(fileURLWithPath: posixPath)
                NSWorkspace.shared.activateFileViewerSelecting([url])
            }
        case "openExternalUrl":
            if let urlString = dict["url"] as? String, let url = URL(string: urlString) {
                BridgeOpenPolicy.openExternalURL(url)
            }
        case "openDetachedAgentTask":
            if let rootTaskId = dict["rootTaskId"] as? String, !rootTaskId.isEmpty {
                onOpenDetachedAgentTask?(rootTaskId)
            }
        case "openAgentTaskOrigin":
            if let originType = dict["originType"] as? String, !originType.isEmpty,
               let originId = dict["originId"] as? String, !originId.isEmpty {
                onOpenAgentTaskOrigin?(originType, originId)
            }
        case "pickFiles":
            let panel = NSOpenPanel()
            panel.applyBasilThemedAppearance()
            panel.allowsMultipleSelection = true
            panel.canChooseFiles = true
            panel.canChooseDirectories = true
            panel.canCreateDirectories = false
            panel.title = "Attach Files or Folders"
            panel.begin { [weak self] response in
                guard response == .OK, !panel.urls.isEmpty else { return }
                let paths = panel.urls.map { $0.path }
                self?.callJS("window.basilAgentTask.onFilesPicked", args: paths)
            }
        case "validationRunFocused":
            if let state = AgentTaskValidationRunFocusState(bridgePayload: dict) {
                onValidationRunFocused?(state)
            }
        case "agentStatusChanged":
            // Pushed from the React sidebar whenever the focused row
            // changes or its status updates. Routes into the result-
            // widget singleton's focused-row cache, which the agentTask
            // hotkey handler reads to decide between starting a new
            // capture vs. a follow-up against the focused row.
            //
            // The JS bridge emits all five fields (`isProcessing`,
            // `hasResult`, `isTerminal`, `agentTaskId`, `supportsFollowUp`) and re-emits
            // them live when a focused task completes in place (see
            // `useAgentStatusReporting.ts`). They are still read defensively:
            // a malformed/partial payload leaves `agentTaskId` nil and
            // `supportsFollowUp` false, which makes the hotkey handler
            // conservatively fall through to a new capture.
            let agentTaskId = dict["agentTaskId"] as? String
            let isProcessing = dict["isProcessing"] as? Bool ?? false
            let hasResult = dict["hasResult"] as? Bool ?? false
            let isTerminal = dict["isTerminal"] as? Bool ?? false
            let supportsFollowUp = dict["supportsFollowUp"] as? Bool ?? false
            let didFocusedTaskFinish: Bool
            if let previous = lastReportedFocusedAgentStatus,
               let agentTaskId,
               !agentTaskId.isEmpty {
                didFocusedTaskFinish =
                    previous.agentTaskId == agentTaskId &&
                    previous.isProcessing &&
                    !isProcessing &&
                    isTerminal
            } else {
                didFocusedTaskFinish = false
            }
            lastReportedFocusedAgentStatus = (agentTaskId, isProcessing)
            onAgentStatusChanged?(agentTaskId, isProcessing, hasResult, isTerminal, supportsFollowUp)
            if didFocusedTaskFinish {
                onFocusedAgentTaskCompleted?()
            }
        default:
            #if DEBUG
            DevLogger.shared.info("[AgentTaskResultWebView \(instanceId)] Unknown message type: \(type)", context: "AgentTaskCapture")
            #endif
        }
    }
}

private func finiteCGFloat(_ value: Any?) -> CGFloat? {
    guard let number = value as? NSNumber,
          CFGetTypeID(number) != CFBooleanGetTypeID() else {
        return nil
    }
    let result = CGFloat(truncating: number)
    return result.isFinite ? result : nil
}

private func finitePositiveCGFloat(_ value: Any?) -> CGFloat? {
    guard let result = finiteCGFloat(value), result > 0 else { return nil }
    return result
}

