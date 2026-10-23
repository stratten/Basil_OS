import Foundation

// MARK: - Post-Processing Extension
extension LiveTranscriptionViewModel {
    
    // MARK: - Private Properties
    
    /// Track which meeting IDs are being processed (for multi-source scenarios)
    private static var processingMeetingIds: [String] = []
    private static var completedMeetingIds: Set<String> = []
    
    /// Track the current source being processed
    private static var currentProcessingSource: AudioSource?

    /// Sources that have begun receiving incremental partial segments during the
    /// current post-processing run. The first partial for a source replaces the
    /// (live) track contents; subsequent partials append. Reset per run.
    private static var partialStartedSources: Set<AudioSource> = []

    /// Combined duration (seconds) of all tracks in the current job and the
    /// duration already completed, used to drive the aggregate progress bar.
    private static var aggregateTotalSeconds: Double = 0.0
    private static var completedTrackSeconds: Double = 0.0
    private static var currentTrackDurationSeconds: Double = 0.0

    /// True when the current job processes the members of a grouped meeting from
    /// history (every part x every source). The backend persists each part's
    /// transcript on the absolute meeting timeline, so the in-memory per-source
    /// full-replace swap is skipped (it would keep only the last part / double
    /// the offset); the combined view is rebuilt by reloading the grouped meeting
    /// once all parts finish. False for a just-stopped live session that is not
    /// yet in history, which keeps the existing incremental in-memory mirroring.
    private static var isGroupedReloadRun: Bool = false
    
    // MARK: - Public Methods
    
