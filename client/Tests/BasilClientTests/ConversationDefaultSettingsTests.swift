import XCTest
@testable import BasilClient

final class ConversationDefaultSettingsTests: XCTestCase {
    private func makePayload(conversationDefaultConversationOnly: Bool?) -> [String: Any] {
        if let conversationDefaultConversationOnly {
            return ReasoningDefaultsSettingsPayloadBuilder.makeSettingsPayload(
                localModels: [],
                apiModels: [],
                customModels: [],
                selectedModelId: "",
                useApiModels: false,
                closeAssistantSessionOnInsert: false,
                assistantOutputPasteMode: .always,
                useRegionSelection: false,
                agentTaskDefaultModality: .voice,
                agentTaskAutoReopenOnCompletion: false,
                agentTaskPushToTalk: false,
                agentTaskPushToTalkThreshold: 1000,
                assistantSessionDefaultModality: .speak,
                assistantSessionPushToTalk: false,
                assistantSessionPushToTalkThreshold: 1000,
                conversationDefaultConversationOnly: conversationDefaultConversationOnly
            )
        }
        return ReasoningDefaultsSettingsPayloadBuilder.makeSettingsPayload(
            localModels: [],
            apiModels: [],
            customModels: [],
            selectedModelId: "",
            useApiModels: false,
            closeAssistantSessionOnInsert: false,
            assistantOutputPasteMode: .always,
            useRegionSelection: false,
            agentTaskDefaultModality: .voice,
            agentTaskAutoReopenOnCompletion: false,
            agentTaskPushToTalk: false,
            agentTaskPushToTalkThreshold: 1000,
            assistantSessionDefaultModality: .speak,
            assistantSessionPushToTalk: false,
            assistantSessionPushToTalkThreshold: 1000
        )
    }

    func testPayloadIncludesConversationOnlyDefaultWhenProvided() {
        let payload = makePayload(conversationDefaultConversationOnly: true)
        XCTAssertEqual(payload["conversationDefaultConversationOnly"] as? Bool, true)
    }

    func testPayloadDefaultsConversationOnlyToFalse() {
        let payload = makePayload(conversationDefaultConversationOnly: nil)
        XCTAssertEqual(payload["conversationDefaultConversationOnly"] as? Bool, false)
    }

    func testConversationWidgetSettingsDecodesDefaultConversationOnly() throws {
        let json = #"{"widget_size":[700,600],"widget_position":null,"is_sidebar_collapsed":false,"default_conversation_only":true}"#
        let settings = try JSONDecoder().decode(ConversationWidgetSettings.self, from: Data(json.utf8))
        XCTAssertEqual(settings.defaultConversationOnly, true)
    }

    func testConversationWidgetSettingsDecodesWithoutDefaultConversationOnly() throws {
        let json = #"{"widget_size":[700,600],"widget_position":null,"is_sidebar_collapsed":true}"#
        let settings = try JSONDecoder().decode(ConversationWidgetSettings.self, from: Data(json.utf8))
        XCTAssertNil(settings.defaultConversationOnly)
        XCTAssertTrue(settings.isSidebarCollapsed)
    }
}
