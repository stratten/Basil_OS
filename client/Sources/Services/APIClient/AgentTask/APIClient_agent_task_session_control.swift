import Foundation

extension APIClient {
    /// Continue an AgentTask from a checkpoint with user input.
    func continueSession(request: ContinueSessionRequest) async throws -> ContinueSessionResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }

        let endpoint = "/api/v1/agent-tasks/sessions/\(request.agentTaskId)/continue"
        do {
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            let jsonData = try encoder.encode(request)

            #if DEBUG
            DevLogger.shared.info("Continuing AgentTask checkpoint: \(request.agentTaskId)", context: "APIClient")
            #endif

            let data = try await post(endpoint, body: jsonData, timeout: 600)
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            let response = try decoder.decode(ContinueSessionResponse.self, from: data)

            #if DEBUG
            DevLogger.shared.info("AgentTask checkpoint continued: requiresMoreInput=\(response.requiresMoreInput)", context: "APIClient")
            #endif

            return response
        } catch {
            DevLogger.shared.error("Failed to continue AgentTask checkpoint: \(error.localizedDescription)", context: "APIClient")
            throw error
        }
    }

    /// Cancel an AgentTask durably through its canonical session-control route.
    func cancelAgentTaskSession(
        agentTaskId: String,
        reason: String? = nil
    ) async throws -> AgentTaskCancelResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }

        let endpoint = "/api/v1/agent-tasks/sessions/\(agentTaskId)/cancel"
        do {
            let body = ["reason": reason ?? "User requested cancellation"]
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            let jsonData = try encoder.encode(body)

            #if DEBUG
            DevLogger.shared.info("Canceling AgentTask through REST: \(agentTaskId)", context: "APIClient")
            #endif

            let data = try await post(endpoint, body: jsonData)
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            let response = try decoder.decode(AgentTaskCancelResponse.self, from: data)

            #if DEBUG
            DevLogger.shared.info(
                "AgentTask canceled through REST: finalizedViaAgent=\(response.finalizedViaAgent)",
                context: "APIClient"
            )
            #endif

            return response
        } catch {
            DevLogger.shared.error("Failed to cancel AgentTask through REST: \(error.localizedDescription)", context: "APIClient")
            throw error
        }
    }
}
