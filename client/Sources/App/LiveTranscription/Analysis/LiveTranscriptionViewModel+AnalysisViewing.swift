import Foundation

/// Opening a saved analysis for a meeting other than the one loaded in the main window, such as the arrow on a history row.
extension LiveTranscriptionViewModel {
    /// The meeting a `viewAnalysis` request should open, or nil when the request does not match anything this app knows about.
    ///
    /// A request that names a meeting is checked against that meeting's own history row, so it works without the meeting being selected. Only the selected meeting has its analysis history loaded, so that list cannot vouch for any other row.
    nonisolated static func analysisViewTargetMeetingId(
        filename: String,
        requestedMeetingId: String?,
        selectedMeetingId: String?,
        activeAnalysisMeetingId: String?,
        analysisHistoryFilenames: [String],
        meetings: [MeetingListItem],
        failedOpen: (filename: String, meetingId: String)? = nil
    ) -> String? {
        let loadedMeetingId = selectedMeetingId ?? activeAnalysisMeetingId
        guard let requestedMeetingId, !requestedMeetingId.isEmpty else {
            // The analysis window's Retry names only the file, so a failed open of another meeting's analysis is remembered.
            if let failedOpen, failedOpen.filename == filename { return failedOpen.meetingId }
            guard analysisHistoryFilenames.contains(filename) else { return nil }
            return loadedMeetingId
        }
        if meetings.first(where: { $0.id == requestedMeetingId })?.analysisSummary?.latestFilename == filename {
            return requestedMeetingId
        }
        if requestedMeetingId == loadedMeetingId, analysisHistoryFilenames.contains(filename) {
            return requestedMeetingId
        }
        return nil
    }

    /// The transcript lines belonging to the meeting whose analysis is being opened, or nil when the main window already holds that meeting's transcript.
    ///
    /// The analysis window appends the transcript to copy-all and export text. For a meeting that is not the one loaded, using the loaded lines would export another meeting's transcript, so it is fetched from the backend instead. A grouped meeting is rebuilt the same way selecting it builds it: each member recording, merged onto one timeline. If the fetch fails the analysis still opens, without a transcript section.
    @MainActor
    func transcriptLineDTOsForAnalysis(meetingId: String) async -> [TranscriptLineDTO]? {
        guard meetingId != (selectedMeetingId ?? currentMeetingId) else { return nil }
        let members = meetings.first(where: { $0.id == meetingId })?.members ?? []
        do {
            if members.count > 1 {
                return Self.transcriptLineDTOs(from: try await groupedTranscriptLines(members: members))
            }
            let (metadata, transcript) = try await APIClient.shared.getMeeting(id: meetingId)
            return Self.transcriptLineDTOs(
                from: transcriptionLines(from: transcript, source: .microphone, isPostProcessed: metadata.isPostProcessed)
            )
        } catch {
            #if DEBUG
            DevLogger.shared.error("Could not load the transcript for analysis of \(meetingId): \(error)", context: "LiveTranscriptionViewModel")
            #endif
            return []
        }
    }

    /// Every member recording's lines on one timeline, in the order the main window shows them.
    @MainActor
    private func groupedTranscriptLines(members: [MeetingMember]) async throws -> [TranscriptionLine] {
        var inputs: [GroupedTranscriptMerge.MemberInput] = []
        for member in members {
            let (_, transcript) = try await APIClient.shared.getMeeting(id: member.id)
            let source: AudioSource = (member.source ?? "").lowercased() == "microphone" ? .microphone : .systemAudio
            inputs.append(
                GroupedTranscriptMerge.MemberInput(
                    source: source,
                    recordingPartIndex: member.recordingPartIndex ?? 0,
                    startDate: member.startDate,
                    lines: transcriptionLines(from: transcript, source: source, isPostProcessed: member.isPostProcessed)
                )
            )
        }
        let merged = GroupedTranscriptMerge.merge(inputs)
        // A stable sort on the timeline start keeps simultaneous lines in recording order; lines without a timeline go last.
        return (merged.microphone + merged.systemAudio).enumerated().sorted { left, right in
            let leftStart = left.element.timelineStartSeconds ?? .greatestFiniteMagnitude
            let rightStart = right.element.timelineStartSeconds ?? .greatestFiniteMagnitude
            return leftStart == rightStart ? left.offset < right.offset : leftStart < rightStart
        }.map(\.element)
    }

    nonisolated static func transcriptLineDTOs(from lines: [TranscriptionLine]) -> [TranscriptLineDTO] {
        lines.map { line in
            TranscriptLineDTO(
                id: line.id,
                text: line.text,
                speakerId: line.speakerID,
                isInterim: line.isInterim,
                displayStart: line.displayStart,
                timelineStartSeconds: line.timelineStartSeconds,
                timelineEndSeconds: line.timelineEndSeconds,
                source: line.source?.rawValue,
                lineComplete: line.lineComplete
            )
        }
    }
}
