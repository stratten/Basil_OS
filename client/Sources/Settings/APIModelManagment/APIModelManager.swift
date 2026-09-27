import SwiftUI
import os

// MARK: - API Model Management

/// Settings for API models
struct APIModelSettings: Codable {
    var useApiModels: Bool
    var apiExtendedThinking: Bool
    var anthropicEnabled: Bool
    var openaiEnabled: Bool
    var geminiEnabled: Bool
    var anthropicModels: [String: Bool]
    var openaiModels: [String: Bool]
    var geminiModels: [String: Bool]
    var currentModels: CurrentModels
    
    struct CurrentModels: Codable {
        var reasoning: String
        var vision: String
        var language: String
    }
    
    enum CodingKeys: String, CodingKey {
        case useApiModels = "use_api_models"
        case apiExtendedThinking = "api_extended_thinking"
        case anthropicEnabled = "anthropic_enabled"
        case openaiEnabled = "openai_enabled"
        case geminiEnabled = "gemini_enabled"
        case anthropicModels = "anthropic_models"
        case openaiModels = "openai_models"
        case geminiModels = "gemini_models"
        case currentModels = "current_models"
    }
    
    init(useApiModels: Bool = false,
         apiExtendedThinking: Bool = false,
         anthropicEnabled: Bool = false,
         openaiEnabled: Bool = false,
         geminiEnabled: Bool = false,
         anthropicModels: [String: Bool] = [:],
         openaiModels: [String: Bool] = [:],
         geminiModels: [String: Bool] = [:],
         currentModels: CurrentModels = CurrentModels(reasoning: "", vision: "", language: "")) {
        self.useApiModels = useApiModels
        self.apiExtendedThinking = apiExtendedThinking
        self.anthropicEnabled = anthropicEnabled
        self.openaiEnabled = openaiEnabled
        self.geminiEnabled = geminiEnabled
        self.anthropicModels = anthropicModels
        self.openaiModels = openaiModels
        self.geminiModels = geminiModels
        self.currentModels = currentModels
    }
}

/// Information about an API model
struct APIModelInfo: Identifiable {
    let id: String
    let name: String
    let description: String?
    let provider: String
    let capabilities: [ModelCapabilityType]
    var isEnabled: Bool
    var isDefaultForReasoning: Bool
    var isDefaultForVision: Bool
    var supportsExtendedThinking: Bool
}

/// Information about an API provider
struct APIProviderInfo: Identifiable {
    let id: String
    let name: String
    var isEnabled: Bool
    var usingOwnApiKey: Bool
    var localUsingOwnApiKey: Bool  // Track UI state separately
    var hasKey: Bool
    var models: [APIModelInfo]
}

/// Response structure for API key validation
struct APIKeyValidationResponse: Decodable {
    let provider: String
    let valid: Bool
    let error: String?
    let details: [String: JSONValue]?
    
    // Enum to handle different JSON value types
    enum JSONValue: Decodable {
        case string(String)
        case bool(Bool)
        case int(Int)
        case double(Double)
        case null
        
        init(from decoder: Decoder) throws {
            let container = try decoder.singleValueContainer()
            
            if let stringValue = try? container.decode(String.self) {
                self = .string(stringValue)
            } else if let boolValue = try? container.decode(Bool.self) {
                self = .bool(boolValue)
            } else if let intValue = try? container.decode(Int.self) {
                self = .int(intValue)
            } else if let doubleValue = try? container.decode(Double.self) {
                self = .double(doubleValue)
            } else if container.decodeNil() {
                self = .null
            } else {
                throw DecodingError.dataCorruptedError(
                    in: container,
                    debugDescription: "Cannot decode JSON value"
                )
            }
        }
        
        // Helper methods to extract values
        var boolValue: Bool? {
            if case .bool(let value) = self {
                return value
            }
            return nil
        }
        
        var stringValue: String? {
            if case .string(let value) = self {
                return value
            }
            return nil
        }
    }
}

