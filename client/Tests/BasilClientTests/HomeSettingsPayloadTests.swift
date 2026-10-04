import XCTest
@testable import BasilClient

final class HomeSettingsPayloadTests: XCTestCase {
    private func makeModel(id: String, provider: String, isApiModel: Bool) -> ReasoningModelInfo {
        ReasoningModelInfo(id: id, name: id, displayName: id, provider: provider, isApiModel: isApiModel)
    }

    private func makeFields(
        localModels: [ReasoningModelInfo] = [],
        apiModels: [ReasoningModelInfo] = [],
        customModels: [ReasoningModelInfo] = [],
        localTranscriptionModels: [TranscriptionModelOption] = [],
        apiTranscriptionModels: [TranscriptionModelOption] = []
    ) -> HomeSettingsFields {
        HomeSettingsFields(
            setupAssistantPending: true,
            setupAssistantCompleted: false,
            setupAssistantStateAvailable: true,
            permissionsGrantedCount: 3,
            permissionsTotalCount: 5,
            enableMonitoringAtStartup: true,
            enableVoiceListenerAtStartup: false,
            startActivityCaptureAtLaunch: false,
            startMeetingDetectionAtLaunch: true,
            backgroundBehaviorAvailable: true,
            activityCaptureEnabled: true,
            activityCaptureAvailable: true,
            meetingDetectionEnabled: false,
            meetingDetectionAvailable: true,
            proactiveSuggestionsEnabled: true,
            proactiveSuggestionsAvailable: true,
            localModels: localModels,
            apiModels: apiModels,
            customModels: customModels,
            selectedModelId: "local-1",
            useApiModels: false,
            reasoningModelsAvailable: true,
            localTranscriptionModels: localTranscriptionModels,
            apiTranscriptionModels: apiTranscriptionModels,
            selectedTranscriptionModelId: "parakeet-1",
            transcriptionModelsAvailable: true
        )
    }

    func testMapsAllFieldsToCamelCaseKeys() {
        let payload = HomeSettingsPayloadBuilder.makeFieldsPayload(makeFields(
            localModels: [makeModel(id: "local-1", provider: "ollama", isApiModel: false)]
        ))

        XCTAssertEqual(payload["setupAssistantPending"] as? Bool, true)
        XCTAssertEqual(payload["setupAssistantCompleted"] as? Bool, false)
        XCTAssertEqual(payload["setupAssistantStateAvailable"] as? Bool, true)
        XCTAssertEqual(payload["permissionsGrantedCount"] as? Int, 3)
        XCTAssertEqual(payload["permissionsTotalCount"] as? Int, 5)
        XCTAssertEqual(payload["enableMonitoringAtStartup"] as? Bool, true)
        XCTAssertEqual(payload["enableVoiceListenerAtStartup"] as? Bool, false)
        XCTAssertEqual(payload["startActivityCaptureAtLaunch"] as? Bool, false)
        XCTAssertEqual(payload["startMeetingDetectionAtLaunch"] as? Bool, true)
        XCTAssertEqual(payload["backgroundBehaviorAvailable"] as? Bool, true)
        XCTAssertEqual(payload["activityCaptureEnabled"] as? Bool, true)
        XCTAssertEqual(payload["activityCaptureAvailable"] as? Bool, true)
        XCTAssertEqual(payload["meetingDetectionEnabled"] as? Bool, false)
        XCTAssertEqual(payload["meetingDetectionAvailable"] as? Bool, true)
        XCTAssertEqual(payload["proactiveSuggestionsEnabled"] as? Bool, true)
        XCTAssertEqual(payload["proactiveSuggestionsAvailable"] as? Bool, true)
        XCTAssertEqual((payload["localModels"] as? [[String: Any]])?.count, 1)
        XCTAssertEqual(payload["selectedModelId"] as? String, "local-1")
        XCTAssertEqual(payload["useApiModels"] as? Bool, false)
        XCTAssertEqual(payload["reasoningModelsAvailable"] as? Bool, true)
        XCTAssertEqual(payload["selectedTranscriptionModelId"] as? String, "parakeet-1")
        XCTAssertEqual(payload["transcriptionModelsAvailable"] as? Bool, true)
    }

    func testEmptyModelListsProduceEmptyArraysNotNil() {
        let payload = HomeSettingsPayloadBuilder.makeFieldsPayload(makeFields())
        XCTAssertEqual((payload["localModels"] as? [[String: Any]])?.count, 0)
        XCTAssertEqual((payload["apiModels"] as? [[String: Any]])?.count, 0)
        XCTAssertEqual((payload["customModels"] as? [[String: Any]])?.count, 0)
        XCTAssertEqual((payload["localTranscriptionModels"] as? [[String: Any]])?.count, 0)
        XCTAssertEqual((payload["apiTranscriptionModels"] as? [[String: Any]])?.count, 0)
    }

    func testModelPayloadsReuseTheReasoningDefaultsModelInfoShape() {
        let payload = HomeSettingsPayloadBuilder.makeFieldsPayload(makeFields(
            apiModels: [makeModel(id: "gpt-5", provider: "openai", isApiModel: true)]
        ))
        let apiModelPayloads = payload["apiModels"] as? [[String: Any]]
        XCTAssertEqual(apiModelPayloads?.first?["id"] as? String, "gpt-5")
        XCTAssertEqual(apiModelPayloads?.first?["provider"] as? String, "openai")
        XCTAssertEqual(apiModelPayloads?.first?["isApiModel"] as? Bool, true)
    }

    func testTranscriptionModelPayloadIncludesItsPickerFields() {
        let payload = HomeSettingsPayloadBuilder.makeFieldsPayload(makeFields(
            localTranscriptionModels: [
                TranscriptionModelOption(
                    id: "NVIDIA-parakeet",
                    displayName: "Parakeet",
                    isApiModel: false,
                    provider: nil
                )
            ],
            apiTranscriptionModels: [
                TranscriptionModelOption(
                    id: "whisper-1",
                    displayName: "Whisper API",
                    isApiModel: true,
                    provider: "openai"
                )
            ]
        ))

        let localPayload = (payload["localTranscriptionModels"] as? [[String: Any]])?.first
        let apiPayload = (payload["apiTranscriptionModels"] as? [[String: Any]])?.first
        XCTAssertEqual(localPayload?["id"] as? String, "NVIDIA-parakeet")
        XCTAssertEqual(localPayload?["isApiModel"] as? Bool, false)
        XCTAssertNil(localPayload?["provider"])
        XCTAssertEqual(apiPayload?["id"] as? String, "whisper-1")
        XCTAssertEqual(apiPayload?["provider"] as? String, "openai")
    }
}
