import AppKit
@preconcurrency import WebKit

extension SettingsShellWindowController {
    func wireMemoryIntelligenceSettingsWebView(_ memoryWebView: ReactMemoryIntelligenceSettingsWebView) {
        memoryWebView.onReady = { [weak self] in
            Task { @MainActor in
                await self?.loadMemoryIntelligenceAndSendInit()
            }
        }
        memoryWebView.onUpdateSetting = { [weak self] requestId, patch in
            Task { @MainActor in
                await self?.putMemorySetting(requestId: requestId, patch: patch)
            }
        }
        memoryWebView.onRunIntelligenceNow = { [weak self] requestId in
            Task { @MainActor in
                await self?.runMemoryIntelligenceNow(requestId: requestId)
            }
        }
        memoryWebView.onDeclineProposal = { [weak self] requestId, id in
            guard let self, self.memoryProposalsCache.contains(where: { $0.id == id }) else {
                memoryWebView.sendIntentResult(requestId: requestId, status: "error", message: "The selected memory proposal is unavailable.")
                return
            }
            Task { @MainActor in
                await self.declineMemoryProposal(requestId: requestId, id: id)
            }
        }
        memoryWebView.onOpenMemoryFile = { [weak self] fileName in
            guard let self, self.memoryDocumentsCache.contains(where: { $0.fileName == fileName }) else { return }
            self.openMemoryFile(fileName)
        }
        memoryWebView.onOpenMemoryProposal = { [weak self] id in
            guard let self, self.memoryProposalsCache.contains(where: { $0.id == id }) else { return }
            self.openMemoryProposal(id)
        }
    }

    private func loadMemoryIntelligenceAndSendInit() async {
        guard let memoryWebView else { return }
        do {
            let settings = try await APIClient.shared.getMemoryIntelligenceSettings()
            let documents = try await APIClient.shared.listMemoryDocuments()
            let proposals = try await APIClient.shared.listMemoryProposals()
            if availableMemoryModelsCache.isEmpty {
                availableMemoryModelsCache = await loadMemoryReasoningModelOptions()
            }
            memorySettingsCache = settings
            memoryDocumentsCache = documents
            memoryProposalsCache = proposals
            memoryWebView.sendInit(
                settings: settings,
                proposals: proposals,
                documents: documents,
                availableModels: availableMemoryModelsCache
            )
        } catch {
            memoryWebView.sendLoadError(message: "Failed to load Personal Context settings.")
        }
    }

    private func putMemorySetting(requestId: String, patch: ReactMemorySettingPatch) async {
        guard let memoryWebView, memorySettingsCache != nil else {
            memoryWebView?.sendIntentResult(requestId: requestId, status: "error", message: "Memory settings have not finished loading.")
            return
        }
        if case .memoryProcessingModel = patch.field,
           case .nullableString(let modelId) = patch.value,
           let modelId,
           !availableMemoryModelsCache.contains(where: { $0.id == modelId }) {
            memoryWebView.sendIntentResult(requestId: requestId, status: "error", message: "The selected evaluator model is unavailable.")
            return
        }
        let key: String
        let jsonValue: Any
        switch patch.field {
        case .memoryAfterTaskEnabled:
            key = "memory_after_task_enabled"
        case .memoryDailyEnabled:
            key = "memory_daily_enabled"
        case .memoryDailyTimeLocal:
            key = "memory_daily_time_local"
        case .memoryProcessingModel:
            key = "memory_processing_model"
        }
        switch patch.value {
        case .bool(let value):
            jsonValue = value
        case .string(let value):
            jsonValue = value
        case .nullableString(let value):
            jsonValue = value ?? NSNull()
        }
        do {
            let data = try JSONSerialization.data(withJSONObject: [key: jsonValue])
            let responseData = try await APIClient.shared.put("/settings/memory-intelligence", data: data)
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            struct MemoryIntelligenceUpdateResponse: Codable { let status: String; let updatedSettings: MemoryIntelligenceSettingsDTO }
            let response = try decoder.decode(MemoryIntelligenceUpdateResponse.self, from: responseData)
            memorySettingsCache = response.updatedSettings
            memoryWebView.sendIntentResult(requestId: requestId, status: "success", message: nil)
            memoryWebView.sendSnapshot(
                settings: response.updatedSettings,
                proposals: memoryProposalsCache,
                documents: memoryDocumentsCache,
                availableModels: availableMemoryModelsCache
            )
        } catch {
            memoryWebView.sendIntentResult(requestId: requestId, status: "error", message: "Failed to update memory setting.")
        }
    }

    private func runMemoryIntelligenceNow(requestId: String) async {
        guard let memoryWebView, let settings = memorySettingsCache else {
            memoryWebView?.sendIntentResult(requestId: requestId, status: "error", message: "Memory settings have not finished loading.")
            return
        }
        do {
            let result = try await APIClient.shared.runMemoryIntelligenceNow()
            do {
                try await reloadMemoryListsAndSendSnapshot(settings: settings)
            } catch {
                memoryWebView.sendIntentResult(requestId: requestId, status: "error", message: "Memory intelligence ran, but the refreshed lists are unavailable. Reopen this tab to retry.")
                return
            }
            let message = result.errors.isEmpty
                ? "Added \(result.memoryProposalsAdded) memory proposal(s) and \(result.skillCandidatesAdded) skill candidate(s)."
                : "Memory intelligence completed with errors: \(result.errors.joined(separator: ", "))"
            memoryWebView.sendIntentResult(requestId: requestId, status: result.errors.isEmpty ? "success" : "error", message: message)
        } catch {
            memoryWebView.sendIntentResult(requestId: requestId, status: "error", message: "Failed to run memory intelligence.")
        }
    }

