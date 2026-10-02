import Foundation

// MARK: - Meeting History Management
extension LiveTranscriptionViewModel {

    /// Timeline gap (seconds) between two persisted segments treated as a
    /// silence boundary when reconstructing sentence-level lines on reload.
    /// Persisted segments carry neither the backend `lineComplete` flag nor
    /// the live 3s global line-break timer, so this proxies both using the
    /// gap between consecutive segments' timeline seconds (see
    /// `TranscriptSegmentCoalescer`).
    static let reloadCoalesceSilenceGapSeconds = 2.0
    static let meetingHistoryPageSize = 50

    // MARK: - Load Meeting History
    
    /// Load the list of past meetings from the backend
    func loadMeetingHistory() async {
        meetingHistoryRequestGeneration &+= 1
        let requestGeneration = meetingHistoryRequestGeneration
        isLoadingMeetings = true
        isLoadingMoreMeetings = false
        meetingHistoryLoadMoreError = nil

        // Branch on the sidebar search text: a non-empty query routes through the
        // backend transcript search endpoint; empty falls back to the recent list.
        let query = meetingSearchText.trimmingCharacters(in: .whitespacesAndNewlines)
        let filters = meetingSearchFilters

        do {
            let page = try await fetchMeetingHistoryPage(query: query, filters: filters, offset: 0)
            
            guard requestGeneration == meetingHistoryRequestGeneration,
                  filters == meetingSearchFilters else { return }
            meetings = page.meetings
            hasMoreMeetings = page.hasMore
            isLoadingMeetings = false
            
            #if DEBUG
            DevLogger.shared.info("✅ Loaded \(page.meetings.count) meetings (query=\(query.isEmpty ? "<none>" : query), hasMore=\(page.hasMore))", context: "LiveTranscriptionViewModel")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to load meeting history: \(error)", context: "LiveTranscriptionViewModel")
            #endif
            
            guard requestGeneration == meetingHistoryRequestGeneration else { return }
            meetings = []
            hasMoreMeetings = false
            isLoadingMeetings = false
        }
    }

    /// Append the next page for the current history query without replacing its
    /// already-loaded results. Generation matching drops an outdated append when
    /// a new search or a full refresh supersedes it in flight.
    func loadMoreMeetingHistory() async {
        guard !isLoadingMeetings, !isLoadingMoreMeetings, hasMoreMeetings else { return }

        let requestGeneration = meetingHistoryRequestGeneration
        let query = meetingSearchText.trimmingCharacters(in: .whitespacesAndNewlines)
        let filters = meetingSearchFilters
        let offset = meetings.count
        isLoadingMoreMeetings = true
        meetingHistoryLoadMoreError = nil

        do {
            let page = try await fetchMeetingHistoryPage(query: query, filters: filters, offset: offset)
            guard requestGeneration == meetingHistoryRequestGeneration,
                  query == meetingSearchText.trimmingCharacters(in: .whitespacesAndNewlines),
                  filters == meetingSearchFilters else { return }

            let existingIds = Set(meetings.map(\.id))
            let additions = page.meetings.filter { !existingIds.contains($0.id) }
            meetings.append(contentsOf: additions)
            hasMoreMeetings = page.hasMore && !additions.isEmpty
            isLoadingMoreMeetings = false
        } catch {
            guard requestGeneration == meetingHistoryRequestGeneration else { return }
            meetingHistoryLoadMoreError = "Could not load more meetings."
            isLoadingMoreMeetings = false
        }
    }

    private func fetchMeetingHistoryPage(
        query: String,
        filters: MeetingHistorySearchFilters,
        offset: Int
    ) async throws -> (meetings: [MeetingListItem], hasMore: Bool) {
        let fetchedMeetings: [MeetingListItem]
        if query.isEmpty && !filters.isActive {
            fetchedMeetings = try await APIClient.shared.listMeetings(limit: Self.meetingHistoryPageSize + 1, offset: offset)
        } else {
            fetchedMeetings = try await APIClient.shared.searchMeetings(
                query: query,
                filters: filters,
                limit: Self.meetingHistoryPageSize + 1,
                offset: offset
            )
        }
        return (
            meetings: Array(fetchedMeetings.prefix(Self.meetingHistoryPageSize)),
            hasMore: fetchedMeetings.count > Self.meetingHistoryPageSize
        )
    }

