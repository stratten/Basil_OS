import Foundation

// MARK: - Capture controls: pause/resume, cancel, and the live-transcription toggle
extension LiveTranscriptionViewModel {
    static let recordOnlyIdleStatusMessage = "Ready to record (live transcription off)"
    static let liveTranscriptionUnavailableStatus = "live_transcription_unavailable"
    static let recordingOnlyStatus = "recording_only"

    nonisolated static func streamClockMarkerMessage(elapsedSeconds: TimeInterval) -> String {
        String(format: "{\"type\":\"native_stream_clock\",\"elapsed_seconds\":%.4f}", max(0, elapsedSeconds))
    }

    nonisolated static func captureStateControlMessage(paused: Bool) -> String {
        "{\"type\":\"native_capture_state\",\"paused\":\(paused ? "true" : "false")}"
    }

    nonisolated static func liveTranscriptionControlMessage(enabled: Bool) -> String {
        "{\"type\":\"native_live_transcription\",\"enabled\":\(enabled ? "true" : "false")}"
    }

    func recordingStatusMessage() -> String {
        if isCapturePaused {
            return "Paused"
        }
        return sessionLiveTranscriptionEnabled ? "Recording and transcribing..." : "Recording (live transcription off)"
    }

    func sendControlToActiveSockets(_ text: String) {
        for socket in [microphoneWebSocketTask, systemAudioWebSocketTask].compactMap({ $0 }) {
            socket.send(.string(text)) { error in
                #if DEBUG
                if let error {
                    DevLogger.shared.warning("Failed to send capture control \(text): \(error)", context: "LiveTranscriptionViewModel")
                }
                #endif
            }
        }
    }

    // MARK: Pause and resume

