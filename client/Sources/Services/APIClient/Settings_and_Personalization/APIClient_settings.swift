import Foundation
import os

extension Notification.Name {
    static let appearanceSettingsCacheUpdated = Notification.Name("appearanceSettingsCacheUpdated")
}

// MARK: - Settings Methods for APIClient
extension APIClient {
    func cacheTranscriptionSettings(_ settings: TranscriptionSettings) {
        cachedTranscriptionSettings = settings
    }
    
    func cacheBehaviorSettings(_ settings: BehaviorSettings) {
        #if DEBUG
        DevLogger.shared.info("💾 Caching behavior settings with enableMonitoringAtStartup=\(settings.enableMonitoringAtStartup)", context: "APIClient")
        #endif
        cachedBehaviorSettings = settings
    }
    
    func cacheAppearanceSettings(_ settings: AppearanceSettings) {
        #if DEBUG
        DevLogger.shared.info("💾 Caching appearance settings with font=\(settings.preferredFont)", context: "APIClient")
        #endif
        cachedAppearanceSettings = settings
        AestheticSystem.loadFromSettings(settings)
        NotificationCenter.default.post(name: .appearanceSettingsCacheUpdated, object: nil)
    }

    func cacheGeneralSettings(_ settings: GeneralSettings) {
        #if DEBUG
        DevLogger.shared.info("💾 Caching general settings with dateDisplayStyle=\(settings.dateDisplayStyle)", context: "APIClient")
        #endif
        cachedGeneralSettings = settings

        // Also update the shared date-display preference immediately so history
        // surfaces re-render with the correct style (mirrors AestheticSystem on appearance).
        let style = DateDisplayStyle(rawValue: settings.dateDisplayStyle) ?? .relative
        DateDisplayPreferenceStore.shared.update(style)
    }

    func getCachedGeneralSettings() -> GeneralSettings {
        // Check if we have settings in memory cache
        if let settings = cachedGeneralSettings {
            #if DEBUG
            DevLogger.shared.info("Using cached general settings (dateDisplayStyle: \(settings.dateDisplayStyle))", context: "APIClient")
            #endif
            return settings
        }

        // Try to get fresh settings from the server
        if let data = try? getSync("/settings/general"),
           let response = try? JSONDecoder().decode(GeneralSettingsResponse.self, from: data) {
            #if DEBUG
            DevLogger.shared.info("Retrieved fresh general settings from server (dateDisplayStyle: \(response.settings.dateDisplayStyle))", context: "APIClient")
            #endif
            cacheGeneralSettings(response.settings)
            return response.settings
        } else {
            #if DEBUG
            DevLogger.shared.error("Failed to get general settings from server", context: "APIClient")
            #endif
        }

        // Fall back to defaults if everything else fails
        #if DEBUG
        DevLogger.shared.warning("Using default general settings (no cached or server settings available)", context: "APIClient")
        #endif
        let defaultSettings = GeneralSettings(hasCompletedOnboarding: false, dateDisplayStyle: "relative")
        cacheGeneralSettings(defaultSettings)
        return defaultSettings
    }
    
    func getCachedBehaviorSettings() -> BehaviorSettings {
        #if DEBUG
        if let settings = cachedBehaviorSettings {
            DevLogger.shared.info("📤 Using cached behavior settings with enableMonitoringAtStartup=\(settings.enableMonitoringAtStartup)", context: "APIClient")
        } else {
            DevLogger.shared.warning("⚠️ No cached behavior settings found, using defaults", context: "APIClient")
        }
        #endif
        
        // Return cached settings if available, otherwise return defaults
        return cachedBehaviorSettings ?? BehaviorSettings(
            startOnStartup: false,
            showNotifications: true,
            minimizeToTray: true,
            holdEnabled: false,
            holdDuration: 0.5,
            enableMonitoringAtStartup: false,
            allowMacContactsForGeneration: false
        )
    }
    
