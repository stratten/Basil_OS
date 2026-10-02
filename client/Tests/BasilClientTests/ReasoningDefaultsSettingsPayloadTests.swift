import XCTest
@testable import BasilClient

final class ReasoningDefaultsSettingsPayloadTests: XCTestCase {
    private func makeModel(id: String, provider: String, isApiModel: Bool) -> ReasoningModelInfo {
        ReasoningModelInfo(id: id, name: id, displayName: id, provider: provider, isApiModel: isApiModel)
    }

    func testMapsAllFieldsToCamelCaseKeysWithRawEnumValues() {
        let payload = ReasoningDefaultsSettingsPayloadBuilder.makeSettingsPayload(
            localModels: [makeModel(id: "local-1", provider: "ollama", isApiModel: false)],
            apiModels: [makeModel(id: "gpt-5", provider: "openai", isApiModel: true)],
            customModels: [makeModel(id: "custom-1", provider: "custom", isApiModel: true)],
            selectedModelId: "gpt-5",
            useApiModels: true,
            closeAssistantSessionOnInsert: true,
            assistantOutputPasteMode: .auto,
            useRegionSelection: true,
            agentTaskDefaultModality: .text,
            agentTaskAutoReopenOnCompletion: false,
            agentTaskPushToTalk: true,
            agentTaskPushToTalkThreshold: 1200,
            assistantSessionDefaultModality: .type,
            assistantSessionPushToTalk: false,
            assistantSessionPushToTalkThreshold: 900
        )

        XCTAssertEqual((payload["localModels"] as? [[String: Any]])?.count, 1)
        XCTAssertEqual((payload["apiModels"] as? [[String: Any]])?.count, 1)
        XCTAssertEqual((payload["customModels"] as? [[String: Any]])?.count, 1)
        XCTAssertEqual(payload["selectedModelId"] as? String, "gpt-5")
        XCTAssertEqual(payload["useApiModels"] as? Bool, true)
        XCTAssertEqual(payload["closeAssistantSessionOnInsert"] as? Bool, true)
        XCTAssertEqual(payload["assistantOutputPasteMode"] as? String, "auto")
        XCTAssertEqual(payload["useRegionSelection"] as? Bool, true)
        XCTAssertEqual(payload["agentTaskDefaultModality"] as? String, "text")
        XCTAssertEqual(payload["agentTaskAutoReopenOnCompletion"] as? Bool, false)
        XCTAssertEqual(payload["agentTaskPushToTalk"] as? Bool, true)
        XCTAssertEqual(payload["agentTaskPushToTalkThreshold"] as? Int, 1200)
        XCTAssertEqual(payload["assistantSessionDefaultModality"] as? String, "type")
        XCTAssertEqual(payload["assistantSessionPushToTalk"] as? Bool, false)
        XCTAssertEqual(payload["assistantSessionPushToTalkThreshold"] as? Int, 900)
    }

    func testEmptyModelListsProduceEmptyArraysNotNil() {
        let payload = ReasoningDefaultsSettingsPayloadBuilder.makeSettingsPayload(
            localModels: [], apiModels: [], customModels: [],
            selectedModelId: "", useApiModels: false,
            closeAssistantSessionOnInsert: false, assistantOutputPasteMode: .always, useRegionSelection: false,
            agentTaskDefaultModality: .voice, agentTaskAutoReopenOnCompletion: true,
            agentTaskPushToTalk: false, agentTaskPushToTalkThreshold: 750,
            assistantSessionDefaultModality: .speak, assistantSessionPushToTalk: false,
            assistantSessionPushToTalkThreshold: 750
        )
        XCTAssertEqual((payload["localModels"] as? [[String: Any]])?.count, 0)
        XCTAssertEqual((payload["apiModels"] as? [[String: Any]])?.count, 0)
        XCTAssertEqual((payload["customModels"] as? [[String: Any]])?.count, 0)
    }

    func testModelInfoPayloadMapsAllFields() {
        let model = makeModel(id: "model-x", provider: "anthropic", isApiModel: true)
        let payload = ReasoningDefaultsSettingsPayloadBuilder.makeModelInfoPayload(model)
        XCTAssertEqual(payload["id"] as? String, "model-x")
        XCTAssertEqual(payload["name"] as? String, "model-x")
        XCTAssertEqual(payload["displayName"] as? String, "model-x")
        XCTAssertEqual(payload["provider"] as? String, "anthropic")
        XCTAssertEqual(payload["isApiModel"] as? Bool, true)
    }

    func testAssistantSessionSettingsDefaultsMissingModalityForOlderBackends() throws {
        let data = Data("""
        {"enable_push_to_talk":true,"push_to_talk_threshold_ms":1200}
        """.utf8)
        let settings = try JSONDecoder().decode(AssistantSessionSettings.self, from: data)
        XCTAssertTrue(settings.enablePushToTalk)
        XCTAssertEqual(settings.pushToTalkThresholdMs, 1200)
        XCTAssertEqual(settings.defaultInputModality, "speak")
    }
}
