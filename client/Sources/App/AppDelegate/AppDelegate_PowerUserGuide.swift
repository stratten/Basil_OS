import AppKit

extension AppDelegate {
    @MainActor
    func presentPowerUserGuideWindowFromDelegate() {
        PowerUserGuideWindowController.shared.show()
    }
}
