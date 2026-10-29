import Combine
import SwiftUI

// MARK: - View Model

@MainActor
final class TranscriptionAPIModelsViewModel: ObservableObject {
    @Published var useApiTranscriptionModels: Bool = false
    @Published var openaiTranscriptionEnabled: Bool = false
    @Published var openaiHasKey: Bool = false
    @Published var models: [TranscriptionAPIModelInfo] = []
    @Published var isLoading: Bool = false
    @Published var error: String? = nil
    @Published var currentModel: String = ""
    
    @Published var apiKeys: [String: String] = [:]
    @Published var validationInProgress: [String: Bool] = [:]
    @Published var keyValidationResults: [String: (isValid: Bool, message: String?)] = [:]
    
    private let api = APIClient.shared
    
    func loadModels() async {
        isLoading = true
        error = nil
        
        do {
            let response = try await api.getApiTranscriptionModels()
            useApiTranscriptionModels = response.apiTranscriptionModelsEnabled
            models = response.models
            currentModel = response.currentModel
            
            // Read provider status (has_key, enabled) from the response.
            if let openaiStatus = response.providers?["openai"] {
                openaiTranscriptionEnabled = openaiStatus.enabled
                openaiHasKey = openaiStatus.hasKey
            }
            
            // Also load provider-level state from model settings
            let settingsData = try await api.get("/settings/models")
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            
            struct ModelSettingsPartial: Codable {
                let status: String?
                let settings: SettingsInner?
                let useApiTranscriptionModels: Bool?
                let openaiTranscriptionEnabled: Bool?
                
                struct SettingsInner: Codable {
                    let useApiTranscriptionModels: Bool?
                    let openaiTranscriptionEnabled: Bool?
                }
            }
            
            if let partial = try? decoder.decode(ModelSettingsPartial.self, from: settingsData) {
                if let inner = partial.settings {
                    if let val = inner.useApiTranscriptionModels {
                        useApiTranscriptionModels = val
                    }
                    if let val = inner.openaiTranscriptionEnabled {
                        openaiTranscriptionEnabled = val
                    }
                }
            }
        } catch {
            self.error = "Failed to load transcription API models: \(error.localizedDescription)"
        }
        
        isLoading = false
    }
    
    func toggleMaster(enabled: Bool) async {
        do {
            let response = try await api.toggleApiTranscriptionModels(enabled: enabled)
            useApiTranscriptionModels = response.apiTranscriptionModelsEnabled
            if let openaiEnabled = response.providersEnabled["openai"] {
                openaiTranscriptionEnabled = openaiEnabled
            }
            if enabled {
                await loadModels()
            }
        } catch {
            self.error = "Failed to toggle API transcription: \(error.localizedDescription)"
            useApiTranscriptionModels = !enabled
        }
    }
    
    func toggleProvider(provider: String, enabled: Bool) async {
        do {
            _ = try await api.updateTranscriptionProvider(provider: provider, enabled: enabled)
            if enabled {
                await loadModels()
            }
        } catch {
            self.error = "Failed to update provider: \(error.localizedDescription)"
            if provider == "openai" {
                openaiTranscriptionEnabled = !enabled
            }
        }
    }
    
    func toggleModel(provider: String, modelId: String, enabled: Bool) async {
        do {
            _ = try await api.updateTranscriptionApiModel(
                provider: provider, modelId: modelId, enabled: enabled
            )
            await loadModels()
        } catch {
            self.error = "Failed to update model: \(error.localizedDescription)"
        }
    }
    
    func saveApiKey(provider: String) async {
        guard let key = apiKeys[provider], !key.isEmpty else { return }
        
        validationInProgress[provider] = true
        
        do {
            let testData = try await api.testApiKey(provider: provider, key: key)
            
            struct TestResponse: Codable {
                let provider: String
                let valid: Bool
                let error: String?
            }
            
            let testResult = try JSONDecoder().decode(TestResponse.self, from: testData)
            
            if testResult.valid {
                _ = try await api.setApiKey(provider: provider, key: key)
                keyValidationResults[provider] = (isValid: true, message: "API key is valid and saved")
                
                openaiTranscriptionEnabled = true
                await toggleProvider(provider: provider, enabled: true)
            } else {
                keyValidationResults[provider] = (isValid: false, message: testResult.error ?? "Invalid API key")
            }
        } catch {
            keyValidationResults[provider] = (isValid: false, message: "Validation failed: \(error.localizedDescription)")
        }
        
        validationInProgress[provider] = false
    }
}
