import Foundation
import os // For logger if needed, or use existing APIClient logger

// Define the response/request structs that mirror the Pydantic models

struct CaptureStatsResponse: Codable, Hashable {
    var total_files: Int
    var total_size_bytes: Int
    var files_last_7_days: Int
    var size_last_7_days_bytes: Int
    var files_last_30_days: Int
    var size_last_30_days_bytes: Int
}

struct CleanupSettingsResponse: Codable, Hashable {
    var auto_cleanup_enabled: Bool
    var retention_days: Int
    var cleanup_hour: Int
    var cleanup_minute: Int
}

struct UpdateCleanupSettingsRequest: Codable {
    var auto_cleanup_enabled: Bool
    var retention_days: Int
    var cleanup_hour: Int?
    var cleanup_minute: Int?
}

struct ClearCapturesResponse: Codable, Hashable {
    var status: String
    var message: String
    var files_deleted: Int
    var space_freed_bytes: Int
    var records_deleted: Int?
    var derived_entries_deleted: Int?
    var errors: [String]?
}

// MARK: - Activity Capture Scheduler Models
struct ActivityCaptureStatusResponse: Codable {
    let enabled: Bool
    let frequencyMinutes: Double  // Changed from Int to Double to match API response (supports fractional minutes like 0.5)
    let lastCaptureTime: String?
    let nextCaptureTime: String?
    let pendingCapturesCount: Int
    let failedCapturesCount: Int
    let totalCapturesToday: Int
    let totalCapturesLast7Days: Int
    let totalCapturesLast30Days: Int
    let skippedCaptureCount: Int?
    let compactedCaptureCount: Int?
    let lastPolicyDecision: String?
    let lastPolicyDecisionTime: String?
    
    enum CodingKeys: String, CodingKey {
        case enabled
        case frequencyMinutes = "frequency_minutes"
        case lastCaptureTime = "last_capture_time"
        case nextCaptureTime = "next_capture_time"
        case pendingCapturesCount = "pending_captures_count"
        case failedCapturesCount = "failed_captures_count"
        case totalCapturesToday = "total_captures_today"
        case totalCapturesLast7Days = "total_captures_last_7_days"
        case totalCapturesLast30Days = "total_captures_last_30_days"
        case skippedCaptureCount = "skipped_capture_count"
        case compactedCaptureCount = "compacted_capture_count"
        case lastPolicyDecision = "last_policy_decision"
        case lastPolicyDecisionTime = "last_policy_decision_time"
    }
    
    // Computed properties for backward compatibility
    var isEnabled: Bool { enabled }
    var isRunning: Bool { enabled }  // The scheduler status endpoint reports runtime activity as enabled.
    var todaysCaptures: Int { totalCapturesToday }
    var pendingCaptures: Int { pendingCapturesCount }
    var failedCaptures: Int { failedCapturesCount }
    var nextCapture: String? { nextCaptureTime }
    var lastCapture: String? { lastCaptureTime }
}

struct ActivityProcessingProgressResponse: Codable, Equatable {
    let active: Bool
    let total: Int
    let processed: Int
    let succeeded: Int
    let failed: Int
    let remaining: Int
    let etaSeconds: Double?
    let cancelRequested: Bool
    let startedAt: String?
    let lastError: String?
    let maxRecords: Int
    let analysisConcurrency: Int?
    let processingStrategy: String?

    enum CodingKeys: String, CodingKey {
        case active, total, processed, succeeded, failed, remaining
        case etaSeconds = "eta_seconds"
        case cancelRequested = "cancel_requested"
        case startedAt = "started_at"
        case lastError = "last_error"
        case maxRecords = "max_records"
        case analysisConcurrency = "analysis_concurrency"
        case processingStrategy = "processing_strategy"
    }
}

private struct ActivityProcessingStartResponse: Decodable {
    let data: Payload

    struct Payload: Decodable {
        let progress: ActivityProcessingProgressResponse
    }
}

private struct ActivityProcessingCancelResponse: Decodable {
    let data: Payload

