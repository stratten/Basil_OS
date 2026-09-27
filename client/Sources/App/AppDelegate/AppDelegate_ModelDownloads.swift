import Foundation

// MARK: - Model Download Widget

extension AppDelegate {
    /// Show the floating model download mini widget when the global monitor
    /// observes download activity from any application surface.
    @MainActor
    func showModelDownloadWidget() {
        if modelDownloadWindowController == nil {
            modelDownloadWindowController = ModelDownloadWindowController()
        }
        modelDownloadWindowController?.show()
    }

    /// Dismiss the mini widget when the global monitor has no active or
    /// recently terminal download state left to display.
    @MainActor
    func hideModelDownloadWidgetIfNeeded() {
        guard let controller = modelDownloadWindowController, controller.isVisible else { return }
        controller.dismiss()
    }
}
