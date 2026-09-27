import Foundation

extension AgentTaskCaptureViewModel {
    /// Internal helper: opens the widget directly in text-entry mode without ever
    /// arming the microphone. Used when the user's default-input-modality preference
    /// is `.text`. Mirrors the visible state changes of `enterTextEntryMode()` minus
    /// the audio-stop side effects.
    func startInTextEntryMode() {
        isCapturing = false
        hasCompleted = false
        timerCancellable?.cancel()
        timerCancellable = nil

        // Reset feedback state so the next voice re-arm starts clean.
        wordsDetected = []
        lastWordTime = nil
        silenceDetectionActive = false
        silenceRemaining = 0.0
        audioLevel = 0.0
        progressPercentage = 1.0
        remainingSeconds = totalDuration

        isTextEntryMode = true
        textPrompt = ""
        isSubmittingTextPrompt = false
        statusMessage = "Type your request"

        // Match the size used by `enterTextEntryMode()` so the panel opens at the
        // correct text-mode dimensions and keeps reference content unclipped.
        requestCapturePanelResizeForCurrentState()
    }

    /// Switches from audio capture mode to text entry mode
    func enterTextEntryMode() {
        #if DEBUG
        DevLogger.shared.info("Entering text entry mode for agentTask", context: "AgentTaskCapture")
        #endif

        // Always stop the audio engine — isCapturing may already be false
        // in hotkey mode where the backend capture completes early
        isCapturing = false
        timerCancellable?.cancel()
        timerCancellable = nil
        audioCaptureService.stopRecording(sendAudioData: false, flowContext: "agentTask")

        NotificationCenter.default.post(
            name: Notification.Name("RecordingStateChanged"),
            object: nil,
            userInfo: ["isRecording": false, "source": "agentTask"]
        )

        // Clear any audio data since we're switching to text
        // The context (screenshot, app info) is retained

        isTextEntryMode = true
        textPrompt = ""
        statusMessage = "Type your request"

        // Request window resize for text entry mode with extra breathing room and
        // enough height for any existing reference rows.
        requestCapturePanelResizeForCurrentState()
    }

    /// Switches from text entry mode back to audio capture mode and re-arms the mic.
    /// Symmetric counterpart to `enterTextEntryMode()`.
    func enterVoiceMode() {
        guard isTextEntryMode else { return }

        #if DEBUG
        DevLogger.shared.info("Entering voice mode for agentTask (from text entry)", context: "AgentTaskCapture")
        #endif

        // Leave text mode and clear text-entry state.
        isTextEntryMode = false
        textPrompt = ""
        isSubmittingTextPrompt = false

        // Reset feedback / progress state so the new audio capture starts clean.
        wordsDetected = []
        lastWordTime = nil
        silenceDetectionActive = false
        silenceRemaining = 0.0
        audioLevel = 0.0
        progressPercentage = 1.0
        remainingSeconds = totalDuration

        // Resize panel back to voice-mode dimensions, accounting for any retained
        // reference rows so the rounded widget does not clip.
        requestCapturePanelResizeForCurrentState()

        // Re-arm the audio capture pipeline. `startCapture()` resets `hasCompleted`
        // and re-posts the `RecordingStateChanged` notification.
        startCapture()
    }

    /// Submits the text AgentTask to the backend. `modelId` is optional and,
    /// when present, is forwarded as `model_id` in the request payload —
    /// added for the new capture-input model picker
    /// (see AgentTaskCaptureInput_Migration/02_Prior_Art_Manifest.md section 2.7).
    /// Existing SwiftUI call sites that call `submitTextPrompt()` with no
    /// argument are unaffected by the default value.
    func submitTextPrompt(modelId: String? = nil) async {
        let agentTaskText = textPrompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !agentTaskText.isEmpty else {
            #if DEBUG
            DevLogger.shared.warning("Cannot submit empty text request", context: "AgentTaskCapture")
            #endif
            return
        }

        #if DEBUG
        DevLogger.shared.info("Submitting text AgentTask: '\(agentTaskText.prefix(50))...'", context: "AgentTaskCapture")
        #endif

        isSubmittingTextPrompt = true
        statusMessage = "Processing request..."

        do {
            // Build the request payload
            var payload: [String: Any] = ["agent_task": agentTaskText]

            // Include pre-generated agent_task_id for multi-agent routing
            if let agentTaskId = preGeneratedAgentTaskId {
                payload["agent_task_id"] = agentTaskId
                #if DEBUG
                DevLogger.shared.info("Including pre-generated agent_task_id: \(agentTaskId)", context: "AgentTaskCapture")
                #endif
            }

            if let rootId = rootTaskId {
                payload["root_task_id"] = rootId
            }
            if let previousId = previousTaskId {
                payload["previous_task_id"] = previousId
            }

            // Include reference_paths for dropped files/folders
            if !referencePaths.isEmpty {
                payload["reference_paths"] = referencePaths.map { $0.path }
                #if DEBUG
                DevLogger.shared.info("Including \(referencePaths.count) reference paths in text request", context: "AgentTaskCapture")
                #endif
            }

            if let modelId, !modelId.isEmpty {
                payload["model_id"] = modelId
                #if DEBUG
                DevLogger.shared.info("Including model_id override: \(modelId)", context: "AgentTaskCapture")
                #endif
            }

            let jsonData = try JSONSerialization.data(withJSONObject: payload)

            // POST to /process-prompt endpoint
            let apiBase = APIClient.shared.baseURL
            guard let url = URL(string: "\(apiBase)/api/v1/agent-tasks/process") else {
                throw NSError(domain: BasilTeamIdentity.agentTask.displayName, code: 400, userInfo: [NSLocalizedDescriptionKey: "Invalid API URL"])
            }

            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = jsonData

            // Fire-and-forget: send the request in the background, transition immediately
            // The result widget will pick up progress via WebSocket events
            Task.detached {
                do {
                    let (data, response) = try await URLSession.shared.data(for: request)
                    if let httpResponse = response as? HTTPURLResponse, !(200...299).contains(httpResponse.statusCode) {
                        #if DEBUG
                        await MainActor.run {
                            DevLogger.shared.error("Text request API error: HTTP \(httpResponse.statusCode)", context: "AgentTaskCapture")
                        }
                        #endif
                    } else {
                        #if DEBUG
                        if let responseString = String(data: data, encoding: .utf8) {
                            await MainActor.run {
                                DevLogger.shared.info("Text request response: \(responseString.prefix(200))...", context: "AgentTaskCapture")
                            }
                        }
                        #endif
                    }
                } catch {
                    #if DEBUG
                    await MainActor.run {
                        DevLogger.shared.error("Text request background request failed: \(error)", context: "AgentTaskCapture")
                    }
                    #endif
                }
            }

            // Transition to result widget immediately
            await MainActor.run {
                isSubmittingTextPrompt = false
                statusMessage = "Request submitted"
                hasCompleted = true
                onCaptureComplete?()
            }

        } catch {
            #if DEBUG
            DevLogger.shared.error("Failed to submit text request: \(error)", context: "AgentTaskCapture")
            #endif

            await MainActor.run {
                isSubmittingTextPrompt = false
                statusMessage = "Error: \(error.localizedDescription)"
            }
        }
    }
}
