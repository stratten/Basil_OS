import Foundation

// MARK: - Transcription API Methods for APIClient
extension APIClient {
    
    /// Fetch transcription history
    /// - Parameters:
    ///   - days: Only fetch transcriptions from the last N days (optional)
    ///   - limit: Maximum number of transcriptions to return (default: 50)
    /// - Returns: TranscriptionHistoryResponse with list of transcriptions
    func listTranscriptions(days: Int? = nil, limit: Int = 50) async throws -> TranscriptionHistoryResponse {
        #if DEBUG
        DevLogger.shared.info("📋 Fetching transcription history (days: \(days ?? 0), limit: \(limit))", context: "APIClient")
        #endif
        
        var queryItems: [URLQueryItem] = [
            URLQueryItem(name: "limit", value: String(limit))
        ]
        
        if let days = days {
            queryItems.append(URLQueryItem(name: "days", value: String(days)))
        }
        
        let queryString = queryItems.map { "\($0.name)=\($0.value ?? "")" }.joined(separator: "&")
        let endpoint = "/transcription/history?\(queryString)"
        
        let data = try await get(endpoint)
        let response = try JSONDecoder().decode(TranscriptionHistoryResponse.self, from: data)
        
        #if DEBUG
        DevLogger.shared.info("✅ Fetched \(response.transcriptions.count) transcriptions", context: "APIClient")
        #endif
        
        return response
    }
    
    /// Search transcriptions by text and filters
    /// - Parameters:
    ///   - query: Text to search for in transcription text (optional)
    ///   - model: Filter by model name (optional)
    ///   - app: Filter by application name (optional)
    ///   - category: Filter by task category (optional)
    ///   - days: Only search within the last N days (optional)
    ///   - limit: Maximum number of results to return (default: 50)
    /// - Returns: TranscriptionHistoryResponse with list of matching transcriptions
    func searchTranscriptions(
        query: String? = nil,
        model: String? = nil,
        app: String? = nil,
        category: String? = nil,
        days: Int? = nil,
        limit: Int = 50
    ) async throws -> TranscriptionHistoryResponse {
        #if DEBUG
        DevLogger.shared.info("🔍 Searching transcriptions (query: \(query ?? "nil"), model: \(model ?? "nil"), app: \(app ?? "nil"))", context: "APIClient")
        #endif
        
        var urlComponents = URLComponents(string: "/transcription/search")!
        var queryItems: [URLQueryItem] = []
        
        if let query = query, !query.isEmpty {
            queryItems.append(URLQueryItem(name: "query", value: query))
        }
        if let model = model {
            queryItems.append(URLQueryItem(name: "model", value: model))
        }
        if let app = app {
            queryItems.append(URLQueryItem(name: "app", value: app))
        }
        if let category = category {
            queryItems.append(URLQueryItem(name: "category", value: category))
        }
        if let days = days {
            queryItems.append(URLQueryItem(name: "days", value: String(days)))
        }
        queryItems.append(URLQueryItem(name: "limit", value: String(limit)))
        
        urlComponents.queryItems = queryItems
        
        let endpoint = urlComponents.string ?? "/transcription/search"
        
        let data = try await get(endpoint)
        
        do {
            let response = try JSONDecoder().decode(TranscriptionHistoryResponse.self, from: data)
            #if DEBUG
            DevLogger.shared.info("✅ Search returned \(response.transcriptions.count) transcriptions", context: "APIClient")
            #endif
            return response
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to decode transcription search results: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }
}
