import Foundation

// MARK: - Ambient Suggestion Settings
struct AmbientSuggestionSettingsData: Codable {
    var enabled: Bool
    var frequencyMinutes: Double
    var frequencySeconds: Double
    var evaluationModel: String
    var mode: String
    var enabledCapabilities: [String]
    var autoExecuteCapabilities: [String]
    var minimumConfidence: Double
    var cooldownMinutes: Double
    var excludedAppNames: [String]
    var allowCloudEvaluation: Bool
    var panelPosition: WidgetPosition?
    var panelSize: WidgetSize
    var panelVisibleOnLaunch: Bool

    enum CodingKeys: String, CodingKey {
        case enabled
        case frequencyMinutes = "frequency_minutes"
        case frequencySeconds = "frequency_seconds"
        case evaluationModel = "evaluation_model"
        case mode
        case enabledCapabilities = "enabled_capabilities"
        case autoExecuteCapabilities = "auto_execute_capabilities"
        case minimumConfidence = "minimum_confidence"
        case cooldownMinutes = "cooldown_minutes"
        case excludedAppNames = "excluded_app_names"
        case allowCloudEvaluation = "allow_cloud_evaluation"
        case panelPosition = "panel_position"
        case panelSize = "panel_size"
        case panelVisibleOnLaunch = "panel_visible_on_launch"
    }
}

struct AmbientSuggestionSettingsGetResponse: Codable {
    let settings: AmbientSuggestionSettingsData
}

struct AmbientSuggestionSettingsUpdateResponse: Codable {
    let status: String
    let updatedSettings: AmbientSuggestionSettingsData
    let message: String?

    enum CodingKeys: String, CodingKey {
        case status
        case updatedSettings = "updated_settings"
        case message
    }
}

struct AmbientSuggestionSettingsUpdate: Codable {
    var enabled: Bool? = nil
    var frequencyMinutes: Double? = nil
    var frequencySeconds: Double? = nil
    var evaluationModel: String? = nil
    var mode: String? = nil
    var enabledCapabilities: [String]? = nil
    var autoExecuteCapabilities: [String]? = nil
    var minimumConfidence: Double? = nil
    var cooldownMinutes: Double? = nil
    var excludedAppNames: [String]? = nil
    var allowCloudEvaluation: Bool? = nil
    var panelPosition: WidgetPosition? = nil
    var panelSize: WidgetSize? = nil
    var panelVisibleOnLaunch: Bool? = nil

    enum CodingKeys: String, CodingKey {
        case enabled
        case frequencyMinutes = "frequency_minutes"
        case frequencySeconds = "frequency_seconds"
        case evaluationModel = "evaluation_model"
        case mode
        case enabledCapabilities = "enabled_capabilities"
        case autoExecuteCapabilities = "auto_execute_capabilities"
        case minimumConfidence = "minimum_confidence"
        case cooldownMinutes = "cooldown_minutes"
        case excludedAppNames = "excluded_app_names"
        case allowCloudEvaluation = "allow_cloud_evaluation"
        case panelPosition = "panel_position"
        case panelSize = "panel_size"
        case panelVisibleOnLaunch = "panel_visible_on_launch"
    }
}

struct AmbientSuggestionStatusResponse: Codable {
    let initialized: Bool
    let enabled: Bool
    let isRunning: Bool?
    let frequencyMinutes: Double?
    let frequencySeconds: Double?
    let evaluationModel: String?
    let mode: String?
    let enabledCapabilities: [String]?
    let autoExecuteCapabilities: [String]?
    let minimumConfidence: Double?
    let cooldownMinutes: Double?
    let allowCloudEvaluation: Bool?
    let isEvaluating: Bool?
    let evaluationStartedAt: String?
    let lastEvaluationCompletedAt: String?
    let nextEvaluationTime: String?
    let lastCaptureTime: String?
    let openSuggestionsCount: Int?
    let lastStatusMessage: String?

    enum CodingKeys: String, CodingKey {
        case initialized
        case enabled
        case isRunning = "is_running"
        case frequencyMinutes = "frequency_minutes"
        case frequencySeconds = "frequency_seconds"
        case evaluationModel = "evaluation_model"
        case mode
        case enabledCapabilities = "enabled_capabilities"
        case autoExecuteCapabilities = "auto_execute_capabilities"
        case minimumConfidence = "minimum_confidence"
        case cooldownMinutes = "cooldown_minutes"
        case allowCloudEvaluation = "allow_cloud_evaluation"
        case isEvaluating = "is_evaluating"
        case evaluationStartedAt = "evaluation_started_at"
        case lastEvaluationCompletedAt = "last_evaluation_completed_at"
        case nextEvaluationTime = "next_evaluation_time"
        case lastCaptureTime = "last_capture_time"
        case openSuggestionsCount = "open_suggestions_count"
        case lastStatusMessage = "last_status_message"
    }
}

extension APIClient {
    func getAmbientSuggestionSettings() async throws -> AmbientSuggestionSettingsData {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/ambient-suggestions"
        let responseData = try await get(endpoint)
        let response = try JSONDecoder().decode(AmbientSuggestionSettingsGetResponse.self, from: responseData)
        return response.settings
    }

    func updateAmbientSuggestionSettings(_ updateData: AmbientSuggestionSettingsUpdate) async throws -> AmbientSuggestionSettingsData {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/ambient-suggestions"
        let requestData = try JSONEncoder().encode(updateData)
        let responseData = try await put(endpoint, data: requestData)
        let response = try JSONDecoder().decode(AmbientSuggestionSettingsUpdateResponse.self, from: responseData)
        return response.updatedSettings
    }

    func getAmbientSuggestionStatus() async throws -> AmbientSuggestionStatusResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let responseData = try await get("/ambient-suggestions/status")
        return try JSONDecoder().decode(AmbientSuggestionStatusResponse.self, from: responseData)
    }

    func startAmbientSuggestions() async throws -> AmbientSuggestionOperationResponse {
        try await postAmbientSuggestionOperation("/ambient-suggestions/start")
    }

    func stopAmbientSuggestions() async throws -> AmbientSuggestionOperationResponse {
        try await postAmbientSuggestionOperation("/ambient-suggestions/stop")
    }

    func toggleAmbientSuggestions() async throws -> AmbientSuggestionOperationResponse {
        try await postAmbientSuggestionOperation("/ambient-suggestions/toggle")
    }

    func captureAmbientSuggestionOnce() async throws -> AmbientSuggestionOperationResponse {
        try await postAmbientSuggestionOperation("/ambient-suggestions/capture-once")
    }

    func updateAmbientSuggestionOutcome(suggestionId: String, outcome: String) async throws -> AmbientSuggestionRecord? {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/ambient-suggestions/suggestions/\(suggestionId)/outcome"
        let payload = AmbientSuggestionOutcomeRequest(outcome: outcome)
        let requestData = try JSONEncoder().encode(payload)
        let responseData = try await post(endpoint, body: requestData)
        let response = try JSONDecoder().decode(AmbientSuggestionOperationResponse.self, from: responseData)
        return response.suggestion
    }

    private func postAmbientSuggestionOperation(_ endpoint: String) async throws -> AmbientSuggestionOperationResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let responseData = try await post(endpoint, body: Data())
        return try JSONDecoder().decode(AmbientSuggestionOperationResponse.self, from: responseData)
    }
}
