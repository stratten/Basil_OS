import SwiftUI

@MainActor
final class ReasoningSettingsViewModel: ObservableObject {
    @Published private(set) var localModels: [ReasoningModelInfo] = []
    @Published private(set) var apiModels: [ReasoningModelInfo] = []
    @Published private(set) var customModels: [ReasoningModelInfo] = []
    @Published var selectedModelId: String = ""
    @Published private(set) var useApiModels: Bool = false
    @Published var isLoading: Bool = true
    @Published var error: String? = nil
    @Published var closeAssistantSessionOnInsert: Bool = false
    @Published var assistantOutputPasteMode: AssistantOutputPasteMode = .always
    @Published var useRegionSelection: Bool = false
    
    @Published var agentTaskPushToTalk: Bool = false
    @Published var agentTaskPushToTalkThreshold: Int = 750
    /// Default modality applied when the user initiates a new agentTask
    /// (initial widget or new-AgentTask overlay). Follow-up captures are always voice.
    @Published var agentTaskDefaultModality: AgentTaskInputModality = .voice
    @Published var agentTaskAutoReopenOnCompletion: Bool = true
    
    // MARK: - AssistantSession Settings Properties
    @Published var assistantSessionPushToTalk: Bool = false
    @Published var assistantSessionPushToTalkThreshold: Int = 750
    /// Default modality applied when the user opens the unified AssistantSession
    /// (AssistantSession) widget. The hotkey handler reads this from
    /// `/settings/assistant-session` before `startAssistantSessionFlow` so
    /// the widget renders in the preferred mode without flicker.
    @Published var assistantSessionDefaultModality: AssistantSessionInputMode = .speak
    @Published var conversationDefaultConversationOnly: Bool = false

    // MARK: - Skills Intelligence Properties
    @Published var skillCandidates: [SkillCandidateDTO] = []
    @Published var savedSkills: [SkillDTO] = []
    @Published var isLoadingSkillsState: Bool = false
    @Published var isRunningSkillsIntelligence: Bool = false
    @Published var skillsStatusMessage: String?
    @Published private(set) var pendingCandidateActionIDs: Set<String> = []
    @Published private(set) var pendingSkillDeletionSlugs: Set<String> = []
    @Published var memoryAfterTaskEnabled: Bool = false
    @Published var memoryDailyEnabled: Bool = false
    @Published var memoryDailyTimeLocal: String = "03:00"
    @Published var memoryProcessingModel: String?
    @Published var skillAfterTaskEnabled: Bool = false
    @Published var skillDailyEnabled: Bool = false
    @Published var skillDailyTimeLocal: String = "03:00"
    @Published var skillProcessingModel: String?
    /// Minimum observation_count for a pending candidate to be considered
    /// "recurring" (first-class) and eligible for reconciliation review. Below
    /// this a candidate is a "single sighting" (second-class) and is excluded
    /// from reconciliation clustering while remaining openable.
    @Published var skillReconciliationMinInstances: Int = 2

    /// True while the Skill Reconciliation Workspace window is open. Drives the
    /// Settings freeze overlay (list + list actions + Run now are locked). Set by
    /// `openReconciliationWorkspace()` / the launcher `onClose`, and re-derived on
    /// `loadSkillsState()` for the Settings-reopened-while-workspace-open case.
    @Published var reconciliationActive: Bool = false
    private var skillsStateLoadGeneration = 0

    /// Pending candidates observed at least `skillReconciliationMinInstances`
    /// times (first-class; part of reconciliation review).
    var recurringCandidates: [SkillCandidateDTO] {
        skillCandidates.filter { $0.observationCount >= skillReconciliationMinInstances }
    }

    /// Pending candidates seen fewer than the threshold (second-class; excluded
    /// from reconciliation but still visible/openable).
    var singleSightingCandidates: [SkillCandidateDTO] {
        skillCandidates.filter { $0.observationCount < skillReconciliationMinInstances }
    }

    var availableSkillProcessingModels: [ReasoningModelInfo] {
        if useApiModels {
            return (localModels + apiModels + customModels).sorted { $0.displayName < $1.displayName }
        }
        return localModels.sorted { $0.displayName < $1.displayName }
    }

    var skillsCadenceSummary: String {
        var cadence: [String] = []
        if skillAfterTaskEnabled {
            cadence.append("after successful work")
        }
        if skillDailyEnabled {
            cadence.append("daily at \(skillDailyTimeLocal)")
        }
        if cadence.isEmpty {
            return "Off. Basil will not propose reusable skills unless you enable it."
        }
        return "Runs \(cadence.joined(separator: " and ")). New skills still require approval."
    }
    

