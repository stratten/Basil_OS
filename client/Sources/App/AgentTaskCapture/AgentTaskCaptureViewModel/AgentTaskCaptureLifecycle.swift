import Combine
import Foundation
import SwiftUI

extension AgentTaskCaptureViewModel {
    func startCapture() {
        // Consume the one-shot initial modality preference. Subsequent calls
        // (e.g. from `enterVoiceMode()`) always take the normal audio path.
        let initialModality = pendingInitialModality
        pendingInitialModality = .voice

        if initialModality == .text {
            #if DEBUG
            DevLogger.shared.info("Starting agentTask capture in TEXT modality (per user preference)", context: "AgentTaskCapture")
            #endif
            startInTextEntryMode()
            return
        }

        #if DEBUG
        DevLogger.shared.info("Starting agentTask capture", context: "AgentTaskCapture")
        #endif

        if let blockingOwner = AudioCaptureService.blockingRecordingOwners().first {
            statusMessage = "Microphone in use by \(blockingOwner). Switch to text entry or finish that recording."
            hasCompleted = false
            return
        }

        isCapturing = true
        remainingSeconds = totalDuration
        progressPercentage = 1.0
        startTime = Date()
        hasCompleted = false
        statusMessage = "Listening for request..."

        // Notify HotkeyService to enable escape key handling
        NotificationCenter.default.post(
            name: Notification.Name("RecordingStateChanged"),
            object: nil,
            userInfo: ["isRecording": true, "source": "agentTask"]
        )

        // Reset real-time feedback properties
        wordsDetected = []
        lastWordTime = nil
        silenceDetectionActive = false
        silenceRemaining = 0.0

        if useIntelligentCapture {
            statusMessage = "Say what you need."
        } else {
            statusMessage = "Listening for request..."
            startTimer()
        }

        // Start real audio capture for audio level monitoring
        Task {
            do {
                try await audioCaptureService.startRecording(flowContext: "agentTask")
                #if DEBUG
                DevLogger.shared.info("Audio capture started for agentTask level monitoring", context: "AgentTaskCapture")
                #endif
            } catch {
                #if DEBUG
                DevLogger.shared.error("Failed to start audio capture: \(error)", context: "AgentTaskCapture")
                #endif
                await MainActor.run {
                    if case let AudioCaptureError.configurationFailed(message) = error,
                       message.hasPrefix("Microphone is already in use") {
                        stopCapture(shouldProcessAudio: false)
                        statusMessage = "\(message) Switch to text entry or finish that recording."
                        hasCompleted = false
                        return
                    }
                    statusMessage = "Microphone error"
                    cancelCapture()
                }
            }
        }
    }

    func cancelCapture() {
        guard !hasCompleted else { return } // Prevent multiple calls
        hasCompleted = true

        #if DEBUG
        DevLogger.shared.info("Canceling agentTask capture", context: "AgentTaskCapture")
        #endif
        // Stop this widget's in-progress capture without canceling any
        // already-running agent execution. Voice-initiated captures also have
        // backend streaming state that must be stopped explicitly.

        // Stop capture WITHOUT processing/submitting audio
        stopCapture(shouldProcessAudio: false)
        Task {
            await notifyBackendCaptureCanceled()
        }
        statusMessage = "Canceled"
        onCaptureCanceled?()
    }

    func completeCapture() {
        guard !hasCompleted else { return } // Prevent multiple calls
        hasCompleted = true

        #if DEBUG
        DevLogger.shared.info("Completing agentTask capture", context: "AgentTaskCapture")
        #endif

        // Stop capture AND process/submit the audio
        stopCapture(shouldProcessAudio: true)
        statusMessage = "Processing AgentTask..."
        onCaptureComplete?()
    }

    func startTimer() {
        timerCancellable = Timer.publish(every: 0.1, on: .main, in: .common)
            .autoconnect()
            .sink { [weak self] _ in
                self?.updateTimer()
            }
    }

    func updateTimer() {
        guard let startTime = startTime, isCapturing else { return }

        let elapsed = Date().timeIntervalSince(startTime)
        let remaining = max(0, Double(totalDuration) - elapsed)

        remainingSeconds = Int(ceil(remaining))
        progressPercentage = CGFloat(remaining / Double(totalDuration))

        if remaining <= 0 {
            // Time's up - complete capture
            completeCapture()
        } else if remaining <= 3 {
            statusMessage = "Finishing up..."
        }
    }

    func stopCapture(shouldProcessAudio: Bool) {
        isCapturing = false
        timerCancellable?.cancel()
        timerCancellable = nil
        audioLevel = 0.0

        // Notify HotkeyService to disable escape key handling
        NotificationCenter.default.post(
            name: Notification.Name("RecordingStateChanged"),
            object: nil,
            userInfo: ["isRecording": false, "source": "agentTask"]
        )

        // Stop audio capture
        audioCaptureService.stopRecording(sendAudioData: false, flowContext: "agentTask")

        // Only process final audio if not canceled
        if shouldProcessAudio {
            Task {
                // Wait briefly for recording to complete, then get final audio data
                try? await Task.sleep(nanoseconds: 100_000_000) // 100ms

                guard let finalAudioData = audioCaptureService.lastRecordingData, !finalAudioData.isEmpty else {
                    #if DEBUG
                    DevLogger.shared.warning("[AGENT_TASK] No final audio data available after wake word capture", context: "AgentTaskCapture")
                    #endif
                    return
                }

                await processFinalAgentTaskAudio(audioData: finalAudioData)
            }
        } else {
            #if DEBUG
            DevLogger.shared.info("Audio capture stopped - skipping audio processing (canceled)", context: "AgentTaskCapture")
            #endif
        }

        #if DEBUG
        DevLogger.shared.info("Audio capture stopped", context: "AgentTaskCapture")
        #endif
    }

    func notifyBackendCaptureCanceled() async {
        let payload: [String: Any] = ["reason": "client_cancel"]

        do {
            let body = try JSONSerialization.data(withJSONObject: payload)
            _ = try await APIClient.shared.post(
                "/api/v1/voice-listener/stop-agent-task-capture",
                body: body,
                timeout: 10
            )
            #if DEBUG
            DevLogger.shared.info("[AGENT_TASK] Backend AgentTask capture stop notified after cancel", context: "AgentTaskCapture")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.warning("[AGENT_TASK] Failed to notify backend capture stop after cancel: \(error)", context: "AgentTaskCapture")
            #endif
        }
    }
}
