import XCTest
@testable import BasilClient

final class TranscriptionSettingsPreservationTests: XCTestCase {

    private func sampleSettingsWithAutomation() -> TranscriptionSettings {
        TranscriptionSettings(
            modelUnloadDelay: 120,
            autoPaste: true,
            autoCloseOnPaste: true,
            language: "en",
            selectedModel: "base",
            widgetSize: WidgetSize(width: 400, height: 300),
            widgetPosition: WidgetPosition(x: 10, y: 20, screenID: 1),
            isWidgetMinimized: false,
            enablePushToTalk: true,
            pushToTalkThresholdMs: 1000,
            autoRetranscribeOnStop: true,
            autoRetranscribeDuringRecording: true,
            retranscribeWindowSeconds: 180,
            autoAnalyzeOnComplete: true,
            autoAnalyzeModes: ["summary", "action_items", "suggested_actions"],
            autoAnalyzeCustomInstructions: "Focus on follow-ups",
            autoAnalyzeTiming: "before",
            textReplacements: [
                TranscriptionTextReplacementRule(source: "slash", replacement: "/"),
            ]
        )
    }

    func testApplyingOverridesOnlySpecifiedField() {
        let original = sampleSettingsWithAutomation()
        let newSize = WidgetSize(width: 142, height: 73)

        let updated = original.applying(widgetSize: newSize)

        XCTAssertEqual(updated.widgetSize, newSize)
        XCTAssertEqual(updated.autoRetranscribeOnStop, original.autoRetranscribeOnStop)
        XCTAssertEqual(updated.autoRetranscribeDuringRecording, original.autoRetranscribeDuringRecording)
        XCTAssertEqual(updated.retranscribeWindowSeconds, original.retranscribeWindowSeconds)
        XCTAssertEqual(updated.autoAnalyzeOnComplete, original.autoAnalyzeOnComplete)
        XCTAssertEqual(updated.autoAnalyzeModes, original.autoAnalyzeModes)
        XCTAssertEqual(updated.autoAnalyzeCustomInstructions, original.autoAnalyzeCustomInstructions)
        XCTAssertEqual(updated.autoAnalyzeTiming, original.autoAnalyzeTiming)
        XCTAssertEqual(updated.selectedModel, original.selectedModel)
        XCTAssertEqual(updated.textReplacements, original.textReplacements)
    }

    func testApplyingWidgetPositionPreservesAutomationFields() {
        let original = sampleSettingsWithAutomation()
        let newPosition = WidgetPosition(x: 148, y: 0, screenID: 1)

        let updated = original.applying(widgetPosition: newPosition)

        XCTAssertEqual(updated.widgetPosition, newPosition)
        XCTAssertEqual(updated.autoAnalyzeOnComplete, true)
        XCTAssertEqual(updated.autoAnalyzeModes, ["summary", "action_items", "suggested_actions"])
        XCTAssertEqual(updated.autoAnalyzeTiming, "before")
        XCTAssertEqual(updated.autoRetranscribeOnStop, true)
        XCTAssertEqual(updated.textReplacements, original.textReplacements)
    }

    func testApplyingSelectedModelPreservesAutomationFields() {
        let original = sampleSettingsWithAutomation()

        let updated = original.applying(selectedModel: "openai-whisper-1")

        XCTAssertEqual(updated.selectedModel, "openai-whisper-1")
        XCTAssertEqual(updated.autoAnalyzeOnComplete, original.autoAnalyzeOnComplete)
        XCTAssertEqual(updated.autoAnalyzeModes, original.autoAnalyzeModes)
        XCTAssertEqual(updated.autoAnalyzeCustomInstructions, original.autoAnalyzeCustomInstructions)
        XCTAssertEqual(updated.autoAnalyzeTiming, original.autoAnalyzeTiming)
        XCTAssertEqual(updated.retranscribeWindowSeconds, original.retranscribeWindowSeconds)
        XCTAssertEqual(updated.textReplacements, original.textReplacements)
    }

    func testApplyingTextReplacementsOverridesOnlyThatField() {
        let original = sampleSettingsWithAutomation()
        let replacementRules = [
            TranscriptionTextReplacementRule(source: "dash", replacement: "-"),
        ]

        let updated = original.applying(textReplacements: replacementRules)

        XCTAssertEqual(updated.textReplacements, replacementRules)
        XCTAssertEqual(updated.selectedModel, original.selectedModel)
        XCTAssertEqual(updated.widgetSize, original.widgetSize)
        XCTAssertEqual(updated.autoAnalyzeModes, original.autoAnalyzeModes)
    }

    func testApplyingWithNoOverridesReturnsEquivalentCopy() {
        let original = sampleSettingsWithAutomation()

        let copy = original.applying()

        XCTAssertEqual(copy.modelUnloadDelay, original.modelUnloadDelay)
        XCTAssertEqual(copy.autoPaste, original.autoPaste)
        XCTAssertEqual(copy.autoCloseOnPaste, original.autoCloseOnPaste)
        XCTAssertEqual(copy.language, original.language)
        XCTAssertEqual(copy.selectedModel, original.selectedModel)
        XCTAssertEqual(copy.widgetSize, original.widgetSize)
        XCTAssertEqual(copy.widgetPosition, original.widgetPosition)
        XCTAssertEqual(copy.isWidgetMinimized, original.isWidgetMinimized)
        XCTAssertEqual(copy.enablePushToTalk, original.enablePushToTalk)
        XCTAssertEqual(copy.pushToTalkThresholdMs, original.pushToTalkThresholdMs)
        XCTAssertEqual(copy.autoRetranscribeOnStop, original.autoRetranscribeOnStop)
        XCTAssertEqual(copy.autoRetranscribeDuringRecording, original.autoRetranscribeDuringRecording)
        XCTAssertEqual(copy.retranscribeWindowSeconds, original.retranscribeWindowSeconds)
        XCTAssertEqual(copy.autoAnalyzeOnComplete, original.autoAnalyzeOnComplete)
        XCTAssertEqual(copy.autoAnalyzeModes, original.autoAnalyzeModes)
        XCTAssertEqual(copy.autoAnalyzeCustomInstructions, original.autoAnalyzeCustomInstructions)
        XCTAssertEqual(copy.autoAnalyzeTiming, original.autoAnalyzeTiming)
        XCTAssertEqual(copy.textReplacements, original.textReplacements)
    }

