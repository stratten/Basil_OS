import Foundation
import os

// MARK: - AssistantSession History Data Models

/// Summary item for AssistantSession history sidebar.
///
/// Renamed from the legacy `SuggestionHistoryListItem` as part of the
/// AssistantSession rename rollout. The `inputModality` field (added with the
/// schema's `input_modality` column) distinguishes voice-entered from
/// text-entered AssistantSession outputs; `nil` means the row was either
/// produced by the screen-only / NO_INSTRUCTION_DEFAULT path, or it
/// predates the column being added.
struct AssistantOutputHistoryListItem: Codable, Identifiable {
    let id: Int
    let outputType: String
    let inputModality: String?
    let title: String
    let outputPreview: String
    let timestamp: String
    let status: String
    let refinementCount: Int
    let appName: String?

    enum CodingKeys: String, CodingKey {
        case id
        case outputType = "output_type"
        case inputModality = "input_modality"
        case title
        case outputPreview = "output_preview"
        case timestamp
        case status
        case refinementCount = "refinement_count"
        case appName = "app_name"
    }

    var displayTitle: String {
        title.isEmpty ? "Untitled output" : title
    }

    var parsedDate: Date? {
        return AssistantOutputHistoryTimestamp.parse(timestamp)
    }

    /// Icon for the input modality (voice vs text). For rows whose
    /// modality is unknown or not applicable, falls back to a sensible
    /// per-output_type default.
    var modalityIcon: String {
        if let modality = inputModality {
            switch modality {
            case "voice": return "mic.fill"
            case "text": return "keyboard"
            default: break
            }
        }
        switch outputType {
        case "regular": return "lightbulb"
        default: return "doc.text"
        }
    }
}

/// Refinement entry within a AssistantSession output detail.
struct AssistantSessionRefinementEntry: Codable {
    let instruction: String
    let output: String
    let timestamp: String

    var parsedDate: Date? {
        return AssistantOutputHistoryTimestamp.parse(timestamp)
    }
}

/// Parser for AssistantSession-history timestamps emitted by the backend.
///
/// Both sources are UTC, but neither carries a timezone marker:
///   * `assistant_outputs.generated_at` -- SQLite `CURRENT_TIMESTAMP`
///     ("YYYY-MM-DD HH:MM:SS")
///   * `refinements[].timestamp` -- Python `datetime.utcnow().isoformat()`
///     ("YYYY-MM-DDTHH:MM:SS[.ffffff]")
///
/// `DateFormatter` defaults `timeZone` to the system default
/// (`TimeZone.current`) when not set explicitly, which would parse a
/// genuinely-UTC string like "2026-04-21T23:30:00" as 23:30 *local* time --
/// then `sidebarFormat` (also local) would render it as "11:30 pm" for an
/// EDT user even though the underlying moment was 7:30 pm local. Pinning
/// `timeZone = .utc` on the parser side gives `Date` the correct absolute
/// instant; the formatter's local-timezone conversion then renders it
/// correctly.
///
/// Kept as a separate enum so `AssistantOutputHistoryListItem`,
/// `AssistantOutputHistoryDetail`, and `AssistantSessionRefinementEntry` share one
/// implementation. Distinct from `DateFormattingUtils.parseISO8601`, which
/// documents the opposite assumption (timestamps without timezone are
/// *local* time from `datetime.now().isoformat()`) for transcription
/// history and is correct for that surface.
enum AssistantOutputHistoryTimestamp {
    private static let utc = TimeZone(identifier: "UTC")

    private static let formatters: [DateFormatter] = {
        let formats = [
            "yyyy-MM-dd'T'HH:mm:ss.SSSSSS",
            "yyyy-MM-dd'T'HH:mm:ss.SSS",
            "yyyy-MM-dd'T'HH:mm:ss",
            "yyyy-MM-dd HH:mm:ss",
        ]
        return formats.map { format in
            let f = DateFormatter()
            f.dateFormat = format
            f.locale = Locale(identifier: "en_US_POSIX")
            f.timeZone = utc
            return f
        }
    }()

    static func parse(_ raw: String) -> Date? {
        for formatter in formatters {
            if let date = formatter.date(from: raw) {
                return date
            }
        }
        return nil
    }
}

