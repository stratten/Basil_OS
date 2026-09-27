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

        // Update the detected words and reset silence detection
        self.wordsDetected = Array(words.suffix(5)) // Keep last 5 words for display
        self.lastWordTime = Date()
        self.silenceDetectionActive = false
        self.silenceRemaining = 0.0

        // Update status message to show we're hearing words
        statusMessage = "Listening... \(words.suffix(3).joined(separator: " "))"

        #if DEBUG
        DevLogger.shared.info("🗣️ Words detected: \(words.joined(separator: " "))", context: "AgentTaskCapture")
        #endif
    }

    func handleSilenceProgress(_ data: [String: Any]) {
        guard let eventData = data["data"] as? [String: Any],
              let remainingTime = eventData["remaining_time"] as? Double else { return }

        self.silenceDetectionActive = true
        self.silenceRemaining = remainingTime

        // Update status message to show countdown
        if remainingTime > 1.0 {
            statusMessage = "Finishing in \(Int(ceil(remainingTime)))s..."
        } else {
            statusMessage = "Processing..."
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
