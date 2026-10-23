import XCTest
@testable import BasilClient

final class ReactReasoningAPIModelsPayloadTests: XCTestCase {
    func testEmptyProvidersProduceEmptyPayload() {
        let summaries = ReasoningApiModelsPayloadBuilder.makeProviderSummaries(providers: [])
        XCTAssertEqual(summaries.count, 0)
    }

    func testMapsProviderAndModelFieldsAndPreservesOrder() {
        let model = APIModelInfo(
            id: "claude-sonnet", name: "Claude Sonnet", description: "fast",
            provider: "anthropic", capabilities: [.reasoning, .vision],
            isEnabled: true, isDefaultForReasoning: false, isDefaultForVision: false,
            supportsExtendedThinking: true
        )
        let provider = APIProviderInfo(
            id: "anthropic", name: "Anthropic", isEnabled: true,
            usingOwnApiKey: false, localUsingOwnApiKey: true, hasKey: true, models: [model]
        )
        let summaries = ReasoningApiModelsPayloadBuilder.makeProviderSummaries(providers: [provider])
        XCTAssertEqual(summaries.count, 1)
        XCTAssertEqual(summaries[0]["id"] as? String, "anthropic")
        XCTAssertEqual(summaries[0]["usingOwnApiKey"] as? Bool, true)
        XCTAssertEqual(summaries[0]["hasKey"] as? Bool, true)
        let models = summaries[0]["models"] as! [[String: Any]]
        XCTAssertEqual(models[0]["id"] as? String, "claude-sonnet")
        XCTAssertEqual(models[0]["description"] as? String, "fast")
        XCTAssertEqual(models[0]["supportsExtendedThinking"] as? Bool, true)
        XCTAssertEqual(models[0]["capabilities"] as? [String], ["reasoning", "vision"])
    }

    func testNilDescriptionBecomesEmptyString() {
        let model = APIModelInfo(
            id: "gpt-4o", name: "GPT-4o", description: nil,
            provider: "openai", capabilities: [.reasoning],
            isEnabled: false, isDefaultForReasoning: false, isDefaultForVision: false,
            supportsExtendedThinking: false
        )
        let provider = APIProviderInfo(
            id: "openai", name: "Openai", isEnabled: false,
            usingOwnApiKey: false, localUsingOwnApiKey: false, hasKey: false, models: [model]
        )
        let models = ReasoningApiModelsPayloadBuilder.makeProviderSummaries(providers: [provider])[0]["models"] as! [[String: Any]]
        XCTAssertEqual(models[0]["description"] as? String, "")
        XCTAssertEqual(models[0]["enabled"] as? Bool, false)
    }
}
