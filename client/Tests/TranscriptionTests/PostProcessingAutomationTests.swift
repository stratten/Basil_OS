import XCTest
@testable import BasilClient

final class PostProcessingAutomationTests: XCTestCase {

    func testShouldAutoRetranscribeRequiresEnabledAndAudio() {
        XCTAssertTrue(PostProcessingAutomation.shouldAutoRetranscribeOnStop(enabled: true, hasRecordedAudio: true))
        // Disabled → never.
        XCTAssertFalse(PostProcessingAutomation.shouldAutoRetranscribeOnStop(enabled: false, hasRecordedAudio: true))
        // No audio → nothing to upgrade.
        XCTAssertFalse(PostProcessingAutomation.shouldAutoRetranscribeOnStop(enabled: true, hasRecordedAudio: false))
    }

    func testPlanRetranscribeOnly() {
        XCTAssertEqual(
            PostProcessingAutomation.plan(autoRetranscribe: true, autoAnalyze: false, timing: "after"),
            [.retranscribe]
        )
    }

    func testPlanAnalyzeOnly() {
        XCTAssertEqual(
            PostProcessingAutomation.plan(autoRetranscribe: false, autoAnalyze: true, timing: "after"),
            [.analyze]
        )
    }

    func testPlanBothAfterOrdersRetranscribeThenAnalyze() {
        XCTAssertEqual(
            PostProcessingAutomation.plan(autoRetranscribe: true, autoAnalyze: true, timing: "after"),
            [.retranscribe, .analyze]
        )
    }

    func testPlanBothUnknownTimingDefaultsToAfterOrder() {
        XCTAssertEqual(
            PostProcessingAutomation.plan(autoRetranscribe: true, autoAnalyze: true, timing: "unexpected"),
            [.retranscribe, .analyze]
        )
    }

    func testPlanBothBeforeOrdersAnalyzeThenRetranscribe() {
        XCTAssertEqual(
            PostProcessingAutomation.plan(autoRetranscribe: true, autoAnalyze: true, timing: "before"),
            [.analyze, .retranscribe]
        )
    }

    func testExecutionModelUsesConfiguredAPIIdentifierBeforePickerCatalogLoads() {
        XCTAssertEqual(
            PostProcessingAutomation.executionModel(
                configuredModelID: "openai-whisper-1",
                sessionModel: ""
            ),
            "openai-whisper-1"
        )
    }

    func testExecutionModelPreservesPerSessionPickerChoiceAndCadenceArmsWithoutCatalog() {
        XCTAssertEqual(
            PostProcessingAutomation.executionModel(
                configuredModelID: "openai-whisper-1",
                sessionModel: "Whisper (OpenAI API)"
            ),
            "Whisper (OpenAI API)"
        )
        XCTAssertTrue(PostProcessingAutomation.shouldArmMidRecordingCadence(enabled: true))
        XCTAssertFalse(PostProcessingAutomation.shouldArmMidRecordingCadence(enabled: false))
    }

    // Adversarial: nothing enabled → empty plan (no automatic work).
    func testPlanNeitherIsEmpty() {
        XCTAssertTrue(
            PostProcessingAutomation.plan(autoRetranscribe: false, autoAnalyze: false, timing: "after").isEmpty
        )
    }
}