    private let apiClient = APIClient.shared // Renamed from 'api' for clarity if it's shared instance
    
    func loadAllSettings() async {
        isLoading = true // General loading for the whole tab
        error = nil
        
        await loadReasoningModels() // Existing function to load models
        await loadAssistantSessionSettings() // Load AssistantSession (AssistantSession) preferences
        await loadAgentTaskSettings()
        await loadConversationSettings()

        isLoading = false
    }

    // MARK: - AssistantSession Settings Loading

    /// One-shot initial fetch so the picker and toggle reflect persisted
    /// preferences on first open instead of waiting for the user to mutate
    /// something. Failures are
    /// logged but non-fatal so a missing/erroring endpoint doesn't block
    /// the rest of the tab.
    func loadAssistantSessionSettings() async {
        do {
            let data = try await apiClient.get("/settings/assistant-session")
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            let response = try decoder.decode(AssistantSessionSettingsResponse.self, from: data)
            self.assistantSessionPushToTalk = response.settings.enablePushToTalk
            self.assistantSessionPushToTalkThreshold = response.settings.pushToTalkThresholdMs
            self.assistantSessionDefaultModality = response.settings.resolvedDefaultInputMode

            #if DEBUG
            DevLogger.shared.info("✅ Loaded AssistantSession settings - modality: \(response.settings.defaultInputModality), ptt: \(response.settings.enablePushToTalk)", context: "ReasoningSettings")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to load AssistantSession settings: \(error)", context: "ReasoningSettings")
            #endif
            self.error = "Failed to load Dill settings: \(error.localizedDescription)"
        }
    }

    func loadAgentTaskSettings() async {
        do {
            let data = try await apiClient.get("/settings/agent-task")
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            let response = try decoder.decode(AgentTaskSettingsResponse.self, from: data)
            let settings = response.settings
            self.agentTaskPushToTalk = settings.enablePushToTalk
            self.agentTaskPushToTalkThreshold = settings.pushToTalkThresholdMs
            self.agentTaskDefaultModality = settings.modality
            self.agentTaskAutoReopenOnCompletion = settings.autoReopenOnCompletion
            apiClient.cacheAgentTaskSettings(settings)
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to load AgentTask settings: \(error)", context: "ReasoningSettings")
            #endif
            self.error = "Failed to load Paprika settings: \(error.localizedDescription)"
        }
    }

