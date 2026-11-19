import Foundation

/// How long until a detected meeting's recording is stopped automatically, so the meeting window can show a countdown.
struct AutoEndCountdown: Equatable {
    /// When the backend will report the meeting as ended.
    var deadline: Date
    /// The full length of the countdown, so the window can draw how much of it has elapsed.
    var totalSeconds: Double
}

// MARK: - Auto-end countdown (meeting detection)
//
// The backend tells the client when a detected meeting app has gone quiet and when it will end the meeting. Only a
// recording that detection started is ever stopped that way, so only that recording shows a countdown. Dismissing
// the countdown keeps this recording running through the rest of its meeting, and it lasts until the recording
// ends: `isRecording` clears both fields, so the next recording starts with auto-end armed again.
extension LiveTranscriptionViewModel {

    /// True when a backend `meeting_ended` for `bundleID` should stop this recording.
    func shouldFinalizeForAutoEnd(bundleID: String) -> Bool {
        isRecording && !isAutoEndDismissed && autoStartedBundleID == bundleID
    }

    /// A recording that a calendar event started has no meeting app yet. When the call's own app appears in the audio probe, bind it, so the backend's end events for that app end this recording like any detected one. Returns true when the app was adopted.
    @discardableResult
    func adoptAutoEndSource(bundleID: String) -> Bool {
        guard isAwaitingAutoEndSource, autoStartedBundleID == nil, !bundleID.isEmpty else { return false }
        autoStartedBundleID = bundleID
        isAwaitingAutoEndSource = false
        return true
    }

    func beginAutoEndCountdown(bundleID: String, deadline: Date, totalSeconds: Double) {
        guard shouldFinalizeForAutoEnd(bundleID: bundleID), totalSeconds > 0 else { return }
        let countdown = AutoEndCountdown(deadline: deadline, totalSeconds: totalSeconds)
        if autoEndCountdown != countdown {
            autoEndCountdown = countdown
        }
    }

    /// The meeting app's audio came back, so the countdown no longer applies.
    func endAutoEndCountdown(bundleID: String) {
        guard autoStartedBundleID == bundleID, autoEndCountdown != nil else { return }
        autoEndCountdown = nil
    }

    /// The user chose to keep recording: hide the countdown and ignore the automatic stop for this recording.
    func dismissAutoEnd() {
        guard isRecording else { return }
        isAutoEndDismissed = true
        autoEndCountdown = nil
    }
}
