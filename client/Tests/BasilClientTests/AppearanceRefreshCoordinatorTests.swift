import XCTest
@testable import BasilClient

@MainActor
final class AppearanceRefreshCoordinatorTests: XCTestCase {
    private final class RefreshProbe: AppearanceRefreshable {
        var refreshCount = 0

        func refreshAppearance() {
            refreshCount += 1
        }
    }

    func testRegisterImmediatelyRefreshesHost() {
        let probe = RefreshProbe()

        AppearanceRefreshCoordinator.shared.register(probe)

        XCTAssertEqual(probe.refreshCount, 1)
        AppearanceRefreshCoordinator.shared.unregister(probe)
    }

    func testAestheticUpdateRefreshesAllRegisteredHosts() {
        let first = RefreshProbe()
        let second = RefreshProbe()
        AppearanceRefreshCoordinator.shared.register(first)
        AppearanceRefreshCoordinator.shared.register(second)

        NotificationCenter.default.post(name: .aestheticSystemUpdated, object: nil)

        XCTAssertEqual(first.refreshCount, 2)
        XCTAssertEqual(second.refreshCount, 2)
        AppearanceRefreshCoordinator.shared.unregister(first)
        AppearanceRefreshCoordinator.shared.unregister(second)
    }

    func testUnregisteredHostDoesNotReceiveUpdates() {
        let probe = RefreshProbe()
        AppearanceRefreshCoordinator.shared.register(probe)
        AppearanceRefreshCoordinator.shared.unregister(probe)

        NotificationCenter.default.post(name: .aestheticSystemUpdated, object: nil)

        XCTAssertEqual(probe.refreshCount, 1)
    }

    func testDeallocatedHostIsPruned() {
        weak var weakProbe: RefreshProbe?
        autoreleasepool {
            let probe = RefreshProbe()
            weakProbe = probe
            AppearanceRefreshCoordinator.shared.register(probe)
        }

        XCTAssertNil(weakProbe)
        XCTAssertEqual(AppearanceRefreshCoordinator.shared.registeredHostCount, 0)
    }

    func testAppearanceUpdateCachesSettingsAndRecordsRevision() {
        WebSocketService.shared.handleAppearanceUpdated([
            "revision": 17,
            "appearance_settings": [
                "background_color_red": 0.2,
                "background_color_green": 0.3,
                "background_color_blue": 0.4,
                "preferred_font": "Menlo",
            ],
        ])

        XCTAssertEqual(APIClient.shared.getCachedAppearanceSettings().preferredFont, "Menlo")
        XCTAssertEqual(AestheticSystem.currentAppearanceRevision, 17)
    }

    func testAppearanceUpdatePostsAestheticSystemNotification() {
        var notificationCount = 0
        let observer = NotificationCenter.default.addObserver(
            forName: .aestheticSystemUpdated,
            object: nil,
            queue: nil
        ) { _ in
            notificationCount += 1
        }
        defer { NotificationCenter.default.removeObserver(observer) }

        WebSocketService.shared.handleAppearanceUpdated([
            "appearance_settings": ["preferred_font": "Arial"],
        ])

        XCTAssertEqual(notificationCount, 1)
    }

    func testMalformedAppearanceUpdateDoesNotChangeRevision() {
        let initialRevision = AestheticSystem.currentAppearanceRevision

        WebSocketService.shared.handleAppearanceUpdated([
            "revision": initialRevision + 1,
            "appearance_settings": ["preferred_font": 42],
        ])

        XCTAssertEqual(AestheticSystem.currentAppearanceRevision, initialRevision)
    }
}
