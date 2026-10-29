import Foundation

// MARK: - Onboarding API Models

/// Information about a starter model
struct StarterModelInfo: Codable {
    let modelType: String
    let variant: String
    let modelId: String
    let description: String
    let isInstalled: Bool
    let taskId: String?
    
    enum CodingKeys: String, CodingKey {
        case modelType = "model_type"
        case variant
        case modelId = "model_id"
        case description
        case isInstalled = "is_installed"
        case taskId = "task_id"
    }
}

/// Response from starter models endpoints
struct StarterModelsResponse: Codable {
    let models: [StarterModelInfo]
    let allInstalled: Bool
    let downloadsStarted: Int
    
    enum CodingKeys: String, CodingKey {
        case models
        case allInstalled = "all_installed"
        case downloadsStarted = "downloads_started"
    }
}

/// Combined download progress for onboarding
struct OnboardingDownloadProgress: Codable {
    let overallProgress: Double
    let allComplete: Bool
    let completedModels: Int
    let totalModels: Int
    let phaseMessage: String
    let models: [String: ModelProgressInfo]
    
    enum CodingKeys: String, CodingKey {
        case overallProgress = "overall_progress"
        case allComplete = "all_complete"
        case completedModels = "completed_models"
        case totalModels = "total_models"
        case phaseMessage = "phase_message"
        case models
    }
}

struct ModelProgressInfo: Codable {
    let status: String
    let progress: Double
    let description: String
    let totalDownloaded: Int64?
    let totalSize: Int64?
    
    enum CodingKeys: String, CodingKey {
        case status
        case progress
        case description
        case totalDownloaded = "total_downloaded"
        case totalSize = "total_size"
    }
}

// MARK: - APIClient Onboarding Extension
extension APIClient {
    
    /// Check the status of starter models without starting downloads
    func getStarterModelsStatus() async throws -> StarterModelsResponse {
        let data = try await get("/onboarding/starter-models")
        let decoder = JSONDecoder()
        return try decoder.decode(StarterModelsResponse.self, from: data)
    }
    
    /// Start downloading all missing starter models
    /// Called automatically on first app launch
    func startStarterModelDownloads() async throws -> StarterModelsResponse {
        let data = try await postForData("/onboarding/start-starter-downloads")
        let decoder = JSONDecoder()
        return try decoder.decode(StarterModelsResponse.self, from: data)
    }
    
    /// Get combined download progress for all starter models
    func getOnboardingDownloadProgress() async throws -> OnboardingDownloadProgress {
        let data = try await get("/onboarding/download-progress")
        let decoder = JSONDecoder()
        return try decoder.decode(OnboardingDownloadProgress.self, from: data)
    }
    
    /// Convenience method to trigger starter downloads for first-time users
    /// This is fire-and-forget - downloads happen in background
    func triggerFirstLaunchDownloadsIfNeeded() {
        Task {
            do {
                // First check if all models are already installed
                let status = try await getStarterModelsStatus()
                
                if status.allInstalled {
                    #if DEBUG
                    DevLogger.shared.info("[Onboarding] All starter models already installed, skipping downloads", context: "APIClient")
                    #endif
                    return
                }
                
                // Start downloads for missing models
                let result = try await startStarterModelDownloads()
                
                #if DEBUG
                DevLogger.shared.info("[Onboarding] Started \(result.downloadsStarted) starter model downloads", context: "APIClient")
                for model in result.models {
                    let status = model.isInstalled ? "✓ installed" : (model.taskId != nil ? "⬇️ downloading" : "⏳ pending")
                    DevLogger.shared.info("[Onboarding]   - \(model.modelId): \(status)", context: "APIClient")
                }
                #endif
            } catch {
                #if DEBUG
                DevLogger.shared.error("[Onboarding] Failed to trigger starter downloads: \(error)", context: "APIClient")
                #endif
                // Don't crash the app if this fails - it's a nice-to-have optimization
            }
        }
    }
}

