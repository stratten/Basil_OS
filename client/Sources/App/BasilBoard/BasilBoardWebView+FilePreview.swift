import AppKit
import Foundation

extension BasilBoardWebView {
    func handleOpenFilePreviewBridgeMessage(type: String, dict: [String: Any]) -> Bool {
        switch type {
        case "openFile":
            guard let path = dict["path"] as? String,
                  let posixPath = FilePathUtility.resolveBridgeArtifactPath(path) else {
                return true
            }
            NSWorkspace.shared.open(URL(fileURLWithPath: posixPath))
            return true
        case "openContainingFolder":
            guard let path = dict["path"] as? String,
                  let posixPath = FilePathUtility.resolveBridgeArtifactPath(path) else {
                return true
            }
            NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: posixPath)])
            return true
        case "openFilePreviewWindow":
            guard let path = dict["path"] as? String,
                  let posixPath = FilePathUtility.resolveBridgeArtifactPath(path) else {
                return true
            }
            AgentTaskFilePreviewWindowController.shared.open(path: posixPath)
            return true
        case "openLocalWebPreview":
            guard let mode = dict["mode"] as? String,
                  let targetUrl = dict["targetUrl"] as? String,
                  let artifactId = dict["artifactId"] as? String,
                  let agentTaskId = dict["agentTaskId"] as? String else {
                return true
            }
            AgentTaskLocalWebPreviewWindowController.shared.open(
                mode: mode,
                targetUrl: targetUrl,
                artifactId: artifactId,
                agentTaskId: agentTaskId,
                sessionId: dict["sessionId"] as? String,
                displayName: dict["displayName"] as? String
            )
            return true
        case "checkFilePreviewAvailability":
            guard let requestId = dict["requestId"] as? String,
                  !requestId.isEmpty,
                  requestId.count <= 160,
                  let paths = dict["paths"] as? [String],
                  paths.count <= 32 else {
                return true
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
            emitBridgeCallback(
                "onFilePreviewAvailability",
                payload: ["requestId": requestId, "availablePaths": availablePaths]
            )
            return true
        default:
            return false
        }
    }
}
