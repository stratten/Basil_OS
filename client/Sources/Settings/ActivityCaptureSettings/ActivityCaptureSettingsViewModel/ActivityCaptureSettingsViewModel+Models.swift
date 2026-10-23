import Foundation

extension ActivityCaptureSettingsViewModel {
    // MARK: - Computed Properties for UI
    var localModels: [ActivityCaptureModelInfo] {
        availableModels.filter { $0.isLocal }
    }
    
    var apiModels: [ActivityCaptureModelInfo] {
        availableModels.filter { !$0.isLocal }
    }
    
    // MARK: - Model Loading
    func loadAvailableModels() async {
        isLoadingModels = true
        
        do {
            var models: [ActivityCaptureModelInfo] = []
            
            // STEP 1: Load local models from /models/installed
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
            
            // Extract local reasoning models
            for (modelType, modelTypeInfo) in localModelsResponse {
                for (_, variant) in modelTypeInfo.variants {
                    if variant.valid == true,
                       let capabilities = variant.capabilities,
                       capabilities.contains("reasoning") {
                        models.append(ActivityCaptureModelInfo(
                            id: variant.modelId,
                            displayName: variant.name,
                            provider: modelType,
                            isLocal: true
                        ))
                    }
                }
            }
            
            // STEP 2: Load API models from /settings/api_models/reasoning
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
            
            // Add API models if enabled
            if apiModelsResponse.apiModelsEnabled {
                for model in apiModelsResponse.models {
                    models.append(ActivityCaptureModelInfo(
                        id: model.id,
                        displayName: model.displayName,
                        provider: model.provider,
                        isLocal: false
                    ))
                }
            }
            
            // Sort models: Local models first, then API models
            models.sort { model1, model2 in
                if model1.isLocal != model2.isLocal {
                    return model1.isLocal // Local models first
                }
                return model1.displayName < model2.displayName // Then alphabetically
            }
            
            availableModels = models
            
            // Set default model if none selected
            if selectedProcessingModel.isEmpty && !models.isEmpty {
                // Prefer local models for activity processing (cost efficiency)
                if let localModel = models.first(where: { $0.isLocal }) {
                    selectedProcessingModel = localModel.id
                } else {
                    selectedProcessingModel = models.first?.id ?? ""
                }
            }
            
        } catch {
            print("Failed to load available models: \(error)")
        }
        
        isLoadingModels = false
    }
}