    func getCachedTranscriptionSettings() -> TranscriptionSettings {
        // Check if we have settings in memory cache
        if let settings = cachedTranscriptionSettings {
            #if DEBUG
            DevLogger.shared.info("Using cached settings (autoCloseOnPaste: \(settings.autoCloseOnPaste), autoRetranscribeOnStop: \(settings.autoRetranscribeOnStop), autoAnalyzeOnComplete: \(settings.autoAnalyzeOnComplete), autoAnalyzeModes: \(settings.autoAnalyzeModes))", context: "APIClient")
            #endif
            return settings
        }
        // Try to get fresh settings from the server
        if let data = try? getSync("/settings/transcription"),
           let response = try? JSONDecoder().decode(TranscriptionSettingsResponse.self, from: data) {
            #if DEBUG
            DevLogger.shared.info("Retrieved fresh settings from server (autoCloseOnPaste: \(response.settings.autoCloseOnPaste), autoRetranscribeOnStop: \(response.settings.autoRetranscribeOnStop), autoAnalyzeOnComplete: \(response.settings.autoAnalyzeOnComplete), autoAnalyzeModes: \(response.settings.autoAnalyzeModes))", context: "APIClient")
            #endif
            // Update our cache with these fresh settings
            cachedTranscriptionSettings = response.settings
            return response.settings
        } else {
            #if DEBUG
            DevLogger.shared.error("Failed to get settings from server", context: "APIClient")
            #endif
        }
        // Fall back to default settings if everything else fails
        #if DEBUG
        DevLogger.shared.warning("Using default settings (no cached or server settings available)", context: "APIClient")
        #endif
        let defaultSettings = TranscriptionSettings(
            modelUnloadDelay: TranscriptionModelUnloadDelay.minutes1.rawValue,
            autoPaste: false,
            autoCloseOnPaste: false,
            language: "en",
            selectedModel: "",
            widgetSize: nil,
            widgetPosition: nil,
            isWidgetMinimized: false,
            enablePushToTalk: false,
            pushToTalkThresholdMs: 750,
            autoRetranscribeOnStop: false,
            autoRetranscribeDuringRecording: false,
            retranscribeWindowSeconds: 600,
            autoAnalyzeOnComplete: false,
            autoAnalyzeModes: [],
            autoAnalyzeCustomInstructions: "",
            autoAnalyzeTiming: "after",
            textReplacements: []
        )
        // Cache these default settings
        cachedTranscriptionSettings = defaultSettings
        return defaultSettings
    }
    
    func getCachedAppearanceSettings() -> AppearanceSettings {
        // Check if we have settings in memory cache
        if let settings = cachedAppearanceSettings {
            #if DEBUG
            DevLogger.shared.info("Using cached appearance settings (font: \(settings.preferredFont))", context: "APIClient")
            #endif
            return settings
        }
        
        // Try to get fresh settings from the server
        if let data = try? getSync("/settings/appearance"),
           let response = try? JSONDecoder().decode(AppearanceSettingsResponse.self, from: data) {
            #if DEBUG
            DevLogger.shared.info("Retrieved fresh appearance settings from server (font: \(response.settings.preferredFont))", context: "APIClient")
            #endif
            // Update our cache with these fresh settings
            cacheAppearanceSettings(response.settings)
            return response.settings
        } else {
            #if DEBUG
            DevLogger.shared.error("Failed to get appearance settings from server", context: "APIClient")
            #endif
        }
        
        // Fall back to default settings if everything else fails
        #if DEBUG
        DevLogger.shared.warning("Using default appearance settings (no cached or server settings available)", context: "APIClient")
        #endif
        let defaultSettings = AppearanceSettings()
        // Cache these default settings
        cacheAppearanceSettings(defaultSettings)
        return defaultSettings
    }
    