    /// Stops capturing audio without ending the recording part; nothing is post-processed until the meeting is ended.
    func pauseCapture() {
        guard isRecording, !isCapturePaused, connectionState == .recording else { return }
        recordingClock.pause()
        isCapturePaused = true
        stopMicrophoneAudioEngine()
        updateMicrophoneAudioLevel(0.0)
        if #available(macOS 14.0, *) {
            suspendSystemAudioCapture()
        }
        sendControlToActiveSockets(Self.captureStateControlMessage(paused: true))
        statusMessage = recordingStatusMessage()
    }

    func resumeCapture() async {
        guard isRecording, isCapturePaused else { return }
        recordingClock.resume()
        isCapturePaused = false

        if microphoneWebSocketTask != nil {
            do {
                try await sendNativeStreamTimingControl(for: .microphone)
            } catch {
                recoverMicrophoneWebSocket(reason: "resume timing failed: \(error.localizedDescription)")
            }
        }
        if #available(macOS 14.0, *), systemAudioWebSocketTask != nil {
            do {
                try await sendNativeStreamTimingControl(for: .systemAudio)
            } catch {
                recoverSystemAudioWebSocket(reason: "resume timing failed: \(error.localizedDescription)")
            }
        }
        // The user can pause again or end the meeting while the timing controls are in flight.
        guard isRecording, !isCapturePaused else { return }
        sendControlToActiveSockets(Self.captureStateControlMessage(paused: false))

        var systemAudioResumeFailed = false
        if #available(macOS 14.0, *) {
            do {
                try resumeSystemAudioCapture()
            } catch {
                systemAudioResumeFailed = true
                DevLogger.shared.error("Failed to resume system audio capture: \(error)", context: "LiveTranscriptionViewModel")
            }
        }

        if enableMicrophone, audioEngine == nil, microphoneWebSocketTask != nil, microphoneInputRecoveryTask == nil {
            do {
                try setupAudioEngine()
            } catch {
                microphoneInputRecoveryState = .failed(message: error.localizedDescription)
                statusMessage = "Microphone unavailable. Retry microphone to continue capture."
                return
            }
        }
        statusMessage = systemAudioResumeFailed
            ? "System audio could not resume. Recording microphone only."
            : recordingStatusMessage()
    }

    // MARK: Cancel

    /// Discards the current recording part: stops capture without post-processing, deletes the part's audio and transcript on the backend, and removes the native system-audio backup files.
    func cancelActiveRecording() async {
        guard isRecording else { return }
        let meetingIds = [microphoneMeetingId, systemAudioMeetingId].compactMap { $0 }
        let resumedFrom = recordingMode == .resume ? resumedFromMeetingId : nil

        var backupDirectories: [URL] = []
        if #available(macOS 14.0, *) {
            let recorderFiles = [
                systemAudioState?.processTapRecorder?.fileURL,
                systemAudioState?.globalOutputRecorder?.fileURL
            ].compactMap { $0 }
            var candidateDirectories = recorderFiles.map { $0.deletingLastPathComponent() }
            if let pausedDirectory = systemAudioState?.pausedBackupDirectory {
                candidateDirectories.append(pausedDirectory)
            }
            for directory in candidateDirectories {
                // Only per-recording UUID folders under Documents/Basil/Recordings are removed.
                if directory.deletingLastPathComponent().lastPathComponent == "Recordings" {
                    backupDirectories.append(directory)
                }
            }
        }

        meetingMetadataSaveTask?.cancel()
        meetingMetadataSaveTask = nil
        stopRecording(runPostStopActions: false)
        hasRecordedAudio = false
        hasTranscription = false
        lastRetranscribeCheckpointByMeeting.removeAll()

        for directory in backupDirectories {
            do {
                try FileManager.default.removeItem(at: directory)
            } catch {
                DevLogger.shared.error("Failed to delete canceled system-audio backup \(directory.path): \(error)", context: "LiveTranscriptionViewModel")
            }
        }

        var failedDiscards = 0
        for meetingId in meetingIds {
            do {
                _ = try await APIClient.shared.discardMeetingRecording(id: meetingId)
            } catch {
                failedDiscards += 1
                DevLogger.shared.error("Failed to discard canceled recording \(meetingId): \(error)", context: "LiveTranscriptionViewModel")
            }
        }

        if let resumedFrom {
            await loadMeetingHistory()
            await selectMeeting(resumedFrom)
        } else {
            await startNewMeeting()
        }
        statusMessage = failedDiscards == 0
            ? "Recording canceled"
            : "Recording canceled, but some audio could not be deleted"
    }

    // MARK: Live transcription

    /// Switches live transcription for the current or next recording part; while recording, audio keeps flowing to the recording with no gap.
    func setSessionLiveTranscriptionEnabled(_ enabled: Bool) {
        liveTranscriptionSelectionTouched = true
        guard enabled != sessionLiveTranscriptionEnabled else { return }
        sessionLiveTranscriptionEnabled = enabled

        if isRecording {
            if !enabled {
                liveTranscriptionWasDisabledThisPart = true
            }
            sendControlToActiveSockets(Self.liveTranscriptionControlMessage(enabled: enabled))
            statusMessage = recordingStatusMessage()
            return
        }

        if enabled {
            if transcriptionState != .loadingModels {
                Task { await self.prepareLiveTranscriptionModels() }
            }
        } else {
            if transcriptionState == .loadingModels {
                transcriptionState = .idle
            }
            statusMessage = Self.recordOnlyIdleStatusMessage
        }
    }

    /// Applies the saved "live transcription by default" setting unless the user already chose for this meeting.
    func loadLiveTranscriptionDefault() async {
        let port = APIClient.shared.currentPort
        guard let url = URL(string: "http://localhost:\(port)/settings/transcription") else { return }
        guard let result = try? await URLSession.shared.data(from: url),
              let httpResponse = result.1 as? HTTPURLResponse,
              httpResponse.statusCode == 200,
              let decoded = try? JSONDecoder().decode(TranscriptionSettingsResponse.self, from: result.0) else {
            return
        }
        guard !liveTranscriptionSelectionTouched, !isRecording else { return }

        let enabled = decoded.settings.live_transcription_by_default
        let wasEnabled = sessionLiveTranscriptionEnabled
        sessionLiveTranscriptionEnabled = enabled
        if enabled {
            if !wasEnabled && transcriptionState != .loadingModels {
                Task { await self.prepareLiveTranscriptionModels() }
            }
        } else if transcriptionState != .loadingModels {
            statusMessage = Self.recordOnlyIdleStatusMessage
        }
    }

    func prepareLiveTranscriptionModels() async {
        transcriptionState = .loadingModels
        statusMessage = "Loading models..."
        await preinitializeBackendModels()
        if isRecording {
            statusMessage = recordingStatusMessage()
        } else if !sessionLiveTranscriptionEnabled {
            statusMessage = Self.recordOnlyIdleStatusMessage
        }
    }

    /// The backend could not start live transcription mid-recording; keep recording and fall back to transcribing after the meeting ends.
    func handleLiveTranscriptionUnavailable() {
        guard isRecording, sessionLiveTranscriptionEnabled else { return }
        sessionLiveTranscriptionEnabled = false
        liveTranscriptionWasDisabledThisPart = true
        sendControlToActiveSockets(Self.liveTranscriptionControlMessage(enabled: false))
        statusMessage = "Live transcription unavailable; recording continues"
    }
}
