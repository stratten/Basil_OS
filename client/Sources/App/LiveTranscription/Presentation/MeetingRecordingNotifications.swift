import Foundation

extension Notification.Name {
    /// Posted once a recording genuinely starts so the meeting-detected join
    /// prompt can dismiss itself when any meeting is already being recorded.
    static let liveTranscriptionRecordingDidStart = Notification.Name("liveTranscriptionRecordingDidStart")
}
