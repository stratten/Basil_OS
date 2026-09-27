import Foundation

// MARK: - Command Approval API Methods
extension APIClient {
    
    /// Evaluate if a command needs approval before execution
    func evaluateExecutionApproval(command: String, context: [String: String]? = nil) async throws -> ExecutionApprovalRequest {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        
        let endpoint = "/api/v1/agent-tasks/approval/evaluate"
        DevLogger.shared.info("📤 POST request to evaluate command approval: \(endpoint)", context: "APIClient")
        
        var payload: [String: Any] = [
            "command": command
        ]
        
        if let context = context {
            payload["context"] = context
        }
        
        guard let url = URL(string: "\(baseURL)\(endpoint)") else {
            throw APIError.invalidURL
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        let requestBody = try JSONSerialization.data(withJSONObject: payload, options: [])
        request.httpBody = requestBody
        
        #if DEBUG
        DevLogger.shared.info("[COMMAND APPROVAL] Evaluating command: \(command.prefix(50))...", context: "APIClient")
        #endif
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        
        #if DEBUG
        DevLogger.shared.info("📥 Command approval evaluation response status: \(httpResponse.statusCode)", context: "APIClient")
        #endif
        
        guard httpResponse.statusCode == 200 else {
            throw APIError.serverError(statusCode: httpResponse.statusCode)
        }
        
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let approvalRequest = try decoder.decode(ExecutionApprovalRequest.self, from: data)
        
        #if DEBUG
        DevLogger.shared.info("📥 Command approval: needs=\(approvalRequest.needsApproval), risk=\(approvalRequest.riskLevel), blocked=\(approvalRequest.isBlocked)", context: "APIClient")
        #endif
        
        return approvalRequest
    }
    
    /// Submit user's approval decision for a command
    func submitApprovalDecision(_ decision: ExecutionApprovalDecision) async throws -> ExecutionApprovalDecisionResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        
        let endpoint = "/api/v1/agent-tasks/approval/decide"
        DevLogger.shared.info("📤 POST request to submit approval decision: \(endpoint)", context: "APIClient")
        
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let requestBody = try encoder.encode(decision)
        
        guard let url = URL(string: "\(baseURL)\(endpoint)") else {
            throw APIError.invalidURL
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = requestBody
        
        #if DEBUG
        DevLogger.shared.info("[COMMAND APPROVAL] Submitting decision: approved=\(decision.approved), remember=\(decision.rememberChoice)", context: "APIClient")
        #endif
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        
        guard httpResponse.statusCode == 200 else {
            throw APIError.serverError(statusCode: httpResponse.statusCode)
        }
        
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let decisionResponse = try decoder.decode(ExecutionApprovalDecisionResponse.self, from: data)
        
        #if DEBUG
        DevLogger.shared.info("📥 Approval decision submitted: \(decisionResponse.message)", context: "APIClient")
        #endif
        
        return decisionResponse
    }
    
    /// Get current command approval settings
    func getApprovalSettings() async throws -> ExecutionApprovalSettings {
        guard isBackendAvailable else {
            #if DEBUG
            DevLogger.shared.error("❌ Backend not available for approval settings", context: "APIClient")
            #endif
            throw APIError.backendNotAvailable
        }
        
        let endpoint = "/api/v1/agent-tasks/approval/settings"
        
        do {
            #if DEBUG
            DevLogger.shared.info("📤 Fetching approval settings from \(endpoint)...", context: "APIClient")
            #endif
            
            let data = try await get(endpoint)
            
            #if DEBUG
            if let jsonString = String(data: data, encoding: .utf8) {
                DevLogger.shared.info("📥 Raw JSON response: \(jsonString)", context: "APIClient")
            }
            #endif
            
            let decoder = JSONDecoder()
            // Don't use convertFromSnakeCase - ExecutionApprovalSettings has explicit CodingKeys
            let settings = try decoder.decode(ExecutionApprovalSettings.self, from: data)
            
            #if DEBUG
            DevLogger.shared.info("✅ Decoded approval settings: mode=\(settings.approvalMode), whitelisted=\(settings.whitelistedCount)", context: "APIClient")
            #endif
            
            return settings
        } catch let decodingError as DecodingError {
            #if DEBUG
            DevLogger.shared.error("❌ Decoding error: \(decodingError)", context: "APIClient")
            switch decodingError {
            case .keyNotFound(let key, let context):
                DevLogger.shared.error("  - Missing key '\(key.stringValue)' in \(context.codingPath)", context: "APIClient")
            case .typeMismatch(let type, let context):
                DevLogger.shared.error("  - Type mismatch for type \(type) at \(context.codingPath)", context: "APIClient")
            case .valueNotFound(let type, let context):
                DevLogger.shared.error("  - Value not found for type \(type) at \(context.codingPath)", context: "APIClient")
            case .dataCorrupted(let context):
                DevLogger.shared.error("  - Data corrupted at \(context.codingPath): \(context.debugDescription)", context: "APIClient")
            @unknown default:
                DevLogger.shared.error("  - Unknown decoding error", context: "APIClient")
            }
            #endif
            throw decodingError
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to fetch approval settings: \(error)", context: "APIClient")
            #endif
            throw error
        }
    }
    
    /// Update command approval settings
    func updateApprovalSettings(_ request: UpdateApprovalSettingsRequest) async throws -> ExecutionApprovalSettings {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        
        let endpoint = "/api/v1/agent-tasks/approval/settings"
        
        do {
            let encoder = JSONEncoder()
            // Don't use convertToSnakeCase - UpdateApprovalSettingsRequest has explicit CodingKeys
            let jsonData = try encoder.encode(request)
            
            #if DEBUG
            DevLogger.shared.info("🔄 Updating approval settings...", context: "APIClient")
            #endif
            
            let data = try await post(endpoint, body: jsonData)
            let decoder = JSONDecoder()
            // Don't use convertFromSnakeCase - ExecutionApprovalSettings has explicit CodingKeys
            let response = try decoder.decode(ExecutionApprovalSettings.self, from: data)
            
            #if DEBUG
            DevLogger.shared.info("✅ Updated approval settings: mode=\(response.approvalMode)", context: "APIClient")
            #endif
            
            return response
        } catch {
            DevLogger.shared.error("❌ Failed to update approval settings: \(error.localizedDescription)", context: "APIClient")
            throw error
        }
    }
    
    /// Get all whitelisted command patterns
    func getWhitelistPatterns() async throws -> WhitelistResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        
        let endpoint = "/api/v1/agent-tasks/whitelist"
        
        do {
            #if DEBUG
            DevLogger.shared.info("📤 Fetching whitelist patterns from \(endpoint)...", context: "APIClient")
            #endif
            
            let data = try await get(endpoint)
            
            #if DEBUG
            if let jsonString = String(data: data, encoding: .utf8) {
                DevLogger.shared.info("📥 Raw whitelist response: \(jsonString)", context: "APIClient")
            }
            #endif
            
            let decoder = JSONDecoder()
            // Don't use convertFromSnakeCase - WhitelistResponse and WhitelistPattern have explicit CodingKeys
            decoder.dateDecodingStrategy = .iso8601
            let response = try decoder.decode(WhitelistResponse.self, from: data)
            
            #if DEBUG
            DevLogger.shared.info("✅ Decoded whitelist patterns: \(response.totalCount) patterns", context: "APIClient")
            #endif
            
            return response
        } catch {
            DevLogger.shared.error("❌ Failed to fetch whitelist patterns: \(error.localizedDescription)", context: "APIClient")
            throw error
        }
    }
    