// MARK: - API Model Manager

class APIModelManager {
    static let shared = APIModelManager()
    
    private init() {}
    
    // MARK: - API Model Methods
    
    func loadApiModels(existingProviders: [APIProviderInfo] = []) async -> (settings: APIModelSettings, providers: [APIProviderInfo], error: String?) {
        do {
            #if DEBUG
            DevLogger.shared.info("Starting to load API models", context: "APIModels")
            #endif
            
            let data = try await APIClient.shared.getApiModelSettings()
            
            #if DEBUG
            DevLogger.shared.info("Received API model settings data: \(data.count) bytes", context: "APIModels")
            let responseString = String(data: data, encoding: .utf8) ?? "Unable to decode as string"
            DevLogger.shared.info("Response content: \(responseString)", context: "APIModels")
            #endif
            
            let decoder = JSONDecoder()
            
            #if DEBUG
            DevLogger.shared.info("Attempting to decode API models response", context: "APIModels")
            #endif
            
            // Define a top-level response structure to match the server response format
            struct APIModelsResponse: Codable {
                let status: String
                let settings: SettingsData
                let apiModels: [String: APIProviderModels]
                
                enum CodingKeys: String, CodingKey {
                    case status
                    case settings
                    case apiModels = "api_models"
                }
            }
            
            struct SettingsData: Codable {
                let useApiModels: Bool
                let apiExtendedThinking: Bool
                let currentModels: CurrentModelsData
                
                struct CurrentModelsData: Codable {
                    let reasoning: String
                    let vision: String
                    let language: String
                }
                
                enum CodingKeys: String, CodingKey {
                    case useApiModels = "use_api_models"
                    case apiExtendedThinking = "api_extended_thinking"
                    case currentModels = "current_models"
                }
            }
            
            struct APIProviderModels: Codable {
                let enabled: Bool
                let usingOwnApiKey: Bool?
                let hasKey: Bool?
                let models: [String: APIModelDetails]
                let modelOrder: [String]?
                
                enum CodingKeys: String, CodingKey {
                    case enabled
                    case usingOwnApiKey = "using_own_api_key"
                    case hasKey = "has_key"
                    case models
                    case modelOrder = "model_order"
                }
            }
            
            struct APIModelDetails: Codable {
                let name: String?
                let displayName: String?
                let description: String?
                let enabled: Bool
                let capabilities: [String]
                let isDefaultForReasoning: Bool?
                let isDefaultForVision: Bool?
                let supportsExtendedThinking: Bool?
                
                enum CodingKeys: String, CodingKey {
                    case name
                    case displayName = "display_name"
                    case description
                    case enabled
                    case capabilities
                    case isDefaultForReasoning = "is_default_for_reasoning"
                    case isDefaultForVision = "is_default_for_vision"
                    case supportsExtendedThinking = "supports_extended_thinking"
                }
                
                #if DEBUG
                func debugDescription() -> String {
                    return "Name: \(displayName ?? name ?? "Unknown"), Enabled: \(enabled), Capabilities: \(capabilities), Default for Reasoning: \(isDefaultForReasoning ?? false), Default for Vision: \(isDefaultForVision ?? false)"
                }
                #endif
            }
            
            let response = try decoder.decode(APIModelsResponse.self, from: data)
            
            #if DEBUG
            DevLogger.shared.info("Successfully decoded API models response", context: "APIModels")
            DevLogger.shared.info("Status: \(response.status)", context: "APIModels")
            DevLogger.shared.info("Settings: useApiModels=\(response.settings.useApiModels)", context: "APIModels")
            DevLogger.shared.info("Provider count: \(response.apiModels.count)", context: "APIModels")
            
            for (provider, providerData) in response.apiModels {
                DevLogger.shared.info("Provider: \(provider), Enabled: \(providerData.enabled), Models: \(providerData.models.count)", context: "APIModels")
                
                for (modelId, modelData) in providerData.models {
                    DevLogger.shared.info("  Model: \(modelId) - \(modelData.debugDescription())", context: "APIModels")
                }
            }
            #endif
            
            // Extract provider-specific model enabled states
            var anthropicModels: [String: Bool] = [:]
            var openaiModels: [String: Bool] = [:]
            var geminiModels: [String: Bool] = [:]
            
            if let anthropicData = response.apiModels["anthropic"] {
                for (modelId, modelData) in anthropicData.models {
                    anthropicModels[modelId] = modelData.enabled
                }
            }
            
            if let openaiData = response.apiModels["openai"] {
                for (modelId, modelData) in openaiData.models {
                    openaiModels[modelId] = modelData.enabled
                }
            }
            
            if let geminiData = response.apiModels["gemini"] {
                for (modelId, modelData) in geminiData.models {
                    geminiModels[modelId] = modelData.enabled
                }
            }
            
            // Create settings object
            let settings = APIModelSettings(
                useApiModels: response.settings.useApiModels,
                apiExtendedThinking: response.settings.apiExtendedThinking,
                anthropicEnabled: response.apiModels["anthropic"]?.enabled ?? false,
                openaiEnabled: response.apiModels["openai"]?.enabled ?? false,
                geminiEnabled: response.apiModels["gemini"]?.enabled ?? false,
                anthropicModels: anthropicModels,
                openaiModels: openaiModels,
                geminiModels: geminiModels,
                currentModels: APIModelSettings.CurrentModels(
                    reasoning: response.settings.currentModels.reasoning,
                    vision: response.settings.currentModels.vision,
                    language: response.settings.currentModels.language
                )
            )
            
            #if DEBUG
            DevLogger.shared.info("Updated API settings", context: "APIModels")
            #endif
            
            // Build provider list
            var newProviders: [APIProviderInfo] = []
            
            // Define the desired order of providers
            let providerOrder: [String] = ["anthropic", "openai", "gemini"]
            
            for providerId in providerOrder {
                guard let providerData = response.apiModels[providerId] else { continue }
                
                var modelInfos: [APIModelInfo] = []
                
                // Use modelOrder if available, otherwise iterate dictionary keys (unordered)
                let idsToIterate: [String]
                if let orderedIds = providerData.modelOrder, !orderedIds.isEmpty {
                    idsToIterate = orderedIds
                    #if DEBUG
                    DevLogger.shared.info("Using server-provided model order for \(providerId): \(orderedIds.joined(separator: ", "))", context: "APIModels")
                    #endif
                } else {
                    // Fallback to dictionary keys if modelOrder is nil or empty
                    idsToIterate = Array(providerData.models.keys)
                    #if DEBUG
                    DevLogger.shared.warning("model_order not found or empty for \(providerId). Falling back to dictionary key order (potentially random).", context: "APIModels")
                    #endif
                }
                
                for modelId in idsToIterate {
                    guard let modelDetails = providerData.models[modelId] else {
                        #if DEBUG
                        DevLogger.shared.warning("Model ID \(modelId) from model_order not found in models dictionary for provider \(providerId). Skipping.", context: "APIModels")
                        #endif
                        continue
                    }
                    
                    // Determine if model is default for reasoning or vision
                    let isDefaultForReasoning = response.settings.currentModels.reasoning == modelId
                    let isDefaultForVision = response.settings.currentModels.vision == modelId
                    
                    let modelInfo = APIModelInfo(
                        id: modelId,
                        name: modelDetails.displayName ?? modelDetails.name ?? modelId,
                        description: modelDetails.description,
                        provider: providerId,
                        capabilities: modelDetails.capabilities.compactMap { ModelCapabilityType(rawValue: $0.lowercased()) },
                        isEnabled: modelDetails.enabled,
                        isDefaultForReasoning: isDefaultForReasoning,
                        isDefaultForVision: isDefaultForVision,
                        supportsExtendedThinking: modelDetails.supportsExtendedThinking ?? false
                    )
                    modelInfos.append(modelInfo)
                }
                
                // When loading from the backend, preserve the local UI state if it exists
                let existingProvider = existingProviders.first(where: { $0.id == providerId })
                
                // Initialize localUsingOwnApiKey from the backend state when starting up
                // If existingProviders is empty (app just started), use the backend value
                // Otherwise, preserve the local UI state during refreshes
                let localUsingOwnApiKey = existingProviders.isEmpty 
                    ? (providerData.usingOwnApiKey ?? false) 
                    : (existingProvider?.localUsingOwnApiKey ?? (providerData.usingOwnApiKey ?? false))
                
                let providerInfo = APIProviderInfo(
                    id: providerId,
                    name: providerId.capitalized,
                    isEnabled: providerData.enabled,
                    usingOwnApiKey: providerData.usingOwnApiKey ?? false,
                    localUsingOwnApiKey: localUsingOwnApiKey,
                    hasKey: providerData.hasKey ?? false,
                    models: modelInfos
                )
                
                #if DEBUG
                DevLogger.shared.info("Created provider info: \(providerId), Models: \(modelInfos.count)", context: "APIModels")
                #endif
                
                newProviders.append(providerInfo)
            }
            
            // Sort providers to ensure consistent order regardless of enabled state
            newProviders.sort { $0.id < $1.id }
            
            #if DEBUG
            DevLogger.shared.info("Built provider list with \(newProviders.count) providers", context: "APIModels")
            #endif
            
            return (settings, newProviders, nil)
            
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to load API models: \(error.localizedDescription)", context: "APIModels")
            
            if let decodingError = error as? DecodingError {
                switch decodingError {
                case .keyNotFound(let key, let context):
                    DevLogger.shared.error("Key not found: \(key.stringValue) in \(context.codingPath.map { $0.stringValue })", context: "APIModels")
                case .typeMismatch(let type, let context):
                    DevLogger.shared.error("Type mismatch: expected \(type) at \(context.codingPath.map { $0.stringValue })", context: "APIModels")
                case .valueNotFound(let type, let context):
                    DevLogger.shared.error("Value not found: expected \(type) at \(context.codingPath.map { $0.stringValue })", context: "APIModels")
                case .dataCorrupted(let context):
                    DevLogger.shared.error("Data corrupted: \(context.debugDescription)", context: "APIModels")
                @unknown default:
                    DevLogger.shared.error("Unknown decoding error: \(decodingError)", context: "APIModels")
                }
            }
            #endif
            
            return (APIModelSettings(), [], "Failed to load API models: \(error.localizedDescription)")
        }
    }
    
