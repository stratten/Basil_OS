import SwiftUI

class APIModelsViewModel: ObservableObject {
    @Published var apiSettings = APIModelSettings()
    @Published var apiProviders: [APIProviderInfo] = []
    @Published var isLoading = false
    @Published var error: String? = nil
    
    private let apiModelManager = APIModelManager.shared
    
    func loadApiModels() async {
        isLoading = true
        error = nil
        
        let result = await apiModelManager.loadApiModels(existingProviders: apiProviders)
        
        await MainActor.run {
            self.apiSettings = result.settings
            self.apiProviders = result.providers
            self.error = result.error
            self.isLoading = false
        }
    }
    
    func temporarilyDisableModels(for providerId: String) {
        for i in 0..<apiProviders.count {
            if apiProviders[i].id == providerId {
                for j in 0..<apiProviders[i].models.count {
                    apiProviders[i].models[j].isEnabled = false
                }
            }
        }
    }
    
    func updateApiModelsMasterToggle(enabled: Bool) async {
        // Optimistic update: local state is already updated by the Toggle binding
        let error = await apiModelManager.updateApiModelsMasterToggle(enabled: enabled)
        
        if let error = error {
            self.error = error
            // Revert on error
            await MainActor.run {
                self.apiSettings.useApiModels = !enabled
            }
        }
        // Success: local state is already correct, no reload needed
    }
    
    func updateProviderEnabled(provider: String, enabled: Bool) async {
        // Optimistic update: local state is already updated by the Toggle binding
        let error = await apiModelManager.updateProviderEnabled(provider: provider, enabled: enabled, currentProviders: apiProviders)
        
        if let error = error {
            self.error = error
            // Revert on error
            await MainActor.run {
                if let providerIndex = apiProviders.firstIndex(where: { $0.id == provider }) {
                    apiProviders[providerIndex].isEnabled = !enabled
                }
            }
        }
        // Success: local state is already correct, no reload needed
    }
    
    func updateProviderApiKeySource(provider: String, useOwnKey: Bool) async {
        // Optimistic update: local state is already updated by the Toggle binding
        let error = await apiModelManager.updateProviderApiKeySource(provider: provider, useOwnKey: useOwnKey, currentProviders: apiProviders)
        
        if let error = error {
            self.error = error
            // Revert on error
            await MainActor.run {
                if let providerIndex = apiProviders.firstIndex(where: { $0.id == provider }) {
                    apiProviders[providerIndex].localUsingOwnApiKey = !useOwnKey
                }
            }
        }
        // Success: local state is already correct, no reload needed
    }
    
    func updateModelEnabled(provider: String, modelId: String, enabled: Bool) async {
        // Optimistic update: local state is already updated by the Toggle binding
        // Just sync with backend - no need to reload unless there's an error
        
        let result = await apiModelManager.updateModelEnabled(provider: provider, modelId: modelId, enabled: enabled, currentProviders: apiProviders)
        
        if let error = result.error {
            self.error = error
        }
        
        // Only revert the toggle if there was an error
        if result.shouldRevert {
            await MainActor.run {
                if let providerIndex = apiProviders.firstIndex(where: { $0.id == provider }),
                   let modelIndex = apiProviders[providerIndex].models.firstIndex(where: { $0.id == modelId }) {
                    apiProviders[providerIndex].models[modelIndex].isEnabled = !enabled
                }
            }
        }
        // Success case: local state is already correct, no reload needed
    }
}
