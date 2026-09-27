import SwiftUI
import Combine

extension TranscriptionWidgetViewModel {
    func copyToClipboard() {
        NSPasteboard.general.clearContents()
        let trimmed = transcriptionText.trimmingCharacters(in: .whitespacesAndNewlines)
        let rules = APIClient.shared.getCachedTranscriptionSettings().textReplacements
        let normalized = TranscriptionOutputTextNormalizer.apply(trimmed, rules: rules)
        let toPaste = normalized.isEmpty ? "" : normalized + " "
        NSPasteboard.general.setString(toPaste, forType: .string)
    }

    func clearTranscription() {
        #if DEBUG
        DevLogger.shared.info("Clearing transcription - Current state: recording=\(isRecording), processing=\(isProcessingRecording)", context: "text_state")
        #endif
        if isRecording {
            transcriptionText = "Recording in progress..."
        } else if isProcessingRecording {
            transcriptionText = "Processing transcription..."
        } else {
            transcriptionText = "Ready to record"
        }
        error = nil
        #if DEBUG
        DevLogger.shared.info("Transcription cleared, new text: \"\(transcriptionText)\"", context: "text_state")
        #endif
    }

    func cleanup() {
        if recordingLifecycle == .starting {
            cancelRecordingStartup()
        }
        if preventRecordingStop && isRecording {
            #if DEBUG
            DevLogger.shared.info("Cleanup limited due to UI transition", context: "TranscriptionWidget")
            #endif
            cancellables.removeAll()
            return
        }
        #if DEBUG
        DevLogger.shared.info("Cleaning up TranscriptionWidgetViewModel", context: "TranscriptionWidget")
        #endif
        if isRecording {
            #if DEBUG
            DevLogger.shared.info("Stopping active recording during cleanup", context: "TranscriptionWidget")
            #endif
            stopRecording()
        }
        cancellables.removeAll()
        isConnected = false
        isModelReady = false
        isModelLoading = false
        transitionRecordingLifecycle(to: .idle)
        error = nil
        pulseScale = 1.0
        updateAudioLevel(0.0)
        transcriptionText = "Initializing transcription service..."
        if timerCancellable != nil {
            timerCancellable?.cancel()
            timerCancellable = nil
        }
        #if DEBUG
        DevLogger.shared.info("TranscriptionWidgetViewModel cleaned up", context: "TranscriptionWidget")
        #endif
    }

    func startRecordingTimer() {
        elapsedSeconds = 0
        timerCancellable = Timer.publish(every: 1.0, on: .main, in: .common)
            .autoconnect()
            .sink { [weak self] _ in
                guard let self = self else { return }
                self.elapsedSeconds += 1
            }
    }

    func stopRecordingTimer() {
        timerCancellable?.cancel()
        timerCancellable = nil
    }

    func toggleMinimizedState() {
        preventRecordingStop = true
        let currentTimerValue = elapsedSeconds
        isMinimized.toggle()
        elapsedSeconds = currentTimerValue
        NotificationCenter.default.post(
            name: NSNotification.Name("MinimizedStateChanged"),
            object: nil,
            userInfo: ["isMinimized": isMinimized]
        )
        Task {
            try? await APIClient.shared.updateTranscriptionWidgetMinimizedState(isMinimized)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            self.preventRecordingStop = false
        }
    }

    func saveMinimizedState() {
        // This is now handled directly in toggleMinimizedState for better synchronization
    }
}

