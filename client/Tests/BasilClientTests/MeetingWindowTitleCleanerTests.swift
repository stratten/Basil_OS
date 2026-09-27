import XCTest
@testable import BasilClient

final class MeetingWindowTitleCleanerTests: XCTestCase {
    func testStripsTrailingAppNameSuffix() {
        let result = MeetingWindowTitleCleaner.cleanedTitle(rawWindowTitle: "Google Meet - Microsoft Edge", appName: "Microsoft Edge")
        XCTAssertEqual(result, "Google Meet")
    }

    func testSuffixMatchIsCaseInsensitive() {
        let result = MeetingWindowTitleCleaner.cleanedTitle(rawWindowTitle: "Google Meet - microsoft edge", appName: "Microsoft Edge")
        XCTAssertEqual(result, "Google Meet")
    }

    func testReturnsNilWhenTitleIsJustTheAppName() {
        let result = MeetingWindowTitleCleaner.cleanedTitle(rawWindowTitle: "Microsoft Edge", appName: "Microsoft Edge")
        XCTAssertNil(result)
    }

    func testReturnsNilForEmptyOrNilTitle() {
        XCTAssertNil(MeetingWindowTitleCleaner.cleanedTitle(rawWindowTitle: "", appName: "Zoom"))
        XCTAssertNil(MeetingWindowTitleCleaner.cleanedTitle(rawWindowTitle: nil, appName: "Zoom"))
    }

    func testPreservesTitleWithoutAppNameSuffix() {
        let result = MeetingWindowTitleCleaner.cleanedTitle(rawWindowTitle: "Product Sync - Engineering", appName: "Zoom")
        XCTAssertEqual(result, "Product Sync - Engineering")
    }

    func testPreservesLegitimateHyphenBeforeAppNameSuffix() {
        let result = MeetingWindowTitleCleaner.cleanedTitle(rawWindowTitle: "Product Sync - Engineering - Microsoft Edge", appName: "Microsoft Edge")
        XCTAssertEqual(result, "Product Sync - Engineering")
    }
}
