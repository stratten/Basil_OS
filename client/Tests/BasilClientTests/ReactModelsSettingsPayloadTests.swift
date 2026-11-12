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

    func test_makeModelWireItem_tagsLocalModelsWithTheirFileFormat() {
        func wireFormat(handler: String?) -> String? {
            let model = ModelDownloadInfo(id: "Qwen-f", modelType: "Qwen", variantId: "f", name: "Qwen F", capabilities: [.reasoning], variants: [:], handler: handler)
            return ModelsSettingsPayloadBuilder.makeModelWireItem(model, downloadProgress: [:], downloadProgressMetadata: [:])["format"] as? String
        }
        XCTAssertEqual(wireFormat(handler: "mlx"), "MLX")
        XCTAssertEqual(wireFormat(handler: "llama_cpp"), "GGUF")
        XCTAssertNil(wireFormat(handler: "huggingface"))
        XCTAssertNil(wireFormat(handler: nil))
    }

    func test_makeModelWireItem_includesTheRegistryComparisonFactsOnlyWhenListed() {
        let rated = ModelDownloadInfo(id: "Qwen-r", modelType: "Qwen", variantId: "r", name: "Qwen R", capabilities: [.reasoning], variants: [:], speedRating: 7, accuracyRating: 8, recommendedRam: " 16GB ")
        let ratedItem = ModelsSettingsPayloadBuilder.makeModelWireItem(rated, downloadProgress: [:], downloadProgressMetadata: [:])
        XCTAssertEqual(ratedItem["speedRating"] as? Int, 7)
        XCTAssertEqual(ratedItem["accuracyRating"] as? Int, 8)
        XCTAssertEqual(ratedItem["recommendedRam"] as? String, "16GB")

        let blankRam = ModelDownloadInfo(id: "Qwen-b", modelType: "Qwen", variantId: "b", name: "Qwen B", capabilities: [.reasoning], variants: [:], recommendedRam: "   ")
        let blankItem = ModelsSettingsPayloadBuilder.makeModelWireItem(blankRam, downloadProgress: [:], downloadProgressMetadata: [:])
        XCTAssertNil(blankItem["recommendedRam"])

        let plain = makeModel(id: "Qwen-p", modelType: "Qwen", variantId: "p", name: "Qwen P", capabilities: [.reasoning])
        let plainItem = ModelsSettingsPayloadBuilder.makeModelWireItem(plain, downloadProgress: [:], downloadProgressMetadata: [:])
        XCTAssertNil(plainItem["speedRating"])
        XCTAssertNil(plainItem["accuracyRating"])
        XCTAssertNil(plainItem["recommendedRam"])
    }

    func test_modelVariant_decodesRegistryRatingsFromTheBackendCatalog() throws {
        let json = """
        {"name": "Qwen R", "size": "5.0GB", "speed_rating": 7, "accuracy_rating": 8, "recommended_ram": "16GB", "handler": "llama_cpp"}
        """
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let variant = try decoder.decode(ModelVariant.self, from: Data(json.utf8))
        XCTAssertEqual(variant.speedRating, 7)
        XCTAssertEqual(variant.accuracyRating, 8)
        XCTAssertEqual(variant.recommendedRam, "16GB")

        let bare = try decoder.decode(ModelVariant.self, from: Data(#"{"name": "Cloud", "size": "0"}"#.utf8))
        XCTAssertNil(bare.speedRating)
        XCTAssertNil(bare.accuracyRating)
        XCTAssertNil(bare.recommendedRam)
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

    func test_makeModelWireItem_carriesTheBackendStatusMessageWhileDownloading() {
        let model = makeModel(id: "Qwen-e", modelType: "Qwen", variantId: "e", name: "Qwen E", capabilities: [.reasoning], status: .downloading(progress: 0))
        let metadata: [String: [String: Any]] = [
            "Qwen-e": ["message": "Waiting for Hugging Face to start sending data (20s)..."],
        ]
        let item = ModelsSettingsPayloadBuilder.makeModelWireItem(model, downloadProgress: ["Qwen-e": 0], downloadProgressMetadata: metadata)
        XCTAssertEqual(item["statusMessage"] as? String, "Waiting for Hugging Face to start sending data (20s)...")
    }

    func test_makeModelWireItem_leavesOutABlankOrMissingStatusMessage() {
        let model = makeModel(id: "Qwen-f", modelType: "Qwen", variantId: "f", name: "Qwen F", capabilities: [.reasoning], status: .downloading(progress: 0))
        let blank = ModelsSettingsPayloadBuilder.makeModelWireItem(model, downloadProgress: ["Qwen-f": 0], downloadProgressMetadata: ["Qwen-f": ["message": "  \n"]])
        let missing = ModelsSettingsPayloadBuilder.makeModelWireItem(model, downloadProgress: ["Qwen-f": 0], downloadProgressMetadata: ["Qwen-f": ["total_downloaded": Int64(0)]])
        let notAString = ModelsSettingsPayloadBuilder.makeModelWireItem(model, downloadProgress: ["Qwen-f": 0], downloadProgressMetadata: ["Qwen-f": ["message": 5]])
        XCTAssertNil(blank["statusMessage"])
        XCTAssertNil(missing["statusMessage"])
        XCTAssertNil(notAString["statusMessage"])
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

    func test_makeDeviceMemoryEntry_includesPositiveMemory() {
        let entry = ModelsSettingsPayloadBuilder.makeDeviceMemoryEntry(16)
        XCTAssertEqual(entry["deviceMemoryGb"] as? Int, 16)
        XCTAssertEqual(entry.count, 1)
    }

    func test_makeDeviceMemoryEntry_omitsUnknownOrNonPositiveMemory() {
        XCTAssertTrue(ModelsSettingsPayloadBuilder.makeDeviceMemoryEntry(nil).isEmpty)
        XCTAssertTrue(ModelsSettingsPayloadBuilder.makeDeviceMemoryEntry(0).isEmpty)
        XCTAssertTrue(ModelsSettingsPayloadBuilder.makeDeviceMemoryEntry(-8).isEmpty)
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
