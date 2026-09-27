import Foundation

extension AppDelegate {
    @MainActor
    func showBasilBoard() {
        statusBarManager?.windowCoordinator.openBasilBoard()
    }
}
