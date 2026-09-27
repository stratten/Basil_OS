import XCTest
@testable import BasilClient

@MainActor
final class ReactModelsSettingsPayloadTests: XCTestCase {
    private func makeModel(
        id: String,
        modelType: String,
        variantId: String,
        name: String,
        capabilities: [ModelCapabilityType],
        status: ModelDownloadStatus = .downloadable,
        size: Int64? = nil
    ) -> ModelDownloadInfo {
        ModelDownloadInfo(id: id, modelType: modelType, variantId: variantId, name: name, capabilities: capabilities, status: status, size: size, variants: [:])
    }

    func test_sortedGroupKeys_ordersPreferredProvidersFirstThenAlphabetical() {
        let groups: [String: [ModelDownloadInfo]] = [
            "Zephyr": [], "Mistral": [], "Qwen": [], "Anthropic": [], "Aardvark": [],
        ]
        XCTAssertEqual(
            ModelsSettingsPayloadBuilder.sortedGroupKeys(groups),
            ["Qwen", "Mistral", "Anthropic", "Aardvark", "Zephyr"]
        )
    }

    func test_makeModelWireItem_availableStatus() {
        let model = makeModel(id: "Qwen-a", modelType: "Qwen", variantId: "a", name: "Qwen A", capabilities: [.reasoning], status: .available(path: "/tmp/a"), size: 4_000_000_000)
        let item = ModelsSettingsPayloadBuilder.makeModelWireItem(model, downloadProgress: [:], downloadProgressMetadata: [:])
        XCTAssertEqual(item["statusKind"] as? String, "available")
        XCTAssertEqual(item["size"] as? Int64, 4_000_000_000)
        XCTAssertEqual(item["capabilities"] as? [String], ["reasoning"])
        XCTAssertNil(item["progress"])
    }

    func test_makeModelWireItem_downloadingStatusPrefersLiveProgressOverModelStatus() {
        let model = makeModel(id: "Qwen-b", modelType: "Qwen", variantId: "b", name: "Qwen B", capabilities: [.reasoning], status: .downloading(progress: 0.2))
        let item = ModelsSettingsPayloadBuilder.makeModelWireItem(model, downloadProgress: ["Qwen-b": 0.55], downloadProgressMetadata: [:])
        XCTAssertEqual(item["statusKind"] as? String, "downloading")
        XCTAssertEqual(item["progress"] as? Double, 0.55)
    }

    func test_makeModelWireItem_errorStatusIncludesMessage() {
        let model = makeModel(id: "Qwen-c", modelType: "Qwen", variantId: "c", name: "Qwen C", capabilities: [.reasoning], status: .error(message: "Backend not available"))
        let item = ModelsSettingsPayloadBuilder.makeModelWireItem(model, downloadProgress: [:], downloadProgressMetadata: [:])
        XCTAssertEqual(item["statusKind"] as? String, "error")
        XCTAssertEqual(item["errorMessage"] as? String, "Backend not available")
    }

    func test_makeModelWireItem_includesProgressMetadataFields() {
        let model = makeModel(id: "Qwen-d", modelType: "Qwen", variantId: "d", name: "Qwen D", capabilities: [.reasoning], status: .downloading(progress: 0.4))
        let metadata: [String: [String: Any]] = [
            "Qwen-d": ["total_downloaded": Int64(1000), "total_size": Int64(4000), "current_file": "model.gguf", "files_completed": 1, "total_files": 2],
        ]
        let item = ModelsSettingsPayloadBuilder.makeModelWireItem(model, downloadProgress: ["Qwen-d": 0.4], downloadProgressMetadata: metadata)
        XCTAssertEqual(item["totalDownloaded"] as? Int64, 1000)
        XCTAssertEqual(item["totalSize"] as? Int64, 4000)
        XCTAssertEqual(item["currentFile"] as? String, "model.gguf")
        XCTAssertEqual(item["filesCompleted"] as? Int, 1)
        XCTAssertEqual(item["totalFiles"] as? Int, 2)
    }

    func test_makeCapabilityGroups_filtersByCapabilityAndDropsEmptyGroups() {
        let groups: [String: [ModelDownloadInfo]] = [
            "Qwen": [makeModel(id: "Qwen-a", modelType: "Qwen", variantId: "a", name: "Qwen A", capabilities: [.reasoning])],
            "NVIDIA": [makeModel(id: "NVIDIA-a", modelType: "NVIDIA", variantId: "a", name: "Parakeet", capabilities: [.transcription])],
        ]
        let reasoningGroups = ModelsSettingsPayloadBuilder.makeCapabilityGroups(modelGroups: groups, capability: .reasoning, downloadProgress: [:], downloadProgressMetadata: [:])
        XCTAssertEqual(reasoningGroups.count, 1)
        XCTAssertEqual(reasoningGroups.first?["provider"] as? String, "Qwen")
    }

    func test_alertFactory_informativeTextWithSizeIncludesFreedSpaceEstimate() {
        let text = ModelsSettingsAlertFactory.informativeText(modelSize: 4_000_000_000)
        XCTAssertTrue(text.contains("free up approximately"))
        XCTAssertTrue(text.contains("huggingface"))
    }

    func test_alertFactory_informativeTextWithoutSizeOmitsFreedSpaceSentence() {
        let text = ModelsSettingsAlertFactory.informativeText(modelSize: nil)
        XCTAssertFalse(text.contains("free up approximately"))
        XCTAssertTrue(text.contains("Model files will be removed from disk."))
    }
}
