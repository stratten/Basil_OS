import XCTest
@testable import BasilClient

final class CustomModelsPayloadTests: XCTestCase {
    func testEmptyModelsProduceEmptyPayload() {
        let summaries = CustomModelsPayloadBuilder.makeModelSummaries(
            models: [], downloadProgressMap: [:], downloadStatus: [:]
        )
        XCTAssertEqual(summaries.count, 0)
    }

    func testMapsApiModelFieldsAndDerivesNeedsDownloadFalse() {
        let model = CustomModelConfig(
            modelId: "my-openai-compatible", displayName: "My Endpoint", handler: "openai_compatible",
            baseUrl: "http://localhost:11434/v1", modelIdentifier: "llama-3.3-70b", modelPath: nil,
            downloadUrl: nil, contextWindow: 8192, maxOutputTokens: 4096, requiresAuth: true,
            apiKeyName: "custom_my-openai-compatible", capabilities: ["reasoning"],
            features: ["streaming", "system_prompts"], featureConfig: nil, toolRendering: nil,
            toolCallFormat: nil, description: "test model", fileSize: nil, fileSizeHuman: nil
        )
        let summaries = CustomModelsPayloadBuilder.makeModelSummaries(
            models: [model], downloadProgressMap: [:], downloadStatus: [:]
        )
        XCTAssertEqual(summaries.count, 1)
        XCTAssertEqual(summaries[0]["modelId"] as? String, "my-openai-compatible")
        XCTAssertEqual(summaries[0]["isLocal"] as? Bool, false)
        XCTAssertEqual(summaries[0]["needsDownload"] as? Bool, false)
        XCTAssertEqual(summaries[0]["baseUrl"] as? String, "http://localhost:11434/v1")
        XCTAssertEqual(summaries[0]["contextWindow"] as? Int, 8192)
        XCTAssertNil(summaries[0]["downloadProgress"])
        XCTAssertNil(summaries[0]["downloadStatus"])
    }

    func testDerivesNeedsDownloadTrueForUndownloadedHuggingFaceModel() {
        let model = CustomModelConfig(
            modelId: "llama-gguf", displayName: "Llama GGUF", handler: "llama_cpp",
            baseUrl: nil, modelIdentifier: nil, modelPath: nil,
            downloadUrl: "https://huggingface.co/org/repo", contextWindow: 4096, maxOutputTokens: 2048,
            requiresAuth: false, apiKeyName: nil, capabilities: ["reasoning"], features: ["streaming"],
            featureConfig: nil, toolRendering: nil, toolCallFormat: nil, description: nil,
            fileSize: 4_000_000_000, fileSizeHuman: "4.0 GB"
        )
        let summaries = CustomModelsPayloadBuilder.makeModelSummaries(
            models: [model], downloadProgressMap: ["llama-gguf": 0.42], downloadStatus: ["llama-gguf": "downloading"]
        )
        XCTAssertEqual(summaries[0]["needsDownload"] as? Bool, true)
        XCTAssertEqual(summaries[0]["isLocal"] as? Bool, true)
        XCTAssertEqual(summaries[0]["fileSizeHuman"] as? String, "4.0 GB")
        XCTAssertEqual(summaries[0]["downloadProgress"] as? Double, 0.42)
        XCTAssertEqual(summaries[0]["downloadStatus"] as? String, "downloading")
    }

    func testNeedsDownloadFalseOncePathIsSet() {
        let model = CustomModelConfig(
            modelId: "llama-gguf", displayName: "Llama GGUF", handler: "llama_cpp",
            baseUrl: nil, modelIdentifier: nil, modelPath: "/Users/test/model.gguf",
            downloadUrl: "https://huggingface.co/org/repo", contextWindow: 4096, maxOutputTokens: 2048,
            requiresAuth: false, apiKeyName: nil, capabilities: ["reasoning"], features: [],
            featureConfig: nil, toolRendering: nil, toolCallFormat: nil, description: nil,
            fileSize: nil, fileSizeHuman: nil
        )
        let summaries = CustomModelsPayloadBuilder.makeModelSummaries(
            models: [model], downloadProgressMap: [:], downloadStatus: [:]
        )
        XCTAssertEqual(summaries[0]["needsDownload"] as? Bool, false)
        XCTAssertEqual(summaries[0]["modelPath"] as? String, "/Users/test/model.gguf")
    }

    func testNilOptionalFieldsSerializeAsNSNullNotMissing() {
        let model = CustomModelConfig(
            modelId: "bare", displayName: "Bare", handler: "openai_compatible",
            baseUrl: nil, modelIdentifier: nil, modelPath: nil, downloadUrl: nil,
            contextWindow: 4096, maxOutputTokens: 4096, requiresAuth: false, apiKeyName: nil,
            capabilities: ["reasoning"], features: [], featureConfig: nil, toolRendering: nil,
            toolCallFormat: nil, description: nil, fileSize: nil, fileSizeHuman: nil
        )
        let summaries = CustomModelsPayloadBuilder.makeModelSummaries(
            models: [model], downloadProgressMap: [:], downloadStatus: [:]
        )
        XCTAssertNotNil(summaries[0]["baseUrl"])
        XCTAssertTrue(summaries[0]["baseUrl"] is NSNull)
        XCTAssertTrue(summaries[0]["description"] is NSNull)
    }

    func testReportsChangesForEveryActiveModelDownload() {
        let initial = CustomModelsPayloadBuilder.changedDownloadProgress(
            previous: [:],
            downloadProgressMap: ["first": 0.25, "second": 0.5],
            downloadStatus: ["first": "downloading", "second": "downloading"]
        )
        XCTAssertEqual(initial.changes["first"], CustomModelsDownloadProgress(progress: 0.25, status: "downloading"))
        XCTAssertEqual(initial.changes["second"], CustomModelsDownloadProgress(progress: 0.5, status: "downloading"))

        let next = CustomModelsPayloadBuilder.changedDownloadProgress(
            previous: initial.snapshot,
            downloadProgressMap: ["first": 0.5, "second": 0.5],
            downloadStatus: ["first": "downloading", "second": "downloading"]
        )
        XCTAssertEqual(next.changes.count, 1)
        XCTAssertEqual(next.changes["first"], CustomModelsDownloadProgress(progress: 0.5, status: "downloading"))
    }
}
