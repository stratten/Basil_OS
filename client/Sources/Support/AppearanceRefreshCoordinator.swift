import Foundation

@MainActor
protocol AppearanceRefreshable: AnyObject {
    func refreshAppearance()
}

@MainActor
final class AppearanceRefreshCoordinator {
    static let shared = AppearanceRefreshCoordinator()

    private var hosts: [ObjectIdentifier: WeakAppearanceRefreshableBox] = [:]
    private var notificationObserver: NSObjectProtocol?

    private init() {
        notificationObserver = NotificationCenter.default.addObserver(
            forName: .aestheticSystemUpdated,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated {
                self?.refreshAll()
            }
        }
    }

    func register(_ host: AppearanceRefreshable) {
        hosts[ObjectIdentifier(host)] = WeakAppearanceRefreshableBox(host)
        host.refreshAppearance()
    }

    func unregister(_ host: AppearanceRefreshable) {
        hosts.removeValue(forKey: ObjectIdentifier(host))
    }

    var registeredHostCount: Int {
        pruneDeallocatedHosts()
        return hosts.count
    }

    private func refreshAll() {
        for (id, box) in hosts {
            guard let host = box.host else {
                hosts.removeValue(forKey: id)
                continue
            }
            host.refreshAppearance()
        }
    }

    private func pruneDeallocatedHosts() {
        hosts = hosts.filter { $0.value.host != nil }
    }
}

private struct WeakAppearanceRefreshableBox {
    weak var host: AppearanceRefreshable?

    init(_ host: AppearanceRefreshable) {
        self.host = host
    }
}
