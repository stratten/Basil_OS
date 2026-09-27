import AppKit
@preconcurrency import WebKit

extension SettingsShellWindowController {
    func wireMemoriesSettingsWebView(_ memoriesWebView: ReactMemoriesSettingsWebView) {
        memoriesWebView.onReady = { [weak self] in
            Task { @MainActor in await self?.loadMemoriesAndSendInit() }
        }
        memoriesWebView.onRequestUpdateSettings = { [weak self] requestId, fields in
            Task { @MainActor in await self?.updateMemoriesSettings(requestId: requestId, fields: fields) }
        }
        memoriesWebView.onRequestCollectNow = { [weak self] requestId in
            Task { @MainActor in await self?.runMemoriesCollectNow(requestId: requestId) }
        }
        memoriesWebView.onRequestSummarizeNow = { [weak self] requestId in
            Task { @MainActor in await self?.runMemoriesSummarizeNow(requestId: requestId) }
        }
        memoriesWebView.onRequestRetryFailedSummaries = { [weak self] requestId in
            Task { @MainActor in await self?.retryMemoriesFailedSummaries(requestId: requestId) }
        }
        memoriesWebView.onRequestCancelSummarize = { [weak self] requestId in
            Task { @MainActor in await self?.cancelMemoriesSummarize(requestId: requestId) }
        }
        memoriesWebView.onRequestRefreshStats = { [weak self] requestId in
            Task { @MainActor in await self?.refreshMemoriesStats(requestId: requestId) }
        }
        memoriesWebView.onRequestNarrativeProgress = { [weak self] requestId in
            Task { @MainActor in await self?.sendMemoriesNarrativeProgress(requestId: requestId) }
        }
    }

    private func loadMemoriesAndSendInit() async {
        memoriesLoadGeneration += 1
        let generation = memoriesLoadGeneration
        guard let memoriesWebView else { return }
        do {
            let settings = try await APIClient.shared.getZettelSettings()
            if availableMemoriesModelsCache.isEmpty {
                availableMemoriesModelsCache = await loadMemoriesReasoningModelOptions()
            }
            let stats = try? await APIClient.shared.getZettelStats()
            let progress = try? await APIClient.shared.getNarrativeProgress()
            guard generation == memoriesLoadGeneration else { return }
            memoriesSettingsCache = settings
            memoriesWebView.sendInit(
                settings: settings,
                stats: stats,
                narrativeProgress: progress,
                availableModels: availableMemoriesModelsCache
            )
        } catch {
            guard generation == memoriesLoadGeneration else { return }
            memoriesWebView.sendLoadError(message: "Failed to load Memories settings.")
        }
    }

    private func isValidMemoriesModel(_ id: String) -> Bool {
        id.isEmpty || availableMemoriesModelsCache.contains { $0.id == id }
    }

    private func updateMemoriesSettings(requestId: String, fields: ReactMemoriesSettingsFields) async {
        memoriesLoadGeneration += 1
        guard let memoriesWebView, memoriesSettingsCache != nil else {
            memoriesWebView?.sendIntentResult(requestId: requestId, status: "error", message: "Memories settings have not finished loading.")
            return
        }
        guard isValidMemoriesModel(fields.narrativeModel) else {
            memoriesWebView.sendIntentResult(requestId: requestId, status: "error", message: "The selected evaluator model is unavailable.")
            return
        }
        do {
            let updated = try await APIClient.shared.updateZettelSettings(fields.asZettelSettingsData)
            memoriesSettingsCache = updated
            let stats = try? await APIClient.shared.getZettelStats()
            memoriesWebView.sendSnapshot(settings: updated, stats: stats, availableModels: availableMemoriesModelsCache)
            memoriesWebView.sendIntentResult(requestId: requestId, status: "success", message: nil)
        } catch {
            memoriesWebView.sendIntentResult(requestId: requestId, status: "error", message: "Error: failed to save Memories settings")
        }
    }

    private func runMemoriesCollectNow(requestId: String) async {
        memoriesLoadGeneration += 1
        guard let memoriesWebView, let settings = memoriesSettingsCache else {
            memoriesWebView?.sendIntentResult(requestId: requestId, status: "error", message: "Memories settings have not finished loading.")
            return
        }
        do {
            let message = try await APIClient.shared.runZettelCardingNow()
            let stats = try? await APIClient.shared.getZettelStats()
            memoriesWebView.sendSnapshot(settings: settings, stats: stats, availableModels: availableMemoriesModelsCache)
            memoriesWebView.sendIntentResult(requestId: requestId, status: "success", message: message ?? "Collection pass completed.")
        } catch {
            memoriesWebView.sendIntentResult(requestId: requestId, status: "error", message: "Error: failed to collect now")
        }
    }

