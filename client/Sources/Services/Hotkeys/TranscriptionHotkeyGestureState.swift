import Foundation

/// Owns the relationship between one accepted transcription double-press and
/// its release so push-to-talk cannot affect an unrelated recording.
struct TranscriptionHotkeyGestureState {
    enum ControllerState: Equatable {
        case idle
        case starting
        case recording
        case processing
        case failed
    }

    enum PressAction: Equatable {
        case start(UUID)
        case cancelStartup
        case stopRecording
        case none
    }

    enum ReleaseAction: Equatable {
        case deferStop(UUID)
        case stopRecording
        case none
    }

    private struct OwnedStartGesture {
        let id: UUID
        var hasDeferredStop = false
    }

    private var ownedStartGesture: OwnedStartGesture?

    mutating func acceptPress(controllerState: ControllerState) -> PressAction {
        ownedStartGesture = nil

        switch controllerState {
        case .idle, .failed:
            let id = UUID()
            ownedStartGesture = OwnedStartGesture(id: id)
            return .start(id)
        case .starting:
            return .cancelStartup
        case .recording:
            return .stopRecording
        case .processing:
            return .none
        }
    }

    mutating func release(
        holdDuration: TimeInterval,
        threshold: TimeInterval,
        pushToTalkEnabled: Bool,
        controllerState: ControllerState
    ) -> ReleaseAction {
        guard var gesture = ownedStartGesture else {
            return .none
        }

        guard pushToTalkEnabled, holdDuration >= threshold else {
            ownedStartGesture = nil
            return .none
        }

        switch controllerState {
        case .recording:
            ownedStartGesture = nil
            return .stopRecording
        case .idle, .starting:
            gesture.hasDeferredStop = true
            ownedStartGesture = gesture
            return .deferStop(gesture.id)
        case .processing, .failed:
            ownedStartGesture = nil
            return .none
        }
    }

    mutating func consumeDeferredStop(for gestureID: UUID) -> Bool {
        guard let gesture = ownedStartGesture,
              gesture.id == gestureID,
              gesture.hasDeferredStop else {
            return false
        }

        ownedStartGesture = nil
        return true
    }

    mutating func reset() {
        ownedStartGesture = nil
    }
}