    func updateTranscriptionWidgetSize(_ size: NSSize) async throws {
        // First, get the most recent settings from the server
        let data = try await get("/settings/transcription")
        let response = try JSONDecoder().decode(TranscriptionSettingsResponse.self, from: data)
        let currentSettings = response.settings
        // Update our cache with these fresh settings
        cacheTranscriptionSettings(currentSettings)
        // Convert NSSize to WidgetSize
        let widgetSize = WidgetSize(width: Int(size.width), height: Int(size.height))
        let settings = currentSettings.applying(widgetSize: widgetSize)
        // Encode and send
        do {
            let encoder = JSONEncoder()
            let data = try encoder.encode(settings)
            _ = try await put("/settings/transcription", data: data)
            // Update the cached settings
            cachedTranscriptionSettings = settings
            #if DEBUG
            DevLogger.shared.info("✅ Successfully updated transcription widget size to: \(size.width) x \(size.height)", context: "APIClient")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to update transcription widget size: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }
    
    func updateTranscriptionWidgetPosition(_ position: NSPoint, screenID: Int) async throws {
        // First, get the most recent settings from the server
        let data = try await get("/settings/transcription")
        let response = try JSONDecoder().decode(TranscriptionSettingsResponse.self, from: data)
        let currentSettings = response.settings
        // Update our cache with these fresh settings
        cacheTranscriptionSettings(currentSettings)
        // Convert NSPoint and screenID to WidgetPosition
        let widgetPosition = WidgetPosition(x: position.x, y: position.y, screenID: screenID)
        let settings = currentSettings.applying(widgetPosition: widgetPosition)
        // Encode and send
        do {
            let encoder = JSONEncoder()
            let data = try encoder.encode(settings)
            _ = try await put("/settings/transcription", data: data)
            // Update the cached settings
            cachedTranscriptionSettings = settings
            #if DEBUG
            DevLogger.shared.info("✅ Successfully updated transcription widget position to: \(position.x), \(position.y) on screen \(screenID)", context: "APIClient")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to update transcription widget position: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }
    
    func updateTranscriptionWidgetMinimizedState(_ isMinimized: Bool) async throws {
        // First, get the most recent settings from the server
        let data = try await get("/settings/transcription")
        let response = try JSONDecoder().decode(TranscriptionSettingsResponse.self, from: data)
        let currentSettings = response.settings
        // Update our cache with these fresh settings
        cacheTranscriptionSettings(currentSettings)
        let settings = currentSettings.applying(isWidgetMinimized: isMinimized)
        // Encode and send
        do {
            let encoder = JSONEncoder()
            let data = try encoder.encode(settings)
            _ = try await put("/settings/transcription", data: data)
            // Update the cached settings
            cachedTranscriptionSettings = settings
            #if DEBUG
            DevLogger.shared.info("✅ Successfully updated transcription widget minimized state to: \(isMinimized)", context: "APIClient")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to update transcription widget minimized state: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }
    
    func updateUIPreference(key: String, value: Any) async throws {
        // This method can be kept for other UI preferences
        // Using underscore to avoid "unused variable" warning
        let _: [String: Any] = [key: value]
    }

    /// Fetches the current API model settings
    /// - Returns: Data containing API model settings
    func getApiModelSettings() async throws -> Data {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/api_models"
        logger.debug("📤 GET request for API model settings: \(endpoint)")
        do {
            #if DEBUG
            DevLogger.shared.info("Requesting API model settings from \(endpoint)", context: "APIClient")
            #endif
            let data = try await get(endpoint)
            #if DEBUG
            DevLogger.shared.info("Received API model settings response: \(data.count) bytes", context: "APIClient")
            let responseString = String(data: data, encoding: .utf8) ?? "Unable to decode as string"
            DevLogger.shared.info("Response content: \(responseString.prefix(200))...", context: "APIClient")
            #endif
            logger.debug("📥 Received API model settings response")
            return data
        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to fetch API model settings: \(error.localizedDescription)", context: "APIClient")
            #endif
            logger.error("❌ Failed to fetch API model settings: \(error.localizedDescription)")
            throw error
        }
    }

    /// Toggles the master switch for API models
    /// - Parameter enabled: Whether API models should be enabled
    /// - Returns: Data containing the operation response
    func toggleApiModels(enabled: Bool) async throws -> Data {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/api_models/toggle"
        logger.debug("📤 PUT request to toggle API models: \(endpoint), enabled: \(enabled)")
        struct ToggleRequest: Codable {
            let enabled: Bool
        }
        let request = ToggleRequest(enabled: enabled)
        let encoder = JSONEncoder()
        let requestData = try encoder.encode(request)
        do {
            let data = try await put(endpoint, data: requestData)
            logger.debug("📥 API models toggle response received")
            return data
        } catch {
            logger.error("❌ Failed to toggle API models: \(error.localizedDescription)")
            throw error
        }
    }

    /// Updates settings for an API provider
    /// - Parameters:
    ///   - provider: The provider ID (e.g., "anthropic", "openai")
    ///   - enabled: Whether the provider should be enabled
    ///   - useOwnApiKey: Whether to use the user's own API key
    /// - Returns: Data containing the operation response
    func updateApiProviderSettings(provider: String, enabled: Bool, useOwnApiKey: Bool) async throws -> Data {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/api_models/api_providers/\(provider)"
        logger.debug("📤 PUT request to update API provider: \(endpoint), enabled: \(enabled), useOwnApiKey: \(useOwnApiKey)")
        struct ProviderRequest: Codable {
            let enabled: Bool
            let use_own_api_key: Bool
            enum CodingKeys: String, CodingKey {
                case enabled
                case use_own_api_key
            }
        }
        let request = ProviderRequest(enabled: enabled, use_own_api_key: useOwnApiKey)
        let encoder = JSONEncoder()
        let requestData = try encoder.encode(request)
        do {
            let data = try await put(endpoint, data: requestData)
            logger.debug("📥 API provider update response received")
            return data
        } catch {
            logger.error("❌ Failed to update API provider: \(error.localizedDescription)")
            throw error
        }
    }

    /// Updates settings for an API model
    /// - Parameters:
    ///   - provider: The provider ID (e.g., "anthropic", "openai")
    ///   - modelId: The model ID
    ///   - enabled: Whether the model should be enabled
    ///   - setAsDefaultFor: Optional array of capabilities for which this model should be the default
    /// - Returns: Data containing the operation response
    func updateApiModelSettings(provider: String, modelId: String, enabled: Bool, setAsDefaultFor: [String]? = nil) async throws -> Data {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/api_models/\(provider)/\(modelId)"
        logger.debug("📤 PUT request to update API model: \(endpoint), enabled: \(enabled), setAsDefaultFor: \(setAsDefaultFor?.joined(separator: ",") ?? "none")")
        struct ModelRequest: Codable {
            let enabled: Bool
            let set_as_default_for: [String]?
            enum CodingKeys: String, CodingKey {
                case enabled
                case set_as_default_for
            }
        }
        let request = ModelRequest(enabled: enabled, set_as_default_for: setAsDefaultFor)
        let encoder = JSONEncoder()
        let requestData = try encoder.encode(request)
        do {
            let data = try await put(endpoint, data: requestData)
            logger.debug("📥 API model update response received")
            return data
        } catch {
            logger.error("❌ Failed to update API model: \(error.localizedDescription)")
            throw error
        }
    }

    /// Sets an API key for a provider
    /// - Parameters:
    ///   - provider: The provider ID (e.g., "anthropic", "openai")
    ///   - key: The API key to set
    /// - Returns: Data containing the operation response
    func setApiKey(provider: String, key: String) async throws -> Data {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/api_models/api_keys"
        logger.debug("📤 POST request to set API key for \(provider)")
        struct ApiKeyRequest: Codable {
            let provider: String
            let key: String
        }
        let request = ApiKeyRequest(provider: provider, key: key)
        do {
            let data = try await postForData(endpoint, request)
            logger.debug("📥 API key set response received")
            return data
        } catch {
            logger.error("❌ Failed to set API key: \(error.localizedDescription)")
            throw error
        }
    }

    /// Removes the user-supplied API key for a provider from the OS credential store.
    func deleteApiKey(provider: String) async throws {
        _ = try await delete("/settings/api_models/api_keys/\(provider)")
    }

    /// Tests if an API key is valid
    /// - Parameters:
    ///   - provider: The provider ID (e.g., "anthropic", "openai")
    ///   - key: The API key to test
    /// - Returns: Data containing the test response
    func testApiKey(provider: String, key: String) async throws -> Data {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/api_models/api_keys/test"
        logger.debug("📤 POST request to test API key for \(provider)")
        struct ApiKeyTestRequest: Codable {
            let provider: String
            let key: String
        }
        let request = ApiKeyTestRequest(provider: provider, key: key)
        do {
            let data = try await postForData(endpoint, request)
            logger.debug("📥 API key test response received")
            return data
        } catch {
            logger.error("❌ Failed to test API key: \(error.localizedDescription)")
            throw error
        }
    }
    
    // MARK: - AgentTask Settings Methods
    
    func cacheAgentTaskSettings(_ settings: AgentTaskSettings) {
        cachedAgentTaskSettings = settings
    }
    
    func getCachedAgentTaskSettings() -> AgentTaskSettings {
        // Check if we have settings in memory cache
        if let settings = cachedAgentTaskSettings {
            #if DEBUG
            DevLogger.shared.info("Using cached agentTask settings", context: "APIClient")
            #endif
            return settings
        }
        
        // Try to get fresh settings from the server
        if let data = try? getSync("/settings/agent-task"),
           let response = try? JSONDecoder().decode(AgentTaskSettingsResponse.self, from: data) {
            #if DEBUG
            DevLogger.shared.info("Retrieved fresh agentTask settings from server", context: "APIClient")
            #endif
            // Update our cache with these fresh settings
            cachedAgentTaskSettings = response.settings
            return response.settings
        } else {
            #if DEBUG
            DevLogger.shared.error("Failed to get agentTask settings from server", context: "APIClient")
            #endif
        }
        
        // Fall back to default settings if everything else fails
        #if DEBUG
        DevLogger.shared.warning("Using default agentTask settings (no cached or server settings available)", context: "APIClient")
        #endif
        let defaultSettings = AgentTaskSettings(
            widgetPosition: nil,
            resultWidgetSize: WidgetSize(width: 320, height: 180),
            enablePushToTalk: false,
            pushToTalkThresholdMs: 750,
            defaultInputModality: AgentTaskInputModality.voice.rawValue,
            autoReopenOnCompletion: true
        )
        // Cache these default settings
        cachedAgentTaskSettings = defaultSettings
        return defaultSettings
    }
    
    func updateAgentTaskWidgetPosition(_ position: NSPoint, screenID: Int) async throws {
        // First, get the most recent settings from the server
        let data = try await get("/settings/agent-task")
        let response = try JSONDecoder().decode(AgentTaskSettingsResponse.self, from: data)
        let currentSettings = response.settings
        // Update our cache with these fresh settings
        cacheAgentTaskSettings(currentSettings)
        
        // Convert NSPoint and screenID to WidgetPosition
        let widgetPosition = WidgetPosition(x: position.x, y: position.y, screenID: screenID)
        
        // Create updated settings object
        let settings = AgentTaskSettings(
            widgetPosition: widgetPosition,
            resultWidgetSize: currentSettings.resultWidgetSize,
            enablePushToTalk: currentSettings.enablePushToTalk,
            pushToTalkThresholdMs: currentSettings.pushToTalkThresholdMs,
            defaultInputModality: currentSettings.defaultInputModality,
            autoReopenOnCompletion: currentSettings.autoReopenOnCompletion
        )
        
        // Encode and send
        do {
            let encoder = JSONEncoder()
            let data = try encoder.encode(settings)
            _ = try await put("/settings/agent-task", data: data)
            // Update the cached settings
            cachedAgentTaskSettings = settings
            #if DEBUG
            DevLogger.shared.info("✅ Successfully updated agentTask widget position to: \(position.x), \(position.y) on screen \(screenID)", context: "APIClient")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to update agentTask widget position: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }
    
    func updateAgentTaskResultWidgetSize(_ size: NSSize) async throws {
        // First, get the most recent settings from the server
        let data = try await get("/settings/agent-task")
        let response = try JSONDecoder().decode(AgentTaskSettingsResponse.self, from: data)
        let currentSettings = response.settings
        // Update our cache with these fresh settings
        cacheAgentTaskSettings(currentSettings)
        
        // Convert NSSize to array format for the API
        let widgetSize = WidgetSize(width: Int(size.width), height: Int(size.height))
        
        // Create updated settings object
        let settings = AgentTaskSettings(
            widgetPosition: currentSettings.widgetPosition,
            resultWidgetSize: widgetSize,
            enablePushToTalk: currentSettings.enablePushToTalk,
            pushToTalkThresholdMs: currentSettings.pushToTalkThresholdMs,
            defaultInputModality: currentSettings.defaultInputModality,
            autoReopenOnCompletion: currentSettings.autoReopenOnCompletion
        )
        
        // Encode and send
        do {
            let encoder = JSONEncoder()
            let data = try encoder.encode(settings)
            _ = try await put("/settings/agent-task", data: data)
            // Update the cached settings
            cachedAgentTaskSettings = settings
            #if DEBUG
            DevLogger.shared.info("✅ Successfully updated agentTask result widget size to: \(size.width) x \(size.height)", context: "APIClient")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to update agentTask result widget size: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }
} 

// MARK: - Voice Listener Settings
struct VoiceListenerSettingsData: Codable {
    var voiceListenerEnabled: Bool

    enum CodingKeys: String, CodingKey {
        case voiceListenerEnabled = "voice_listener_enabled"
    }
}

// MARK: - Activity Capture Settings
struct ActivityCaptureSettingsData: Codable {
    var activityCaptureEnabled: Bool
    var startAtStartup: Bool
    var frequencyMinutes: Double
    var processingModel: String
    var processingMode: String
    var scheduledProcessingTime: String
    var processingMaxRecords: Int
    var maxFileAgeDays: Int
    var maxStorageMb: Int
    var autoCleanupEnabled: Bool
    var excludedBundleIds: [String]
    var idleThresholdSeconds: Double
    var postWakeGraceSeconds: Double

    enum CodingKeys: String, CodingKey {
        case activityCaptureEnabled = "enabled"
        case startAtStartup = "start_at_startup"
        case frequencyMinutes = "frequency_minutes"
        case processingModel = "processing_model"
        case processingMode = "processing_mode"
        case scheduledProcessingTime = "scheduled_processing_time"
        case processingMaxRecords = "processing_max_records"
        case maxFileAgeDays = "max_file_age_days"
        case maxStorageMb = "max_storage_mb"
        case autoCleanupEnabled = "auto_cleanup_enabled"
        case excludedBundleIds = "excluded_bundle_ids"
        case idleThresholdSeconds = "idle_threshold_seconds"
        case postWakeGraceSeconds = "post_wake_grace_seconds"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        activityCaptureEnabled = try container.decode(Bool.self, forKey: .activityCaptureEnabled)
        startAtStartup = try container.decode(Bool.self, forKey: .startAtStartup)
        frequencyMinutes = try container.decode(Double.self, forKey: .frequencyMinutes)
        processingModel = try container.decode(String.self, forKey: .processingModel)
        processingMode = try container.decode(String.self, forKey: .processingMode)
        scheduledProcessingTime = try container.decode(String.self, forKey: .scheduledProcessingTime)
        processingMaxRecords = try container.decode(Int.self, forKey: .processingMaxRecords)
        maxFileAgeDays = try container.decode(Int.self, forKey: .maxFileAgeDays)
        maxStorageMb = try container.decode(Int.self, forKey: .maxStorageMb)
        autoCleanupEnabled = try container.decode(Bool.self, forKey: .autoCleanupEnabled)
        excludedBundleIds = try container.decode([String].self, forKey: .excludedBundleIds)
        idleThresholdSeconds = try container.decodeIfPresent(
            Double.self,
            forKey: .idleThresholdSeconds
        ) ?? 120
        postWakeGraceSeconds = try container.decodeIfPresent(
            Double.self,
            forKey: .postWakeGraceSeconds
        ) ?? 5
    }
}

struct ActivityCaptureSettingsGetResponse: Codable {
    let settings: ActivityCaptureSettingsData
}

struct ActivityCaptureSettingsUpdateResponse: Codable {
    let status: String
    let updatedSettings: ActivityCaptureSettingsData
    let message: String?
    
    enum CodingKeys: String, CodingKey {
        case status
        case updatedSettings = "updated_settings"
        case message
    }
}

struct ActivityCaptureSettingsUpdate: Codable {
    var enabled: Bool?
    var startAtStartup: Bool?
    var frequencyMinutes: Double?
    var processingModel: String?
    var processingMode: String?
    var scheduledProcessingTime: String?
    var processingMaxRecords: Int?
    var maxFileAgeDays: Int?
    var maxStorageMb: Int?
    var autoCleanupEnabled: Bool?
    var excludedBundleIds: [String]?
    var idleThresholdSeconds: Double?
    var postWakeGraceSeconds: Double?

    enum CodingKeys: String, CodingKey {
        case enabled
        case startAtStartup = "start_at_startup"
        case frequencyMinutes = "frequency_minutes"
        case processingModel = "processing_model"
        case processingMode = "processing_mode"
        case scheduledProcessingTime = "scheduled_processing_time"
        case processingMaxRecords = "processing_max_records"
        case maxFileAgeDays = "max_file_age_days"
        case maxStorageMb = "max_storage_mb"
        case autoCleanupEnabled = "auto_cleanup_enabled"
        case excludedBundleIds = "excluded_bundle_ids"
        case idleThresholdSeconds = "idle_threshold_seconds"
        case postWakeGraceSeconds = "post_wake_grace_seconds"
    }
}

// MARK: - Voice Listener Settings Response Wrappers
struct VoiceListenerStatusResponse: Codable {
    let status: String
    let settings: VoiceListenerSettingsData
}

struct VoiceListenerStatusUpdateResponse: Codable {
    let status: String
    let updatedSettings: VoiceListenerSettingsData
    
    enum CodingKeys: String, CodingKey {
        case status
        case updatedSettings = "updated_settings"
    }
}

extension APIClient {
    func getVoiceListenerSettings() async throws -> VoiceListenerSettingsData {
        guard isBackendAvailable else {
            DevLogger.shared.error("Backend not available for getVoiceListenerSettings", context: "APIClient")
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/voice-listener/settings"
        DevLogger.shared.info("📤 GET request for Voice Listener settings: \(endpoint)", context: "APIClient")
        
        do {
            let data = try await get(endpoint)
            let decoder = JSONDecoder()
            let response = try decoder.decode(VoiceListenerStatusResponse.self, from: data)
            DevLogger.shared.info("📥 Successfully fetched Voice Listener settings. Enabled: \(response.settings.voiceListenerEnabled)", context: "APIClient")
            return response.settings
        } catch {
            DevLogger.shared.error("❌ Failed to fetch Voice Listener settings: \(error.localizedDescription)", context: "APIClient")
            throw error
        }
    }

    func updateVoiceListenerSettings(enabled: Bool) async throws -> VoiceListenerSettingsData {
        guard isBackendAvailable else {
            DevLogger.shared.error("Backend not available for updateVoiceListenerSettings", context: "APIClient")
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/voice-listener/settings"
        DevLogger.shared.info("📤 PUT request to update Voice Listener settings: \(endpoint), enabled: \(enabled)", context: "APIClient")
        
        let payload = VoiceListenerSettingsData(voiceListenerEnabled: enabled)
        
        #if DEBUG
        let tempEncoder = JSONEncoder()
        tempEncoder.keyEncodingStrategy = .convertToSnakeCase
        if let tempData = try? tempEncoder.encode(payload), let jsonString = String(data: tempData, encoding: .utf8) {
            DevLogger.shared.info("📤 Voice Listener update payload (simulated): \(jsonString)", context: "APIClient")
        }
        #endif

        do {
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            let requestData = try encoder.encode(payload)
            let responseData = try await put(endpoint, data: requestData)
            let decoder = JSONDecoder()
            let response = try decoder.decode(VoiceListenerStatusUpdateResponse.self, from: responseData)
            DevLogger.shared.info("📥 Successfully updated Voice Listener settings. Enabled: \(response.updatedSettings.voiceListenerEnabled)", context: "APIClient")
            return response.updatedSettings
        } catch {
            DevLogger.shared.error("❌ Failed to update Voice Listener settings: \(error.localizedDescription)", context: "APIClient")
            throw error
        }
    }
    // MARK: - Activity Capture Settings Methods
    
    func getActivityCaptureSettings() async throws -> ActivityCaptureSettingsData {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/activity-capture"
        DevLogger.shared.info("📤 GET request to fetch Activity Capture settings: \(endpoint)", context: "APIClient")
        
        do {
            let responseData = try await get(endpoint)
            let response = try JSONDecoder().decode(ActivityCaptureSettingsGetResponse.self, from: responseData)
            return response.settings
        } catch {
            DevLogger.shared.error("❌ Failed to fetch Activity Capture settings: \(error)", context: "APIClient")
            throw error
        }
    }
    
    func updateActivityCaptureSettings(
        enabled: Bool,
        frequencyMinutes: Double,
        processingModel: String,
        processingMode: String,
        scheduledProcessingTime: String,
        processingMaxRecords: Int,
        maxFileAgeDays: Int,
        maxStorageMb: Int,
        autoCleanupEnabled: Bool,
        idleThresholdSeconds: Double,
        postWakeGraceSeconds: Double
    ) async throws -> ActivityCaptureSettingsData {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/activity-capture"
        DevLogger.shared.info("📤 PUT request to update Activity Capture settings: \(endpoint)", context: "APIClient")
        
        let updateData = ActivityCaptureSettingsUpdate(
            enabled: enabled,
            frequencyMinutes: frequencyMinutes,
            processingModel: processingModel,
            processingMode: processingMode,
            scheduledProcessingTime: scheduledProcessingTime,
            processingMaxRecords: processingMaxRecords,
            maxFileAgeDays: maxFileAgeDays,
            maxStorageMb: maxStorageMb,
            autoCleanupEnabled: autoCleanupEnabled,
            idleThresholdSeconds: idleThresholdSeconds,
            postWakeGraceSeconds: postWakeGraceSeconds
        )
        
        do {
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            let requestData = try encoder.encode(updateData)
            let responseData = try await put(endpoint, data: requestData)
            let response = try JSONDecoder().decode(ActivityCaptureSettingsUpdateResponse.self, from: responseData)
            return response.updatedSettings
        } catch {
            DevLogger.shared.error("❌ Failed to update Activity Capture settings: \(error)", context: "APIClient")
            throw error
        }
    }

    func updateActivityCaptureExcludedBundleIds(_ bundleIDs: [String]) async throws -> ActivityCaptureSettingsData {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/activity-capture"
        let updateData = ActivityCaptureSettingsUpdate(excludedBundleIds: bundleIDs)
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let requestData = try encoder.encode(updateData)
        let responseData = try await put(endpoint, data: requestData)
        let response = try JSONDecoder().decode(ActivityCaptureSettingsUpdateResponse.self, from: responseData)
        return response.updatedSettings
    }

    func updateActivityCaptureStartAtStartup(_ startAtStartup: Bool) async throws -> ActivityCaptureSettingsData {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/activity-capture"
        let updateData = ActivityCaptureSettingsUpdate(startAtStartup: startAtStartup)
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let requestData = try encoder.encode(updateData)
        let responseData = try await put(endpoint, data: requestData)
        let response = try JSONDecoder().decode(ActivityCaptureSettingsUpdateResponse.self, from: responseData)
        return response.updatedSettings
    }

    func startActivityCapture() async throws {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        _ = try await post("/activity-capture/capture/start", body: Data())
    }
}