    // MARK: - API Key Management
    
    func saveApiKey(provider: String, key: String, providerInfo: APIProviderInfo? = nil) async -> (isValid: Bool, message: String?, error: String?) {
        do {
            // First test if the key is valid
            do {
                #if DEBUG
                DevLogger.shared.info("Testing API key for \(provider)", context: "APIModels")
                #endif
                
                let testData = try await APIClient.shared.testApiKey(provider: provider, key: key)
                
                #if DEBUG
                DevLogger.shared.info("Received API key test response data: \(testData.count) bytes", context: "APIModels")
                DevLogger.shared.info("Raw response: \(String(data: testData, encoding: .utf8) ?? "unable to decode")", context: "APIModels")
                #endif
                
                let decoder = JSONDecoder()
                let testResponse = try decoder.decode(APIKeyValidationResponse.self, from: testData)
                
                #if DEBUG
                DevLogger.shared.info("API key test response: valid=\(testResponse.valid), error=\(testResponse.error ?? "none")", context: "APIModels")
                if let details = testResponse.details {
                    DevLogger.shared.info("API key test details: \(details)", context: "APIModels")
                }
                #endif
                
                if testResponse.valid {
                    // Key is valid, save it
                    _ = try await APIClient.shared.setApiKey(provider: provider, key: key)
                    
                    // Now that we have a valid key, update the provider to use it if requested
                    if let providerInfo = providerInfo, providerInfo.localUsingOwnApiKey {
                        let updateError = await updateProviderApiKeySourceWithBackend(provider: provider, providerInfo: providerInfo)
                        if let updateError = updateError {
                            return (true, "API key validated and saved successfully, but failed to update provider settings", updateError)
                        }
                        
                        // Ensure the UI state stays in sync with the backend state
                        #if DEBUG
                        DevLogger.shared.info("API key validated and saved, setting localUsingOwnApiKey to true", context: "APIModels")
                        #endif
                    }
                    
                    // Check if the key was validated with an actual API call
                    let apiValidated = testResponse.details?["api_validated"]?.boolValue ?? false
                    let validationMethod = apiValidated ? "API validation" : "format validation"
                    
                    return (true, "API key validated (\(validationMethod)) and saved successfully", nil)
                } else {
                    // Key is invalid - provide more specific error messages
                    var errorMessage = testResponse.error ?? "Invalid API key format"
                    
                    // Check for specific error types in the error message
                    if errorMessage.contains("API validation failed") {
                        // This is from our enhanced validation
                        if errorMessage.contains("Invalid API key") {
                            errorMessage = "The API key was rejected by \(provider.capitalized). Please check that you've entered it correctly."
                        } else if errorMessage.contains("Insufficient quota") {
                            errorMessage = "Your \(provider.capitalized) account has insufficient quota or credits to use this API key."
                        }
                    }
                    
                    return (false, errorMessage, nil)
                }
            } catch let error as NSError {
                // Check if it's a 404 error (endpoint not found)
                if error.domain == NSURLErrorDomain && error.code == 404 {
                    // If the test endpoint is not available, try to save the key directly
                    #if DEBUG
                    DevLogger.shared.info("API key test endpoint not available, attempting to save key directly", context: "APIModels")
                    #endif
                    
                    // Try to save the key without validation
                    _ = try await APIClient.shared.setApiKey(provider: provider, key: key)
                    
                    // Update the provider to use the key if requested
                    if let providerInfo = providerInfo, providerInfo.localUsingOwnApiKey {
                        let updateError = await updateProviderApiKeySourceWithBackend(provider: provider, providerInfo: providerInfo)
                        if let updateError = updateError {
                            return (true, "API key saved (validation unavailable), but failed to update provider settings", updateError)
                        }
                    }
                    
                    return (true, "API key saved (validation service unavailable)", nil)
                } else if error is DecodingError {
                    // Handle decoding errors specifically
                    #if DEBUG
                    DevLogger.shared.error("Error decoding API key test response: \(error.localizedDescription)", context: "APIModels")
                    #endif
                    
                    return (false, "Error processing API key validation response. Please try again or contact support.", nil)
                } else {
                    // Other error
                    #if DEBUG
                    DevLogger.shared.error("Error testing API key: \(error.localizedDescription)", context: "APIModels")
                    #endif
                    
                    // Provide more user-friendly error messages
                    var errorMessage = "Error validating API key: \(error.localizedDescription)"
                    
                    if error.domain == NSURLErrorDomain {
                        switch error.code {
                        case NSURLErrorTimedOut:
                            errorMessage = "Connection timed out while validating the API key. Please try again."
                        case NSURLErrorNotConnectedToInternet:
                            errorMessage = "No internet connection available. Please check your network and try again."
                        case NSURLErrorCannotConnectToHost:
                            errorMessage = "Could not connect to the \(provider.capitalized) API server. Please try again later."
                        default:
                            errorMessage = "Network error while validating API key: \(error.localizedDescription)"
                        }
                    }
                    
                    return (false, errorMessage, nil)
                }
            }
        } catch {
            // Handle error
            #if DEBUG
            DevLogger.shared.error("Error saving API key: \(error.localizedDescription)", context: "APIModels")
            #endif
            
            return (false, "Error saving API key: \(error.localizedDescription)", nil)
        }
    }
    
