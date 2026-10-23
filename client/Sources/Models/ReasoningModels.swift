import Foundation

// MARK: - Shared Model Service Types

struct ReasoningModelInfoVM: Identifiable {
    let id: String
    let name: String
    let displayName: String
    let provider: String
    let isApiModel: Bool
}

struct ReasoningSettingsModelVM: Codable {
    let persistenceDuration: Int
    let visionModel: String
    let languageModel: String
    var reasoningModel: String
    let transcriptionModel: String
    var useApiModels: Bool
}

/// Represents a model that can be used for reasoning operations (conversation and suggestions)
struct ModelServiceInfo: Identifiable {
    let id: String
    let name: String
    let displayName: String
    let provider: String
    let isApiModel: Bool
    
    init(id: String, name: String, displayName: String, provider: String, isApiModel: Bool) {
        self.id = id
        self.name = name
        self.displayName = displayName
        self.provider = provider
        self.isApiModel = isApiModel
    }
    
    // MARK: - Model Loading Functions
    
    /// Loads available reasoning models from both local and API sources
    /// Returns a list of models that can be used for reasoning operations
    static func loadAvailableModels() async -> [ModelServiceInfo] {
        #if DEBUG
        DevLogger.shared.info("Loading available reasoning models", context: "ModelService")
        #endif
        
        let apiClient = APIClient.shared
        var models: [ModelServiceInfo] = []
        
        do {
            // Load model settings to get preferences
            let modelSettings = try await loadModelSettings()
            let useApiModels = modelSettings.useApiModels
            
            #if DEBUG
            DevLogger.shared.info("Loading models - API models enabled: \(useApiModels)", context: "ModelService")
            #endif
            
            // Load local models
            let localModelsData = try await apiClient.get("/models/installed")
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            
            // Decode the shared backend installed-model response.
            struct ModelVariant: Codable {
                let modelId: String  // Canonical registry ID from backend
                let name: String
                let capabilities: [String]?
                let valid: Bool?
            }
            
            struct ModelType: Codable {
                let variants: [String: ModelVariant]
            }
            
            let localModelsResponse = try decoder.decode([String: ModelType].self, from: localModelsData)
            
            #if DEBUG
            DevLogger.shared.info("Found \(localModelsResponse.count) local model types", context: "ModelService")
            #endif
            
            // Process local models
            for (modelType, modelTypeInfo) in localModelsResponse {
                for (_, variant) in modelTypeInfo.variants {
                    if variant.valid == true,
                       let capabilities = variant.capabilities,
                       capabilities.contains("reasoning") {
                        // Use the canonical model_id from the backend - never construct it
                        models.append(ModelServiceInfo(
                            id: variant.modelId,
                            name: variant.name,
                            displayName: variant.name,
                            provider: modelType,
                            isApiModel: false
                        ))
                        
                        #if DEBUG
                        DevLogger.shared.info("✅ Added local reasoning model: \(variant.name) with id \(variant.modelId)", context: "ModelService")
                        #endif
                    }
                }
            }
            
            // Sort local models by name
            models.sort { $0.name < $1.name }
            
            // If API models are enabled, load them as well
            if useApiModels {
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
                DevLogger.shared.info("Found \(apiModelsResponse.models.count) API reasoning models", context: "ModelService")
                #endif
                
                for model in apiModelsResponse.models {
                    models.append(ModelServiceInfo(
                        id: model.id,
                        name: model.name,
                        displayName: model.displayName,
                        provider: model.provider,
                        isApiModel: true
                    ))
                    
                    #if DEBUG
                    DevLogger.shared.info("✅ Added API reasoning model: \(model.displayName) with id \(model.id)", context: "ModelService")
                    #endif
                }
            }
            
            // Final sort by provider then name for a consistent order
            models.sort { (model1, model2) -> Bool in
                if model1.provider == model2.provider {
                    return model1.displayName < model2.displayName
                }
                return model1.provider < model2.provider
            }
            
            #if DEBUG
            DevLogger.shared.info("Loaded \(models.count) total reasoning models", context: "ModelService")
            #endif
            
            return models
            
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to load reasoning models: \(error)", context: "ModelService")
            #endif
            
            return []
        }
    }
    
    /// Load the model settings from the server
    static func loadModelSettings() async throws -> ModelServiceSettings {
        do {
            #if DEBUG
            DevLogger.shared.info("Loading model settings", context: "ModelService")
            #endif
            
            let apiClient = APIClient.shared
            
            do {
                // Use the shared model-settings endpoint and response-decoding contract.
                let settingsData = try await apiClient.get("/settings/models")
                let decoder = JSONDecoder()
                decoder.keyDecodingStrategy = .convertFromSnakeCase
                
                // Create a response wrapper for decoding
                struct ResponseWrapper: Codable {
                    let status: String
                    let settings: ModelServiceSettings
                }
                
                // Decode the complete response
                let response = try decoder.decode(ResponseWrapper.self, from: settingsData)
                
                #if DEBUG
                DevLogger.shared.info("Loaded model settings - reasoning model: \(response.settings.reasoningModel), API models enabled: \(response.settings.useApiModels)", context: "ModelService")
                #endif
                
                return response.settings
            } catch {
                // Check if this is the model_dump error by looking at the error description
                let errorString = error.localizedDescription
                if errorString.contains("model_dump") {
                    #if DEBUG
                    DevLogger.shared.warning("⚠️ Server error with model_dump in settings API, using defaults", context: "ModelService")
                    #endif
                    
                    // Create default settings
                    return ModelServiceSettings(
                        persistenceDuration: 30,
                        visionModel: "default",
                        languageModel: "default",
                        reasoningModel: "default",
                        transcriptionModel: "default",
                        useApiModels: true
                    )
                }
                
                // For other errors, rethrow
                throw error
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to load model settings: \(error)", context: "ModelService")
            #endif
            throw error
        }
    }
    
    /// Gets the recommended model ID based on settings and available models
    static func getRecommendedModelId(settings: ModelServiceSettings, availableModels: [ModelServiceInfo]) -> String? {
        // Build a dictionary for quick lookup
        var modelById: [String: ModelServiceInfo] = [:]
        var modelByDisplayName: [String: ModelServiceInfo] = [:]
        
        for model in availableModels {
            modelById[model.id] = model
            modelByDisplayName[model.displayName] = model
        }
        
        // Try to find the model directly by ID
        if let model = modelById[settings.reasoningModel] {
            return model.id
        }
        
        // Try to find the model by display name
        if let model = modelByDisplayName[settings.reasoningModel] {
            return model.id
        }
        
        // Try to find by API/local preference
        let preferredModels = availableModels.filter { $0.isApiModel == settings.useApiModels }
        if !preferredModels.isEmpty {
            return preferredModels.first?.id
        }
        
        // As a fallback, return any available model
        return availableModels.first?.id
    }
}

// MARK: - API Response Models for Model Loading

/// Model settings response
struct ModelServiceSettings: Codable {
    let persistenceDuration: Int
    let visionModel: String
    let languageModel: String
    var reasoningModel: String
    let transcriptionModel: String
    var useApiModels: Bool
    
    init(
        persistenceDuration: Int,
        visionModel: String,
        languageModel: String,
        reasoningModel: String,
        transcriptionModel: String,
        useApiModels: Bool
    ) {
        self.persistenceDuration = persistenceDuration
        self.visionModel = visionModel
        self.languageModel = languageModel
        self.reasoningModel = reasoningModel
        self.transcriptionModel = transcriptionModel
        self.useApiModels = useApiModels
    }
} 