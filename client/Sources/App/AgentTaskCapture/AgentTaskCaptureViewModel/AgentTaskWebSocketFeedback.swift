import Foundation

extension AgentTaskCaptureViewModel {
    func setupWebSocketSubscription() {
        webSocketService.eventSubject
            .sink { [weak self] event in
                Task { @MainActor in
                    self?.handleWebSocketEvent(event)
                }
            }
            .store(in: &cancellables)
    }

    func handleWebSocketEvent(_ event: WebSocketEvent) {
        switch event {
        case .agentTaskWordDetected(let data):
            handleWordDetected(data)
        case .agentTaskSilenceProgress(let data):
            handleSilenceProgress(data)
        case .agentTaskCaptureComplete(let data):
            handleCaptureComplete(data)
        default:
            break
        }
    }

    func handleWordDetected(_ data: [String: Any]) {
        guard let eventData = data["data"] as? [String: Any],
              let words = eventData["words"] as? [String] else { return }

        // Update the detected words. The silence countdown is not touched here: words are transcribed a little behind the speaker, so a word can arrive during a countdown for a later pause, and only the backend's own "counting" signal says whether the speaker resumed.
        self.wordsDetected = Array(words.suffix(5)) // Keep last 5 words for display
        self.lastWordTime = Date()

        // Show we're hearing words, unless a countdown is already showing its own status
        if !silenceDetectionActive {
            statusMessage = "Listening... \(words.suffix(3).joined(separator: " "))"
        }

        #if DEBUG
        DevLogger.shared.info("🗣️ Words detected: \(words.joined(separator: " "))", context: "AgentTaskCapture")
        #endif
    }

    func handleSilenceProgress(_ data: [String: Any]) {
        guard let eventData = data["data"] as? [String: Any],
              let remainingTime = eventData["remaining_time"] as? Double else { return }

        // The backend reports counting == false the moment the speaker resumes, because the countdown it was running no longer applies. Without this the ring would stay up until the next transcribed word arrived, which can be seconds later.
        if (eventData["counting"] as? Bool) == false {
            self.silenceDetectionActive = false
            self.silenceRemaining = 0.0
            statusMessage = "Listening..."
            return
        }

        self.silenceDetectionActive = true
        self.silenceRemaining = remainingTime

        // Update status message to show countdown. Nothing is being processed yet: the request is still being listened to until the countdown ends.
        if remainingTime > 1.0 {
            statusMessage = "Finishing in \(Int(ceil(remainingTime)))s..."
        } else {
            statusMessage = "Finishing..."
        }

        #if DEBUG
        DevLogger.shared.info("🤫 Silence progress: \(String(format: "%.1f", remainingTime))s remaining", context: "AgentTaskCapture")
        #endif
    }

    func handleCaptureComplete(_ data: [String: Any]) {
        guard let eventData = data["data"] as? [String: Any],
              let reason = eventData["reason"] as? String else { return }

        #if DEBUG
        DevLogger.shared.info("✅ Intelligent capture completed: \(reason)", context: "AgentTaskCapture")
        #endif

        // Complete the capture with the intelligent detection reason
        statusMessage = "Processing request..."
        completeCapture()
    }
}