    struct Payload: Decodable {
        let cancelRequested: Bool

        enum CodingKeys: String, CodingKey {
            case cancelRequested = "cancel_requested"
        }
    }
}

struct ActivityCaptureConfigRequest: Codable {
    let frequencyMinutes: Int
}

extension APIClient {

    func fetchCaptureStats() async throws -> CaptureStatsResponse {
        guard isBackendAvailable else { throw APIError.backendNotAvailable }
        let endpoint = "/api/v1/capture-management/stats"
        self.logger.info("📤 GET request for capture stats: \(endpoint)")
        let data = try await get(endpoint)
        let decoder = JSONDecoder()
        do {
            let response = try decoder.decode(CaptureStatsResponse.self, from: data)
            self.logger.info("📥 Received capture stats.")
            return response
        } catch {
            self.logger.error("❌ Failed to decode CaptureStatsResponse: \(error.localizedDescription)")
            throw APIError.decodingFailed(error)
        }
    }

    func fetchCleanupSettings() async throws -> CleanupSettingsResponse {
        guard isBackendAvailable else { throw APIError.backendNotAvailable }
        let endpoint = "/api/v1/capture-management/settings"
        self.logger.info("📤 GET request for cleanup settings: \(endpoint)")
        let data = try await get(endpoint)
        let decoder = JSONDecoder()
        do {
            let response = try decoder.decode(CleanupSettingsResponse.self, from: data)
            self.logger.info("📥 Received cleanup settings.")
            return response
        } catch {
            self.logger.error("❌ Failed to decode CleanupSettingsResponse: \(error.localizedDescription)")
            throw APIError.decodingFailed(error)
        }
    }

    func updateCleanupSettings(autoCleanupEnabled: Bool, retentionDays: Int, cleanupHour: Int? = nil, cleanupMinute: Int? = nil) async throws -> CleanupSettingsResponse {
        guard isBackendAvailable else { throw APIError.backendNotAvailable }
        let endpoint = "/api/v1/capture-management/settings"
        let requestBody = UpdateCleanupSettingsRequest(
            auto_cleanup_enabled: autoCleanupEnabled,
            retention_days: retentionDays,
            cleanup_hour: cleanupHour,
            cleanup_minute: cleanupMinute
        )
        self.logger.info("📤 POST request to update cleanup settings: \(endpoint)")
        
        let encoder = JSONEncoder()
        guard let jsonData = try? encoder.encode(requestBody) else {
            throw NSError(domain: "APIClient", code: 0, userInfo: [NSLocalizedDescriptionKey: "Failed to encode UpdateCleanupSettingsRequest"])
        }
        
        let data = try await post(endpoint, body: jsonData)
        let decoder = JSONDecoder()
        do {
            let response = try decoder.decode(CleanupSettingsResponse.self, from: data)
            self.logger.info("📥 Successfully updated cleanup settings.")
            return response
        } catch {
            self.logger.error("❌ Failed to decode CleanupSettingsResponse after update: \(error.localizedDescription)")
            throw APIError.decodingFailed(error)
        }
    }

    func clearAllCaptures() async throws -> ClearCapturesResponse {
        guard isBackendAvailable else { throw APIError.backendNotAvailable }
        let endpoint = "/api/v1/capture-management/clear-all"
        self.logger.info("📤 POST request to clear all captures: \(endpoint)")
        let data = try await post(endpoint, body: Data())
        let decoder = JSONDecoder()
        do {
            let response = try decoder.decode(ClearCapturesResponse.self, from: data)
            self.logger.info("📥 Successfully cleared all captures: \(response.message)")
            return response
        } catch {
            self.logger.error("❌ Failed to decode ClearCapturesResponse after clear all: \(error.localizedDescription)")
            throw APIError.decodingFailed(error)
        }
    }