    /// Start post-processing the recorded meeting(s)
    /// - Parameters:
    ///   - operation: "both" (default) runs transcription then diarization, "transcribe" for re-transcription only, "diarize" for speaker identification only
    ///   - startedAutomatically: true when launched from meeting automation preferences.
    func startPostProcessing(operation: String = "both", startedAutomatically: Bool = false) async {
        // Collect all meeting IDs that need processing. For a grouped meeting
        // opened from history this is EVERY part x EVERY source (ordered by
        // recording_part_index then source) so a resumed multi-part meeting is
        // upgraded in full - previously only the latest part per source was
        // enumerated, silently dropping all earlier parts.
        let groupedMembers = groupedMeetingMembersForPostProcessing()
        var meetingIds: [(id: String, source: AudioSource)] = groupedMembers

        // Fallback: a just-stopped live session not yet present in the history
        // list has no grouped members to resolve, so use the current per-source
        // ids (the live session is single-part by construction).
        if meetingIds.isEmpty {
            if let micId = microphoneMeetingId {
                meetingIds.append((id: micId, source: .microphone))
            }
            if let sysId = systemAudioMeetingId {
                meetingIds.append((id: sysId, source: .systemAudio))
            }
        }

        // Grouped reload run when we resolved members from history. Drives both
        // the offset handling and the end-of-job rebuild below.
        let isGroupedReloadRun = !groupedMembers.isEmpty
        let groupedReloadMeetingId = selectedMeetingId
        let workOwnerID = selectedMeetingId ?? meetingIds.first?.id
        let autoAnalyzeOnCompletion = sessionAutoAnalyzeOnComplete
        let autoAnalyzeTiming = sessionAutoAnalyzeTiming

        guard !meetingIds.isEmpty else {
            #if DEBUG
            DevLogger.shared.error("No meeting IDs available for post-processing", context: "LiveTranscriptionViewModel")
            #endif
            return
        }
        
        guard !postProcessingModel.isEmpty else {
            #if DEBUG
            DevLogger.shared.error("No model selected for post-processing", context: "LiveTranscriptionViewModel")
            #endif
            return
        }
        
        // For diarization, check if transcription exists
        if operation == "diarize" && !hasTranscription {
            #if DEBUG
            DevLogger.shared.warning("Cannot diarize without transcription", context: "LiveTranscriptionViewModel")
            #endif
            return
        }
        
        isPostProcessing = true
        postProcessingStartedAutomatically = startedAutomatically
        postProcessingProgress = 0.0
        postProcessingAggregateProgress = 0.0
        postProcessingStage = "queued"
        // Always retain a concrete owner. A nil selectedMeetingId denotes the
        // live/just-stopped session and must not make a subsequently fresh
        // meeting appear to own this background job via nil == nil.
        activePostProcessingMeetingId = workOwnerID
        Self.processingMeetingIds = meetingIds.map { $0.id }
        Self.completedMeetingIds.removeAll()
        Self.partialStartedSources.removeAll()
        // Source counters drive the "source i of n" label so the progress row
        // no longer pairs a per-file count with the aggregate duration clock.
        postProcessingSourceTotal = meetingIds.count
        postProcessingSourceIndex = 0

        // Aggregate combined-duration progress across the sequential tracks so
        // the bar advances 0->100% over the whole workload instead of resetting
        // between mic and system. Durations come from the selected meeting's
        // members (same source as computeResumeTimelineOffset); fall back to the
        // representative duration for a single-track meeting.
        Self.aggregateTotalSeconds = aggregatePostProcessingTotalSeconds(for: meetingIds.map { $0.id })
        Self.completedTrackSeconds = 0.0
        Self.isGroupedReloadRun = isGroupedReloadRun
        // Per-source start offsets correct cross-track skew only for the live
        // just-stopped case (segments come back 0-based per source). For a
        // grouped reload run the backend returns absolute-timeline segments per
        // part and the end-of-job reload re-applies cross-track skew via
        // GroupedTranscriptMerge, so adding a skew offset here would double-count.
        postProcessingSourceStartOffsets = isGroupedReloadRun
            ? [:]
            : computeSourceStartOffsets(for: meetingIds.map { $0.id })
        
        // Set message based on operation and number of sources
        let sourceInfo = meetingIds.count > 1 ? " (\(meetingIds.count) audio sources)" : ""
        if operation == "both" {
            postProcessingMessage = "Starting transcript tools\(sourceInfo)..."
        } else if operation == "transcribe" {
            postProcessingMessage = "Starting transcript improvement\(sourceInfo)..."
        } else {
            postProcessingMessage = "Starting speaker labeling\(sourceInfo)..."
        }
        
        #if DEBUG
        DevLogger.shared.info("Post-processing \(meetingIds.count) meeting(s): \(meetingIds.map { $0.id })", context: "LiveTranscriptionViewModel")
        #endif
        
        // Process each meeting sequentially to maintain temporal ordering
        for (sourceOrdinal, (meetingId, source)) in meetingIds.enumerated() {
            postProcessingSourceIndex = sourceOrdinal + 1
            do {
                // Start post-processing job
                let port = APIClient.shared.currentPort
                let url = URL(string: "http://localhost:\(port)/meetings/\(meetingId)/post-process")!
                
                var request = URLRequest(url: url)
                request.httpMethod = "POST"
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                
                let body = ["model": postProcessingModel, "operation": operation]
                request.httpBody = try JSONEncoder().encode(body)
                
                let (data, response) = try await URLSession.shared.data(for: request)
                
                guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
                    throw NSError(domain: "PostProcessing", code: -1, userInfo: [NSLocalizedDescriptionKey: "Failed to start post-processing for \(source.displayName)"])
                }
                
                let result = try JSONDecoder().decode([String: String].self, from: data)
                
                #if DEBUG
                DevLogger.shared.info("Post-processing started for \(source.displayName): \(result)", context: "LiveTranscriptionViewModel")
                #endif
                
                // Connect to progress WebSocket and wait for completion
                await connectPostProcessingWebSocket(meetingId: meetingId, source: source)
                
            } catch {
                #if DEBUG
                DevLogger.shared.error("Failed to start post-processing for \(source.displayName): \(error)", context: "LiveTranscriptionViewModel")
                #endif
                await MainActor.run {
                    postProcessingMessage = "Error updating transcript for \(source.displayName): \(error.localizedDescription)"
                }
            }
        }
        
        // All meetings processed, finalize
        await MainActor.run {
            isPostProcessing = false
            postProcessingAggregateProgress = 1.0
            postProcessingMessage = "Transcript tools complete for all sources"
            postProcessingStartedAutomatically = false
            activePostProcessingMeetingId = nil
            Self.processingMeetingIds.removeAll()
            Self.completedMeetingIds.removeAll()
            Self.partialStartedSources.removeAll()
            Self.aggregateTotalSeconds = 0.0
            Self.completedTrackSeconds = 0.0
            Self.currentTrackDurationSeconds = 0.0
            Self.isGroupedReloadRun = false
            postProcessingSourceIndex = 0
            postProcessingSourceTotal = 0
        }

