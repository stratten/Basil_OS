import Foundation

extension AgentTaskCaptureViewModel {
    @MainActor
    func processFinalAgentTaskAudio(audioData: Data) async {
        do {
            #if DEBUG
            DevLogger.shared.info("[AGENT_TASK] Processing final audio from wake word flow (\(audioData.count) bytes)", context: "AgentTaskCapture")
            #endif

            let apiBase = APIClient.shared.baseURL
            guard let url = URL(string: "\(apiBase)/api/v1/agent-tasks/process-audio") else {
                throw NSError(domain: BasilTeamIdentity.agentTask.displayName, code: 400,
                              userInfo: [NSLocalizedDescriptionKey: "Invalid agentTask processing API URL"])
            }

            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.timeoutInterval = 30.0

            // Use multipart form data (same as hotkey flow)
            let boundary = "Boundary-\(UUID().uuidString)"
            request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

            var body = Data()
            let filename = "agentTask.wav"
            let mimetype = "audio/wav"

            // Add audio file
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"audio_file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
            body.append("Content-Type: \(mimetype)\r\n\r\n".data(using: .utf8)!)
            body.append(audioData)
            body.append("\r\n".data(using: .utf8)!)

            // Add pre-generated agent_task_id if provided (for new AgentTasks started from result widget)
            if let preGenId = preGeneratedAgentTaskId {
                body.append("--\(boundary)\r\n".data(using: .utf8)!)
                body.append("Content-Disposition: form-data; name=\"agent_task_id\"\r\n\r\n".data(using: .utf8)!)
                body.append("\(preGenId)".data(using: .utf8)!)
                body.append("\r\n".data(using: .utf8)!)

                #if DEBUG
                DevLogger.shared.info("[AGENT_TASK] 🆔 Including pre-generated agent_task_id in request: \(preGenId)", context: "AgentTaskCapture")
                #endif
            }

            if let rootId = rootTaskId {
                body.append("--\(boundary)\r\n".data(using: .utf8)!)
                body.append("Content-Disposition: form-data; name=\"root_task_id\"\r\n\r\n".data(using: .utf8)!)
                body.append("\(rootId)".data(using: .utf8)!)
                body.append("\r\n".data(using: .utf8)!)
            }
            if let previousId = previousTaskId {
                body.append("--\(boundary)\r\n".data(using: .utf8)!)
                body.append("Content-Disposition: form-data; name=\"previous_task_id\"\r\n\r\n".data(using: .utf8)!)
                body.append("\(previousId)".data(using: .utf8)!)
                body.append("\r\n".data(using: .utf8)!)
            }

            if let modelId = selectedAgentTaskModelId, !modelId.isEmpty {
                body.append("--\(boundary)\r\n".data(using: .utf8)!)
                body.append("Content-Disposition: form-data; name=\"model_id\"\r\n\r\n".data(using: .utf8)!)
                body.append(modelId.data(using: .utf8)!)
                body.append("\r\n".data(using: .utf8)!)

                #if DEBUG
                DevLogger.shared.info("[AGENT_TASK] Including model_id override in audio request: \(modelId)", context: "AgentTaskCapture")
                #endif
            }

            // Add reference_paths if any files/folders were dropped onto the widget
            if !referencePaths.isEmpty {
                if let pathsJson = try? JSONSerialization.data(withJSONObject: referencePaths.map { $0.path }) {
                    body.append("--\(boundary)\r\n".data(using: .utf8)!)
                    body.append("Content-Disposition: form-data; name=\"reference_paths\"\r\n\r\n".data(using: .utf8)!)
                    body.append(pathsJson)
                    body.append("\r\n".data(using: .utf8)!)

                    #if DEBUG
                    DevLogger.shared.info("[AGENT_TASK] 📂 Including \(referencePaths.count) reference paths in audio request", context: "AgentTaskCapture")
                    #endif
                }
            }

            body.append("--\(boundary)--\r\n".data(using: .utf8)!)

            request.httpBody = body

            let (data, response) = try await URLSession.shared.data(for: request)

            if let httpResponse = response as? HTTPURLResponse, !(200...299).contains(httpResponse.statusCode) {
                // Non-2xx = no agent task will ever be persisted for the
                // provisional ID we handed off to the result widget. Notify
                // listeners (e.g. AgentTaskResultWidgetController) so the
                // transient row can be cleared and the result widget stops
                // polling an ID the backend doesn't know about.
                postProvisionalFailureNotification(
                    reason: "http_error",
                    message: "Task processing API error: HTTP \(httpResponse.statusCode)"
                )
                throw NSError(domain: BasilTeamIdentity.agentTask.displayName, code: httpResponse.statusCode,
                              userInfo: [NSLocalizedDescriptionKey: "Task processing API error: HTTP \(httpResponse.statusCode)"])
            }

            // Parse response for both logging and provisional-failure handling.
            // The backend signals "no speech / no task created" by returning
            // success=false / processed=false in the JSON body. Without this
            // check the result widget keeps the provisional row in
            // "Processing..." forever and polls an ID that 404s on every
            // request (the ghost-task / 404-storm pattern from the logs).
            if let responseJson = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                #if DEBUG
                DevLogger.shared.info("[AGENT_TASK] ✅ Wake word agentTask processing response: \(responseJson)", context: "AgentTaskCapture")
                #endif

                let success = (responseJson["success"] as? Bool) ?? true
                let processed = (responseJson["processed"] as? Bool) ?? true
                if !success || !processed {
                    let backendMessage = (responseJson["message"] as? String)
                        ?? "Audio could not be processed."
                    let reason: String
                    if backendMessage.lowercased().contains("no speech") {
                        reason = "no_speech"
                    } else if backendMessage.lowercased().contains("cancel") {
                        reason = "canceled"
                    } else {
                        reason = "backend_failure"
                    }
                    postProvisionalFailureNotification(reason: reason, message: backendMessage)
                }
            }

        } catch {
            #if DEBUG
            DevLogger.shared.error("[AGENT_TASK] ❌ Failed to process wake word agentTask audio: \(error)", context: "AgentTaskCapture")
            #endif
            // Network / serialization failure also leaves a provisional row
            // hanging on the result widget; clear it explicitly.
            postProvisionalFailureNotification(
                reason: "network_error",
                message: "Failed to deliver audio to backend: \(error.localizedDescription)"
            )
        }
    }

    /// Notify the result-widget controller that the provisional agent task ID
    /// we handed off at capture-start will never get a backend record. The
    /// controller forwards this to the React store so the transient row is
    /// removed (or marked as failed) instead of polling forever.
    func postProvisionalFailureNotification(reason: String, message: String) {
        guard let agentTaskId = preGeneratedAgentTaskId, !agentTaskId.isEmpty else { return }
        var userInfo: [String: Any] = [
            "agentTaskId": agentTaskId,
            "reason": reason,
            "message": message,
        ]
        if let rootId = rootTaskId { userInfo["rootTaskId"] = rootId }
        if let prevId = previousTaskId { userInfo["previousTaskId"] = prevId }
        NotificationCenter.default.post(
            name: Notification.Name("AgentTaskProvisionalFailed"),
            object: nil,
            userInfo: userInfo
        )
        #if DEBUG
        DevLogger.shared.info(
            "[AGENT_TASK] 🚫 Posted AgentTaskProvisionalFailed for \(agentTaskId) (reason=\(reason))",
            context: "AgentTaskCapture"
        )
        #endif
    }
}