    private func runMemoriesSummarizeNow(requestId: String) async {
        memoriesLoadGeneration += 1
        guard let memoriesWebView, let settings = memoriesSettingsCache else {
            memoriesWebView?.sendIntentResult(requestId: requestId, status: "error", message: "Memories settings have not finished loading.")
            return
        }
        do {
            // Re-save the current in-memory settings first so a just-typed Items-per-run value cannot race its focus-loss persistence and launch an uncapped run.
            let updatedSettings = try await APIClient.shared.updateZettelSettings(settings)
            memoriesSettingsCache = updatedSettings
            let message = try await APIClient.shared.runZettelNarrativeNow()
            let stats = try? await APIClient.shared.getZettelStats()
            memoriesWebView.sendSnapshot(settings: updatedSettings, stats: stats, availableModels: availableMemoriesModelsCache)
            memoriesWebView.sendIntentResult(requestId: requestId, status: "success", message: message ?? "Summaries started.")
        } catch {
            memoriesWebView.sendIntentResult(requestId: requestId, status: "error", message: "Error: failed to generate summaries")
        }
    }

    private func retryMemoriesFailedSummaries(requestId: String) async {
        memoriesLoadGeneration += 1
        guard let memoriesWebView, let settings = memoriesSettingsCache else {
            memoriesWebView?.sendIntentResult(requestId: requestId, status: "error", message: "Memories settings have not finished loading.")
            return
        }
        do {
            let message = try await APIClient.shared.retryFailedZettelNarratives()
            let stats = try? await APIClient.shared.getZettelStats()
            memoriesWebView.sendSnapshot(settings: settings, stats: stats, availableModels: availableMemoriesModelsCache)
            memoriesWebView.sendIntentResult(requestId: requestId, status: "success", message: message ?? "Unfinished entries reset. Start summarization when ready.")
        } catch {
            memoriesWebView.sendIntentResult(requestId: requestId, status: "error", message: "Error: failed to retry summaries")
        }
    }

    private func cancelMemoriesSummarize(requestId: String) async {
        guard let memoriesWebView else { return }
        do {
            let message = try await APIClient.shared.cancelZettelNarrative()
            memoriesWebView.sendIntentResult(requestId: requestId, status: "success", message: message ?? "Stopping summaries after items in progress.")
        } catch {
            memoriesWebView.sendIntentResult(requestId: requestId, status: "error", message: "Error: failed to stop summaries")
        }
    }

    private func refreshMemoriesStats(requestId: String) async {
        memoriesLoadGeneration += 1
        guard let memoriesWebView, let settings = memoriesSettingsCache else {
            memoriesWebView?.sendIntentResult(requestId: requestId, status: "error", message: "Memories settings have not finished loading.")
            return
        }
        do {
            let stats = try await APIClient.shared.getZettelStats()
            memoriesWebView.sendSnapshot(settings: settings, stats: stats, availableModels: availableMemoriesModelsCache)
            memoriesWebView.sendIntentResult(requestId: requestId, status: "success", message: nil)
        } catch {
            memoriesWebView.sendIntentResult(requestId: requestId, status: "error", message: "Failed to refresh counts.")
        }
    }

    private func sendMemoriesNarrativeProgress(requestId: String) async {
        guard let memoriesWebView else { return }
        guard let progress = try? await APIClient.shared.getNarrativeProgress() else { return }
        memoriesWebView.sendProgress(requestId: requestId, progress: progress)
    }

    private func loadMemoriesReasoningModelOptions() async -> [ActivityCaptureModelInfo] {
        var models: [ActivityCaptureModelInfo] = []
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase

        struct ModelVariant: Codable { let modelId: String; let name: String; let capabilities: [String]?; let valid: Bool? }
        struct ModelType: Codable { let variants: [String: ModelVariant] }
        struct APIModelResponse: Codable {
            let id: String; let name: String; let displayName: String
            let provider: String; let isApiModel: Bool
        }
        struct APIModelsResponseData: Codable {
            let models: [APIModelResponse]; let apiModelsEnabled: Bool
        }

        do {
            let localData = try await APIClient.shared.get("/models/installed")
            let localResponse = try decoder.decode([String: ModelType].self, from: localData)
            for (modelType, info) in localResponse {
                for (_, variant) in info.variants {
                    if variant.valid == true,
                       let capabilities = variant.capabilities,
                       capabilities.contains("reasoning") {
                        models.append(ActivityCaptureModelInfo(
                            id: variant.modelId, displayName: variant.name,
                            provider: modelType, isLocal: true
                        ))
                    }
                }
            }
            let apiData = try await APIClient.shared.get("/settings/api_models/reasoning")
            let apiResponse = try decoder.decode(APIModelsResponseData.self, from: apiData)
            if apiResponse.apiModelsEnabled {
                for model in apiResponse.models {
                    models.append(ActivityCaptureModelInfo(
                        id: model.id, displayName: model.displayName,
                        provider: model.provider, isLocal: false
                    ))
                }
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error("[MEMORIES_SETTINGS] Failed to load reasoning model options: \(error)", context: "SettingsShellWindowController")
            #endif
        }
        models.sort { a, b in
            if a.isLocal != b.isLocal { return a.isLocal }
            return a.displayName < b.displayName
        }
        return models
    }
}