    func testCompactPreferenceRoundTripRetainsExpandedWidgetSize() {
        let original = sampleSettingsWithAutomation()
        let expandedSize = WidgetSize(width: 400, height: 300)

        let compact = original.applying(isWidgetMinimized: true)
        let reexpanded = compact.applying(isWidgetMinimized: false)

        XCTAssertTrue(compact.isWidgetMinimized)
        XCTAssertFalse(reexpanded.isWidgetMinimized)
        XCTAssertEqual(compact.widgetSize, expandedSize)
        XCTAssertEqual(reexpanded.widgetSize, expandedSize)
    }

    func testBackendTranscriptionSettingsDecodeWithDefaultKeysPreservesAutomationFields() throws {
        let payload = """
        {
          "status": "success",
          "settings": {
            "model_unload_delay": 60,
            "auto_paste": true,
            "auto_close_on_paste": false,
            "language": "en",
            "selected_model": "openai-whisper-1",
            "widget_size": [142, 73],
            "widget_position": [154.0, 2.0, 1],
            "is_widget_minimized": true,
            "enable_push_to_talk": false,
            "push_to_talk_threshold_ms": 750,
            "auto_retranscribe_on_stop": true,
            "auto_retranscribe_during_recording": true,
            "retranscribe_window_seconds": 300,
            "auto_analyze_on_complete": true,
            "auto_analyze_modes": ["summary", "action_items", "suggested_actions"],
            "auto_analyze_custom_instructions": "",
            "auto_analyze_timing": "after",
            "text_replacements": [{"source": "slash", "replacement": "/"}]
          }
        }
        """
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .useDefaultKeys

        let response = try decoder.decode(
            TranscriptionSettingsResponse.self,
            from: Data(payload.utf8)
        )

        XCTAssertTrue(response.settings.autoRetranscribeOnStop)
        XCTAssertTrue(response.settings.autoRetranscribeDuringRecording)
        XCTAssertEqual(response.settings.retranscribeWindowSeconds, 300)
        XCTAssertTrue(response.settings.autoAnalyzeOnComplete)
        XCTAssertEqual(response.settings.autoAnalyzeModes, ["summary", "action_items", "suggested_actions"])
        XCTAssertEqual(response.settings.autoAnalyzeTiming, "after")
        XCTAssertEqual(
            response.settings.textReplacements,
            [TranscriptionTextReplacementRule(source: "slash", replacement: "/")]
        )
    }

    func testBackendTranscriptionSettingsDecodeWithoutTextReplacementsDefaultsToEmpty() throws {
        let payload = """
        {
          "status": "success",
          "settings": {
            "model_unload_delay": 60,
            "auto_paste": true,
            "auto_close_on_paste": false,
            "language": "en",
            "selected_model": "openai-whisper-1",
            "widget_size": [142, 73],
            "widget_position": [154.0, 2.0, 1],
            "is_widget_minimized": true,
            "enable_push_to_talk": false,
            "push_to_talk_threshold_ms": 750,
            "auto_retranscribe_on_stop": true,
            "auto_retranscribe_during_recording": true,
            "retranscribe_window_seconds": 300,
            "auto_analyze_on_complete": true,
            "auto_analyze_modes": ["summary"],
            "auto_analyze_custom_instructions": "",
            "auto_analyze_timing": "after"
          }
        }
        """
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .useDefaultKeys

        let response = try decoder.decode(
            TranscriptionSettingsResponse.self,
            from: Data(payload.utf8)
        )

        XCTAssertEqual(response.settings.textReplacements, [])
    }

    func testBackendTranscriptionSettingsDecodeFailsWithConvertFromSnakeCase() {
        let payload = """
        {
          "status": "success",
          "settings": {
            "model_unload_delay": 60,
            "auto_paste": true,
            "auto_close_on_paste": false,
            "language": "en",
            "selected_model": "openai-whisper-1",
            "widget_size": [142, 73],
            "widget_position": [154.0, 2.0, 1],
            "is_widget_minimized": true,
            "enable_push_to_talk": false,
            "push_to_talk_threshold_ms": 750,
            "auto_retranscribe_on_stop": true,
            "auto_retranscribe_during_recording": true,
            "retranscribe_window_seconds": 300,
            "auto_analyze_on_complete": true,
            "auto_analyze_modes": ["summary"],
            "auto_analyze_custom_instructions": "",
            "auto_analyze_timing": "after"
          }
        }
        """
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase

        XCTAssertThrowsError(
            try decoder.decode(TranscriptionSettingsResponse.self, from: Data(payload.utf8))
        )
    }
}