    /// Debounced sidebar search trigger (mirrors AssistantOutputHistoryViewModel).
    /// Bound to `meetingSearchText` changes; reloads the (filtered) history after
    /// a short delay so each keystroke doesn't fire a request.
    func triggerMeetingSearch() {
        meetingSearchTask?.cancel()
        meetingSearchTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 300_000_000) // 300ms debounce
            if !Task.isCancelled {
                await self?.loadMeetingHistory()
            }
        }
    }
    
    // MARK: - Select Past Meeting
    
    /// Load and display a past meeting (read-only mode)
    /// - Parameter meetingId: ID of the meeting to load
    func selectMeeting(_ meetingId: String) async {
        #if DEBUG
        DevLogger.shared.info("📂 Loading meeting: \(meetingId)", context: "LiveTranscriptionViewModel")
        #endif
        
        // Don't allow switching meetings while recording
        guard !isRecording else {
            #if DEBUG
            DevLogger.shared.warning("⚠️ Cannot load meeting while recording", context: "LiveTranscriptionViewModel")
            #endif
            return
        }
        
        // Grouped (multi-source) meetings carry a members[] list. Load each member
        // transcript and interleave them so reopening shows a single combined view.
        let listEntry: MeetingListItem? = await MainActor.run {
            self.meetings.first(where: { $0.id == meetingId })
        }

        // Acknowledge the selection from already-loaded sidebar data before the
        // heavier transcript request completes. This keeps navigation responsive
        // without showing the previously selected meeting's transcript underneath
        // the newly selected row.
        await MainActor.run {
            self.selectedMeetingId = meetingId
            self.isViewingPastMeeting = true
            self.analysisJustCompleted = false
            self.clearInactivePostProcessingDisplay(for: meetingId)
            if let listEntry {
                self.meetingName = listEntry.name
                self.meetingPurpose = listEntry.purpose ?? ""
                self.meetingParticipants = listEntry.participants.joined(separator: ", ")
            }
            self.loadedMeetingTranscript = nil
            self.transcriptionLines = []
            self.microphoneTranscript = []
            self.systemAudioTranscript = []
            self.microphoneMeetingId = nil
            self.systemAudioMeetingId = nil
            self.hasRecordedAudio = false
            self.hasTranscription = false
            self.analysisHistory = []
            self.isLoadingAnalysisHistory = true
        }

        if let members = listEntry?.members, members.count > 1 {
            await loadGroupedMeeting(
                representativeId: meetingId,
                members: members,
                displayName: listEntry?.name
            )
            return
        }
        
        do {
            // Fetch meeting data from backend
            let (metadata, transcript) = try await APIClient.shared.getMeeting(id: meetingId)
            
            #if DEBUG
            DevLogger.shared.info("📦 Received metadata: name=\(metadata.name), hasAudio=\(metadata.audioPath != nil), hasTranscript=\(transcript != nil)", context: "LiveTranscriptionViewModel")
            if let transcript = transcript {
                DevLogger.shared.info("📝 Transcript has \(transcript.segments.count) segments", context: "LiveTranscriptionViewModel")
            }
            #endif
            
            let applied = await MainActor.run { () -> Bool in
                // A slower request for a previously clicked meeting must not
                // replace a newer selection.
                guard self.selectedMeetingId == meetingId else { return false }

                #if DEBUG
                DevLogger.shared.info("🔄 Setting UI state: selectedMeetingId=\(meetingId), isViewingPastMeeting=true", context: "LiveTranscriptionViewModel")
                #endif
                
                // Load meeting metadata into form fields
                self.meetingName = metadata.name
                self.meetingPurpose = metadata.purpose ?? ""
                
                // Parse participants list
                if !metadata.participants.isEmpty {
                    self.meetingParticipants = metadata.participants.joined(separator: ", ")
                } else {
                    self.meetingParticipants = ""
                }
                
                // Load transcript if available
                if let transcript = transcript {
                    self.loadedMeetingTranscript = transcript
                    
                    // Convert transcript segments to TranscriptionLine format for display
                    let rawLines = transcript.segments.enumerated().map { index, segment in
                        TranscriptionLine(
                            id: UUID().uuidString,  // Generate unique ID for each line
                            text: segment.text,
                            speakerID: segment.speakerValue?.stringValue,
                            isInterim: segment.isInterim ?? false,  // Use backend value or default to false
                            start: String(format: "%.2f", segment.start),
                            end: String(format: "%.2f", segment.end),
                            diff: segment.end - segment.start,
                            timelineStartSeconds: segment.start,
                            timelineEndSeconds: segment.end,
                            source: .microphone,  // Default to microphone for past meetings
                            lineComplete: true  // Past transcripts are always complete
                        )
                    }
                    // Retranscribed/diarized transcripts are already sentence-level;
                    // only live (not-yet-post-processed) transcripts need the persisted
                    // fine-grained segments re-coalesced to match live display granularity.
                    self.transcriptionLines = metadata.isPostProcessed
                        ? rawLines
                        : TranscriptSegmentCoalescer.coalesce(
                            rawLines,
                            minWords: Self.liveSentenceBreakMinWords,
                            silenceGapSeconds: Self.reloadCoalesceSilenceGapSeconds,
                            normalize: self.normalizeWhitespace
                        )
                } else {
                    self.loadedMeetingTranscript = nil
                    self.transcriptionLines = []
                }
                
                // Set meeting IDs for post-processing/analysis (use the loaded meeting ID)
                self.microphoneMeetingId = meetingId
                self.systemAudioMeetingId = nil
                
                // Enable post-processing if there's audio
                self.hasRecordedAudio = metadata.audioPath != nil
                self.hasTranscription = !self.transcriptionLines.isEmpty
                
                #if DEBUG
                DevLogger.shared.info("✅ Loaded meeting: \(metadata.name) with \(self.transcriptionLines.count) lines", context: "LiveTranscriptionViewModel")
                DevLogger.shared.info("   hasRecordedAudio=\(self.hasRecordedAudio), hasTranscription=\(self.hasTranscription)", context: "LiveTranscriptionViewModel")
                DevLogger.shared.info("   meetingName='\(self.meetingName)', purpose='\(self.meetingPurpose)'", context: "LiveTranscriptionViewModel")
                #endif
                
                // Force UI update
                self.objectWillChange.send()
                return true
            }

            guard applied else { return }

            // If the on-stop tail upgrade never completed for this meeting (left
            // `is_post_processed = false`), finish it now in the background rather
            // than requiring the user to notice and run "Post-Process" by hand.
            if !metadata.isPostProcessed, metadata.audioPath != nil, let duration = metadata.durationSeconds, duration > 0 {
                let inferredSource: AudioSource = (metadata.audioSource ?? "").lowercased() == "microphone" ? .microphone : .systemAudio
                Task { [weak self] in
                    await self?.attemptDeferredTailRetranscription(
                        meetingId: meetingId, source: inferredSource, durationSeconds: duration
                    )
                }
            }

            // Load analysis history for this meeting (already runs on MainActor)
            await self.loadAnalysisHistory(meetingId: meetingId)
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to load meeting: \(error)", context: "LiveTranscriptionViewModel")
            #endif
            
            await MainActor.run {
                guard self.selectedMeetingId == meetingId else { return }
                // Reset on error
                self.selectedMeetingId = nil
                self.isViewingPastMeeting = false
                self.isLoadingAnalysisHistory = false
                self.statusMessage = "Failed to load meeting"
            }
        }
    }
    
    // MARK: - Load Grouped Meeting
    
    /// Load a grouped (multi-source) meeting by fetching each member transcript,
    /// tagging segments with their real source, and interleaving them into a single
    /// combined transcript (mirrors the live `updateCombinedTranscript()` behavior).
    /// - Parameters:
    ///   - representativeId: ID of the representative member (the one shown in the sidebar)
    ///   - members: All member recordings belonging to this meeting's session
    ///   - displayName: Cleaned display name from the meeting list (no per-source suffix)
    private func loadGroupedMeeting(
        representativeId: String,
        members: [MeetingMember],
        displayName: String?
    ) async {
        #if DEBUG
        DevLogger.shared.info("📂 Loading grouped meeting: \(representativeId) with \(members.count) members", context: "LiveTranscriptionViewModel")
        #endif
        
        do {
            var memberInputs: [GroupedTranscriptMerge.MemberInput] = []
            var microphoneId: String? = nil
            var systemAudioId: String? = nil
            var anyAudio = false
            var representativeMetadata: MeetingListItem? = nil

            // Members arrive ordered by (recording_part_index, start_time) from the
            // backend, so iterating in order accumulates resumed parts in timeline
            // order. Persisted segment times already carry each part's resume
            // offset, so the lines are fed to GroupedTranscriptMerge unshifted and
            // it applies only intra-part cross-track skew (no global offset, which
            // would double-count the resume offset for later parts).
            for member in members {
                let (metadata, transcript) = try await APIClient.shared.getMeeting(id: member.id)
                
                let isMicrophone = (member.source ?? "").lowercased() == "microphone"
                let source: AudioSource = isMicrophone ? .microphone : .systemAudio
                let lines = transcriptionLines(from: transcript, source: source, isPostProcessed: member.isPostProcessed)
                
                memberInputs.append(
                    GroupedTranscriptMerge.MemberInput(
                        source: source,
                        recordingPartIndex: member.recordingPartIndex ?? 0,
                        startDate: member.startDate,
                        lines: lines
                    )
                )
                
                // Point post-processing/analysis at the latest part per source
                // (resume continuation). Members are part-ordered, so the last
                // assignment wins.
                if isMicrophone {
                    microphoneId = member.id
                } else {
                    systemAudioId = member.id
                }
                
                if metadata.audioPath != nil {
                    anyAudio = true
                }
                // Prefer the representative member's metadata for the form fields.
                if member.id == representativeId || representativeMetadata == nil {
                    representativeMetadata = metadata
                }

                // Same deferred-completion fallback as the single-meeting path,
                // applied per member: a member left with `is_post_processed =
                // false` because its on-stop tail pass never ran gets finished
                // in the background now that this meeting has been reopened.
                if !metadata.isPostProcessed, metadata.audioPath != nil, let duration = metadata.durationSeconds, duration > 0 {
                    let memberId = member.id
                    Task { [weak self] in
                        await self?.attemptDeferredTailRetranscription(
                            meetingId: memberId, source: source, durationSeconds: duration
                        )
                    }
                }
            }
            
            // Accumulate ALL parts per source (keeps part 0 instead of letting a
            // later part overwrite it) and correct intra-part cross-track skew.
            let merged = GroupedTranscriptMerge.merge(memberInputs)
            
            let applied = await MainActor.run { () -> Bool in
                // A slower grouped request for a previously clicked meeting must
                // not replace a newer selection.
                guard self.selectedMeetingId == representativeId else { return false }

                if let metadata = representativeMetadata {
                    self.meetingName = displayName ?? metadata.name
                    self.meetingPurpose = metadata.purpose ?? ""
                    self.meetingParticipants = metadata.participants.isEmpty
                        ? ""
                        : metadata.participants.joined(separator: ", ")
                }
                
                // Populate the per-source transcripts and interleave them.
                self.microphoneTranscript = merged.microphone
                self.systemAudioTranscript = merged.systemAudio
                self.updateCombinedTranscript()
                // The combined view is authoritative for a grouped meeting; there is
                // no single backing transcript to expose here.
                self.loadedMeetingTranscript = nil
                
                // Point post-processing/analysis at the right per-source audio.
                self.microphoneMeetingId = microphoneId
                self.systemAudioMeetingId = systemAudioId
                
                self.hasRecordedAudio = anyAudio
                self.hasTranscription = !self.transcriptionLines.isEmpty
                
                #if DEBUG
                DevLogger.shared.info("✅ Loaded grouped meeting with \(self.transcriptionLines.count) interleaved lines (mic=\(merged.microphone.count), system=\(merged.systemAudio.count))", context: "LiveTranscriptionViewModel")
                #endif
                
                self.objectWillChange.send()
                return true
            }

            guard applied else { return }

            // Analysis history is keyed off the representative member.
            await self.loadAnalysisHistory(meetingId: representativeId)
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to load grouped meeting: \(error)", context: "LiveTranscriptionViewModel")
            #endif
            
            await MainActor.run {
                guard self.selectedMeetingId == representativeId else { return }
                self.selectedMeetingId = nil
                self.isViewingPastMeeting = false
                self.isLoadingAnalysisHistory = false
                self.statusMessage = "Failed to load meeting"
            }
        }
    }
    
    /// Convert backend transcript segments into `TranscriptionLine`s tagged with the
    /// given audio source (used when loading grouped meeting members).
    ///
    /// Live (not-yet-post-processed) members store raw, fine-grained persisted
    /// segments, so they are re-coalesced to sentence-level lines here (per
    /// member/part, before `GroupedTranscriptMerge` shifts timeline seconds)
    /// to match the granularity shown during live recording. Retranscribed
    /// members are already sentence-level and pass through unchanged.
    private func transcriptionLines(
        from transcript: BackendMeetingTranscript?,
        source: AudioSource,
        startOffset: Double = 0.0,
        isPostProcessed: Bool
    ) -> [TranscriptionLine] {
        guard let transcript = transcript else { return [] }
        let rawLines = transcript.segments.map { segment -> TranscriptionLine in
            // Shift onto the shared session timeline. `start`/`end` strings keep
            // the raw per-track value (legacy display), but the canonical
            // timeline seconds used for interleaving carry the offset.
            let timelineStart = segment.start + startOffset
            let timelineEnd = segment.end + startOffset
            return TranscriptionLine(
                id: UUID().uuidString,
                text: segment.text,
                speakerID: segment.speakerValue?.stringValue,
                isInterim: segment.isInterim ?? false,
                start: String(format: "%.2f", timelineStart),
                end: String(format: "%.2f", timelineEnd),
                diff: segment.end - segment.start,
                timelineStartSeconds: timelineStart,
                timelineEndSeconds: timelineEnd,
                source: source,
                lineComplete: true
            )
        }
        guard !isPostProcessed else { return rawLines }
        return TranscriptSegmentCoalescer.coalesce(
            rawLines,
            minWords: Self.liveSentenceBreakMinWords,
            silenceGapSeconds: Self.reloadCoalesceSilenceGapSeconds,
            normalize: self.normalizeWhitespace
        )
    }
    
    // MARK: - Start New Meeting
    
    /// Start a new meeting (auto-saves current meeting if it exists)
    func startNewMeeting() async {
        #if DEBUG
        DevLogger.shared.info("✨ Starting new meeting", context: "LiveTranscriptionViewModel")
        #endif
        
        // Auto-save logic:
        // Current meeting is already saved by MeetingRecorder during recording
        // We just need to finalize metadata if the meeting was stopped properly
        // (This is handled by stopRecording in the recording extension)
        
        await MainActor.run {
            // Clear all meeting state
            self.transcriptionLines.removeAll()
            self.microphoneTranscript.removeAll()
            self.systemAudioTranscript.removeAll()
            self.microphoneMeetingId = nil
            self.systemAudioMeetingId = nil
            self.sessionId = nil
            self.selectedMeetingId = nil
            self.loadedMeetingTranscript = nil
            self.hasRecordedAudio = false
            self.hasTranscription = false
            self.isViewingPastMeeting = false

            // Clear any resume arming so this brand-new meeting cannot inherit a
            // prior session's timeline offset / part index or be treated as a
            // resumed part. Identity reset in startRecording() is gated on
            // `recordingMode != .resume`, so leaving these set would let a new
            // meeting reuse resume semantics (and a stale session/id).
            self.recordingMode = .fresh
            self.resumeTimelineOffsetSeconds = 0.0
            self.recordingPartIndex = 0
            self.resumedFromMeetingId = nil
            self.microphoneStreamTimingReady = false
            self.systemAudioStreamTimingReady = false
            
            // A prior meeting can keep processing while this fresh meeting is
            // prepared. Never detach that work by clearing its owner or its
            // completion state; only remove its display values from this new
            // meeting's surface.
            if self.isPostProcessing {
                self.clearInactivePostProcessingDisplay(for: nil)
            } else {
                self.postProcessingProgress = 0.0
                self.postProcessingAggregateProgress = 0.0
                self.postProcessingMessage = ""
                self.postProcessingStage = ""
                self.postProcessingCurrentTime = 0.0
                self.postProcessingTotalTime = 0.0
                self.postProcessingETA = 0.0
                self.postProcessingStartedAutomatically = false
                self.activePostProcessingMeetingId = nil
            }
            self.windowRetranscriptionStatus = nil
            self.isApplyingWindowedRetranscription = false
            // Re-seed automation overrides from global defaults on the next
            // settings fetch for this fresh recording.
            self.sessionAutomationSeeded = false
            self.liveTranscriptionSelectionTouched = false
            
            // Preserve prior analysis ownership and completion while a new
            // meeting is created. The UI gates these values by the concrete
            // owner, so they cannot leak onto this fresh meeting.
            if !self.isAnalyzing {
                self.analysisJustCompleted = false
                self.analysisProgress = 0.0
                self.analysisMessage = ""
                self.analysisStartedAutomatically = false
                self.activeAnalysisMeetingId = nil
            }
            self.selectedAnalysisModes.removeAll()
            self.analysisCustomInstructions = ""
            
            // Generate new meeting name with timestamp
            let formatter = DateFormatter()
            formatter.dateFormat = "yyyy-MM-dd HH:mm"
            self.meetingName = "Meeting \(formatter.string(from: Date()))"
            self.meetingPurpose = ""
            self.meetingParticipants = ""
            
            // Reset status
            self.statusMessage = "Ready to start transcription"
            self.connectionState = .ready
            
            #if DEBUG
            DevLogger.shared.info("✅ New meeting ready", context: "LiveTranscriptionViewModel")
            #endif
        }
        
        await loadLiveTranscriptionDefault()

        // Refresh meeting list to show the previous meeting (if it was saved)
        await loadMeetingHistory()
    }
    
    // MARK: - Delete Meeting
    
    /// Delete a meeting and its associated data
    /// - Parameter meetingId: ID of the meeting to delete
    func deleteMeeting(_ meetingId: String) async {
        #if DEBUG
        DevLogger.shared.info("🗑️ Deleting meeting: \(meetingId)", context: "LiveTranscriptionViewModel")
        #endif
        
        do {
            // Delete from backend
            try await APIClient.shared.deleteMeeting(id: meetingId)
            
            // If we're currently viewing this meeting, clear the view
            if selectedMeetingId == meetingId {
                await startNewMeeting()
            }
            
            // Refresh the meeting list
            await loadMeetingHistory()
            
            #if DEBUG
            DevLogger.shared.info("✅ Successfully deleted meeting", context: "LiveTranscriptionViewModel")
            #endif
        } catch {
            #if DEBUG
            DevLogger.shared.error("❌ Failed to delete meeting: \(error)", context: "LiveTranscriptionViewModel")
            #endif
        }
    }
    
    // MARK: - Refresh Meeting List
    
    /// Refresh the meeting list (called after creating, deleting, or updating meetings)
    func refreshMeetingList() async {
        await loadMeetingHistory()
    }
    
    // MARK: - Toggle Sidebar
    
    /// Toggle the sidebar collapsed/expanded state
    func toggleSidebar() {
        isSidebarCollapsed.toggle()
        storedSidebarCollapsed = isSidebarCollapsed
    }
    
    /// Set sidebar collapsed state
    /// - Parameter collapsed: Whether sidebar should be collapsed
    func setSidebarCollapsed(_ collapsed: Bool) {
        isSidebarCollapsed = collapsed
        storedSidebarCollapsed = collapsed
    }
    
    // MARK: - Resume Meeting
    
    /// Resume the currently viewed past meeting as a new recording part.
    ///
    /// The new audio is recorded under fresh meeting ids (existing files are never
    /// overwritten), but it shares the original meeting's `session_id` so history
    /// regroups the parts, and its transcript is offset onto the logical timeline
    /// so old and new lines interleave when the meeting is reopened.
    func resumeSelectedMeeting() async {
        guard !isRecording else {
            #if DEBUG
            DevLogger.shared.warning("⚠️ Cannot resume while recording", context: "LiveTranscriptionViewModel")
            #endif
            return
        }
        
        let meetingId = await MainActor.run { self.selectedMeetingId }
        guard let meetingId = meetingId else {
            #if DEBUG
            DevLogger.shared.warning("⚠️ Cannot resume: no meeting selected", context: "LiveTranscriptionViewModel")
            #endif
            return
        }
        
        let listEntry: MeetingListItem? = await MainActor.run {
            self.meetings.first(where: { $0.id == meetingId })
        }
        
        // Logical session to continue. Prefer the list entry's session, then the
        // in-memory session of the just-finished recording (the sidebar refresh
        // from auto-view may not have landed yet, so the list entry can be nil),
        // and only mint a new id for a truly legacy/standalone meeting.
        let resumeSessionId = listEntry?.sessionId ?? self.sessionId ?? UUID().uuidString
        
        // Next ordering index: one past the highest known recording part.
        let maxPartIndex = listEntry?.members?.compactMap { $0.recordingPartIndex }.max() ?? 0
        let nextPartIndex = maxPartIndex + 1
        
        // Where the new part begins on the logical timeline: the furthest known
        // end time across the loaded transcript and the grouped members.
        let timelineOffset = await MainActor.run { () -> Double in
            self.computeResumeTimelineOffset(listEntry: listEntry)
        }
        
        #if DEBUG
        DevLogger.shared.info("▶️ Resuming meeting \(meetingId): session=\(resumeSessionId), partIndex=\(nextPartIndex), offset=\(timelineOffset)s", context: "LiveTranscriptionViewModel")
        #endif
        
        await MainActor.run {
            self.prepareResumeRecordingSession(
                sessionId: resumeSessionId,
                timelineOffsetSeconds: timelineOffset,
                recordingPartIndex: nextPartIndex,
                resumedFromMeetingId: meetingId
            )
            self.startRecording()
        }
    }
    
    /// Compute where a resumed part should begin on the logical meeting timeline,
    /// using the furthest end among the loaded transcript lines and grouped members.
    private func computeResumeTimelineOffset(listEntry: MeetingListItem?) -> Double {
        var offset = 0.0
        
        // Loaded transcript lines already carry timeline-relative end times.
        for line in transcriptionLines {
            if let end = line.timelineEndSeconds {
                offset = max(offset, end)
            }
        }
        
        // Grouped members report their own offset + duration; use the furthest.
        if let members = listEntry?.members {
            for member in members {
                let memberOffset = member.timelineOffsetSeconds ?? 0.0
                let memberDuration = member.durationSeconds ?? 0.0
                offset = max(offset, memberOffset + memberDuration)
            }
        }
        
        // Standalone meetings: fall back to the representative duration.
        if let duration = listEntry?.durationSeconds {
            offset = max(offset, duration)
        }
        
        return offset
    }
    
    // MARK: - Auto-view Just-finished Meeting
    
    /// After recording stops, drop into read-only "viewing" mode for the meeting
    /// that was just recorded so the Resume / Start New controls appear instead
    /// of a bare Start button.
    ///
    /// Uses the in-memory transcript (no backend reload) to avoid a
    /// metadata-finalization race and to avoid clobbering any on-stop
    /// auto-retranscription splice. The sidebar list is refreshed in the
    /// background so the grouped session entry becomes available; once it lands
    /// the selection is reconciled to that representative entry (so it
    /// highlights correctly and Resume can read its members).
    func autoViewJustFinishedSession() {
        // Only when an actual recording produced a meeting to view.
        guard microphoneMeetingId != nil || systemAudioMeetingId != nil else { return }
        guard hasRecordedAudio || !transcriptionLines.isEmpty else { return }
        
        let justViewedId = microphoneMeetingId ?? systemAudioMeetingId
        selectedMeetingId = justViewedId
        isViewingPastMeeting = true
        
        let finishedSessionId = sessionId
        Task { @MainActor in
            await loadMeetingHistory()
            // Only reconcile if the user hasn't navigated away in the meantime.
            guard isViewingPastMeeting, selectedMeetingId == justViewedId else { return }
            if let finishedSessionId = finishedSessionId,
               let representative = meetings.first(where: { $0.sessionId == finishedSessionId }) {
                selectedMeetingId = representative.id
            }
        }
    }
}

