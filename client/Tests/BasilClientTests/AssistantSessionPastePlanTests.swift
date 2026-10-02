import XCTest
@testable import BasilClient

final class AssistantSessionPastePlanTests: XCTestCase {
    private let sourcePID: pid_t = 101
    private let basilPID: pid_t = 202
    private let otherPID: pid_t = 303

    private func plan(
        mode: AssistantOutputPasteMode,
        decision: String? = nil,
        hasOutput: Bool = true,
        hasSource: Bool = true,
        frontmost: pid_t?
    ) -> AssistantSessionPastePlan {
        resolveAssistantSessionPastePlan(
            mode: mode,
            decision: decision,
            hasOutput: hasOutput,
            sourceProcessIdentifier: hasSource ? sourcePID : nil,
            frontmostProcessIdentifier: frontmost,
            basilProcessIdentifier: basilPID
        )
    }

    func testAlwaysPastesWhenSourceAppIsFrontmost() {
        XCTAssertEqual(plan(mode: .always, frontmost: sourcePID), .pasteNow)
    }

    func testAlwaysReactivatesSourceWhenBasilIsFrontmost() {
        XCTAssertEqual(plan(mode: .always, frontmost: basilPID), .reactivateThenPaste)
    }

    func testAlwaysSkipsWhenUserSwitchedToAnotherApp() {
        XCTAssertEqual(plan(mode: .always, frontmost: otherPID), .skip(.switchedApps))
        XCTAssertEqual(plan(mode: .always, frontmost: nil), .skip(.switchedApps))
    }

    func testAlwaysSkipsWithoutASourceApp() {
        XCTAssertEqual(plan(mode: .always, hasSource: false, frontmost: basilPID), .skip(.targetUnavailable))
    }

    func testEmptyOutputIsNeverPasted() {
        XCTAssertEqual(plan(mode: .always, hasOutput: false, frontmost: sourcePID), .skip(nil))
    }

    func testNeverModeReportsNothing() {
        XCTAssertEqual(plan(mode: .never, decision: "insert", frontmost: sourcePID), .skip(nil))
    }

    func testAutoPastesOnlyOnInsert() {
        XCTAssertEqual(plan(mode: .auto, decision: "insert", frontmost: sourcePID), .pasteNow)
        XCTAssertEqual(plan(mode: .auto, decision: "insert", frontmost: basilPID), .reactivateThenPaste)
        XCTAssertEqual(plan(mode: .auto, decision: "show", frontmost: sourcePID), .skip(.shown))
        XCTAssertEqual(plan(mode: .auto, decision: nil, frontmost: sourcePID), .skip(.shown))
        XCTAssertEqual(plan(mode: .auto, decision: "INSERT", frontmost: sourcePID), .skip(.shown))
    }

    func testAutoInsertStillHonorsTheSafeguard() {
        XCTAssertEqual(plan(mode: .auto, decision: "insert", frontmost: otherPID), .skip(.switchedApps))
        XCTAssertEqual(plan(mode: .auto, decision: "insert", hasSource: false, frontmost: sourcePID), .skip(.targetUnavailable))
    }

    func testReasoningSettingsModelDecodesPasteMode() throws {
        let json = #"{"persistence_duration":300,"vision_model":"","language_model":"l","reasoning_model":"r","transcription_model":"t","use_api_models":false,"close_assistant_session_on_insert":true,"assistant_output_paste_mode":"auto","use_region_selection":false}"#
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let settings = try decoder.decode(ReasoningSettingsModel.self, from: Data(json.utf8))
        XCTAssertEqual(settings.assistantOutputPasteMode, .auto)
        XCTAssertTrue(settings.closeAssistantSessionOnInsert)
    }

    func testReasoningSettingsModelRejectsUnknownPasteMode() {
        let json = #"{"persistence_duration":300,"vision_model":"","language_model":"l","reasoning_model":"r","transcription_model":"t","use_api_models":false,"close_assistant_session_on_insert":true,"assistant_output_paste_mode":"sometimes","use_region_selection":false}"#
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        XCTAssertThrowsError(try decoder.decode(ReasoningSettingsModel.self, from: Data(json.utf8)))
    }
}
