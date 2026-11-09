import XCTest
@testable import BasilClient

final class NativeCommandParserTests: XCTestCase {
    func testOpenSettingsWithoutATabIsAccepted() {
        XCTAssertEqual(NativeCommandParser.parse(["verb": "open_settings", "params": [:]]), .success(.openSettings(tab: nil)))
        XCTAssertEqual(NativeCommandParser.parse(["verb": "open_settings"]), .success(.openSettings(tab: nil)))
    }

    func testOpenSettingsWithAListedTabIsAccepted() {
        XCTAssertEqual(NativeCommandParser.parse(["verb": "open_settings", "params": ["tab": "appearance"]]), .success(.openSettings(tab: "appearance")))
    }

    func testEveryListedTabIsAccepted() {
        for tab in NativeCommandParser.settingsTabs {
            XCTAssertEqual(NativeCommandParser.parse(["verb": "open_settings", "params": ["tab": tab]]), .success(.openSettings(tab: tab)))
        }
    }

    func testAnUnlistedTabIsRefused() {
        for tab in ["", "../secrets", "Appearance", "unknown"] {
            guard case .failure = NativeCommandParser.parse(["verb": "open_settings", "params": ["tab": tab]]) else {
                return XCTFail("\(tab) should be refused")
            }
        }
    }

    func testANonStringTabAndExtraParametersAreRefused() {
        guard case .failure = NativeCommandParser.parse(["verb": "open_settings", "params": ["tab": 5]]) else { return XCTFail("a number is not a tab") }
        guard case .failure = NativeCommandParser.parse(["verb": "open_settings", "params": ["tab": "models", "url": "https://example.com"]]) else { return XCTFail("extra parameters are refused") }
    }

    func testAnUnknownOrMissingVerbIsRefused() {
        guard case .failure = NativeCommandParser.parse(["verb": "quit"]) else { return XCTFail("quit is not a verb") }
        guard case .failure = NativeCommandParser.parse(["params": [:]]) else { return XCTFail("a verb is required") }
    }
}