    private func declineMemoryProposal(requestId: String, id: String) async {
        guard let memoryWebView, let settings = memorySettingsCache else {
            memoryWebView?.sendIntentResult(requestId: requestId, status: "error", message: "Memory settings have not finished loading.")
            return
        }
        do {
            try await APIClient.shared.declineMemoryProposal(id: id)
        } catch {
            memoryWebView.sendIntentResult(requestId: requestId, status: "error", message: "Failed to decline proposal.")
            return
        }
        do {
            try await reloadMemoryListsAndSendSnapshot(settings: settings)
            memoryWebView.sendIntentResult(requestId: requestId, status: "success", message: nil)
        } catch {
            memoryWebView.sendIntentResult(requestId: requestId, status: "error", message: "Proposal was declined, but the refreshed list is unavailable. Reopen this tab to retry.")
        }
    }

    private func openMemoryFile(_ fileName: String) {
        ProfileEditorLauncher.shared.open(.memoryFile(name: fileName)) { [weak self] didChange in
            guard didChange, let self, let settings = self.memorySettingsCache else { return }
            Task { @MainActor in
                do {
                    try await self.reloadMemoryListsAndSendSnapshot(settings: settings)
                } catch {
                    #if DEBUG
                    DevLogger.shared.error("[MEMORY_INTELLIGENCE_SETTINGS] Failed to refresh after editing a memory file: \(error)", context: "SettingsShellWindowController")
                    #endif
                }
            }
        }
    }

    private func openMemoryProposal(_ id: String) {
        ProfileEditorLauncher.shared.open(.memoryProposal(id: id)) { [weak self] didChange in
            guard didChange, let self, let settings = self.memorySettingsCache else { return }
            Task { @MainActor in
                do {
                    try await self.reloadMemoryListsAndSendSnapshot(settings: settings)
                } catch {
                    #if DEBUG
                    DevLogger.shared.error("[MEMORY_INTELLIGENCE_SETTINGS] Failed to refresh after editing a memory proposal: \(error)", context: "SettingsShellWindowController")
                    #endif
                }
            }
        }
    }

    private func reloadMemoryListsAndSendSnapshot(settings: MemoryIntelligenceSettingsDTO) async throws {
        guard let memoryWebView else { return }
        let documents = try await APIClient.shared.listMemoryDocuments()
        let proposals = try await APIClient.shared.listMemoryProposals()
        memoryDocumentsCache = documents
        memoryProposalsCache = proposals
        memoryWebView.sendSnapshot(
            settings: settings,
            proposals: proposals,
            documents: documents,
            availableModels: availableMemoryModelsCache
        )
    }

    private func loadMemoryReasoningModelOptions() async -> [ReasoningModelInfo] {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase

        struct ModelVariant: Codable {
            let modelId: String
            let name: String
            let capabilities: [String]?
            let valid: Bool?
        }
        struct ModelType: Codable {
            let variants: [String: ModelVariant]
        }
        struct APIModelResponse: Codable {
            let id: String
            let name: String
            let displayName: String
            let provider: String
            let isApiModel: Bool
        }
        struct APIModelsResponseData: Codable {
            let models: [APIModelResponse]
            let apiModelsEnabled: Bool
        }

        var modelOptions: [ReasoningModelInfo] = []
        do {
            let localModelsData = try await APIClient.shared.get("/models/installed")
            let localModelsResponse = try decoder.decode([String: ModelType].self, from: localModelsData)
            for (provider, modelTypeInfo) in localModelsResponse {
                for (_, variant) in modelTypeInfo.variants {
                    if variant.valid == true,
                       let capabilities = variant.capabilities,
                       capabilities.contains("reasoning") {
                        modelOptions.append(ReasoningModelInfo(
                            id: variant.modelId,
                            name: variant.name,
                            displayName: variant.name,
                            provider: provider,
                            isApiModel: false
                        ))
                    }
                }
            }
            let apiModelsData = try await APIClient.shared.get("/settings/api_models/reasoning")
            let apiModelsResponse = try decoder.decode(APIModelsResponseData.self, from: apiModelsData)
            if apiModelsResponse.apiModelsEnabled {
                modelOptions.append(contentsOf: apiModelsResponse.models.map { model in
                    ReasoningModelInfo(id: model.id, name: model.name, displayName: model.displayName, provider: model.provider, isApiModel: model.isApiModel)
                })
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error("[MEMORY_INTELLIGENCE_SETTINGS] Failed to load reasoning model options: \(error)", context: "SettingsShellWindowController")
            #endif
        }
        return modelOptions.sorted { $0.displayName < $1.displayName }
    }
}
