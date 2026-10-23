import Foundation

extension AgentTaskCaptureViewModel {
    /// Adds file or folder URLs to the reference paths for AgentTask context.
    /// Filters out duplicates and non-existent paths.
    func addReferencePaths(_ urls: [URL]) {
        let newPaths = urls.filter { url in
            FileManager.default.fileExists(atPath: url.path) &&
            !referencePaths.contains(url)
        }
        guard !newPaths.isEmpty else { return }
        referencePaths.append(contentsOf: newPaths)
        requestCapturePanelResizeForCurrentState()

        #if DEBUG
        DevLogger.shared.info("Added \(newPaths.count) reference paths. Total: \(referencePaths.count)", context: "AgentTaskCapture")
        #endif
    }

    /// Removes a reference path at the specified index.
    func removeReferencePath(at index: Int) {
        guard index >= 0 && index < referencePaths.count else { return }
        let removed = referencePaths.remove(at: index)
        requestCapturePanelResizeForCurrentState()

        #if DEBUG
        DevLogger.shared.info("Removed reference path: \(removed.lastPathComponent)", context: "AgentTaskCapture")
        #endif
    }

    /// Clears all reference paths.
    func clearReferencePaths() {
        guard !referencePaths.isEmpty else { return }
        referencePaths.removeAll()
        requestCapturePanelResizeForCurrentState()

        #if DEBUG
        DevLogger.shared.info("Cleared all reference paths", context: "AgentTaskCapture")
        #endif
    }
}