    func loadReasoningModels() async {
        isLoading = true
        error = nil
        
        do {
            // Load local models
            let localModelsData = try await apiClient.get("/models/installed")
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
            
            let localModelsResponse = try decoder.decode([String: ModelType].self, from: localModelsData)
            
            #if DEBUG
            DevLogger.shared.info("Found \(localModelsResponse.count) local model types", context: "ReasoningSettings")
            #endif
            
            var localModelsList: [ReasoningModelInfo] = []
            for (modelType, modelTypeInfo) in localModelsResponse {
                for (_, variant) in modelTypeInfo.variants {
                    if variant.valid == true,
                       let capabilities = variant.capabilities,
                       capabilities.contains("reasoning") {
                        localModelsList.append(ReasoningModelInfo(
                            id: variant.modelId,
                            name: variant.name,
                            displayName: variant.name,
                            provider: modelType,
                            isApiModel: false
                        ))
                        #if DEBUG
                        DevLogger.shared.info("✅ Added local reasoning model: \(variant.name)", context: "ReasoningSettings")
                        #endif
                    }
                }
            }
            
            // Sort local models by name
            localModelsList.sort { $0.name < $1.name }
            
            // Load API models
            let apiModelsData = try await apiClient.get("/settings/api_models/reasoning")
            
            struct APIModelResponse: Codable {
                let id: String
                let name: String
                let displayName: String
                let provider: String
                let isApiModel: Bool
                let description: String?
            }
            
            struct APIModelsResponseData: Codable {
                let status: String
                let models: [APIModelResponse]
                let apiModelsEnabled: Bool
                let currentModel: String?
                
                enum CodingKeys: String, CodingKey {
                    case status
                    case models
                    case apiModelsEnabled
                    case currentModel
                }
            }
            
            let apiModelsResponse = try decoder.decode(APIModelsResponseData.self, from: apiModelsData)
            
            #if DEBUG
            DevLogger.shared.info("Found \(apiModelsResponse.models.count) API reasoning models", context: "ReasoningSettings")
            DevLogger.shared.info("API models enabled: \(apiModelsResponse.apiModelsEnabled)", context: "ReasoningSettings")
            #endif
            
            var apiModelsList: [ReasoningModelInfo] = []
            var customModelsList: [ReasoningModelInfo] = []
            
            for model in apiModelsResponse.models {
                // Local models are loaded from /models/installed above. The reasoning
                // endpoint also includes them for consumers that need a unified list.
                guard model.isApiModel else {
                    #if DEBUG
                    DevLogger.shared.info("Skipping local model from API reasoning models: \(model.displayName)", context: "ReasoningSettings")
                    #endif
                    continue
                }

                let modelInfo = ReasoningModelInfo(
                    id: model.id,
                    name: model.name,
                    displayName: model.displayName,
                    provider: model.provider,
                    isApiModel: true
                )
                
                // Separate custom models from regular API models.
                if model.provider == "custom" {
                    customModelsList.append(modelInfo)
                    #if DEBUG
                    DevLogger.shared.info("✅ Added custom reasoning model: \(model.displayName)", context: "ReasoningSettings")
                    #endif
                } else {
                    apiModelsList.append(modelInfo)
                    #if DEBUG
                    DevLogger.shared.info("✅ Added API reasoning model: \(model.displayName)", context: "ReasoningSettings")
                    #endif
                }
            }
            
            // Load current model settings
            let modelSettings = try await loadModelSettings()
            self.closeAssistantSessionOnInsert = modelSettings.closeAssistantSessionOnInsert
            self.assistantOutputPasteMode = modelSettings.assistantOutputPasteMode
            self.useRegionSelection = modelSettings.useRegionSelection
            
            // Update the view model
            self.localModels = localModelsList
            self.apiModels = apiModelsList
            self.customModels = customModelsList
            self.useApiModels = modelSettings.useApiModels
            
            #if DEBUG
            DevLogger.shared.info("API models enabled setting from system: \(modelSettings.useApiModels)", context: "ReasoningSettings")
            #endif
            
            // SIMPLIFIED MODEL SELECTION LOGIC
            // Get the current model selection from settings
            let currentModelSelection = modelSettings.reasoningModel
            
            #if DEBUG
            DevLogger.shared.info("Current model selection: \(currentModelSelection)", context: "ReasoningSettings")
            #endif
            
            // Check if the currently selected model is in the available models list
            let isModelAvailable = 
                (localModelsList.contains(where: { $0.id == currentModelSelection })) ||
                (apiModelsList.contains(where: { $0.id == currentModelSelection }) && modelSettings.useApiModels) ||
                (customModelsList.contains(where: { $0.id == currentModelSelection }) && modelSettings.useApiModels)
            
            #if DEBUG
            DevLogger.shared.info("Checking if current model is available:", context: "ReasoningSettings")
            DevLogger.shared.info("- Current model selection: \(currentModelSelection)", context: "ReasoningSettings")
            DevLogger.shared.info("- Available in local models: \(localModelsList.contains(where: { $0.id == currentModelSelection }))", context: "ReasoningSettings")
            DevLogger.shared.info("- Available in API models: \(apiModelsList.contains(where: { $0.id == currentModelSelection }))", context: "ReasoningSettings")
            DevLogger.shared.info("- Available in custom models: \(customModelsList.contains(where: { $0.id == currentModelSelection }))", context: "ReasoningSettings")
            DevLogger.shared.info("- API models enabled: \(modelSettings.useApiModels)", context: "ReasoningSettings")
            DevLogger.shared.info("- Is model available: \(isModelAvailable)", context: "ReasoningSettings")
            #endif
            
            if isModelAvailable {
                // Use the current selection if it's available
                self.selectedModelId = currentModelSelection
                #if DEBUG
                DevLogger.shared.info("Using current model selection: \(currentModelSelection)", context: "ReasoningSettings")
                #endif
            } else {
                // Model not available, find a suitable alternative
                if modelSettings.useApiModels && !apiModelsList.isEmpty {
                    // Use the first available API model
                    self.selectedModelId = apiModelsList.first!.id
                    #if DEBUG
                    DevLogger.shared.info("Current model not available, using first API model: \(self.selectedModelId)", context: "ReasoningSettings")
                    #endif
                } else if modelSettings.useApiModels && !customModelsList.isEmpty {
                    // Use the first available custom model
                    self.selectedModelId = customModelsList.first!.id
                    #if DEBUG
                    DevLogger.shared.info("Current model not available, using first custom model: \(self.selectedModelId)", context: "ReasoningSettings")
                    #endif
                } else if !localModelsList.isEmpty {
                    // Use the first available local model
                    self.selectedModelId = localModelsList.first!.id
                    #if DEBUG
                    DevLogger.shared.info("Current model not available, using first local model: \(self.selectedModelId)", context: "ReasoningSettings")
                    #endif
                } else {
                    // No models available
                    self.selectedModelId = ""
                    #if DEBUG
                    DevLogger.shared.info("No models available", context: "ReasoningSettings")
                    #endif
                }
            }
            
            isLoading = false
        } catch let decodingError as DecodingError {
            #if DEBUG
            switch decodingError {
            case .keyNotFound(let key, let context):
                DevLogger.shared.error("Failed to load reasoning models: Key '\(key.stringValue)' not found at path \(context.codingPath)", context: "ReasoningSettings")
            case .typeMismatch(let type, let context):
                DevLogger.shared.error("Failed to load reasoning models: Type '\(type)' mismatch at path \(context.codingPath)", context: "ReasoningSettings")
            case .valueNotFound(let type, let context):
                DevLogger.shared.error("Failed to load reasoning models: Value of type '\(type)' not found at path \(context.codingPath)", context: "ReasoningSettings")
            case .dataCorrupted(let context):
                DevLogger.shared.error("Failed to load reasoning models: Data corrupted at path \(context.codingPath) - \(context.debugDescription)", context: "ReasoningSettings")
            @unknown default:
                DevLogger.shared.error("Failed to load reasoning models: Unknown decoding error - \(decodingError)", context: "ReasoningSettings")
            }
            #endif
            self.error = "Failed to decode response: \(decodingError.localizedDescription)"
            isLoading = false
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to load reasoning models: \(error)", context: "ReasoningSettings")
            #endif
            self.error = "Failed to load models: \(error.localizedDescription)"
            isLoading = false
        }
    }
    
