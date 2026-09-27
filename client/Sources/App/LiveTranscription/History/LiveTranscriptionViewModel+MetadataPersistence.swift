import Foundation

// MARK: - Meeting Metadata Persistence
extension LiveTranscriptionViewModel {
    
    func scheduleMeetingMetadataSave() {
        guard isViewingPastMeeting, let meetingId = selectedMeetingId, !isRecording else {
            return
        }
        
        let name = meetingName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else {
            return
        }
        
        let purpose = meetingPurpose.trimmingCharacters(in: .whitespacesAndNewlines)
        let participants = meetingParticipants
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        
        meetingMetadataSaveTask?.cancel()
        meetingMetadataSaveTask = Task { [weak self] in
            do {
                try await Task.sleep(nanoseconds: 750_000_000)
                try Task.checkCancellation()
                
                #if DEBUG
                DevLogger.shared.info("Saving meeting metadata edits for \(meetingId): \(name)", context: "LiveTranscriptionViewModel")
                #endif
                
                try await APIClient.shared.updateMeetingMetadata(
                    meetingId: meetingId,
                    name: name,
                    purpose: purpose.isEmpty ? nil : purpose,
                    participants: participants
                )
                
                #if DEBUG
                DevLogger.shared.info("Saved meeting metadata edits for \(meetingId)", context: "LiveTranscriptionViewModel")
                #endif
                await self?.loadMeetingHistory()
            } catch is CancellationError {
                return
            } catch {
                #if DEBUG
                DevLogger.shared.error("Failed to save meeting metadata edits for \(meetingId): \(error.localizedDescription)", context: "LiveTranscriptionViewModel")
                #endif
            }
        }
    }
}
