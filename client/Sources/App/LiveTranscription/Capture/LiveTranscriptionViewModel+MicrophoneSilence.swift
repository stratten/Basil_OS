import Foundation

// MARK: - Silent microphone reclaim
extension LiveTranscriptionViewModel {
    /// Applies the silent-input policy once per watchdog tick. Returns true when it rebuilt the microphone engine, so the caller skips the rest of this tick.
    ///
    /// A call app such as WhatsApp can hold the built-in microphone with voice processing, after which macOS keeps calling this recorder's tap on schedule but fills every buffer with zeros. The stall watchdog never sees that, so this check looks at the samples themselves: it rebuilds the microphone engine to try to take the input back, and warns once several rebuilds have not helped.
    @discardableResult
    func evaluateMicrophoneSilence() -> Bool {
        guard let silentFor = microphoneSilenceTracker.silenceDuration() else {
            // Not silent right now. Only real audio from the current engine proves the input is back; a freshly rebuilt engine that has not delivered a buffer yet proves nothing, so it leaves the warning as it is.
            if microphoneSilenceTracker.hasHeardSignalSinceArming {
                microphoneSilenceReclaimAttempts = 0
                if isMicrophoneSilent { isMicrophoneSilent = false }
            }
            return false
        }

        // The warning stays up through the slow retries that follow it, and clears only when signal returns, so it cannot flicker off while a rebuilt engine waits for its first silent buffer.
        if microphoneSilencePolicy.shouldWarn(silentFor: silentFor, attempts: microphoneSilenceReclaimAttempts), !isMicrophoneSilent {
            isMicrophoneSilent = true
        }

        guard microphoneSilencePolicy.action(silentFor: silentFor, attempts: microphoneSilenceReclaimAttempts) == .reclaim else {
            return false
        }
        reclaimSilentMicrophone(silentFor: silentFor)
        return true
    }

    /// Rebuilds only the microphone engine. The microphone socket, the system-audio capture, and the recording clock are left alone, so the transcript timeline is not disturbed; the rebuilt engine simply resumes sending on the same socket.
    private func reclaimSilentMicrophone(silentFor: TimeInterval) {
        microphoneSilenceReclaimAttempts += 1
        let attempts = microphoneSilenceReclaimAttempts
        let wasWarning = isMicrophoneSilent
        #if DEBUG
        DevLogger.shared.warning("[AUDIO ENGINE] Microphone delivered only silence for \(String(format: "%.1f", silentFor))s; rebuilding the input (attempt \(attempts))", context: "LiveTranscriptionViewModel")
        #endif

        // Stopping the engine clears the silence state, because a stop normally means a pause or a new device. This is a retry of the same situation, so carry the counters across it.
        stopMicrophoneAudioEngine()
        microphoneSilenceReclaimAttempts = attempts
        isMicrophoneSilent = wasWarning

        do {
            try setupAudioEngine()
        } catch {
            #if DEBUG
            DevLogger.shared.error("[AUDIO ENGINE] Rebuilding the silent microphone failed: \(error); falling back to full recovery", context: "LiveTranscriptionViewModel")
            #endif
            retryMicrophoneCaptureAfterDeviceChange()
        }
    }
}
