import Foundation

// MARK: - Recording Session Preparation
//
// Centralizes the "what identity does the next recording use" decision so the
// start path, the WebSocket builders, and the resume UI all rely on one place.
// This prevents a Stop -> Start sequence (or stale history selection) from
// reusing a prior meeting id, which the backend would treat as an overwrite.
extension LiveTranscriptionViewModel {
    
    /// Reset all per-recording identity and transcript state so the next
    /// `startRecording()` always creates a brand-new meeting.
    ///
    /// Clearing the meeting ids forces the WebSocket builders to mint fresh ids,
    /// guaranteeing a new `~/.basil/meetings/<id>` directory rather than writing
    /// over an existing recording's audio/transcript.
    func prepareFreshRecordingSession() {
        recordingMode = .fresh
        resumeTimelineOffsetSeconds = 0.0
        recordingPartIndex = 0
        resumedFromMeetingId = nil
        microphoneStreamTimingReady = false
        systemAudioStreamTimingReady = false
        
        // Drop prior identity so new sockets generate fresh ids.
        microphoneMeetingId = nil
        systemAudioMeetingId = nil
        sessionId = nil
        
        // Leave history-viewing mode and clear any loaded past transcript.
        selectedMeetingId = nil
        isViewingPastMeeting = false
        loadedMeetingTranscript = nil
        
        // Clear live transcript buffers so the new meeting starts clean.
        transcriptionLines.removeAll()
        microphoneTranscript.removeAll()
        systemAudioTranscript.removeAll()
    }
    
    /// Prepare state to resume an existing logical meeting.
    ///
    /// New audio is always recorded under fresh meeting ids (so existing files are
    /// never overwritten), but the shared `sessionId` is preserved so history still
    /// groups the parts together, and new transcript segments are offset onto the
    /// logical timeline via `resumeTimelineOffsetSeconds`.
    ///
    /// - Parameters:
    ///   - sessionId: The logical meeting's shared session id to continue.
    ///   - timelineOffsetSeconds: Where the resumed part begins on the logical timeline.
    ///   - recordingPartIndex: Stable ordering index for the new part.
    ///   - resumedFromMeetingId: The meeting id resume was initiated from (diagnostics).
    func prepareResumeRecordingSession(
        sessionId: String,
        timelineOffsetSeconds: Double,
        recordingPartIndex: Int,
        resumedFromMeetingId: String?
    ) {
        recordingMode = .resume
        resumeTimelineOffsetSeconds = max(0.0, timelineOffsetSeconds)
        self.recordingPartIndex = recordingPartIndex
        self.resumedFromMeetingId = resumedFromMeetingId
        microphoneStreamTimingReady = false
        systemAudioStreamTimingReady = false
        
        // Fresh part ids; the WebSocket builders mint them when nil.
        microphoneMeetingId = nil
        systemAudioMeetingId = nil
        // Preserve the logical session so the backend groups resumed parts.
        self.sessionId = sessionId
        
        // Switch out of read-only history view into live recording mode.
        isViewingPastMeeting = false
        selectedMeetingId = nil
        loadedMeetingTranscript = nil
        
        // Retain the loaded prior-part transcript so the resumed recording
        // continues visually from where it left off, instead of clearing the
        // screen. These buffers were populated when the meeting was opened
        // (loadGroupedMeeting / selectMeeting); new live lines are stamped with
        // resumeTimelineOffsetSeconds (see appendLiveLines) so they sort after
        // the retained lines. Fresh starts still clear in
        // prepareFreshRecordingSession().
        //
        // Single-source / legacy meetings load only into `transcriptionLines`
        // (the per-source buffers stay empty). Seed the buffers from it so the
        // first resumed line does not cause updateCombinedTranscript() to drop
        // the retained transcript. Lines are marked complete so the next live
        // line starts fresh rather than extending a loaded line.
        if microphoneTranscript.isEmpty && systemAudioTranscript.isEmpty && !transcriptionLines.isEmpty {
            for line in transcriptionLines {
                var seeded = line
                seeded.lineComplete = true
                switch seeded.source ?? .microphone {
                case .systemAudio:
                    seeded.source = .systemAudio
                    systemAudioTranscript.append(seeded)
                case .microphone:
                    seeded.source = .microphone
                    microphoneTranscript.append(seeded)
                }
            }
        }
    }
    
    /// Query items describing how the current recording part sits on the logical
    /// meeting timeline. Both the microphone and system-audio sockets append these
    /// so the backend records each part with the correct offset and ordering.
    /// For a fresh recording these are the neutral defaults (mode=fresh, offset=0).
    func resumeRecordingQueryItems() -> [URLQueryItem] {
        var items: [URLQueryItem] = [
            URLQueryItem(name: "recording_mode", value: recordingMode == .resume ? "resume" : "fresh"),
            URLQueryItem(name: "timeline_offset_seconds", value: String(resumeTimelineOffsetSeconds)),
            URLQueryItem(name: "recording_part_index", value: String(recordingPartIndex))
        ]
        if let resumedFromMeetingId = resumedFromMeetingId {
            items.append(URLQueryItem(name: "resumed_from_meeting_id", value: resumedFromMeetingId))
        }
        return items
    }

    /// Sends the current recording-part capture offset before this source emits PCM.
    func sendNativeStreamTimingControl(for source: AudioSource) async throws {
        guard let recordingStartTime else {
            throw WebSocketError.invalidResponse
        }

        let socket: URLSessionWebSocketTask?
        switch source {
        case .microphone:
            microphoneStreamTimingReady = false
            socket = microphoneWebSocketTask
        case .systemAudio:
            systemAudioStreamTimingReady = false
            socket = systemAudioWebSocketTask
        }
        guard let socket else {
            throw WebSocketError.invalidResponse
        }

        let payload: [String: Any] = [
            "type": "native_stream_timing",
            "stream_offset_seconds": max(0, Date().timeIntervalSince(recordingStartTime))
        ]
        let data = try JSONSerialization.data(withJSONObject: payload)
        guard let text = String(data: data, encoding: .utf8) else {
            throw WebSocketError.invalidResponse
        }
        try await socket.send(.string(text))

        switch source {
        case .microphone:
            microphoneStreamTimingReady = true
        case .systemAudio:
            systemAudioStreamTimingReady = true
        }
    }
}
