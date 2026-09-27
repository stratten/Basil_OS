import XCTest
@testable import BasilClient

final class ZettelSettingsDataTests: XCTestCase {
    func testOfflineDefaultsEnableMeetingCards() {
        XCTAssertTrue(ZettelSettingsData.defaults.enabledSources.contains("meeting"))
    }
}
