import Foundation

// MARK: - Zettel (Unified Event Stream) Settings
//
// Mirrors the hand-rolled Codable pattern used for Activity Capture settings
// rather than the generated OpenAPI client, which does not model these routes.
// Field names use explicit snake_case CodingKeys to match the backend
// ZettelSettings / ZettelSettingsUpdate payloads exactly.

struct ZettelSettingsData: Codable, Equatable {
    var enabledSources: [String]
    var historyDays: Int
    var cardingEnabled: Bool
    var cardingIntervalMinutes: Int
    var limitPerSourcePerPass: Int
    var narrativeEnabled: Bool
    var narrativeModel: String
    var narrativeMode: String
    var narrativeScheduledTime: String
    var narrativeIntervalMinutes: Int
    var narrativeBatchSize: Int
    var narrativeMaxAttempts: Int
    /// 0 means no limit, matching the backend sentinel. Non-optional on purpose:
    /// JSONEncoder omits nil optionals, and the backend applies updates with
    /// exclude_unset=True, so an optional could never be cleared once set.
    var narrativeMaxRecords: Int

    enum CodingKeys: String, CodingKey {
        case enabledSources = "enabled_sources"
        case historyDays = "history_days"
        case cardingEnabled = "carding_enabled"
        case cardingIntervalMinutes = "carding_interval_minutes"
        case limitPerSourcePerPass = "limit_per_source_per_pass"
        case narrativeEnabled = "narrative_enabled"
        case narrativeModel = "narrative_model"
        case narrativeMode = "narrative_mode"
        case narrativeScheduledTime = "narrative_scheduled_time"
        case narrativeIntervalMinutes = "narrative_interval_minutes"
        case narrativeBatchSize = "narrative_batch_size"
        case narrativeMaxAttempts = "narrative_max_attempts"
        case narrativeMaxRecords = "narrative_max_records"
    }

    /// Matches the backend defaults so the UI has a sane fallback if the
    /// backend is unreachable at load time.
    static let defaults = ZettelSettingsData(
        enabledSources: [
            "agent_task", "transcription", "assistant_output",
            "scheduled_run", "conversation", "screen_block", "meeting",
        ],
        historyDays: 30,
        cardingEnabled: true,
        cardingIntervalMinutes: 15,
        limitPerSourcePerPass: 500,
        narrativeEnabled: true,
        narrativeModel: "",
        narrativeMode: "scheduled",
        narrativeScheduledTime: "02:00",
        narrativeIntervalMinutes: 30,
        narrativeBatchSize: 50,
        narrativeMaxAttempts: 3,
        narrativeMaxRecords: 0
    )
}

struct ZettelSettingsGetResponse: Codable {
    let settings: ZettelSettingsData
}

struct ZettelSettingsUpdateResponse: Codable {
    let status: String?
    let updatedSettings: ZettelSettingsData
    let message: String?

    enum CodingKeys: String, CodingKey {
        case status
        case updatedSettings = "updated_settings"
        case message
    }
}

/// The narrative run-now endpoint returns the same UpdateResponse envelope; we
/// only surface its message.
struct ZettelNarrativeRunResponse: Codable {
    let status: String?
    let message: String?
}

/// Per-source counters shown in the Memories readout.
struct ZettelSourceStat: Codable, Identifiable, Equatable {
    let kind: String
    let collected: Int
    let awaitingCollection: Int

    var id: String { kind }

    enum CodingKeys: String, CodingKey {
        case kind
        case collected
        case awaitingCollection = "awaiting_collection"
    }
}

/// Read-only progress counters for the unified stream.
struct ZettelStatsData: Codable, Equatable {
    let collected: Int
    let summarized: Int
    let awaitingSummary: Int
    let awaitingRetry: Int
    let failed: Int
    let awaitingCollection: Int
    let bySource: [ZettelSourceStat]

    enum CodingKeys: String, CodingKey {
        case collected
        case summarized
        case awaitingSummary = "awaiting_summary"
        case awaitingRetry = "awaiting_retry"
        case failed
        case awaitingCollection = "awaiting_collection"
        case bySource = "by_source"
    }
}

/// Live progress of a summarize (narrative) run, polled while it drains.
struct NarrativeProgressData: Codable, Equatable {
    let active: Bool
    let total: Int
    let processed: Int
    let finalized: Int
    let stillOpen: Int
    let failed: Int
    let remaining: Int
    let etaSeconds: Double?
    let lastError: String?
    /// Optional so progress polling keeps working against a backend that
    /// predates the cancel endpoint rather than failing to decode entirely.
    let canceling: Bool?
    /// Optional so progress polling keeps working against a backend that predates parallel narrative processing.
    let analysisConcurrency: Int?
    let processingStrategy: String?

    enum CodingKeys: String, CodingKey {
        case active
        case total
        case processed
        case finalized
        case stillOpen = "still_open"
        case failed
        case remaining
        case etaSeconds = "eta_seconds"
        case lastError = "last_error"
        case canceling
        case analysisConcurrency = "analysis_concurrency"
        case processingStrategy = "processing_strategy"
    }