/// Full detail for a single AssistantSession output (for rehydration and display).
struct AssistantOutputHistoryDetail: Codable {
    let id: Int
    let outputType: String
    let inputModality: String?
    let outputText: String
    let contextText: String?
    let explanationText: String?
    let modelName: String?
    let timestamp: String
    let status: String
    let refinementCount: Int
    let refinements: [AssistantSessionRefinementEntry]
    let appName: String?
    let windowTitle: String?
    let screenCapturePath: String?
    let textSelection: String?
    let userRequest: String?
    let processingTimeMs: Int?
    let wasInserted: Bool
    let userRating: Int?
    let userFeedback: String?

    enum CodingKeys: String, CodingKey {
        case id
        case outputType = "output_type"
        case inputModality = "input_modality"
        case outputText = "output_text"
        case contextText = "context_text"
        case explanationText = "explanation_text"
        case modelName = "model_name"
        case timestamp
        case status
        case refinementCount = "refinement_count"
        case refinements
        case appName = "app_name"
        case windowTitle = "window_title"
        case screenCapturePath = "screen_capture_path"
        case textSelection = "text_selection"
        case userRequest = "user_request"
        case processingTimeMs = "processing_time_ms"
        case wasInserted = "was_inserted"
        case userRating = "user_rating"
        case userFeedback = "user_feedback"
    }

    var parsedDate: Date? {
        return AssistantOutputHistoryTimestamp.parse(timestamp)
    }
}

/// Response for AssistantSession history list.
struct AssistantOutputHistoryResponse: Codable {
    let outputs: [AssistantOutputHistoryListItem]
    let totalCount: Int
    let hasMore: Bool

    enum CodingKeys: String, CodingKey {
        case outputs
        case totalCount = "total_count"
        case hasMore = "has_more"
    }
}

/// Response for resuming a AssistantSession output (legacy 'regular' rows).
struct AssistantSessionResumeResponse: Codable {
    let assistantOutputId: Int
    let outputType: String
    let inputModality: String?
    let outputText: String
    let userRequest: String?
    let contextText: String?
    let explanationText: String?
    let appName: String?
    let refinementCount: Int
    let refinements: [AssistantSessionRefinementEntry]

    enum CodingKeys: String, CodingKey {
        case assistantOutputId = "assistant_output_id"
        case outputType = "output_type"
        case inputModality = "input_modality"
        case outputText = "output_text"
        case userRequest = "user_request"
        case contextText = "context_text"
        case explanationText = "explanation_text"
        case appName = "app_name"
        case refinementCount = "refinement_count"
        case refinements
    }
}

/// Response for deleting a AssistantSession output.
struct DeleteAssistantOutputResponse: Codable {
    let status: String
    let id: Int
}

/// Response for rehydrating a AssistantSession output from history into a live
/// in-memory session for refinement.
///
/// The backend creates a fresh in-memory assistantSession session keyed by
/// `sessionId`, seeded with the persisted state. Once we have this
/// response, the AssistantSession widget can be opened in its `.completed`
/// state with `sessionId` already set, so the existing Refine button
/// (which calls `/assistant-sessions/{session_id}/refine`) works without
/// further setup.
struct AssistantSessionRehydrateResponse: Codable {
    let sessionId: String
    let assistantOutputId: Int
    let outputText: String
    let inputModality: String?
    let userRequest: String?
    let contextText: String?
    let explanationText: String?
    let modelName: String?
    let appName: String?
    let refinementCount: Int

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case assistantOutputId = "assistant_output_id"
        case outputText = "output_text"
        case inputModality = "input_modality"
        case userRequest = "user_request"
        case contextText = "context_text"
        case explanationText = "explanation_text"
        case modelName = "model_name"
        case appName = "app_name"
        case refinementCount = "refinement_count"
    }
}

// MARK: - APIClient AssistantSession History Methods
extension APIClient {

