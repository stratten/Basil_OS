import AppKit
import Foundation
import UniformTypeIdentifiers

/// Decides how bridge-originated open requests are honored so web content can never launch code directly.
enum BridgeOpenPolicy {
    enum LocalFileAction: Equatable {
        case open
        case revealInFinder
        case missing
    }

    enum ExternalURLAction: Equatable {
        case open
        case localFile
        case refuse
    }

    static let revealOnlyExtensions: Set<String> = [
        "action", "app", "applescript", "bash", "bat", "bundle", "cjs", "cmd", "command", "csh", "dmg",
        "dylib", "exe", "fileloc", "img", "inetloc", "iso", "jar", "js", "kext", "ksh", "mjs", "mpkg",
        "msi", "osax", "php", "pkg", "pl", "plugin", "prefpane", "ps1", "py", "rb", "scpt", "scptd",
        "service", "sh", "shortcut", "so", "terminal", "tool", "url", "vbs", "webloc", "workflow", "zsh",
    ]

    static func localFileAction(for fileURL: URL, fileManager: FileManager = .default) -> LocalFileAction {
        let path = fileURL.standardizedFileURL.path
        var isDirectory: ObjCBool = false
        guard fileManager.fileExists(atPath: path, isDirectory: &isDirectory) else {
            return .missing
        }
        let pathExtension = URL(fileURLWithPath: path).pathExtension.lowercased()
        if revealOnlyExtensions.contains(pathExtension) {
            return .revealInFinder
        }
        if isDirectory.boolValue {
            return NSWorkspace.shared.isFilePackage(atPath: path) ? .revealInFinder : .open
        }
        if fileManager.isExecutableFile(atPath: path) {
            return .revealInFinder
        }
        if let type = UTType(filenameExtension: pathExtension),
           type.conforms(to: .executable) || type.conforms(to: .script) || type.conforms(to: .application) {
            return .revealInFinder
        }
        return .open
    }

    static func externalURLAction(for url: URL) -> ExternalURLAction {
        switch url.scheme?.lowercased() {
        case "http", "https", "mailto":
            return .open
        case "file":
            return .localFile
        default:
            return .refuse
        }
    }

    @discardableResult
    static func openLocalFile(_ fileURL: URL, workspace: NSWorkspace = .shared) -> Bool {
        let standardizedURL = fileURL.standardizedFileURL
        switch localFileAction(for: standardizedURL) {
        case .open:
            return workspace.open(standardizedURL)
        case .revealInFinder:
            workspace.activateFileViewerSelecting([standardizedURL])
            return true
        case .missing:
            return false
        }
    }

    @discardableResult
    static func openExternalURL(_ url: URL, workspace: NSWorkspace = .shared) -> Bool {
        switch externalURLAction(for: url) {
        case .open:
            return workspace.open(url)
        case .localFile:
            return openLocalFile(url, workspace: workspace)
        case .refuse:
            return false
        }
    }
}
