import Combine
import Foundation

extension MeetingBridgePublisher {
    func configureStreamingObservation() {
        viewModel.$transcriptionLines
            .dropFirst()
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in
                self?.emitTranscriptPatch()
            }
            .store(in: &cancellables)
    }

    func emitTranscriptPatch() {
        synchronizeSelectionGeneration()
        let nextTranscript = buildTranscript()
        let patch = TranscriptPatchDTO.make(previous: lastTranscript, current: nextTranscript)
        guard !patch.isEmpty else { return }
        lastTranscript = nextTranscript
        broadcast(MeetingBridgeEventType.transcriptDelta) { event in
            event.transcriptPatch = patch
        }
    }

    func synchronizeSelectionGeneration() {
        if viewModel.selectedMeetingId != lastSelectedMeetingId {
            lastSelectedMeetingId = viewModel.selectedMeetingId
            selectionGeneration += 1
        }
    }
}

extension TranscriptPatchDTO {
    static func make(previous: [TranscriptLineDTO], current: [TranscriptLineDTO]) -> TranscriptPatchDTO {
        let previousByID = previous.reduce(into: [String: TranscriptLineDTO]()) { result, line in
            result[line.id] = line
        }
        let currentIDs = Set(current.map(\.id))
        let upserts = current.filter { previousByID[$0.id] != $0 }
        let removedIDs = previous.map(\.id).filter { !currentIDs.contains($0) }
        let orderedIDs = current.map(\.id)
        if previous.map(\.id) == orderedIDs && upserts.isEmpty && removedIDs.isEmpty {
            return TranscriptPatchDTO(orderedIDs: [], upserts: [], removedIDs: [])
        }
        return TranscriptPatchDTO(orderedIDs: orderedIDs, upserts: upserts, removedIDs: removedIDs)
    }
}
