import Foundation

// MARK: - Meeting Detection Settings

struct MeetingDetectionSettingsData: Codable {
    var enabled: Bool
    var startAtStartup: Bool
    var mode: String
    var pollSeconds: Double
    var excludedBundleIds: [String]
    var excludedAppNames: [String]
    var cooldownMinutes: Double
    var useCalendarEnrichment: Bool
    var requireCalendarMatch: Bool
    var autoEnd: Bool
    var inactivityTimeoutMinutes: Double

    enum CodingKeys: String, CodingKey {
        case enabled
        case startAtStartup = "start_at_startup"
        case mode
        case pollSeconds = "poll_seconds"
        case excludedBundleIds = "excluded_bundle_ids"
        case excludedAppNames = "excluded_app_names"
        case cooldownMinutes = "cooldown_minutes"
        case useCalendarEnrichment = "use_calendar_enrichment"
        case requireCalendarMatch = "require_calendar_match"
        case autoEnd = "auto_end"
        case inactivityTimeoutMinutes = "inactivity_timeout_minutes"
    }
}

struct MeetingDetectionSettingsGetResponse: Codable {
    let settings: MeetingDetectionSettingsData
}

struct MeetingDetectionSettingsUpdateResponse: Codable {
    let status: String
    let updatedSettings: MeetingDetectionSettingsData
    let message: String?

    enum CodingKeys: String, CodingKey {
        case status
        case updatedSettings = "updated_settings"
        case message
    }
}

struct MeetingDetectionSettingsUpdate: Codable {
    var enabled: Bool? = nil
    var startAtStartup: Bool? = nil
    var mode: String? = nil
    var pollSeconds: Double? = nil
    var excludedBundleIds: [String]? = nil
    var excludedAppNames: [String]? = nil
    var cooldownMinutes: Double? = nil
    var useCalendarEnrichment: Bool? = nil
    var requireCalendarMatch: Bool? = nil
    var autoEnd: Bool? = nil
    var inactivityTimeoutMinutes: Double? = nil

    enum CodingKeys: String, CodingKey {
        case enabled
        case startAtStartup = "start_at_startup"
        case mode
        case pollSeconds = "poll_seconds"
        case excludedBundleIds = "excluded_bundle_ids"
        case excludedAppNames = "excluded_app_names"
        case cooldownMinutes = "cooldown_minutes"
        case useCalendarEnrichment = "use_calendar_enrichment"
        case requireCalendarMatch = "require_calendar_match"
        case autoEnd = "auto_end"
        case inactivityTimeoutMinutes = "inactivity_timeout_minutes"
    }
}

struct MeetingDetectionStatusResponse: Codable {
    let initialized: Bool
    let enabled: Bool
    let isRunning: Bool?
    let mode: String?
    let pollSeconds: Double?
    let lastStatusMessage: String?

    enum CodingKeys: String, CodingKey {
        case initialized
        case enabled
        case isRunning = "is_running"
        case mode
        case pollSeconds = "poll_seconds"
        case lastStatusMessage = "last_status_message"
    }
}

struct MeetingDetectionOperationResponse: Codable {
    let success: Bool
    let message: String
}

struct MeetingDetectionCalendarEventIgnoreRequest: Codable {
    let eventId: String

    enum CodingKeys: String, CodingKey {
        case eventId = "event_id"
    }
}

extension APIClient {
    func getMeetingDetectionSettings() async throws -> MeetingDetectionSettingsData {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let responseData = try await get("/settings/meeting-detection")
        let response = try JSONDecoder().decode(MeetingDetectionSettingsGetResponse.self, from: responseData)
        return response.settings
    }

    func updateMeetingDetectionSettings(_ updateData: MeetingDetectionSettingsUpdate) async throws -> MeetingDetectionSettingsData {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let requestData = try JSONEncoder().encode(updateData)
        let responseData = try await put("/settings/meeting-detection", data: requestData)
        let response = try JSONDecoder().decode(MeetingDetectionSettingsUpdateResponse.self, from: responseData)
        return response.updatedSettings
    }

    func getMeetingDetectionStatus() async throws -> MeetingDetectionStatusResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let responseData = try await get("/meeting-detection/status")
        return try JSONDecoder().decode(MeetingDetectionStatusResponse.self, from: responseData)
    }

    func startMeetingDetection() async throws -> MeetingDetectionOperationResponse {
        try await postMeetingDetectionOperation("/meeting-detection/start")
    }

    func stopMeetingDetection() async throws -> MeetingDetectionOperationResponse {
        try await postMeetingDetectionOperation("/meeting-detection/stop")
    }

    func toggleMeetingDetection() async throws -> MeetingDetectionOperationResponse {
        try await postMeetingDetectionOperation("/meeting-detection/toggle")
    }

    func ignoreMeetingDetectionCalendarEvent(eventID: String) async throws -> MeetingDetectionOperationResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let requestData = try JSONEncoder().encode(MeetingDetectionCalendarEventIgnoreRequest(eventId: eventID))
        let responseData = try await post("/meeting-detection/calendar-event/ignore", body: requestData)
        return try JSONDecoder().decode(MeetingDetectionOperationResponse.self, from: responseData)
    }

    private func postMeetingDetectionOperation(_ endpoint: String) async throws -> MeetingDetectionOperationResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let responseData = try await post(endpoint, body: Data())
        return try JSONDecoder().decode(MeetingDetectionOperationResponse.self, from: responseData)
    }
}