        // Rebuild a grouped meeting's combined view from the freshly persisted
        // per-part transcript.json files. Each part was written on the absolute
        // meeting timeline (its timeline_offset re-applied by the backend), so
        // reloading interleaves all parts x sources correctly instead of leaving
        // only the last-processed part in memory.
        if isGroupedReloadRun, let reloadId = groupedReloadMeetingId,
           selectedMeetingId == reloadId, !isRecording {
            await selectMeeting(reloadId)
        }

        // Auto-analyze AFTER re-transcription when configured. The "before"
        // ordering is handled in stopRecording (analysis runs ahead of the
        // retranscribe call), so it is intentionally excluded here to avoid a
        // duplicate run.
        if autoAnalyzeOnCompletion,
           autoAnalyzeTiming == "after",
           workOwnerID == (selectedMeetingId ?? currentMeetingId) {
            await runAutoAnalyze()
        }
    }

    /// Run meeting analysis using the per-session automation configuration
    /// (modes + custom instructions). Seeds the analysis selection from the
    /// configured modes so `startMeetingAnalysis` analyzes exactly those modes;
    /// no-ops when no valid modes are configured.
    func runAutoAnalyze() async {
        let modes = sessionAutoAnalyzeModes.compactMap { AnalysisMode(rawValue: $0) }
        guard !modes.isEmpty else {
            analysisStartedAutomatically = false
            #if DEBUG
            DevLogger.shared.warning("Auto-analyze requested but no valid modes configured", context: "LiveTranscriptionViewModel")
            #endif
            return
        }
        await MainActor.run {
            analysisStartedAutomatically = true
            selectedAnalysisModes = Set(modes)
            analysisCustomInstructions = sessionAutoAnalyzeCustomInstructions
        }
        await startMeetingAnalysis()
    }
    
    // MARK: - Private Methods
    
    /// Connect to post-processing progress WebSocket
    private func connectPostProcessingWebSocket(meetingId: String, source: AudioSource) async {
        Self.currentProcessingSource = source
        // Remember this track's duration so the aggregate accumulator can grow
        // by the right amount when the track completes.
        await MainActor.run {
            Self.currentTrackDurationSeconds = self.trackDurationSeconds(for: meetingId)
        }
        let port = APIClient.shared.currentPort
        let wsUrl = URL(string: "ws://localhost:\(port)/meetings/\(meetingId)/post-process/status")!
        
        postProcessingWebSocket = URLSession.shared.webSocketTask(with: BackendAuthorization.authorizedRequest(for: wsUrl))
        postProcessingWebSocket?.resume()
        
        #if DEBUG
        DevLogger.shared.info("Connected to post-processing WebSocket", context: "LiveTranscriptionViewModel")
        #endif
        
        // Start receiving messages
        await receivePostProcessingMessages()
    }
    
    /// Receive and process post-processing progress messages
    private func receivePostProcessingMessages() async {
        guard let ws = postProcessingWebSocket else { return }
        
        do {
            let message = try await ws.receive()
            
            switch message {
            case .string(let text):
                if let data = text.data(using: .utf8),
                   let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    await handlePostProcessingMessage(json)
                }
            case .data(let data):
                if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    await handlePostProcessingMessage(json)
                }
            @unknown default:
                break
            }
            
            // Continue receiving if still processing
            if isPostProcessing {
                await receivePostProcessingMessages()
            }
            
        } catch {
            #if DEBUG
            DevLogger.shared.error("Post-processing WebSocket error: \(error)", context: "LiveTranscriptionViewModel")
            #endif
            await MainActor.run {
                isPostProcessing = false
                postProcessingStartedAutomatically = false
                activePostProcessingMeetingId = nil
            }
        }
    }
    
    /// Handle post-processing progress message
    private func handlePostProcessingMessage(_ json: [String: Any]) async {
        await MainActor.run {
            let type = json["type"] as? String ?? ""
            
            switch type {
            case "progress":
                postProcessingProgress = json["overall_progress"] as? Double ?? 0.0
                let stage = json["stage"] as? String ?? ""
                postProcessingStage = stage
                postProcessingMessage = json["message"] as? String ?? ""
                postProcessingETA = json["eta_seconds"] as? Double ?? 0.0

                let trackCurrentTime = json["current_time"] as? Double ?? 0.0
                let trackTotalTime = json["total_time"] as? Double ?? 0.0

                // Drive the combined-duration bar across both sequential tracks.
                // When the aggregate total is known, the readout shows combined
                // elapsed/total and the bar never resets between tracks; when it
                // is unknown (e.g. live just-stopped meeting) fall back to the
                // per-track progress so single-track flows still work.
                if Self.aggregateTotalSeconds > 0 {
                    let combinedCurrent = Self.completedTrackSeconds + trackCurrentTime
                    postProcessingCurrentTime = min(combinedCurrent, Self.aggregateTotalSeconds)
                    postProcessingTotalTime = Self.aggregateTotalSeconds
                } else {
                    postProcessingCurrentTime = trackCurrentTime
                    postProcessingTotalTime = trackTotalTime
                }
                postProcessingAggregateProgress = PostProcessingProgressMath.aggregateProgress(
                    completedTrackSeconds: Self.completedTrackSeconds,
                    currentTrackSeconds: trackCurrentTime,
                    aggregateTotalSeconds: Self.aggregateTotalSeconds,
                    previous: postProcessingAggregateProgress,
                    fallbackPerTrack: postProcessingProgress
                )
                
                // Mark transcription as complete when it finishes (even if diarization is still running)
                if stage == "diarization" || stage == "merging" {
                    hasTranscription = true
                }

                // Render newly-completed segments incrementally (2D), only while
                // the user is viewing the meeting this job belongs to. The
                // terminal `complete` still performs the authoritative swap.
                if isViewingActivePostProcessingMeeting,
                   !Self.isGroupedReloadRun,
                   let newSegments = json["new_segments"] as? [[String: Any]],
                   !newSegments.isEmpty,
                   let source = Self.currentProcessingSource {
                    applyPartialPostProcessingSegments(newSegments, source: source)
                }
                
            case "complete":
                postProcessingProgress = 1.0
                let stage = json["stage"] as? String ?? ""
                
                // Mark transcription as complete (enables diarization button)
                if stage == "complete" || stage == "transcription" {
                    hasTranscription = true
                }
                
                // Advance the aggregate accumulator by this track's duration so
                // the combined bar continues monotonically into the next track.
                Self.completedTrackSeconds += Self.currentTrackDurationSeconds
                if Self.aggregateTotalSeconds > 0 {
                    postProcessingAggregateProgress = PostProcessingProgressMath.aggregateProgress(
                        completedTrackSeconds: Self.completedTrackSeconds,
                        currentTrackSeconds: 0.0,
                        aggregateTotalSeconds: Self.aggregateTotalSeconds,
                        previous: postProcessingAggregateProgress,
                        fallbackPerTrack: postProcessingAggregateProgress
                    )
                }

                // Update transcript with new data, but only when the user is
                // still viewing the meeting this job belongs to. If they've
                // navigated to a different meeting we skip the in-memory swap
                // (the backend has already persisted the upgraded transcript, so
                // reopening this meeting reloads it correctly) to avoid writing
                // these segments onto the other meeting's view.
                // For a grouped reload run the per-source full swap would keep
                // only the last-processed part; the combined view is rebuilt by
                // reloading the grouped meeting once every part completes.
                if isViewingActivePostProcessingMeeting,
                   !Self.isGroupedReloadRun,
                   let transcript = json["transcript"] as? [String: Any],
                   let segments = transcript["segments"] as? [[String: Any]],
                   let source = Self.currentProcessingSource {
                    updateTranscriptFromPostProcessing(segments, source: source)
                }
                
                // Mark this meeting as complete
                if !Self.processingMeetingIds.isEmpty {
                    let currentId = Self.processingMeetingIds.first ?? ""
                    Self.completedMeetingIds.insert(currentId)
                    
                    // Update message based on progress
                    let remaining = Self.processingMeetingIds.count - Self.completedMeetingIds.count
                    if remaining > 0 {
                        postProcessingMessage = "Completed \(Self.completedMeetingIds.count)/\(Self.processingMeetingIds.count) sources..."
                    } else {
                        postProcessingMessage = "Transcript tools complete!"
                    }
                }
                
                // Close WebSocket for this meeting (next meeting will open a new one)
                postProcessingWebSocket?.cancel()
                postProcessingWebSocket = nil
                Self.currentProcessingSource = nil
                
            case "error":
                postProcessingMessage = "Error: \(json["message"] as? String ?? "Unknown error")"
                isPostProcessing = false
                postProcessingStartedAutomatically = false
                activePostProcessingMeetingId = nil
                postProcessingWebSocket?.cancel()
                postProcessingWebSocket = nil
                
            default:
                break
            }
        }
    }
    
    /// Merge microphone and system audio transcripts into a chronologically sorted combined view
    func updateCombinedTranscript() {
        var combined = microphoneTranscript + systemAudioTranscript
        
        // Sort by canonical meeting-elapsed timestamp first, then legacy strings.
        combined = combined.enumerated().sorted { left, right in
            let seconds1 = timelineSortSeconds(for: left.element)
            let seconds2 = timelineSortSeconds(for: right.element)

            switch (seconds1, seconds2) {
            case let (lhs?, rhs?):
                if lhs == rhs {
                    return left.offset < right.offset
                }
                return lhs < rhs
            case (_?, nil):
                return true
            case (nil, _?):
                return false
            case (nil, nil):
                return left.offset < right.offset
            }
        }.map(\.element)
        
        transcriptionLines = combined
    }

    private func timelineSortSeconds(for line: TranscriptionLine) -> Double? {
        if let timelineStartSeconds = line.timelineStartSeconds {
            return timelineStartSeconds
        }
        if let start = line.start {
            return timeStringToSeconds(start)
        }
        return nil
    }
    
    /// Convert time string (HH:MM:SS or MM:SS) to total seconds
    private func timeStringToSeconds(_ timeString: String) -> Double {
        let components = timeString.split(separator: ":").compactMap { Double($0) }
        
        if components.count == 3 {
            // HH:MM:SS
            return components[0] * 3600 + components[1] * 60 + components[2]
        } else if components.count == 2 {
            // MM:SS
            return components[0] * 60 + components[1]
        } else if components.count == 1 {
            // Just seconds
            return components[0]
        }
        
        return 0
    }
    
    /// Convert raw post-processing segment dictionaries into transcript lines,
    /// shifting onto the shared session timeline to correct cross-track skew.
    private func linesFromPostProcessingSegments(_ segments: [[String: Any]], source: AudioSource) -> [TranscriptionLine] {
        var newLines: [TranscriptionLine] = []
        let startOffset = postProcessingSourceStartOffsets[source] ?? 0.0

        for segment in segments {
            guard let start = segment["start"] as? Double,
                  let end = segment["end"] as? Double,
                  let text = segment["text"] as? String else {
                continue
            }

            let speaker = segment["speaker"] as? String ?? "Speaker 1"

            // Convert speaker label to speakerID format (e.g., "Speaker 1" -> "speaker0")
            let speakerID: String?
            if let speakerNum = speaker.components(separatedBy: " ").last,
               let num = Int(speakerNum), num > 0 {
                speakerID = "speaker\(num - 1)"
            } else {
                speakerID = nil
            }

            let timelineStart = start + startOffset
            let timelineEnd = end + startOffset
            var line = TranscriptionLine(
                id: TranscriptTimelineSplice.deterministicSegmentID(
                    source: source,
                    timelineStartSeconds: timelineStart,
                    timelineEndSeconds: timelineEnd,
                    speakerID: speakerID
                ),
                text: text,
                speakerID: speakerID,
                isInterim: false,
                start: String(format: "%.2f", timelineStart),
                end: String(format: "%.2f", timelineEnd),
                diff: end - start,
                timelineStartSeconds: timelineStart,
                timelineEndSeconds: timelineEnd
            )
            line.source = source  // Tag with the audio source
            newLines.append(line)
        }
        return newLines
    }

    /// Update transcript lines with post-processed data (authoritative full swap)
    private func updateTranscriptFromPostProcessing(_ segments: [[String: Any]], source: AudioSource) {
        let newLines = linesFromPostProcessingSegments(segments, source: source)
        
        // Update the appropriate transcript array based on source
        switch source {
        case .microphone:
            microphoneTranscript = newLines
            #if DEBUG
            DevLogger.shared.info("Updated microphone transcript with \(newLines.count) post-processed segments", context: "LiveTranscriptionViewModel")
            #endif
            
        case .systemAudio:
            systemAudioTranscript = newLines
            #if DEBUG
            DevLogger.shared.info("Updated system audio transcript with \(newLines.count) post-processed segments", context: "LiveTranscriptionViewModel")
            #endif
        }
        
        // Merge and sort all transcripts chronologically
        updateCombinedTranscript()
        
        #if DEBUG
        DevLogger.shared.info("Combined transcript now has \(transcriptionLines.count) total segments", context: "LiveTranscriptionViewModel")
        #endif
    }

    /// Apply incremental partial segments for a track during re-transcription so
    /// the higher-quality output appears live. The first partial for a source
    /// replaces the prior (live) contents; subsequent partials append. The
    /// terminal `complete` performs the authoritative full swap and reconciles
    /// any boundary differences.
    private func applyPartialPostProcessingSegments(_ segments: [[String: Any]], source: AudioSource) {
        let partialLines = linesFromPostProcessingSegments(segments, source: source)
        guard !partialLines.isEmpty else { return }

        let isFirstPartial = !Self.partialStartedSources.contains(source)
        Self.partialStartedSources.insert(source)

        switch source {
        case .microphone:
            microphoneTranscript = isFirstPartial ? partialLines : (microphoneTranscript + partialLines)
        case .systemAudio:
            systemAudioTranscript = isFirstPartial ? partialLines : (systemAudioTranscript + partialLines)
        }

        updateCombinedTranscript()
    }

    /// Splice a re-transcribed closed window `[start, end)` (absolute meeting
    /// timeline) into the live per-track transcript, replacing only the lines the
    /// window supersedes with the higher-quality segments. Unlike
    /// `applyPartialPostProcessingSegments`, this is range-aware: content outside
    /// the window is preserved. Used by mid-recording cadence upgrades and the
    /// on-stop tail. The window bounds are shifted by the same per-source start
    /// offset applied to the new lines so removal and insertion share one
    /// coordinate space (the offset is 0 during live recording).
    func applyWindowedRetranscription(
        _ segments: [[String: Any]],
        source: AudioSource,
        start: Double,
        end: Double
    ) {
        let newLines = linesFromPostProcessingSegments(segments, source: source)
        let startOffset = postProcessingSourceStartOffsets[source] ?? 0.0
        let rangeStart = start + startOffset
        let rangeEnd = end + startOffset

        isApplyingWindowedRetranscription = true

        switch source {
        case .microphone:
            microphoneTranscript = TranscriptTimelineSplice.spliceByRange(
                existing: microphoneTranscript, newLines: newLines, start: rangeStart, end: rangeEnd
            )
        case .systemAudio:
            systemAudioTranscript = TranscriptTimelineSplice.spliceByRange(
                existing: systemAudioTranscript, newLines: newLines, start: rangeStart, end: rangeEnd
            )
        }

        updateCombinedTranscript()
        Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: 150_000_000)
            self?.isApplyingWindowedRetranscription = false
        }
    }

    // MARK: - Aggregate-duration progress helpers (1C)

    /// True while the in-flight retranscription job belongs to the meeting the
    /// user is currently viewing. The progress overlay and live transcript
    /// mirroring are both gated on this so a job started on meeting A does not
    /// render its bar (or write its segments) onto a different meeting B.
    var isViewingActivePostProcessingMeeting: Bool {
        activePostProcessingMeetingId == (selectedMeetingId ?? currentMeetingId)
    }

    /// When navigating to a meeting that is NOT the active retranscription job,
    /// clear the (display-only) progress vars so the Transcript Tools card shows
    /// a clean state instead of a stale bar/readout. The running socket is left
    /// untouched (`isPostProcessing` and `activePostProcessingMeetingId` are not
    /// modified), so returning to the active meeting resumes mirroring.
    func clearInactivePostProcessingDisplay(for selectedId: String?) {
        guard activePostProcessingMeetingId != selectedId else { return }
        postProcessingProgress = 0.0
        postProcessingAggregateProgress = 0.0
        postProcessingMessage = ""
        postProcessingStage = ""
        postProcessingCurrentTime = 0.0
        postProcessingTotalTime = 0.0
        postProcessingETA = 0.0
    }

    /// Sum the durations (seconds) of the given track meeting ids from the
    /// selected meeting's members. Returns 0 when none are known (e.g. the
    /// just-stopped live meeting that is not yet in the history list), in which
    /// case the aggregate bar falls back to per-track progress.
    private func aggregatePostProcessingTotalSeconds(for meetingIds: [String]) -> Double {
        let members = matchingMeetingMembers(for: meetingIds)
        guard !members.isEmpty else { return 0.0 }
        return members.reduce(0.0) { $0 + ($1.durationSeconds ?? 0.0) }
    }

    /// Duration (seconds) of a single track meeting id, used to advance the
    /// completed accumulator as each track finishes.
    private func trackDurationSeconds(for meetingId: String) -> Double {
        matchingMeetingMembers(for: [meetingId]).first?.durationSeconds ?? 0.0
    }

    /// Compute per-source start offsets (seconds) onto the shared session
    /// origin from the processed members' absolute start times. Returns an empty
    /// map when fewer than the needed start times are known, in which case no
    /// skew correction is applied (the reopened grouped view corrects it).
    private func computeSourceStartOffsets(for meetingIds: [String]) -> [AudioSource: Double] {
        let members = matchingMeetingMembers(for: meetingIds)
        let starts = members.compactMap { $0.startDate }
        guard let origin = starts.min(), !starts.isEmpty else { return [:] }

        var offsets: [AudioSource: Double] = [:]
        for member in members {
            guard let start = member.startDate else { continue }
            let isMicrophone = (member.source ?? "").lowercased() == "microphone"
            let source: AudioSource = isMicrophone ? .microphone : .systemAudio
            offsets[source] = max(0.0, start.timeIntervalSince(origin))
        }
        return offsets
    }

    /// Enumerate every member (part x source) of the grouped meeting the user is
    /// currently viewing, ordered by `(recordingPartIndex, source)` so parts are
    /// processed in temporal order with microphone ahead of system audio within a
    /// part. Returns an empty list when the selection is not a grouped history
    /// meeting (e.g. a just-stopped live session), in which case the caller falls
    /// back to the current per-source ids.
    private func groupedMeetingMembersForPostProcessing() -> [(id: String, source: AudioSource)] {
        guard let selectedId = selectedMeetingId else { return [] }
        let grouped = meetings.first { meeting in
            meeting.id == selectedId || (meeting.members?.contains { $0.id == selectedId } ?? false)
        }
        guard let members = grouped?.members, !members.isEmpty else { return [] }

        let ordered = members.sorted { lhs, rhs in
            let lp = lhs.recordingPartIndex ?? 0
            let rp = rhs.recordingPartIndex ?? 0
            if lp != rp { return lp < rp }
            return postProcessingSourceRank(lhs.source) < postProcessingSourceRank(rhs.source)
        }
        return ordered.map { member in
            let isMicrophone = (member.source ?? "").lowercased() == "microphone"
            return (id: member.id, source: isMicrophone ? .microphone : .systemAudio)
        }
    }

    /// Stable ordering rank for a member source string (microphone first).
    private func postProcessingSourceRank(_ source: String?) -> Int {
        (source ?? "").lowercased() == "microphone" ? 0 : 1
    }

    /// Resolve `MeetingMember` records for the given ids from the loaded history
    /// list (matching on the member id within each grouped meeting).
    private func matchingMeetingMembers(for meetingIds: [String]) -> [MeetingMember] {
        let idSet = Set(meetingIds)
        var found: [MeetingMember] = []
        for meeting in meetings {
            guard let members = meeting.members else { continue }
            for member in members where idSet.contains(member.id) {
                found.append(member)
            }
        }
        return found
    }
}

