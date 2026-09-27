import Foundation
import os

/// Manages the API key preference setting independently of authentication state.
///
/// This manager handles ONLY the `api_key_preference` setting, which determines
/// how the app accesses API models (Basil Cloud, own keys, or local only).
///
/// Design Principles:
/// - NO keychain dependencies - the preference itself is not sensitive
/// - Single source of truth via backend preferences.json
/// - Can be accessed without requiring user authentication
/// - Syncs to backend immediately on change
@MainActor
final class APIKeyPreferenceManager: ObservableObject {
    // MARK: - Singleton
    static let shared = APIKeyPreferenceManager()
    
    // MARK: - Published State
    @Published private(set) var preference: APIKeyPreference = .useLocalModels
    @Published private(set) var isLoaded = false
    
    // MARK: - Properties
    private let logger = Logger(subsystem: "com.basil.client", category: "APIKeyPreferenceManager")
    private let apiClient = APIClient.shared
    
    // MARK: - Initialization
    private init() {
        // Load preference from backend on init
        Task {
            await loadPreference()
        }
    }
    
    // MARK: - Public Methods
    
    /// Set the API key preference and sync to backend.
    /// This is the primary method for changing the preference.
    func setPreference(_ newPreference: APIKeyPreference) {
        let normalizedPreference = newPreference.normalizedForStorage
        let oldPreference = preference
        preference = normalizedPreference
        
        logger.info("🔐 API key preference changed: \(oldPreference.rawValue) → \(normalizedPreference.rawValue)")
        
        // Sync to backend
        Task {
            await syncPreferenceToBackend()
            
            // If switching to trial, also sync the trial key
            if normalizedPreference == .useBasilCloud {
                await syncTrialKeyToBackend()
            }
        }
    }
    
    /// Load the current preference from backend.
    /// Called on init and can be called to refresh.
    func loadPreference() async {
        do {
            let settings = try await apiClient.getAuthSettings()
            
            if let loadedPreference = APIKeyPreference(rawValue: settings.apiKeyPreference) {
                preference = loadedPreference.normalizedForStorage
                logger.debug("🔐 Loaded API key preference from backend: \(loadedPreference.rawValue) → \(self.preference.rawValue)")
            } else {
                logger.warning("🔐 Invalid API key preference in backend: \(settings.apiKeyPreference), using default")
            }
            
            isLoaded = true
        } catch {
            logger.warning("🔐 Failed to load API key preference from backend: \(error.localizedDescription)")
            // Keep default preference, mark as loaded anyway to prevent blocking
            isLoaded = true
        }
    }
    
    /// Force refresh the preference from backend.
    func refresh() async {
        await loadPreference()
    }
    
    // MARK: - Private Methods
    
    /// Sync the current preference to backend preferences.json
    /// NOTE: This method intentionally does NOT access AuthService to avoid triggering keychain prompts.
    /// Auth state (isAuthenticated, userEmail) is managed separately by AuthService.syncAuthSettingsToBackend().
    private func syncPreferenceToBackend() async {
        do {
            // Use preference-only initializer - does NOT touch auth state
            // Backend will preserve existing isAuthenticated and userEmail values
            let settings = AuthSettingsUpdate(apiKeyPreference: preference.rawValue)
            
            try await apiClient.updateAuthSettings(settings)
            logger.debug("🔐 API key preference synced to backend: \(self.preference.rawValue)")
        } catch {
            logger.warning("🔐 Failed to sync API key preference to backend: \(error.localizedDescription)")
        }
    }
    
    /// Sync trial key to backend when Basil Cloud is selected.
    private func syncTrialKeyToBackend() async {
        guard preference == .useBasilCloud else { return }
        
        do {
            let trialKey = TrialKeyManager.shared.getOrCreateTrialKey()
            try await apiClient.setTrialKey(trialKey)
            logger.info("🎫 Trial key synced to backend (preference: basil_cloud)")
        } catch {
            logger.warning("🔐 Failed to sync trial key to backend: \(error.localizedDescription)")
        }
    }
}

// MARK: - Convenience Extensions

extension APIKeyPreferenceManager {
    /// Whether the selected preference routes through Basil-managed cloud access.
    var usesBasilCloud: Bool {
        preference.isBasilCloudAlias
    }
    
    /// Whether the user is using their own API keys (not trial or app keys)
    var usesOwnKeys: Bool {
        preference == .useOwnKeys
    }
    
    /// Whether the user is using trial keys
    var usesTrial: Bool {
        preference.isBasilCloudAlias
    }
    
    /// Whether the user is using app keys (billed through Basil)
    var usesAppKeys: Bool {
        preference.isBasilCloudAlias
    }
    
    /// Whether the user is using local models only
    var usesLocalModelsOnly: Bool {
        preference == .useLocalModels
    }
    
    /// Whether any API access is configured (not local-only)
    var hasAPIAccess: Bool {
        preference != .useLocalModels
    }
}

private extension APIKeyPreference {
    var normalizedForStorage: APIKeyPreference {
        isBasilCloudAlias ? .useBasilCloud : self
    }
}
