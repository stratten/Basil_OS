import Foundation
import os

// MARK: - AgentTask Processing Methods for APIClient
extension APIClient {
    
    func getAgentTaskExamples() async throws -> [String] {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        let endpoint = "/api/v1/agent-tasks/examples"
        
        do {
            let data = try await get(endpoint)
            let decoder = JSONDecoder()
            let exampleData = try decoder.decode(AgentTaskExampleData.self, from: data)
            return exampleData.examples
        } catch {
            DevLogger.shared.error("❌ Failed to fetch AgentTask examples: \(error.localizedDescription)", context: "APIClient")
            throw error
        }
    }
    
    func processAgentTask(
        _ agentTask: String, 
        clarificationAgentTask: String? = nil,
        agentTaskId: String? = nil,
        rootTaskId: String? = nil,
        previousTaskId: String? = nil,
        modelId: String? = nil,
        onStreamingChunk: ((AgentTaskStreamingChunk) -> Void)? = nil
    ) async throws -> AgentTaskResponse {
        guard isBackendAvailable else {
            throw APIError.backendNotAvailable
        }
        
        let endpoint = "/api/v1/agent-tasks/process"
        DevLogger.shared.info("📤 POST request to process agentTask: \(endpoint)", context: "APIClient")
        
        // Create request payload
        var payload: [String: Any] = [
            "agent_task": agentTask
        ]
        
        if let clarificationAgentTask = clarificationAgentTask {
            payload["clarification_agent_task"] = clarificationAgentTask
        }
        
        if let agentTaskId = agentTaskId {
            payload["agent_task_id"] = agentTaskId
        }
        if let rootTaskId = rootTaskId {
            payload["root_task_id"] = rootTaskId
        }
        if let previousTaskId = previousTaskId {
            payload["previous_task_id"] = previousTaskId
        }
        // Optional explicit model override. Callers like the setup-assistant
        // bridge use this to pin the task to the same model route the setup
        // agent itself is running on, rather than falling through to the
        // user's preferred reasoning model. AgentTaskRequest.model_id on the
        // backend already honors this field.
        if let modelId, !modelId.isEmpty {
            payload["model_id"] = modelId
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
        DevLogger.shared.info("[AGENT_TASK] Processing agent task: \(agentTask.prefix(50))...", context: "APIClient")
        #endif
        
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            
            guard let httpResponse = response as? HTTPURLResponse else {
                throw APIError.invalidResponse
            }
            
            #if DEBUG
            DevLogger.shared.info("📥 AgentTask response status: \(httpResponse.statusCode)", context: "APIClient")
            #endif
            
            if httpResponse.statusCode == 200 {
                // Check if this is a streaming response
                if let contentType = httpResponse.value(forHTTPHeaderField: "Content-Type"),
                   contentType.contains("application/x-ndjson") {
                    // Handle streaming response
                    if let onStreamingChunk = onStreamingChunk {
                        let dataString = String(data: data, encoding: .utf8) ?? ""
                        let lines = dataString.components(separatedBy: .newlines)
                        
                        for line in lines {
                            if !line.isEmpty {
                                if let lineData = line.data(using: .utf8),
                                   let chunk = try? JSONDecoder().decode(AgentTaskStreamingChunk.self, from: lineData) {
                                    onStreamingChunk(chunk)
                                }
                            }
                        }
                    }
                    
                    // For streaming responses, return a basic response indicating streaming was handled
                    return AgentTaskResponse(
                        success: true,
                        operation: "streaming",
                        confidence: 1.0,
                        reasoning: "Response streamed successfully",
                        message: "Task processed with streaming",
                        processingTime: 0.0,
                        agentTaskId: agentTaskId ?? "",
                        data: nil,
                        error: nil
                    )
                } else {
                    // Handle regular JSON response
                    let decoder = JSONDecoder()
                    let agentTaskResponse = try decoder.decode(AgentTaskResponse.self, from: data)
                    
                    #if DEBUG
                    DevLogger.shared.info("📥 AgentTask processed successfully: \(agentTaskResponse.operation)", context: "APIClient")
                    #endif
                    
                    return agentTaskResponse
                }
            } else {
                #if DEBUG
                DevLogger.shared.error("❌ AgentTask processing failed with status: \(httpResponse.statusCode)", context: "APIClient")
                #endif
                throw APIError.serverError(statusCode: httpResponse.statusCode)
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ AgentTask processing error: \(error.localizedDescription)", context: "APIClient")
            #endif
            throw error
        }
    }
    
    func processAgentTaskRefinement(
        rootTaskId: String,
        audioData: Data,
        appName: String? = nil,
        windowTitle: String? = nil,
        screenText: String? = nil
    ) async -> AgentTaskRefinementResponse {
        // Proceed to attempt refinement request; do not short-circuit here
        
        let endpoint = "/api/v1/agent-tasks/\(rootTaskId)/refine-audio"
        DevLogger.shared.info("📤 POST request to refine agentTask: \(endpoint)", context: "APIClient")
        
        do {
            guard let url = URL(string: "\(baseURL)\(endpoint)") else {
                return AgentTaskRefinementResponse(
                    success: false,
                    message: "Invalid URL",
                    transcription: nil,
                    refinementAgentTaskId: nil,
                    rootTaskId: rootTaskId,
                    result: nil,
                    refinementIteration: nil,
                    processed: false
                )
            }
            
            // Create multipart form data request
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            
            let boundary = UUID().uuidString
            request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
            
            var body = Data()
            
            // Add audio file
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"audio_file\"; filename=\"refinement.wav\"\r\n".data(using: .utf8)!)
            body.append("Content-Type: audio/wav\r\n\r\n".data(using: .utf8)!)
            body.append(audioData)
            body.append("\r\n".data(using: .utf8)!)
            
            // Add optional form fields
            if let appName = appName {
                body.append("--\(boundary)\r\n".data(using: .utf8)!)
                body.append("Content-Disposition: form-data; name=\"app_name\"\r\n\r\n".data(using: .utf8)!)
                body.append(appName.data(using: .utf8)!)
                body.append("\r\n".data(using: .utf8)!)
            }
            
            if let windowTitle = windowTitle {
                body.append("--\(boundary)\r\n".data(using: .utf8)!)
                body.append("Content-Disposition: form-data; name=\"window_title\"\r\n\r\n".data(using: .utf8)!)
                body.append(windowTitle.data(using: .utf8)!)
                body.append("\r\n".data(using: .utf8)!)
            }
            
            if let screenText = screenText {
                body.append("--\(boundary)\r\n".data(using: .utf8)!)
                body.append("Content-Disposition: form-data; name=\"screen_text\"\r\n\r\n".data(using: .utf8)!)
                body.append(screenText.data(using: .utf8)!)
                body.append("\r\n".data(using: .utf8)!)
            }
            
            body.append("--\(boundary)--\r\n".data(using: .utf8)!)
            request.httpBody = body
            
            #if DEBUG
            DevLogger.shared.info("[AGENT_TASK] Sending refinement request for root task: \(rootTaskId)", context: "APIClient")
            #endif
            
            let (data, response) = try await URLSession.shared.data(for: request)
            
            if let httpResponse = response as? HTTPURLResponse {
                if httpResponse.statusCode == 200 {
                    let decoder = JSONDecoder()
                    let refinementResponse = try decoder.decode(AgentTaskRefinementResponse.self, from: data)
                    
                    #if DEBUG
                    DevLogger.shared.info("📥 AgentTask refinement processed successfully", context: "APIClient")
                    #endif
                    
                    return refinementResponse
                } else {
                    #if DEBUG
                    DevLogger.shared.error("❌ AgentTask refinement failed with status: \(httpResponse.statusCode)", context: "APIClient")
                    #endif
                    
                    return AgentTaskRefinementResponse(
                        success: false,
                        message: "Server error: \(httpResponse.statusCode)",
                        transcription: nil,
                        refinementAgentTaskId: nil,
                        rootTaskId: rootTaskId,
                        result: nil,
                        refinementIteration: nil,
                        processed: false
                    )
                }
            } else {
                return AgentTaskRefinementResponse(
                    success: false,
                    message: "Invalid response",
                    transcription: nil,
                    refinementAgentTaskId: nil,
                    rootTaskId: rootTaskId,
                    result: nil,
                    refinementIteration: nil,
                    processed: false
                )
            }
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ AgentTask refinement error: \(error.localizedDescription)", context: "APIClient")
            #endif
            
            return AgentTaskRefinementResponse(
                success: false,
                message: "Network error: \(error.localizedDescription)",
                transcription: nil,
                refinementAgentTaskId: nil,
                rootTaskId: rootTaskId,
                result: nil,
                refinementIteration: nil,
                processed: false
            )
        }
    }
}
