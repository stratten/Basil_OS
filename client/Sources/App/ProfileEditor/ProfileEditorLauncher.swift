import Foundation

final class ProfileEditorLauncher {
    static let shared = ProfileEditorLauncher()

    private var activeControllers: [String: ProfileEditorWindowController] = [:]

    private init() {}

    @MainActor
    func open(_ request: ProfileEditorRequest, onClose: @escaping (Bool) -> Void) {
        let key = request.windowKey
        if let controller = activeControllers[key] {
            controller.show()
            return
        }
        var controller: ProfileEditorWindowController!
        controller = ProfileEditorWindowController(request: request) { [weak self, weak controller] didChange in
            onClose(didChange)
            if self?.activeControllers[key] === controller {
                self?.activeControllers[key] = nil
            }
        }
        activeControllers[key] = controller
        controller.show()
    }
}
