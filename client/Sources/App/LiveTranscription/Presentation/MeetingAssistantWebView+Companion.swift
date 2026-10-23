import AppKit
import Foundation

extension MeetingAssistantWebView {
    /// Delivers filesystem paths from a Finder drop or the folder picker to the page. WebKit never exposes file paths to JavaScript, so this AppKit-level callback is the only source of absolute paths.
    func sendCompanionPaths(_ paths: [String], source: String) {
        let cleaned = paths.filter { !$0.isEmpty }
        guard !cleaned.isEmpty else { return }
        let payload: [String: Any] = ["paths": cleaned, "source": source]
        callJS("window.basilMeetingAssistant?.onFilesDropped", args: payload)
    }

    /// Lets the user choose folders or files the Companion may read for context. Read-only: the backend validates every path again before attaching it.
    func presentCompanionFolderPicker() {
        let panel = NSOpenPanel()
        panel.applyBasilThemedAppearance()
        panel.canChooseFiles = true
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = true
        panel.prompt = "Use as Context"
        panel.message = "Choose folders or files the Companion may search during this meeting. They are only read, never changed."
        panel.begin { [weak self] response in
            guard response == .OK else { return }
            self?.sendCompanionPaths(panel.urls.map(\.path), source: "picker")
        }
    }
}
