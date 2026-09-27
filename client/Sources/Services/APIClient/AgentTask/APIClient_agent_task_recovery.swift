import Foundation

// MARK: - AgentTask Recovery Methods
extension APIClient {
    
    /// Retry a failed agentTask
    /// - Parameter agentTaskId: ID of the failed agent task to retry
    /// - Returns: AgentTaskResponse with retry initiation result
    func retryAgentTask(agentTaskId: String) async throws -> AgentTaskResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        
        let endpoint = "/api/v1/agent-tasks/\(agentTaskId)/retry"
        
        #if DEBUG
        DevLogger.shared.info("🔄 Retrying agentTask: \(agentTaskId)", context: "APIClient")
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
        
        if httpResponse.statusCode == 200 {
            let decoder = JSONDecoder()
            let agentTaskResponse = try decoder.decode(AgentTaskResponse.self, from: data)
            
            #if DEBUG
            DevLogger.shared.info("✅ AgentTask retry initiated successfully", context: "APIClient")
            #endif
            
            return agentTaskResponse
        } else {
            #if DEBUG
            DevLogger.shared.error("❌ AgentTask retry failed with status: \(httpResponse.statusCode)", context: "APIClient")
            #endif
            throw APIError.serverError(statusCode: httpResponse.statusCode)
        }
    }
    
    /// Check if an agent task has a resumable checkpoint
    /// - Parameter agentTaskId: ID of the agent task to check
    /// - Returns: CheckpointStatusResponse indicating if checkpoint exists
    func checkAgentTaskCheckpointStatus(agentTaskId: String) async throws -> CheckpointStatusResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        
        let endpoint = "/api/v1/agent-tasks/sessions/\(agentTaskId)/checkpoint-status"
        
        #if DEBUG
        DevLogger.shared.info("🔍 Checking checkpoint status for agent task: \(agentTaskId)", context: "APIClient")
        #endif
        
        let data = try await get(endpoint)
        
        let decoder = JSONDecoder()
        let response = try decoder.decode(CheckpointStatusResponse.self, from: data)
        
        #if DEBUG
        DevLogger.shared.info("✅ Checkpoint status: has_checkpoint=\(response.hasCheckpoint), can_resume=\(response.canResume)", context: "APIClient")
        #endif
        
        return response
    }
}

