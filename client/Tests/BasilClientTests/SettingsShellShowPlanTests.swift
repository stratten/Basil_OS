import XCTest
@testable import BasilClient

final class SettingsShellShowPlanTests: XCTestCase {
    func testNoLiveWindowBuildsAndLoads() {
        XCTAssertEqual(SettingsShellShowPlan.resolve(hasLiveWindow: false, pageIsReady: false), .buildAndLoad)
    }

    func testStaleReadyFlagWithoutALiveWindowStillBuildsAndLoads() {
        XCTAssertEqual(SettingsShellShowPlan.resolve(hasLiveWindow: false, pageIsReady: true), .buildAndLoad)
    }

    func testOpenWindowWithReadyPageReusesItWithoutReloading() {
        XCTAssertEqual(SettingsShellShowPlan.resolve(hasLiveWindow: true, pageIsReady: true), .reuseLoadedPage)
    }

    func testOpenWindowStillLoadingWaitsForItsOwnReadyEvent() {
        XCTAssertEqual(SettingsShellShowPlan.resolve(hasLiveWindow: true, pageIsReady: false), .reuseLoadingPage)
    }
}
