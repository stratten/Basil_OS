import XCTest
@testable import BasilClient

final class ReactCloudTranscriptionBridgeTests: XCTestCase {
    func testSettingsPatchAcceptsEveryAllowedField() {
        let patch = CloudTranscriptionIntentParser.settingsPatch(from: [
            "enabled": true,
            "acknowledge_disclosure": true,
            "provider": "assemblyai",
            "connection": "basil_account",
        ])
        XCTAssertEqual(patch?["enabled"] as? Bool, true)
        XCTAssertEqual(patch?["acknowledge_disclosure"] as? Bool, true)
        XCTAssertEqual(patch?["provider"] as? String, "assemblyai")
        XCTAssertEqual(patch?["connection"] as? String, "basil_account")
    }

    func testSettingsPatchAcceptsAnEmptyPatch() {
        XCTAssertEqual(CloudTranscriptionIntentParser.settingsPatch(from: [:] as [String: Any])?.count, 0)
    }

    func testSettingsPatchRejectsUnknownKeysWrongTypesAndUnknownValues() {
        XCTAssertNil(CloudTranscriptionIntentParser.settingsPatch(from: ["api_key": "secret"]))
        XCTAssertNil(CloudTranscriptionIntentParser.settingsPatch(from: ["enabled": "yes"]))
        XCTAssertNil(CloudTranscriptionIntentParser.settingsPatch(from: ["provider": "../etc"]))
        XCTAssertNil(CloudTranscriptionIntentParser.settingsPatch(from: ["connection": "other"]))
        XCTAssertNil(CloudTranscriptionIntentParser.settingsPatch(from: "not an object"))
        XCTAssertNil(CloudTranscriptionIntentParser.settingsPatch(from: nil))
    }

    func testProviderOnlyAcceptsKnownProviders() {
        XCTAssertEqual(CloudTranscriptionIntentParser.provider(from: "deepgram"), "deepgram")
        XCTAssertEqual(CloudTranscriptionIntentParser.provider(from: "assemblyai"), "assemblyai")
        XCTAssertNil(CloudTranscriptionIntentParser.provider(from: "deepgram/../keys"))
        XCTAssertNil(CloudTranscriptionIntentParser.provider(from: ""))
        XCTAssertNil(CloudTranscriptionIntentParser.provider(from: 7))
        XCTAssertNil(CloudTranscriptionIntentParser.provider(from: nil))
    }

    func testDecodeReturnsTheBackendObjectOnSuccess() {
        let data = Data(#"{"enabled": true, "provider": "deepgram"}"#.utf8)
        guard case .success(let object) = CloudTranscriptionOutcome.decode(statusCode: 200, data: data) else {
            return XCTFail("expected success")
        }
        XCTAssertEqual(object["enabled"] as? Bool, true)
        XCTAssertEqual(object["provider"] as? String, "deepgram")
    }

    func testDecodeReadsTheBackendDetailMessage() {
        let data = Data(#"{"detail": "Add a Deepgram API key first."}"#.utf8)
        guard case .failure(let message) = CloudTranscriptionOutcome.decode(statusCode: 409, data: data) else {
            return XCTFail("expected failure")
        }
        XCTAssertEqual(message, "Add a Deepgram API key first.")
    }

    func testDecodeUsesAFriendlyMessageForValidationFailures() {
        let data = Data(#"{"detail": [{"loc": ["body", "api_key"], "msg": "too short"}]}"#.utf8)
        guard case .failure(let message) = CloudTranscriptionOutcome.decode(statusCode: 422, data: data) else {
            return XCTFail("expected failure")
        }
        XCTAssertEqual(message, "Basil did not accept that value. Check it and try again.")
    }

    func testDecodeNamesTheStatusWhenThereIsNoDetail() {
        guard case .failure(let message) = CloudTranscriptionOutcome.decode(statusCode: 500, data: Data()) else {
            return XCTFail("expected failure")
        }
        XCTAssertEqual(message, "The cloud transcription request failed (status 500).")
    }

    func testDecodeRejectsASuccessBodyThatIsNotAnObject() {
        guard case .failure = CloudTranscriptionOutcome.decode(statusCode: 200, data: Data("[]".utf8)) else {
            return XCTFail("expected failure")
        }
        guard case .failure = CloudTranscriptionOutcome.decode(statusCode: 200, data: Data()) else {
            return XCTFail("expected failure")
        }
    }
}