    func updateSelectedModel(_ modelId: String) async {
        do {
            // First get current settings to preserve other values
            let currentSettings = try await loadModelSettings()
            
            #if DEBUG
            DevLogger.shared.info("Current reasoning model: \(currentSettings.reasoningModel)", context: "ReasoningSettings")
            DevLogger.shared.info("Attempting to update model to: \(modelId)", context: "ReasoningSettings")
            #endif
            
            // Create updated settings
            let settings = ReasoningSettingsModel(
                persistenceDuration: currentSettings.persistenceDuration,
                visionModel: currentSettings.visionModel,
                languageModel: currentSettings.languageModel,
                reasoningModel: modelId, // Always update the reasoning model directly
                transcriptionModel: currentSettings.transcriptionModel,
                useApiModels: currentSettings.useApiModels,
                closeAssistantSessionOnInsert: currentSettings.closeAssistantSessionOnInsert,
                assistantOutputPasteMode: currentSettings.assistantOutputPasteMode,
                useRegionSelection: currentSettings.useRegionSelection
            )
            
            // Encode and send update
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            let data = try encoder.encode(settings)
            
            #if DEBUG
            DevLogger.shared.debug("Sending settings update: \(String(data: data, encoding: .utf8) ?? "invalid data")", context: "ReasoningSettings")
            #endif
            
            let responseData = try await apiClient.put("/settings/models", data: data)
            
            #if DEBUG
            DevLogger.shared.debug("Update response: \(String(data: responseData, encoding: .utf8) ?? "invalid response")", context: "ReasoningSettings")
            #endif
            
            // Verify the update was successful by checking settings again
            let verificationSettings = try await loadModelSettings()
            if verificationSettings.reasoningModel == modelId {
                self.selectedModelId = modelId
                DevLogger.shared.info("✅ Successfully updated reasoning model to: \(modelId)", context: "ReasoningSettings")
            } else {
                self.error = "The reasoning model was not updated."
                DevLogger.shared.warning("⚠️ Update may have failed - Current model is: \(verificationSettings.reasoningModel) but expected: \(modelId)", context: "ReasoningSettings")
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to update reasoning model: \(error)", context: "ReasoningSettings")
            #endif
            self.error = "Failed to update the reasoning model: \(error.localizedDescription)"
            print("❌ Failed to update reasoning model: \(error)")
        }
    }
    
    private func loadModelSettings() async throws -> ReasoningSettingsModel {
        let data = try await apiClient.get("/settings/models")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        
        // First decode the response wrapper
        struct ResponseWrapper: Codable {
            let status: String
            let settings: ReasoningSettingsModel
        }
        
        // Decode the complete response
        return try decoder.decode(ResponseWrapper.self, from: data).settings
    }
    
    func updateCloseAssistantSessionOnInsert(_ value: Bool) async {
        do {
            var modelSettings = try await loadModelSettings()
            modelSettings.closeAssistantSessionOnInsert = value
            try await saveModelSettings(modelSettings)
            self.closeAssistantSessionOnInsert = value
        } catch {
            // Optionally handle error (e.g., revert UI, show error)
            self.error = "Failed to update the close-on-insert setting: \(error.localizedDescription)"
        }
    }

    func updateAssistantOutputPasteMode(_ mode: AssistantOutputPasteMode) async {
        do {
            var modelSettings = try await loadModelSettings()
            modelSettings.assistantOutputPasteMode = mode
            try await saveModelSettings(modelSettings)
            self.assistantOutputPasteMode = mode
        } catch {
            self.error = "Failed to update the paste setting: \(error.localizedDescription)"
        }
    }
    
    func updateUseRegionSelection(_ value: Bool) async {
        do {
            var modelSettings = try await loadModelSettings()
            modelSettings.useRegionSelection = value
            try await saveModelSettings(modelSettings)
            self.useRegionSelection = value
        } catch {
            // Optionally handle error (e.g., revert UI, show error)
            self.error = "Failed to update the region-selection setting: \(error.localizedDescription)"
        }
    }
    
    private func saveModelSettings(_ settings: ReasoningSettingsModel) async throws {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let data = try encoder.encode(settings)
        _ = try await apiClient.put("/settings/models", data: data)
    }


    /// Partial-update payload for `PUT /settings/agent-task`. Every property is
    /// optional so a caller only encodes the single field it intends to
    /// change; synthesized `Encodable` conformance omits `nil` properties from
    /// the JSON body via `encodeIfPresent`, and the backend (`AgentTaskSettingsUpdate`
    /// in `voice_routes.py`) only mutates fields that are present. This
    /// deliberately avoids the previous "GET full settings, mutate one field,
    /// PUT the full object back" pattern: that pattern read a snapshot on the
    /// client, so two of these calls firing close together (e.g. flipping the
    /// modality radio and the push-to-talk switch within the same settings
    /// session) could race, with whichever PUT lands second silently
    /// reverting the other's field back to the stale value it read. Sending
    /// only the changed field removes that race because the backend always
    /// merges against its own fresh on-disk read at request time.
    private struct AgentTaskSettingsPartialUpdate: Encodable {
        var enablePushToTalk: Bool?
        var pushToTalkThresholdMs: Int?
        var defaultInputModality: String?
        var autoReopenOnCompletion: Bool?

        enum CodingKeys: String, CodingKey {
            case enablePushToTalk = "enable_push_to_talk"
            case pushToTalkThresholdMs = "push_to_talk_threshold_ms"
            case defaultInputModality = "default_input_modality"
            case autoReopenOnCompletion = "auto_reopen_on_completion"
        }
    }

    /// Partial-update payload for `PUT /settings/assistant-session`. See
    /// `AgentTaskSettingsPartialUpdate` for why this only encodes the field
    /// actually being changed.
    private struct AssistantSessionSettingsPartialUpdate: Encodable {
        var enablePushToTalk: Bool?
        var pushToTalkThresholdMs: Int?
        var defaultInputModality: String?

        enum CodingKeys: String, CodingKey {
            case enablePushToTalk = "enable_push_to_talk"
            case pushToTalkThresholdMs = "push_to_talk_threshold_ms"
            case defaultInputModality = "default_input_modality"
        }
    }

    /// Merges a single changed field into the client-side AgentTask settings
    /// cache without a network round trip, so `getCachedAgentTaskSettings()`
    /// consumers (the capture controller) see the new value immediately.
    private func updateCachedAgentTaskSettings(
        enablePushToTalk: Bool? = nil,
        pushToTalkThresholdMs: Int? = nil,
        defaultInputModality: String? = nil,
        autoReopenOnCompletion: Bool? = nil
    ) {
        let cached = apiClient.getCachedAgentTaskSettings()
        apiClient.cacheAgentTaskSettings(AgentTaskSettings(
            widgetPosition: cached.widgetPosition,
            resultWidgetSize: cached.resultWidgetSize,
            enablePushToTalk: enablePushToTalk ?? cached.enablePushToTalk,
            pushToTalkThresholdMs: pushToTalkThresholdMs ?? cached.pushToTalkThresholdMs,
            defaultInputModality: defaultInputModality ?? cached.defaultInputModality,
            autoReopenOnCompletion: autoReopenOnCompletion ?? cached.autoReopenOnCompletion
        ))
    }

    func updateAgentTaskPushToTalk(_ enabled: Bool) async {
        do {
            let payload = AgentTaskSettingsPartialUpdate(enablePushToTalk: enabled)
            let updateData = try JSONEncoder().encode(payload)
            _ = try await apiClient.put("/settings/agent-task", data: updateData)

            updateCachedAgentTaskSettings(enablePushToTalk: enabled)
            self.agentTaskPushToTalk = enabled

            #if DEBUG
            DevLogger.shared.info("✅ Updated agentTask push-to-talk to: \(enabled)", context: "ReasoningSettings")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to update agentTask push-to-talk: \(error)", context: "ReasoningSettings")
            #endif
            self.error = "Failed to update Paprika push-to-talk: \(error.localizedDescription)"
        }
    }
    
    func updateAgentTaskDefaultModality(_ modality: AgentTaskInputModality) async {
        do {
            let payload = AgentTaskSettingsPartialUpdate(defaultInputModality: modality.rawValue)
            let updateData = try JSONEncoder().encode(payload)
            _ = try await apiClient.put("/settings/agent-task", data: updateData)

            // Keep the local cache in sync so subsequent `getCachedAgentTaskSettings()`
            // reads (used by the capture controller to apply the default) see the new value.
            updateCachedAgentTaskSettings(defaultInputModality: modality.rawValue)

            self.agentTaskDefaultModality = modality

            #if DEBUG
            DevLogger.shared.info("✅ Updated agentTask default input modality to: \(modality.rawValue)", context: "ReasoningSettings")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to update agentTask default input modality: \(error)", context: "ReasoningSettings")
            #endif
            self.error = "Failed to update the Paprika default input mode: \(error.localizedDescription)"
        }
    }

    func updateAgentTaskAutoReopenOnCompletion(_ enabled: Bool) async {
        let persistedValue = apiClient.getCachedAgentTaskSettings().autoReopenOnCompletion
        do {
            let payload = AgentTaskSettingsPartialUpdate(autoReopenOnCompletion: enabled)
            let updateData = try JSONEncoder().encode(payload)
            _ = try await apiClient.put("/settings/agent-task", data: updateData)

            updateCachedAgentTaskSettings(autoReopenOnCompletion: enabled)
            self.agentTaskAutoReopenOnCompletion = enabled

            #if DEBUG
            DevLogger.shared.info("✅ Updated agentTask auto reopen on completion to: \(enabled)", context: "ReasoningSettings")
            #endif
        } catch {
            self.agentTaskAutoReopenOnCompletion = persistedValue
            #if DEBUG
            DevLogger.shared.error("❌ Failed to update agentTask auto reopen on completion: \(error)", context: "ReasoningSettings")
            #endif
            self.error = "Failed to update the auto-reopen setting: \(error.localizedDescription)"
        }
    }

    func updateAgentTaskPushToTalkThreshold(_ thresholdMs: Int) async {
        do {
            let payload = AgentTaskSettingsPartialUpdate(pushToTalkThresholdMs: thresholdMs)
            let updateData = try JSONEncoder().encode(payload)
            _ = try await apiClient.put("/settings/agent-task", data: updateData)

            updateCachedAgentTaskSettings(pushToTalkThresholdMs: thresholdMs)
            self.agentTaskPushToTalkThreshold = thresholdMs
            
            #if DEBUG
            DevLogger.shared.info("✅ Updated agentTask push-to-talk threshold to: \(thresholdMs)ms", context: "ReasoningSettings")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to update agentTask push-to-talk threshold: \(error)", context: "ReasoningSettings")
            #endif
            self.error = "Failed to update the Paprika push-to-talk threshold: \(error.localizedDescription)"
        }
    }
    
    func updateAssistantSessionPushToTalk(_ enabled: Bool) async {
        do {
            let payload = AssistantSessionSettingsPartialUpdate(enablePushToTalk: enabled)
            let updateData = try JSONEncoder().encode(payload)
            _ = try await apiClient.put("/settings/assistant-session", data: updateData)

            self.assistantSessionPushToTalk = enabled
            
            #if DEBUG
            DevLogger.shared.info("✅ Updated AssistantSession push-to-talk to: \(enabled)", context: "ReasoningSettings")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to update AssistantSession push-to-talk: \(error)", context: "ReasoningSettings")
            #endif
            self.error = "Failed to update Dill push-to-talk: \(error.localizedDescription)"
        }
    }
    
    func updateAssistantSessionPushToTalkThreshold(_ thresholdMs: Int) async {
        do {
            let payload = AssistantSessionSettingsPartialUpdate(pushToTalkThresholdMs: thresholdMs)
            let updateData = try JSONEncoder().encode(payload)
            _ = try await apiClient.put("/settings/assistant-session", data: updateData)

            self.assistantSessionPushToTalkThreshold = thresholdMs
            
            #if DEBUG
            DevLogger.shared.info("✅ Updated AssistantSession push-to-talk threshold to: \(thresholdMs)ms", context: "ReasoningSettings")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to update AssistantSession push-to-talk threshold: \(error)", context: "ReasoningSettings")
            #endif
            self.error = "Failed to update the Dill push-to-talk threshold: \(error.localizedDescription)"
        }
    }

    /// Persists the user's preferred entry mode (speak vs type) for the
    /// unified AssistantSession widget. Sends only the changed field (see
    /// `AssistantSessionSettingsPartialUpdate`); the local `@Published` is
    /// updated optimistically for UI feedback ahead of the round trip.
    func updateAssistantSessionDefaultModality(_ modality: AssistantSessionInputMode) async {
        do {
            let payload = AssistantSessionSettingsPartialUpdate(defaultInputModality: modality.rawValue)
            let updateData = try JSONEncoder().encode(payload)
            _ = try await apiClient.put("/settings/assistant-session", data: updateData)

            self.assistantSessionDefaultModality = modality

            #if DEBUG
            DevLogger.shared.info("✅ Updated AssistantSession default input modality to: \(modality.rawValue)", context: "ReasoningSettings")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to update AssistantSession default input modality: \(error)", context: "ReasoningSettings")
            #endif
            self.error = "Failed to update the Dill default input mode: \(error.localizedDescription)"
        }
    }

    // MARK: - Skills Intelligence Management

    func loadSkillsState() async {
        skillsStateLoadGeneration += 1
        let generation = skillsStateLoadGeneration
        isLoadingSkillsState = true
        skillsStatusMessage = nil

        do {
            async let settings = apiClient.getMemoryIntelligenceSettings()
            async let candidates = apiClient.listSkillCandidates()
            async let skills = apiClient.listSkills()
            async let reconciliationStatus = apiClient.getReconciliationStatus()
            let (loadedSettings, loadedCandidates, loadedSkills, loadedStatus) = try await (
                settings,
                candidates,
                skills,
                reconciliationStatus
            )
            guard generation == skillsStateLoadGeneration else { return }
            applyMemoryIntelligenceSettings(loadedSettings)
            skillCandidates = loadedCandidates
            savedSkills = loadedSkills
            reconciliationActive = loadedStatus.active
        } catch {
            guard generation == skillsStateLoadGeneration else { return }
            #if DEBUG
            DevLogger.shared.error("❌ Failed to load skills state: \(error)", context: "ReasoningSettings")
            #endif
            self.skillsStatusMessage = "Error loading skills: \(error.localizedDescription)"
        }

        if generation == skillsStateLoadGeneration {
            isLoadingSkillsState = false
        }
    }

    func updateSkillAfterTaskEnabled(_ enabled: Bool) async {
        await updateMemoryIntelligenceSettings { settings in
            settings.skillAfterTaskEnabled = enabled
        }
    }

    func updateSkillDailyEnabled(_ enabled: Bool) async {
        await updateMemoryIntelligenceSettings { settings in
            settings.skillDailyEnabled = enabled
        }
    }

    func updateSkillDailyTimeLocal(_ time: String) async {
        await updateMemoryIntelligenceSettings { settings in
            settings.skillDailyTimeLocal = time
        }
    }

    func updateSkillProcessingModel(_ modelId: String?) async {
        await updateMemoryIntelligenceSettings { settings in
            settings.skillProcessingModel = modelId
        }
    }

    func updateSkillReconciliationMinInstances(_ minInstances: Int) async {
        let clamped = max(1, minInstances)
        await updateMemoryIntelligenceSettings { settings in
            settings.skillReconciliationMinInstances = clamped
        }
    }

    func deleteSkill(slug: String) async {
        guard !pendingSkillDeletionSlugs.contains(slug) else { return }
        pendingSkillDeletionSlugs.insert(slug)
        defer {
            pendingSkillDeletionSlugs.remove(slug)
        }
        do {
            try await apiClient.deleteSkill(slug: slug)
            await loadSkillsState()
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to delete skill '\(slug)': \(error)", context: "ReasoningSettings")
            #endif
            self.skillsStatusMessage = "Error deleting skill: \(error.localizedDescription)"
        }
    }

    func declineCandidate(id: String) async {
        guard !pendingCandidateActionIDs.contains(id) else { return }
        pendingCandidateActionIDs.insert(id)
        defer {
            pendingCandidateActionIDs.remove(id)
        }
        do {
            try await apiClient.declineSkillCandidate(id: id)
            await loadSkillsState()
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to decline skill candidate: \(error)", context: "ReasoningSettings")
            #endif
            self.skillsStatusMessage = "Error declining candidate: \(error.localizedDescription)"
        }
    }

    func runIntelligenceNow() async {
        isRunningSkillsIntelligence = true
        skillsStatusMessage = nil

        do {
            let result = try await apiClient.runMemoryIntelligenceNow()
            await loadSkillsState()
            if result.errors.isEmpty {
                self.skillsStatusMessage = "Added \(result.memoryProposalsAdded) memory proposal(s) and \(result.skillCandidatesAdded) skill candidate(s)."
            } else {
                self.skillsStatusMessage = "Completed with errors: \(result.errors.joined(separator: ", "))"
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to run skill intelligence: \(error)", context: "ReasoningSettings")
            #endif
            self.skillsStatusMessage = "Error running skill intelligence: \(error.localizedDescription)"
        }

        isRunningSkillsIntelligence = false
    }

    /// Launch (or focus) the Skill Reconciliation Workspace. Starts a session
    /// (freezing background skill capture) then opens the dedicated window. If a
    /// session is already active, just brings the existing window forward.
    func openReconciliationWorkspace(onWorkspaceClosed: (() -> Void)? = nil) async {
        if let status = try? await apiClient.getReconciliationStatus(), status.active {
            self.reconciliationActive = true
            ReconciliationWorkspaceLauncher.shared.focusOrReopen()
            return
        }
        do {
            _ = try await apiClient.startReconciliationSession()
            self.reconciliationActive = true
            ReconciliationWorkspaceLauncher.shared.open { [weak self] in
                guard let self else { return }
                self.reconciliationActive = false
                Task {
                    await self.loadSkillsState()
                    onWorkspaceClosed?()
                }
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to start reconciliation session: \(error)", context: "ReasoningSettings")
            #endif
            self.skillsStatusMessage = "Error starting reconciliation: \(error.localizedDescription)"
        }
    }

    private func updateMemoryIntelligenceSettings(_ mutate: (inout MemoryIntelligenceSettingsDTO) -> Void) async {
        do {
            var settings = try await apiClient.getMemoryIntelligenceSettings()
            mutate(&settings)
            let updatedSettings = try await apiClient.updateMemoryIntelligenceSettings(settings)
            applyMemoryIntelligenceSettings(updatedSettings)
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to update skill intelligence settings: \(error)", context: "ReasoningSettings")
            #endif
            self.skillsStatusMessage = "Error updating skill settings: \(error.localizedDescription)"
        }
    }

    private func applyMemoryIntelligenceSettings(_ settings: MemoryIntelligenceSettingsDTO) {
        self.memoryAfterTaskEnabled = settings.memoryAfterTaskEnabled
        self.memoryDailyEnabled = settings.memoryDailyEnabled
        self.memoryDailyTimeLocal = settings.memoryDailyTimeLocal
        self.memoryProcessingModel = settings.memoryProcessingModel
        self.skillAfterTaskEnabled = settings.skillAfterTaskEnabled
        self.skillDailyEnabled = settings.skillDailyEnabled
        self.skillDailyTimeLocal = settings.skillDailyTimeLocal
        self.skillProcessingModel = settings.skillProcessingModel
        self.skillReconciliationMinInstances = settings.skillReconciliationMinInstances
    }
}

// MARK: - Model Types
struct ReasoningSettingsModel: Codable {
    let persistenceDuration: Int
    let visionModel: String
    let languageModel: String
    var reasoningModel: String
    let transcriptionModel: String
    var useApiModels: Bool
    var closeAssistantSessionOnInsert: Bool
    var assistantOutputPasteMode: AssistantOutputPasteMode
    var useRegionSelection: Bool
    // Removing defaultApiVisionModel - using unified model approach
} 