    var isCanceling: Bool { canceling == true }
    var isApiParallel: Bool { processingStrategy == "api_parallel" }
}

extension APIClient {
    func getZettelSettings() async throws -> ZettelSettingsData {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/zettel"
        DevLogger.shared.info("📤 GET request for Zettel settings: \(endpoint)", context: "APIClient")
        do {
            let responseData = try await get(endpoint)
            let response = try JSONDecoder().decode(ZettelSettingsGetResponse.self, from: responseData)
            return response.settings
        } catch {
            DevLogger.shared.error("❌ Failed to fetch Zettel settings: \(error)", context: "APIClient")
            throw error
        }
    }

    func updateZettelSettings(_ settings: ZettelSettingsData) async throws -> ZettelSettingsData {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/zettel"
        DevLogger.shared.info("📤 PUT request to update Zettel settings: \(endpoint)", context: "APIClient")
        do {
            let encoder = JSONEncoder()
            let requestData = try encoder.encode(settings)
            let responseData = try await put(endpoint, data: requestData)
            let response = try JSONDecoder().decode(ZettelSettingsUpdateResponse.self, from: responseData)
            return response.updatedSettings
        } catch {
            DevLogger.shared.error("❌ Failed to update Zettel settings: \(error)", context: "APIClient")
            throw error
        }
    }

    /// Read-only progress counters for the Memories settings readout.
    func getZettelStats() async throws -> ZettelStatsData {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/zettel/stats"
        DevLogger.shared.info("📤 GET request for Zettel stats: \(endpoint)", context: "APIClient")
        do {
            let responseData = try await get(endpoint)
            return try JSONDecoder().decode(ZettelStatsData.self, from: responseData)
        } catch {
            DevLogger.shared.error("❌ Failed to fetch Zettel stats: \(error)", context: "APIClient")
            throw error
        }
    }

    /// Triggers one carding (collection) pass immediately. Returns the server's
    /// human-readable message (e.g. a completion note or the first error).
    @discardableResult
    func runZettelCardingNow() async throws -> String? {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/zettel/carding/run-now"
        DevLogger.shared.info("📤 POST request to run Zettel carding pass: \(endpoint)", context: "APIClient")
        struct EmptyBody: Codable {}
        do {
            let responseData = try await postForData(endpoint, EmptyBody())
            let response = try JSONDecoder().decode(ZettelNarrativeRunResponse.self, from: responseData)
            return response.message
        } catch {
            DevLogger.shared.error("❌ Failed to run Zettel carding pass: \(error)", context: "APIClient")
            throw error
        }
    }

    /// Triggers one narrative finalizing pass immediately. Returns the server's
    /// human-readable message (e.g. a completion note or the first error).
    @discardableResult
    func runZettelNarrativeNow() async throws -> String? {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/zettel/narrative/run-now"
        DevLogger.shared.info("📤 POST request to run Zettel narrative pass: \(endpoint)", context: "APIClient")
        struct EmptyBody: Codable {}
        do {
            let responseData = try await postForData(endpoint, EmptyBody())
            let response = try JSONDecoder().decode(ZettelNarrativeRunResponse.self, from: responseData)
            return response.message
        } catch {
            DevLogger.shared.error("❌ Failed to run Zettel narrative pass: \(error)", context: "APIClient")
            throw error
        }
    }

    /// Requeue failed narrative entries and kick a background summarize pass.
    @discardableResult
    func retryFailedZettelNarratives() async throws -> String? {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/zettel/narrative/retry-failed"
        DevLogger.shared.info("📤 POST request to retry failed Zettel narratives: \(endpoint)", context: "APIClient")
        struct EmptyBody: Codable {}
        do {
            let responseData = try await postForData(endpoint, EmptyBody())
            let response = try JSONDecoder().decode(ZettelNarrativeRunResponse.self, from: responseData)
            return response.message
        } catch {
            DevLogger.shared.error("❌ Failed to retry failed Zettel narratives: \(error)", context: "APIClient")
            throw error
        }
    }

    /// Ask an in-flight summarize pass to stop after the current item.
    @discardableResult
    func cancelZettelNarrative() async throws -> String? {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/zettel/narrative/cancel"
        DevLogger.shared.info("📤 POST request to cancel Zettel narrative pass: \(endpoint)", context: "APIClient")
        struct EmptyBody: Codable {}
        do {
            let responseData = try await postForData(endpoint, EmptyBody())
            let response = try JSONDecoder().decode(ZettelNarrativeRunResponse.self, from: responseData)
            return response.message
        } catch {
            DevLogger.shared.error("❌ Failed to cancel Zettel narrative pass: \(error)", context: "APIClient")
            throw error
        }
    }

    /// Live progress of the current (or most recent) summarize run.
    func getNarrativeProgress() async throws -> NarrativeProgressData {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/settings/zettel/narrative/progress"
        do {
            let responseData = try await get(endpoint)
            return try JSONDecoder().decode(NarrativeProgressData.self, from: responseData)
        } catch {
            DevLogger.shared.error("❌ Failed to fetch narrative progress: \(error)", context: "APIClient")
            throw error
        }
    }
}
