import XCTest
@testable import BasilClient

final class ReactMemoryIntelligenceSettingsPayloadTests: XCTestCase {
    func testPatchParsesBooleanFields() {
        let afterTask = ReactMemorySettingPatch(raw: ["field": "memoryAfterTaskEnabled", "value": true])
        guard case .bool(let value) = afterTask?.value else { return XCTFail("Expected bool value") }
        XCTAssertEqual(afterTask?.field, .memoryAfterTaskEnabled)
        XCTAssertTrue(value)

        let daily = ReactMemorySettingPatch(raw: ["field": "memoryDailyEnabled", "value": false])
        guard case .bool(let dailyValue) = daily?.value else { return XCTFail("Expected bool value") }
        XCTAssertFalse(dailyValue)
    }

    func testPatchParsesDailyTimeString() {
        let patch = ReactMemorySettingPatch(raw: ["field": "memoryDailyTimeLocal", "value": "04:15"])
        guard case .string(let value) = patch?.value else { return XCTFail("Expected string value") }
        XCTAssertEqual(patch?.field, .memoryDailyTimeLocal)
        XCTAssertEqual(value, "04:15")
    }

    func testPatchParsesModelStringValue() {
        let patch = ReactMemorySettingPatch(raw: ["field": "memoryProcessingModel", "value": "gpt-5"])
        guard case .nullableString(let value) = patch?.value else { return XCTFail("Expected nullable string value") }
        XCTAssertEqual(value, "gpt-5")
    }

    func testPatchParsesModelNullValueAsDefaultReasoningModel() {
        let patch = ReactMemorySettingPatch(raw: ["field": "memoryProcessingModel", "value": NSNull()])
        guard case .nullableString(let value) = patch?.value else { return XCTFail("Expected nullable string value") }
        XCTAssertNil(value)
    }

    func testPatchRejectsMissingOrBlankModelValue() {
        XCTAssertNil(ReactMemorySettingPatch(raw: ["field": "memoryProcessingModel"]))
        XCTAssertNil(ReactMemorySettingPatch(raw: ["field": "memoryProcessingModel", "value": "   "]))
    }

    func testPatchRejectsUnknownField() {
        XCTAssertNil(ReactMemorySettingPatch(raw: ["field": "notARealField", "value": true]))
    }

    func testPatchRejectsWrongValueTypeForBooleanField() {
        XCTAssertNil(ReactMemorySettingPatch(raw: ["field": "memoryAfterTaskEnabled", "value": "not-a-bool"]))
        XCTAssertNil(ReactMemorySettingPatch(raw: ["field": "memoryAfterTaskEnabled", "value": NSNumber(value: 1)]))
    }

    func testPatchRejectsMissingValueForStringField() {
        XCTAssertNil(ReactMemorySettingPatch(raw: ["field": "memoryDailyTimeLocal"]))
    }

    func testPatchRejectsWrongValueTypeForModelField() {
        XCTAssertNil(ReactMemorySettingPatch(raw: ["field": "memoryProcessingModel", "value": 42]))
    }
}