    func updateApiModelsMasterToggle(enabled: Bool) async -> String? {
        do {
            _ = try await APIClient.shared.toggleApiModels(enabled: enabled)
            return nil
        } catch {
            return "Failed to update API models setting: \(error.localizedDescription)"
        }
    }
    
    func updateProviderEnabled(provider: String, enabled: Bool, currentProviders: [APIProviderInfo]) async -> String? {
        do {
            // Find current setting for useOwnApiKey from the backend state, not the local UI state
            let providerInfo = currentProviders.first(where: { $0.id == provider })
            
            // Only use the backend's usingOwnApiKey value, not the local UI state
            // This ensures we don't try to enable "Use Own API Key" without a valid key
            let useOwnKey = providerInfo?.usingOwnApiKey ?? false
            
            _ = try await APIClient.shared.updateApiProviderSettings(
                provider: provider,
                enabled: enabled,
                useOwnApiKey: useOwnKey
            )
            
            return nil
        } catch {
            // Show error but don't prevent the user from toggling
            return "Note: \(error.localizedDescription)"
        }
    }
    
    func updateProviderApiKeySource(provider: String, useOwnKey: Bool, currentProviders: [APIProviderInfo]) async -> String? {
        do {
            // Find current enabled state
            let isEnabled = currentProviders.first(where: { $0.id == provider })?.isEnabled ?? false
            
            // If toggling to use own key, we'll allow it even without a key set
            // The backend will handle this by disabling all models until a key is set
            _ = try await APIClient.shared.updateApiProviderSettings(
                provider: provider,
                enabled: isEnabled,
                useOwnApiKey: useOwnKey
            )
            
            return nil
        } catch {
            // If there's an error, show it but don't revert the toggle
            // This allows users to set "Use Own API Key" and then provide a key
            return "Note: \(error.localizedDescription)"
        }
    }
    
