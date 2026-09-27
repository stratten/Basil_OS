import Foundation

// MARK: - Error Handling
extension LiveTranscriptionViewModel {
    
    /// Handles errors during recording and WebSocket communication.
    /// `source` identifies which stream's socket failed (when known) so a drop
    /// mid-recording can be recovered for that one source instead of tearing
    /// down both streams. It is nil for non-socket errors (e.g. audio engine).
    func handleError(_ error: Error, source: AudioSource? = nil) {
        #if DEBUG
        DevLogger.shared.error("LiveTranscription error: \(error.localizedDescription)", context: "LiveTranscriptionViewModel")
        #endif
        
        // Only stop recording for fatal errors, not temporary network issues
        let errorString = error.localizedDescription
        let normalizedError = errorString.lowercased()
        let isExpectedShutdownError =
            normalizedError.contains("socket is not connected") ||
            normalizedError.contains("operation canceled") ||
            normalizedError.contains("operation cancelled") ||
            normalizedError.contains("cancelled") ||
            normalizedError.contains("normal closure") ||
            normalizedError.contains("going away")
        let isFatalError = errorString.contains("not found") || 
                          errorString.contains("service unavailable") ||
                          errorString.contains("bad request") ||
                          errorString.contains("forbidden") ||
                          errorString.contains("authentication")
        
        // Less severe errors like "Operation canceled" might be temporary
        let isTemporaryError = errorString.contains("Operation canceled") ||
                              errorString.contains("network connection") ||
                              errorString.contains("timed out")

        // A socket that dies while we are actively recording is recoverable: the
        // server may have closed it (e.g. a 1011 keepalive timeout) or the
        // connection dropped. We reconnect just the affected source rather than
        // treating it as an expected post-stop shutdown.
        let isRecoverableSocketDrop =
            normalizedError.contains("socket is not connected") ||
            normalizedError.contains("connection reset") ||
            normalizedError.contains("connection abort") ||
            normalizedError.contains("network connection was lost") ||
            isTemporaryError

        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }

            if isExpectedShutdownError && (!self.isRecording || self.connectionState == .ready) {
                #if DEBUG
                DevLogger.shared.info("Ignoring expected WebSocket shutdown error after stop: \(errorString)", context: "LiveTranscriptionViewModel")
                #endif
                return
            }

            // Active recording + a known failed source: reconnect ONLY that
            // source (debounced inside the recover* helpers) so the sibling
            // stream keeps running uninterrupted.
            if self.isRecording, let source, isRecoverableSocketDrop {
                #if DEBUG
                DevLogger.shared.warning("Recoverable \(source) socket drop while recording, reconnecting that source: \(errorString)", context: "LiveTranscriptionViewModel")
                #endif
                switch source {
                case .microphone:
                    self.recoverMicrophoneWebSocket(reason: errorString)
                case .systemAudio:
                    // System-audio capture (and its recovery) require macOS 14+.
                    if #available(macOS 14.0, *) {
                        self.recoverSystemAudioWebSocket(reason: errorString)
                    }
                }
                return
            }
            
            if isTemporaryError {
                // Route unattributed temporary errors through the same
                // per-source, in-flight-guarded recovery paths used for
                // attributed socket drops (recoverMicrophoneWebSocket /
                // recoverSystemAudioWebSocket) instead of running a separate
                // combined reconnect here. This branch previously drove its
                // own reconnect against the shared `microphoneReconnectAttempt`
                // counter with no in-flight guard, so it could fire while a
                // per-source recovery was already in progress, double-spend
                // the shared 6-attempt retry budget, and trip `stopRecording()`
                // (ending the meeting and starting post-processing) after only
                // a couple of real network blips instead of six.
                #if DEBUG
                DevLogger.shared.warning("Unattributed temporary WebSocket error, deferring to per-source recovery: \(errorString)", context: "LiveTranscriptionViewModel")
                #endif
                self.statusMessage = "Connection issue, attempting to reconnect..."
                self.connectionState = .connecting
                if self.enableMicrophone {
                    self.recoverMicrophoneWebSocket(reason: errorString)
                }
                if #available(macOS 14.0, *), self.isSystemAudioCaptureActive {
                    self.recoverSystemAudioWebSocket(reason: errorString)
                }
            } else if isFatalError {
                // Fatal error, stop recording
                self.statusMessage = "Error: \(errorString)"
                self.connectionState = .error
                self.stopRecording()
            } else {
                // Other errors - just update status but keep recording
                self.statusMessage = "Warning: \(errorString)"
            }
        }
    }
}