    func listAssistantOutputHistory(inputModality: String? = nil, outputType: String? = nil, limit: Int = 50, offset: Int = 0) async throws -> AssistantOutputHistoryResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }

        var endpoint = "/assistant-outputs?limit=\(limit)&offset=\(offset)"
        if let inputModality = inputModality {
            endpoint += "&input_modality=\(inputModality)"
        }
        if let outputType = outputType {
            endpoint += "&output_type=\(outputType)"
        }

        #if DEBUG
        DevLogger.shared.info("📋 Fetching AssistantSession history (modality: \(inputModality ?? "all"), type: \(outputType ?? "all"), limit: \(limit))", context: "APIClient")
        #endif

        let data = try await get(endpoint)
        let decoder = JSONDecoder()

        do {
            let response = try decoder.decode(AssistantOutputHistoryResponse.self, from: data)
            #if DEBUG
            DevLogger.shared.info("✅ Fetched \(response.outputs.count) AssistantSession outputs", context: "APIClient")
            #endif
            return response
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to decode AssistantSession history: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }

    func searchAssistantOutputHistory(query: String, inputModality: String? = nil, outputType: String? = nil, limit: Int = 50) async throws -> AssistantOutputHistoryResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }

        let encodedQuery = query.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? query
        var endpoint = "/assistant-outputs/search?q=\(encodedQuery)&limit=\(limit)"
        if let inputModality = inputModality {
            endpoint += "&input_modality=\(inputModality)"
        }
        if let outputType = outputType {
            endpoint += "&output_type=\(outputType)"
        }

        #if DEBUG
        DevLogger.shared.info("🔍 Searching AssistantSession history (query: \(query))", context: "APIClient")
        #endif

        let data = try await get(endpoint)
        let decoder = JSONDecoder()

        do {
            let response = try decoder.decode(AssistantOutputHistoryResponse.self, from: data)
            #if DEBUG
            DevLogger.shared.info("✅ Search returned \(response.outputs.count) AssistantSession outputs", context: "APIClient")
            #endif
            return response
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to decode AssistantSession search results: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }

    func getAssistantOutputDetail(id: Int) async throws -> AssistantOutputHistoryDetail {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }

        let endpoint = "/assistant-outputs/\(id)"

        #if DEBUG
        DevLogger.shared.info("📋 Fetching AssistantSession output detail for id: \(id)", context: "APIClient")
        #endif

        let data = try await get(endpoint)
        let decoder = JSONDecoder()

        do {
            let detail = try decoder.decode(AssistantOutputHistoryDetail.self, from: data)
            #if DEBUG
            DevLogger.shared.info("✅ Fetched AssistantSession output detail: \(detail.outputType)", context: "APIClient")
            #endif
            return detail
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to decode AssistantSession output detail: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }

    func deleteAssistantOutput(id: Int) async throws -> DeleteAssistantOutputResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }

        let endpoint = "/assistant-outputs/\(id)"

        #if DEBUG
        DevLogger.shared.info("🗑️ Deleting AssistantSession output: \(id)", context: "APIClient")
        #endif

        let response = try await delete(endpoint)

        #if DEBUG
        DevLogger.shared.info("✅ AssistantSession output deleted: \(response.status)", context: "APIClient")
        #endif

        return DeleteAssistantOutputResponse(status: response.status, id: id)
    }

    func resumeAssistantOutput(id: Int) async throws -> AssistantSessionResumeResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }

        let endpoint = "/assistant-outputs/\(id)/resume"

        #if DEBUG
        DevLogger.shared.info("▶️ Resuming AssistantSession output: \(id)", context: "APIClient")
        #endif

        guard let url = URL(string: "\(baseURL)\(endpoint)") else {
            throw APIError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            throw APIError.serverError(statusCode: httpResponse.statusCode)
        }

        let decoder = JSONDecoder()
        let resumeResponse = try decoder.decode(AssistantSessionResumeResponse.self, from: data)

        #if DEBUG
        DevLogger.shared.info("✅ AssistantSession output resumed: type=\(resumeResponse.outputType)", context: "APIClient")
        #endif

        return resumeResponse
    }

    /// Rehydrate a persisted AssistantSession output into a fresh in-memory session.
    ///
    /// Calls `POST /assistant-sessions/rehydrate-from-history/{id}`, which creates
    /// a new AssistantSessionService session pre-populated with the historical
    /// output text, user request, and context. The returned `sessionId`
    /// is what the widget needs to call the existing
    /// `/assistant-sessions/{session_id}/refine` endpoint when the user records a
    /// refinement.
    func rehydrateAssistantSession(id: Int) async throws -> AssistantSessionRehydrateResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }

        let endpoint = "/assistant-sessions/rehydrate-from-history/\(id)"

        #if DEBUG
        DevLogger.shared.info("▶️ Rehydrating AssistantSession: \(id)", context: "APIClient")
        #endif

        guard let url = URL(string: "\(baseURL)\(endpoint)") else {
            throw APIError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            throw APIError.serverError(statusCode: httpResponse.statusCode)
        }

        let decoder = JSONDecoder()
        let resumeResponse = try decoder.decode(AssistantSessionRehydrateResponse.self, from: data)

        #if DEBUG
        DevLogger.shared.info("✅ AssistantSession output rehydrated: session=\(resumeResponse.sessionId)", context: "APIClient")
        #endif

        return resumeResponse
    }
}