    func updateModelEnabled(provider: String, modelId: String, enabled: Bool, currentProviders: [APIProviderInfo]) async -> (error: String?, shouldRevert: Bool) {
        // Check if we're trying to enable a model for a provider that's using own API key but has no key set
        if enabled {
            if let providerInfo = currentProviders.first(where: { $0.id == provider }),
               providerInfo.localUsingOwnApiKey && !providerInfo.hasKey {
                // Show error message
                return ("You need to set an API key for \(providerInfo.name) before enabling models", true)
            }
        }
        
        do {
            _ = try await APIClient.shared.updateApiModelSettings(
                provider: provider,
                modelId: modelId,
                enabled: enabled
            )
            
            return (nil, false)
        } catch {
            return ("Failed to update model: \(error.localizedDescription)", true)
        }
    }
    
    func setModelAsDefault(provider: String, modelId: String, capability: ModelCapabilityType) async -> String? {
        do {
            _ = try await APIClient.shared.updateApiModelSettings(
                provider: provider,
                modelId: modelId,
                enabled: true,
                setAsDefaultFor: [capability.rawValue]
            )
            
            return nil
        } catch {
            return "Failed to set default model: \(error.localizedDescription)"
        }
    }
    
    func updateProviderApiKeySourceWithBackend(provider: String, providerInfo: APIProviderInfo) async -> String? {
        do {
            // Now that we have a valid key, update the provider to use it
            // This is the ONLY place where we update the backend for "Use Own API Key"
            _ = try await APIClient.shared.updateApiProviderSettings(
                provider: provider,
                enabled: providerInfo.isEnabled,
                useOwnApiKey: true
            )
            
            #if DEBUG
            DevLogger.shared.info("Successfully updated \(provider) to use own API key", context: "APIModels")
            #endif
            
            return nil
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to update provider settings: \(error.localizedDescription)", context: "APIModels")
            #endif
            
            return "Failed to update provider settings: \(error.localizedDescription)"
        }
    }
}

// MARK: - API Models View
