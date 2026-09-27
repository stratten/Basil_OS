import Foundation

// MARK: - AgentTask History Methods
extension APIClient {
    
    /// Fetch a list of agentTasks ordered by most recent
    /// - Parameters:
    ///   - limit: Maximum number of agent tasks to return (default: 50)
    ///   - offset: Pagination offset (default: 0)
    ///   - status: Optional status filter (e.g., "completed")
    /// - Returns: AgentTaskHistoryResponse with list of agent tasks
    func listAgentTasks(limit: Int = 50, offset: Int = 0, status: String? = nil) async throws -> AgentTaskHistoryResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        
        var endpoint = "/api/v1/agent-tasks/history?limit=\(limit)&offset=\(offset)"
        if let status = status {
            endpoint += "&status=\(status)"
        }
        
        #if DEBUG
        DevLogger.shared.info("📋 Fetching agentTask history (limit: \(limit), offset: \(offset))", context: "APIClient")
        #endif
        
        let data = try await get(endpoint)
        
        #if DEBUG
        // Log a preview of the raw response for debugging
        if let jsonString = String(data: data, encoding: .utf8) {
            let preview = String(jsonString.prefix(500))
            DevLogger.shared.info("📦 Raw response preview: \(preview)", context: "APIClient")
        }
        #endif
        
        let decoder = JSONDecoder()
        // Use ISO8601 with fractional seconds support - create formatters inside closure to avoid capture warning
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let dateString = try container.decode(String.self)
            
            // Try with fractional seconds first
            let fractionalFormatter = ISO8601DateFormatter()
            fractionalFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = fractionalFormatter.date(from: dateString) {
                return date
            }
            
            // Fall back to standard ISO8601
            let standardFormatter = ISO8601DateFormatter()
            if let date = standardFormatter.date(from: dateString) {
                return date
            }
            