    func clearCapturesOlderThan(days: Int) async throws -> ClearCapturesResponse {
        guard isBackendAvailable else { throw APIError.backendNotAvailable }
        let endpoint = "/api/v1/capture-management/clear-older-than/\(days)"
        self.logger.info("📤 POST request to clear captures older than \(days) days: \(endpoint)")
        let data = try await post(endpoint, body: Data())
        let decoder = JSONDecoder()
        do {
            let response = try decoder.decode(ClearCapturesResponse.self, from: data)
            self.logger.info("📥 Successfully cleared captures older than \(days) days: \(response.message)")
            return response
        } catch {
            self.logger.error("❌ Failed to decode ClearCapturesResponse after clear older than: \(error.localizedDescription)")
            throw APIError.decodingFailed(error)
        }
    }
    
    // MARK: - Activity Capture Scheduler API Methods
    
    func fetchActivityCaptureStatus() async throws -> ActivityCaptureStatusResponse {
        guard isBackendAvailable else { throw APIError.backendNotAvailable }
        let endpoint = "/activity-capture/status"
        self.logger.info("📤 GET request for activity capture status: \(endpoint)")
        let data = try await get(endpoint)
        let decoder = JSONDecoder()
        do {
            // The new API returns a different structure with capture and processing status
            // We'll need to adapt this to the old structure for compatibility
            let response = try decoder.decode(ActivityCaptureStatusResponse.self, from: data)
            self.logger.info("📥 Received activity capture status.")
            return response
        } catch {
            self.logger.error("❌ Failed to decode ActivityCaptureStatusResponse: \(error.localizedDescription)")
            throw APIError.decodingFailed(error)
        }
    }
    
    func toggleActivityCapture() async throws {
        guard isBackendAvailable else { throw APIError.backendNotAvailable }
        let endpoint = "/activity-capture/toggle"
        self.logger.info("📤 POST request to toggle activity capture: \(endpoint)")
        _ = try await post(endpoint, body: Data())
        self.logger.info("📥 Activity capture toggled successfully.")
    }

    func startActivityCaptureProcessing() async throws -> ActivityProcessingProgressResponse {
        guard isBackendAvailable else { throw APIError.backendNotAvailable }
        let data = try await post("/activity-capture/processing/process-now", body: Data())
        let response = try JSONDecoder().decode(ActivityProcessingStartResponse.self, from: data)
        return response.data.progress
    }

    func getActivityCaptureProcessingProgress() async throws -> ActivityProcessingProgressResponse {
        guard isBackendAvailable else { throw APIError.backendNotAvailable }
        let data = try await get("/activity-capture/processing/progress")
        return try JSONDecoder().decode(ActivityProcessingProgressResponse.self, from: data)
    }

    func cancelActivityCaptureProcessing() async throws -> Bool {
        guard isBackendAvailable else { throw APIError.backendNotAvailable }
        let data = try await post("/activity-capture/processing/cancel", body: Data())
        return try JSONDecoder().decode(ActivityProcessingCancelResponse.self, from: data).data.cancelRequested
    }
    
    // Legacy methods for backward compatibility
    func startActivityCaptureScheduler() async throws {
        try await toggleActivityCapture()
    }
    
    func stopActivityCaptureScheduler() async throws {
        try await toggleActivityCapture()
    }
    
    func configureActivityCaptureScheduler(frequencyMinutes: Int) async throws {
        guard isBackendAvailable else { throw APIError.backendNotAvailable }
        let endpoint = "/activity-capture/scheduler/configure"
        let requestBody = ActivityCaptureConfigRequest(frequencyMinutes: frequencyMinutes)
        
        self.logger.info("📤 POST request to configure activity capture frequency: \(endpoint)")
        
        let encoder = JSONEncoder()
        guard let jsonData = try? encoder.encode(requestBody) else {
            throw NSError(domain: "APIClient", code: 0, userInfo: [NSLocalizedDescriptionKey: "Failed to encode ActivityCaptureConfigRequest"])
        }
        
        _ = try await post(endpoint, body: jsonData)
        self.logger.info("📥 Activity capture scheduler configured successfully.")
    }
} 