    /// Add a new pattern to the whitelist
    func addWhitelistPattern(_ request: AddWhitelistRequest) async throws -> WhitelistPattern {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        
        let endpoint = "/api/v1/agent-tasks/whitelist"
        DevLogger.shared.info("📤 POST request to add whitelist pattern: \(endpoint)", context: "APIClient")
        
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let requestBody = try encoder.encode(request)
        
        guard let url = URL(string: "\(baseURL)\(endpoint)") else {
            throw APIError.invalidURL
        }
        
        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.httpBody = requestBody
        
        #if DEBUG
        DevLogger.shared.info("[WHITELIST] Adding pattern: \(request.pattern)", context: "APIClient")
        #endif
        
        let (data, response) = try await URLSession.shared.data(for: urlRequest)
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        
        guard httpResponse.statusCode == 200 else {
            throw APIError.serverError(statusCode: httpResponse.statusCode)
        }
        
        let decoder = JSONDecoder()
        // Don't use convertFromSnakeCase - WhitelistPattern has explicit CodingKeys
        decoder.dateDecodingStrategy = .iso8601
        let pattern = try decoder.decode(WhitelistPattern.self, from: data)
        
        #if DEBUG
        DevLogger.shared.info("📥 Pattern added to whitelist: \(pattern.id)", context: "APIClient")
        #endif
        
        return pattern
    }
    
    /// Update an existing whitelist pattern
    func updateWhitelistPattern(id: String, request: UpdateWhitelistRequest) async throws -> WhitelistPattern {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        
        let endpoint = "/api/v1/agent-tasks/whitelist/\(id)"
        DevLogger.shared.info("📤 PUT request to update whitelist pattern: \(endpoint)", context: "APIClient")
        
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let requestBody = try encoder.encode(request)
        
        guard let url = URL(string: "\(baseURL)\(endpoint)") else {
            throw APIError.invalidURL
        }
        
        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = "PUT"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.httpBody = requestBody
        
        #if DEBUG
        DevLogger.shared.info("[WHITELIST] Updating pattern: \(id) to '\(request.pattern)'", context: "APIClient")
        #endif
        
        let (data, response) = try await URLSession.shared.data(for: urlRequest)
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        
        guard httpResponse.statusCode == 200 else {
            throw APIError.serverError(statusCode: httpResponse.statusCode)
        }
        
        let decoder = JSONDecoder()
        // Don't use convertFromSnakeCase - WhitelistPattern has explicit CodingKeys
        decoder.dateDecodingStrategy = .iso8601
        let pattern = try decoder.decode(WhitelistPattern.self, from: data)
        
        #if DEBUG
        DevLogger.shared.info("📥 Pattern updated in whitelist: \(pattern.id)", context: "APIClient")
        #endif
        
        return pattern
    }
    
    /// Remove a pattern from the whitelist
    func removeWhitelistPattern(id: String) async throws {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        
        let endpoint = "/api/v1/agent-tasks/whitelist/\(id)"
        DevLogger.shared.info("📤 DELETE request to remove whitelist pattern: \(endpoint)", context: "APIClient")
        
        guard let url = URL(string: "\(baseURL)\(endpoint)") else {
            throw APIError.invalidURL
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        
        #if DEBUG
        DevLogger.shared.info("[WHITELIST] Removing pattern: \(id)", context: "APIClient")
        #endif
        
        let (_, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        
        guard httpResponse.statusCode == 200 else {
            throw APIError.serverError(statusCode: httpResponse.statusCode)
        }
        
        #if DEBUG
        DevLogger.shared.info("📥 Pattern removed from whitelist", context: "APIClient")
        #endif
    }
}