            #if DEBUG
            DevLogger.shared.error("❌ Failed to parse date: \(dateString)", context: "APIClient")
            #endif
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Cannot decode date: \(dateString)")
        }
        
        do {
            let response = try decoder.decode(AgentTaskHistoryResponse.self, from: data)
            #if DEBUG
            DevLogger.shared.info("✅ Fetched \(response.agentTasks.count) agentTasks", context: "APIClient")
            #endif
            return response
        } catch let decodingError as DecodingError {
            #if DEBUG
            switch decodingError {
            case .keyNotFound(let key, let context):
                DevLogger.shared.error("❌ Key '\(key.stringValue)' not found: \(context.debugDescription)", context: "APIClient")
            case .typeMismatch(let type, let context):
                DevLogger.shared.error("❌ Type mismatch for \(type): \(context.debugDescription) at \(context.codingPath)", context: "APIClient")
            case .valueNotFound(let type, let context):
                DevLogger.shared.error("❌ Value not found for \(type): \(context.debugDescription)", context: "APIClient")
            case .dataCorrupted(let context):
                DevLogger.shared.error("❌ Data corrupted: \(context.debugDescription)", context: "APIClient")
            @unknown default:
                DevLogger.shared.error("❌ Unknown decoding error: \(decodingError)", context: "APIClient")
            }
            #endif
            throw decodingError
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to decode agentTask history: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }
    
    /// Fetch all currently active/processing agentTasks
    /// Used to restore multi-agent state on app launch and to populate the active agents sidebar
    /// - Returns: ActiveAgentsResponse with list of active agents
    func listActiveAgentTasks() async throws -> ActiveAgentsResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        
        let endpoint = "/api/v1/agent-tasks/active"
        
        #if DEBUG
        DevLogger.shared.info("🔄 Fetching active agent tasks", context: "APIClient")
        #endif
        
        let data = try await get(endpoint)
        
        let decoder = JSONDecoder()
        // Use ISO8601 with fractional seconds support
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let dateString = try container.decode(String.self)
            
            // Try with fractional seconds first
            let fractionalFormatter = ISO8601DateFormatter()
            fractionalFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = fractionalFormatter.date(from: dateString) {
                return date
            }
            
            // Fall back to standard ISO8601
            let standardFormatter = ISO8601DateFormatter()
            if let date = standardFormatter.date(from: dateString) {
                return date
            }
            
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Cannot decode date: \(dateString)")
        }
        
        let response = try decoder.decode(ActiveAgentsResponse.self, from: data)
        
        #if DEBUG
        DevLogger.shared.info("✅ Fetched \(response.count) active agents", context: "APIClient")
        #endif
        
        return response
    }
    
    /// Fetch full details for a specific agentTask
    /// - Parameter agentTaskId: ID of the agent task to fetch
    /// - Returns: AgentTaskDetail with full agent task information including follow-ups
    func getAgentTask(agentTaskId: String) async throws -> AgentTaskDetail {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        
        let endpoint = "/api/v1/agent-tasks/\(agentTaskId)"
        
        #if DEBUG
        DevLogger.shared.info("📋 Fetching agentTask details for: \(agentTaskId)", context: "APIClient")
        #endif
        
        let data = try await get(endpoint)
        
        let decoder = JSONDecoder()
        // Use custom date decoder for ISO8601 with 'Z' suffix
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let dateString = try container.decode(String.self)
            
            let fractionalFormatter = ISO8601DateFormatter()
            fractionalFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = fractionalFormatter.date(from: dateString) {
                return date
            }
            
            let standardFormatter = ISO8601DateFormatter()
            if let date = standardFormatter.date(from: dateString) {
                return date
            }
            
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Cannot decode date: \(dateString)")
        }
        
        do {
            let agentTask = try decoder.decode(AgentTaskDetail.self, from: data)
            #if DEBUG
            DevLogger.shared.info("✅ Fetched agentTask: \(agentTask.originalPrompt.prefix(30))... with \(agentTask.followUps.count) follow-ups", context: "APIClient")
            #endif
            return agentTask
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to decode agentTask detail: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }
    
    /// Delete a agentTask by ID
    /// - Parameters:
    ///   - agentTaskId: ID of the agent task to delete
    ///   - cascade: If true, also delete all follow-up agent tasks in the chain (default: true)
    /// - Returns: DeleteAgentTaskResponse indicating success/failure
    func deleteAgentTask(agentTaskId: String, cascade: Bool = true) async throws -> DeleteAgentTaskResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        
        let endpoint = "/api/v1/agent-tasks/\(agentTaskId)?cascade=\(cascade)"
        
        #if DEBUG
        DevLogger.shared.info("🗑️ Deleting agentTask: \(agentTaskId) (cascade=\(cascade))", context: "APIClient")
        #endif
        
        let response = try await delete(endpoint)
        
        let success = response.status == "success" || response.status == "deleted"
        let message = response.details ?? "AgentTask deleted"
        
        #if DEBUG
        DevLogger.shared.info("✅ AgentTask deleted: \(message)", context: "APIClient")
        #endif
        
        return DeleteAgentTaskResponse(success: success, message: message)
    }
    
    /// Search agentTasks by text and filters
    /// - Parameters:
    ///   - query: Text to search for in agent task text (optional)
    ///   - status: Filter by status, e.g., "completed" (optional)
    ///   - app: Filter by application name (optional)
    ///   - days: Only search within the last N days (optional)
    ///   - limit: Maximum number of results to return (default: 50)
    /// - Returns: AgentTaskHistoryResponse with list of matching agent tasks
    func searchAgentTasks(
        query: String? = nil,
        status: String? = nil,
        app: String? = nil,
        days: Int? = nil,
        limit: Int = 50
    ) async throws -> AgentTaskHistoryResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        
        var urlComponents = URLComponents(string: "/api/v1/agent-tasks/agent-task-history/search")!
        var queryItems: [URLQueryItem] = []
        
        if let query = query, !query.isEmpty {
            queryItems.append(URLQueryItem(name: "query", value: query))
        }
        if let status = status {
            queryItems.append(URLQueryItem(name: "status", value: status))
        }
        if let app = app {
            queryItems.append(URLQueryItem(name: "app", value: app))
        }
        if let days = days {
            queryItems.append(URLQueryItem(name: "days", value: String(days)))
        }
        queryItems.append(URLQueryItem(name: "limit", value: String(limit)))
        
        urlComponents.queryItems = queryItems
        
        let endpoint = urlComponents.string ?? "/api/v1/agent-tasks/agent-task-history/search"
        
        #if DEBUG
        DevLogger.shared.info("🔍 Searching agentTasks (query: \(query ?? "nil"), status: \(status ?? "nil"), app: \(app ?? "nil"))", context: "APIClient")
        #endif
        
        let data = try await get(endpoint)
        
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let dateString = try container.decode(String.self)
            
            let fractionalFormatter = ISO8601DateFormatter()
            fractionalFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = fractionalFormatter.date(from: dateString) {
                return date
            }
            
            let standardFormatter = ISO8601DateFormatter()
            if let date = standardFormatter.date(from: dateString) {
                return date
            }
            
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Cannot decode date: \(dateString)")
        }
        
        do {
            let response = try decoder.decode(AgentTaskHistoryResponse.self, from: data)
            #if DEBUG
            DevLogger.shared.info("✅ Search returned \(response.agentTasks.count) agentTasks", context: "APIClient")
            #endif
            return response
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to decode agentTask search results: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }
}

